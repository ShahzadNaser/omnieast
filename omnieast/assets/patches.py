"""ISS-2026-00184: point ERPNext's asset account lookups at omnieast.assets.depreciation_accounts.

ERPNext imports these functions by name into several modules, so each module's reference is replaced.
Sites without omnieast get ERPNext's originals. With the switch off, account lookups always read the Office
row (identical to ERPNext while each company has one row) and the reports run ERPNext's originals.

Applied from the `before_request` and `before_job` hooks (every web request, every scheduled / background job),
not from an import in hooks.py: Frappe reads hooks from the Redis cache in production and may never import
hooks.py in a given worker. `bench console` / `execute` and tests call `apply()` themselves.
`apply` is idempotent and cheap after the first call.

After an ERPNext upgrade: each target's parameters are checked against EXPECTED_PARAMS; a target that no
longer matches is left unpatched and reported in the Error Log (see `problems`). Re-run
omnieast.assets.test_depreciation_accounts.
"""

import functools
import importlib
import inspect

import frappe

from omnieast.assets import depreciation_accounts as accounts
from omnieast.assets import reports

MARK = "_omnieast_iss_2026_00184"

DEPRECIATION = "erpnext.assets.doctype.asset.depreciation"
ASSET = "erpnext.assets.doctype.asset.asset"
ASSET_CATEGORY = "erpnext.assets.doctype.asset_category.asset_category"
ASSET_VALUE_ADJUSTMENT = "erpnext.assets.doctype.asset_value_adjustment.asset_value_adjustment"
PURCHASE_INVOICE = "erpnext.accounts.doctype.purchase_invoice.purchase_invoice"
ASSET_CAPITALIZATION = "erpnext.assets.doctype.asset_capitalization.asset_capitalization"
FIXED_ASSET_REGISTER = "erpnext.assets.report.fixed_asset_register.fixed_asset_register"
ASSET_DEPRECIATIONS_AND_BALANCES = (
	"erpnext.accounts.report.asset_depreciations_and_balances.asset_depreciations_and_balances"
)

GET_DEPRECIATION_ACCOUNTS = ["asset_category", "company"]
GET_ASSET_CATEGORY_ACCOUNT = ["fieldname", "item", "asset", "account", "asset_category", "company"]

# parameters of each target in ERPNext 16.61
EXPECTED_PARAMS = {
	(DEPRECIATION, "get_depreciation_accounts"): GET_DEPRECIATION_ACCOUNTS,
	(DEPRECIATION, "_make_depreciation_entry"): [
		"depr_schedule_name",
		"date",
		"sch_start_idx",
		"sch_end_idx",
		"accounting_dimensions",
	],
	(DEPRECIATION, "get_asset_details"): ["asset", "finance_book", "disposal_values"],
	(ASSET, "get_depreciation_accounts"): GET_DEPRECIATION_ACCOUNTS,
	(ASSET, "get_asset_category_account"): GET_ASSET_CATEGORY_ACCOUNT,
	(ASSET_VALUE_ADJUSTMENT, "get_depreciation_accounts"): GET_DEPRECIATION_ACCOUNTS,
	(ASSET_CATEGORY, "get_asset_category_account"): GET_ASSET_CATEGORY_ACCOUNT,
	(PURCHASE_INVOICE, "get_asset_category_account"): GET_ASSET_CATEGORY_ACCOUNT,
	(ASSET_CAPITALIZATION, "get_asset_category_account"): GET_ASSET_CATEGORY_ACCOUNT,
	(FIXED_ASSET_REGISTER, "get_asset_depreciation_amount_map"): ["filters", "finance_book"],
	(FIXED_ASSET_REGISTER, "get_asset_value_adjustment_map"): ["filters", "finance_book"],
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_assets_for_grouped_by_category"): ["filters"],
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_asset_value_adjustment_map_by_category"): ["filters"],
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_assets_for_grouped_by_asset"): ["filters"],
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_asset_value_adjustment_map"): ["filters"],
}

problems: list[str] = []
_applied = False


# --- wrappers ---------------------------------------------------------------------------------------------


def _switch(original, replacement):
	"""Reports: omnieast's copy while enabled, else ERPNext's original."""

	@functools.wraps(original)
	def wrapper(*args, **kwargs):
		if accounts.is_enabled():
			return replacement(*args, **kwargs)
		return original(*args, **kwargs)

	return wrapper


def _account_lookup(original, replacement):
	"""Account lookups.

	- omnieast not installed on the site: ERPNext's original.
	- switch on: the row of the current usage.
	- switch off: always the Office row. With only an Office row per company this is exactly ERPNext's
	  result; once Project rows exist it keeps the choice deterministic (ERPNext's own lookup would pick
	  either row), so switching off is a safe way back to "everything Office".
	"""

	@functools.wraps(original)
	def wrapper(*args, **kwargs):
		if not accounts.is_installed():
			return original(*args, **kwargs)
		if accounts.is_enabled():
			return replacement(*args, **kwargs)
		with accounts.asset_usage_context(usage=accounts.OFFICE):
			return replacement(*args, **kwargs)

	return wrapper


def _make_depreciation_entry(original):
	"""Run the depreciation posting of a schedule with its asset's accounts (scheduled job, button, disposal)."""

	@functools.wraps(original)
	def wrapper(depr_schedule_name, *args, **kwargs):
		if not accounts.is_enabled():
			return original(depr_schedule_name, *args, **kwargs)
		asset = frappe.db.get_value("Asset Depreciation Schedule", depr_schedule_name, "asset")
		with accounts.asset_usage_context(asset):
			return original(depr_schedule_name, *args, **kwargs)

	return wrapper


def _get_asset_details(original):
	"""Sale, sales return, scrap and consumed assets of a capitalization use the disposed asset's accounts."""

	@functools.wraps(original)
	def wrapper(asset, *args, **kwargs):
		if not accounts.is_enabled():
			return original(asset, *args, **kwargs)
		with accounts.asset_usage_context(asset):
			return original(asset, *args, **kwargs)

	return wrapper


def _lookup(replacement):
	return lambda original: _account_lookup(original, replacement)


def _report(replacement):
	return lambda original: _switch(original, replacement)


TARGETS = {
	(DEPRECIATION, "get_depreciation_accounts"): _lookup(accounts.get_depreciation_accounts),
	(DEPRECIATION, "_make_depreciation_entry"): _make_depreciation_entry,
	(DEPRECIATION, "get_asset_details"): _get_asset_details,
	(ASSET, "get_depreciation_accounts"): _lookup(accounts.get_depreciation_accounts),
	(ASSET, "get_asset_category_account"): _lookup(accounts.get_asset_category_account),
	(ASSET_VALUE_ADJUSTMENT, "get_depreciation_accounts"): _lookup(accounts.get_depreciation_accounts),
	(ASSET_CATEGORY, "get_asset_category_account"): _lookup(accounts.get_asset_category_account),
	(PURCHASE_INVOICE, "get_asset_category_account"): _lookup(accounts.get_asset_category_account),
	(ASSET_CAPITALIZATION, "get_asset_category_account"): _lookup(accounts.get_asset_category_account),
	(FIXED_ASSET_REGISTER, "get_asset_depreciation_amount_map"): _report(reports.far_depreciation_amount_map),
	(FIXED_ASSET_REGISTER, "get_asset_value_adjustment_map"): _report(reports.far_value_adjustment_map),
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_assets_for_grouped_by_category"): _report(
		reports.adb_assets_for_grouped_by_category
	),
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_asset_value_adjustment_map_by_category"): _report(
		reports.adb_value_adjustment_map_by_category
	),
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_assets_for_grouped_by_asset"): _report(
		reports.adb_assets_for_grouped_by_asset
	),
	(ASSET_DEPRECIATIONS_AND_BALANCES, "get_asset_value_adjustment_map"): _report(
		reports.adb_value_adjustment_map
	),
}


# --- application ------------------------------------------------------------------------------------------


def _params(func) -> list[str]:
	return list(inspect.signature(func).parameters)


def apply(*args, **kwargs):
	"""Patch every target once per process. Never raises: a request or job must not fail because of this."""
	global _applied
	if _applied:
		return
	_applied = True

	for (module_path, attr), make_wrapper in TARGETS.items():
		try:
			module = importlib.import_module(module_path)
			original = getattr(module, attr, None)
			if original is None:
				problems.append(f"{module_path}.{attr}: not found")
				continue
			if getattr(original, MARK, False):
				continue
			if _params(original) != EXPECTED_PARAMS[(module_path, attr)]:
				problems.append(f"{module_path}.{attr}: parameters are now {_params(original)}")
				continue

			wrapper = make_wrapper(original)
			setattr(wrapper, MARK, True)
			wrapper.omnieast_original = original
			setattr(module, attr, wrapper)
		except Exception as e:
			problems.append(f"{module_path}.{attr}: {e!r}")

	if problems:
		_report_problems()


def _report_problems():
	message = "\n".join(problems)
	print(f"omnieast ISS-2026-00184: asset account patches not applied:\n{message}")
	try:
		if getattr(frappe.local, "site", None) and frappe.db:
			frappe.log_error(
				title="ISS-2026-00184: asset account patches not applied (check after ERPNext upgrade)",
				message=message,
				defer_insert=True,
			)
	except Exception:
		pass


def get_original(module_path: str, attr: str):
	"""ERPNext's function behind a patched name (used by tests)."""
	func = getattr(importlib.import_module(module_path), attr)
	return getattr(func, "omnieast_original", func)
