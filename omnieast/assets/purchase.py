"""ISS-2026-00184: Asset Usage on Purchase Invoice / Purchase Receipt fixed-asset rows.

The header Asset Usage fills blank fixed-asset rows; each row may differ. After ERPNext has set the row's
account (Office row), a Project row is pointed at the Project row's Fixed Asset (or CWIP) account. Office rows
keep ERPNext's account, so with no Project rows the purchase posts exactly as before.
"""

import frappe
from frappe import _

from omnieast.assets.depreciation_accounts import (
	PROJECT,
	USAGE_FIELD,
	get_category_row,
	get_purchase_account,
	is_enabled,
	normalize,
)


def fixed_asset_rows(doc):
	return [d for d in doc.get("items") if d.get("is_fixed_asset")]


def fill_row_usage(doc, method=None):
	"""before_validate: blank fixed-asset rows take the header value."""
	if not is_enabled():
		return
	header = doc.get(USAGE_FIELD)
	for d in fixed_asset_rows(doc):
		if not d.get(USAGE_FIELD) and header:
			d.set(USAGE_FIELD, header)


def validate_purchase(doc, method=None):
	"""validate (after ERPNext's set_expense_account): usage required, PI row = PR row, Project account."""
	if not is_enabled():
		return

	rows = fixed_asset_rows(doc)
	missing = [str(d.idx) for d in rows if not d.get(USAGE_FIELD)]
	if missing:
		frappe.throw(
			_("Please set {0} (Office or Project) on fixed-asset row(s) {1}.").format(
				frappe.bold(_("Asset Usage")), ", ".join(missing)
			),
			frappe.MandatoryError,
			title=_("Missing Asset Usage"),
		)

	arbnb = frappe.get_cached_value("Company", doc.company, "asset_received_but_not_billed")
	for d in rows:
		usage = normalize(d.get(USAGE_FIELD))

		if doc.doctype == "Purchase Invoice" and d.get("pr_detail"):
			receipt_usage = frappe.db.get_value("Purchase Receipt Item", d.pr_detail, USAGE_FIELD)
			if receipt_usage and normalize(receipt_usage) != usage:
				frappe.throw(
					_("Row #{0}: Asset Usage must be {1}, as on Purchase Receipt {2}.").format(
						d.idx, frappe.bold(normalize(receipt_usage)), frappe.bold(d.purchase_receipt)
					),
					title=_("Asset Usage does not match the receipt"),
				)

		if not d.get("asset_category") or (arbnb and d.expense_account == arbnb):
			continue

		target = get_purchase_account(d.asset_category, doc.company, usage)
		if usage == PROJECT:
			d.expense_account = target
		elif target and d.expense_account != target:
			# a row switched back to Office: leave any other account the user chose, undo the Project one
			project_account = _project_purchase_account(d.asset_category, doc.company)
			if not d.expense_account or d.expense_account == project_account:
				d.expense_account = target


def _project_purchase_account(asset_category, company):
	"""The Project row's purchase account, or None (no throw, no Error Log: this is for an Office row)."""
	from erpnext.assets.doctype.asset.asset import is_cwip_accounting_enabled

	row = get_category_row(asset_category, company, PROJECT) or {}
	fieldname = (
		"capital_work_in_progress_account"
		if is_cwip_accounting_enabled(asset_category)
		else "fixed_asset_account"
	)
	return row.get(fieldname)
