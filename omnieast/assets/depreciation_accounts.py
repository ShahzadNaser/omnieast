"""ISS-2026-00184: Office / Project asset accounts. The only place that decides which accounts an asset uses.

Asset Category > Accounts may hold, per company, an Office row and a Project row (`custom_asset_usage`, blank
means Office). An asset, and each fixed-asset row of a Purchase Invoice / Receipt, is marked Office or Project
(`custom_asset_usage`, blank means Office).

ERPNext reads the category row by (category, company) only. omnieast replaces those lookups (see `patches.py`)
with the functions below, which read the row of the *current usage*. The usage is set for the duration of an
asset's posting with `asset_usage_context`; outside such a context it is Office, so every other caller keeps
reading the Office row, as before.

Rules:
- Office: same as ERPNext, including the Company default Accumulated Depreciation / Depreciation Expense.
- Project: the Project row only, never the Office row or the Company defaults. A missing row or account blocks
  the posting and writes an Error Log.

Everything is switched on by Accounts Settings > Enable Office / Project Asset Accounts (`is_enabled`).
"""

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

import frappe
from frappe import _
from frappe.utils import cint

OFFICE = "Office"
PROJECT = "Project"
USAGE_FIELD = "custom_asset_usage"
SETTINGS_FIELD = "custom_enable_asset_usage_accounts"

ACCOUNT_FIELDS = (
	"fixed_asset_account",
	"accumulated_depreciation_account",
	"depreciation_expense_account",
	"capital_work_in_progress_account",
)
ERROR_LOG_TITLE = "ISS-2026-00184: Project accounts missing for {0} / {1}"

# (usage, asset name or None) of the posting running in this context
_current = ContextVar("omnieast_asset_usage", default=None)


class ProjectAccountsMissingError(frappe.ValidationError):
	pass


def is_installed() -> bool:
	"""omnieast installed on this site (other sites on a shared bench get ERPNext untouched)."""
	return "omnieast" in frappe.get_installed_apps()


def is_enabled() -> bool:
	"""omnieast installed on this site and the Accounts Settings switch on.

	Every omnieast entry point asks this first, so it also makes sure the ERPNext lookups are patched
	(idempotent; see patches.py)."""
	from omnieast.assets.patches import apply

	apply()
	if not is_installed():
		return False
	try:
		return bool(cint(frappe.db.get_single_value("Accounts Settings", SETTINGS_FIELD, cache=True)))
	except Exception:
		# field not created yet (before migrate)
		return False


def normalize(usage: str | None) -> str:
	return PROJECT if usage == PROJECT else OFFICE


def get_asset_usage(asset) -> str:
	"""Asset doc, dict or name → Office / Project (blank → Office)."""
	if not asset:
		return OFFICE
	if isinstance(asset, str):
		return normalize(frappe.db.get_value("Asset", asset, USAGE_FIELD))
	return normalize(asset.get(USAGE_FIELD))


def _asset_name(asset) -> str | None:
	if not asset:
		return None
	return asset if isinstance(asset, str) else asset.get("name")


@contextmanager
def asset_usage_context(asset=None, usage: str | None = None):
	"""Run the enclosed ERPNext code with the accounts of `asset`'s usage (or the given `usage`)."""
	usage = normalize(usage) if usage else get_asset_usage(asset)
	token = _current.set((usage, _asset_name(asset)))
	try:
		yield usage
	finally:
		_current.reset(token)


def usage_scope(asset=None, usage: str | None = None):
	"""`asset_usage_context` while the feature is on, else a no-op (pure ERPNext)."""
	return asset_usage_context(asset, usage) if is_enabled() else nullcontext()


def current_usage() -> str:
	current = _current.get()
	return current[0] if current else OFFICE


def current_asset() -> str | None:
	current = _current.get()
	return current[1] if current else None


def get_category_rows(asset_category: str, company: str) -> list[dict]:
	if not asset_category or not company:
		return []
	return frappe.get_all(
		"Asset Category Account",
		filters={"parent": asset_category, "parenttype": "Asset Category", "company_name": company},
		fields=["name", "idx", USAGE_FIELD, *ACCOUNT_FIELDS],
		order_by="idx asc",
	)


def get_category_row(asset_category: str, company: str, usage: str | None = None) -> dict | None:
	"""The (single) row of this category, company and usage; blank rows count as Office."""
	usage = normalize(usage or current_usage())
	for row in get_category_rows(asset_category, company):
		if normalize(row.get(USAGE_FIELD)) == usage:
			return row
	return None


def throw_project_accounts_missing(asset_category, company, missing=None, log=True, reference=None):
	"""Block a Project posting whose category has no complete Project row; write an Error Log first.

	The Error Log is deferred so that it survives the rollback of a failed depreciation run.
	"""
	reference = reference or current_asset()
	missing_labels = ", ".join(_(frappe.unscrub(f)) for f in (missing or ())) or _("the Project row")
	message = _(
		"Asset Category {0} has no complete Project accounts row for company {1} (missing: {2}). "
		"Add or complete the Project row in the category's Accounts table."
	).format(frappe.bold(asset_category), frappe.bold(company), missing_labels)
	if reference:
		message += "<br>" + _("Asset: {0}").format(frappe.bold(reference))

	if log:
		frappe.log_error(
			title=ERROR_LOG_TITLE.format(asset_category, company),
			message=frappe.utils.strip_html(message),
			reference_doctype="Asset" if reference else None,
			reference_name=reference,
			defer_insert=True,
		)
	frappe.throw(message, exc=ProjectAccountsMissingError, title=_("Project accounts missing"))


def required_project_fields(asset_category: str) -> list[str]:
	fields = ["fixed_asset_account"]
	if not frappe.db.get_value("Asset Category", asset_category, "non_depreciable_category"):
		fields += ["accumulated_depreciation_account", "depreciation_expense_account"]
	if frappe.db.get_value("Asset Category", asset_category, "enable_cwip_accounting"):
		fields.append("capital_work_in_progress_account")
	return fields


def check_project_row(asset_category: str, company: str, log=False, reference=None) -> dict:
	"""The complete Project row, or throw (used at save time with log=False)."""
	row = get_category_row(asset_category, company, PROJECT)
	required = required_project_fields(asset_category)
	missing = required if not row else [f for f in required if not row.get(f)]
	if missing:
		throw_project_accounts_missing(asset_category, company, missing, log=log, reference=reference)
	return row


# ---------------------------------------------------------------------------------------------------------
# Replacements for ERPNext's lookups (same signatures and return values). Called only while is_enabled().
# ---------------------------------------------------------------------------------------------------------


def get_depreciation_accounts(asset_category, company):
	"""erpnext.assets.doctype.asset.depreciation.get_depreciation_accounts, for the current usage."""
	if current_usage() == PROJECT:
		row = check_project_row(asset_category, company, log=True)
		return (
			row.fixed_asset_account,
			row.accumulated_depreciation_account,
			row.depreciation_expense_account,
		)

	# Office: ERPNext's own logic, on the Office row
	fixed_asset_account = accumulated_depreciation_account = depreciation_expense_account = None
	non_depreciable_category = frappe.db.get_value(
		"Asset Category", asset_category, "non_depreciable_category"
	)

	accounts = get_category_row(asset_category, company, OFFICE)
	if accounts:
		fixed_asset_account = accounts.fixed_asset_account
		accumulated_depreciation_account = accounts.accumulated_depreciation_account
		depreciation_expense_account = accounts.depreciation_expense_account

	if not fixed_asset_account:
		frappe.throw(_("Please set Fixed Asset Account in Asset Category {0}").format(asset_category))

	if not non_depreciable_category:
		accounts = frappe.get_cached_value(
			"Company", company, ["accumulated_depreciation_account", "depreciation_expense_account"]
		)

		if not accumulated_depreciation_account:
			accumulated_depreciation_account = accounts[0]
		if not depreciation_expense_account:
			depreciation_expense_account = accounts[1]

		if not accumulated_depreciation_account or not depreciation_expense_account:
			frappe.throw(
				_("Please set Depreciation related Accounts in Asset Category {0} or Company {1}").format(
					asset_category, company
				)
			)

	return fixed_asset_account, accumulated_depreciation_account, depreciation_expense_account


def resolve_category_and_company(item=None, asset=None, account=None, asset_category=None, company=None):
	"""How erpnext...asset_category.get_asset_category_account finds the category and company."""
	if item and frappe.db.get_value("Item", item, "is_fixed_asset"):
		asset_category = frappe.db.get_value("Item", item, ["asset_category"])

	elif not asset_category or not company:
		if account:
			if frappe.db.get_value("Account", account, "account_type") != "Fixed Asset":
				account = None

		if not account:
			asset_details = frappe.db.get_value("Asset", asset, ["asset_category", "company"])
			asset_category, company = asset_details or [None, None]

	return asset_category, company


def get_asset_category_account(
	fieldname, item=None, asset=None, account=None, asset_category=None, company=None
):
	"""erpnext.assets.doctype.asset_category.asset_category.get_asset_category_account, for the current usage."""
	asset_category, company = resolve_category_and_company(item, asset, account, asset_category, company)

	if current_usage() == PROJECT and asset_category and company:
		row = get_category_row(asset_category, company, PROJECT)
		if row and row.get(fieldname):
			return row.get(fieldname)
		if fieldname == "capital_work_in_progress_account" and not frappe.db.get_value(
			"Asset Category", asset_category, "enable_cwip_accounting"
		):
			# ERPNext only probes for CWIP here; no CWIP on the Project row is fine while CWIP is off
			return None
		throw_project_accounts_missing(asset_category, company, [fieldname], log=True)

	row = get_category_row(asset_category, company, OFFICE)
	return row.get(fieldname) if row else None


def get_purchase_account(asset_category: str, company: str, usage: str) -> str | None:
	"""Account a purchase debits for a fixed-asset row: CWIP when the category uses CWIP, else Fixed Asset."""
	from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled

	fieldname = (
		"capital_work_in_progress_account"
		if is_cwip_accounting_enabled(asset_category)
		else "fixed_asset_account"
	)
	with asset_usage_context(usage=usage):
		account = get_asset_category_account(fieldname, asset_category=asset_category, company=company)

	if not account and normalize(usage) == OFFICE and fieldname == "capital_work_in_progress_account":
		account = frappe.get_cached_value("Company", company, "capital_work_in_progress_account")
	return account


def get_accounts_for_usage(asset_category: str, company: str, usage: str) -> frappe._dict:
	"""Fixed Asset / Accumulated / Expense of one usage, without throwing or logging (for warnings)."""
	if normalize(usage) == PROJECT:
		row = get_category_row(asset_category, company, PROJECT) or {}
		fa, accumulated, expense = (row.get(f) for f in ACCOUNT_FIELDS[:3])
	else:
		try:
			with asset_usage_context(usage=OFFICE):
				fa, accumulated, expense = get_depreciation_accounts(asset_category, company)
		except frappe.ValidationError:
			frappe.clear_last_message()
			fa = accumulated = expense = None
	return frappe._dict(
		fixed_asset_account=fa,
		accumulated_depreciation_account=accumulated,
		depreciation_expense_account=expense,
	)
