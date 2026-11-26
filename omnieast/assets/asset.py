"""ISS-2026-00184: Asset Usage (Office / Project) on the Asset."""

import frappe
from frappe import _

from omnieast.assets.depreciation_accounts import (
	PROJECT,
	USAGE_FIELD,
	check_project_row,
	get_accounts_for_usage,
	get_purchase_account,
	is_enabled,
	normalize,
	usage_scope,
)

# Asset link → purchase row doctype, most specific first
PURCHASE_ROWS = (
	("purchase_invoice_item", "Purchase Invoice Item"),
	("purchase_receipt_item", "Purchase Receipt Item"),
)


class AssetUsageMixin:
	"""Asset GL (CWIP → Fixed Asset, purchase check) and manual entries use the asset's own row."""

	def validate_make_gl_entry(self):
		with usage_scope(self):
			return super().validate_make_gl_entry()

	def make_gl_entries(self):
		with usage_scope(self):
			return super().make_gl_entries()

	@frappe.whitelist()
	def get_manual_depreciation_entries(self):
		with usage_scope(self):
			return super().get_manual_depreciation_entries()


@frappe.whitelist()
def make_journal_entry(asset_name):
	"""erpnext...asset.make_journal_entry (Asset > Create > Depreciation Entry) with the asset's accounts."""
	from erpnext.assets.doctype.asset import asset as erpnext_asset

	with usage_scope(asset_name):
		return erpnext_asset.make_journal_entry(asset_name)


def get_purchase_row(doc) -> frappe._dict | None:
	"""The purchase row this asset came from: (usage, expense_account, doctype)."""
	for fieldname, doctype in PURCHASE_ROWS:
		if doc.get(fieldname):
			row = frappe.db.get_value(
				doctype, doc.get(fieldname), [USAGE_FIELD, "expense_account"], as_dict=True
			)
			if row:
				row.doctype = doctype
				return row

	# linked to a purchase document only: its fixed-asset rows of this item, if they agree
	for fieldname, doctype in (
		("purchase_invoice", "Purchase Invoice"),
		("purchase_receipt", "Purchase Receipt"),
	):
		if not doc.get(fieldname):
			continue
		rows = frappe.get_all(
			f"{doctype} Item",
			filters={"parent": doc.get(fieldname), "item_code": doc.item_code, "is_fixed_asset": 1},
			fields=[USAGE_FIELD, "expense_account"],
		)
		if len({(normalize(r.get(USAGE_FIELD)), r.expense_account) for r in rows}) == 1:
			rows[0].doctype = f"{doctype} Item"
			return rows[0]
	return None


def before_validate(doc, method=None):
	"""A draft from a purchase takes the purchase row's Asset Usage (assets auto-created on PI / PR submit)."""
	if not is_enabled() or doc.docstatus != 0 or doc.get(USAGE_FIELD):
		return
	row = get_purchase_row(doc)
	if row and row.get(USAGE_FIELD):
		doc.set(USAGE_FIELD, row.get(USAGE_FIELD))


def validate_asset_usage(doc, method=None):
	if not is_enabled() or doc.docstatus != 0:
		return

	if not doc.get(USAGE_FIELD):
		frappe.throw(
			_("Please select {0} (Office or Project).").format(frappe.bold(_("Asset Usage"))),
			frappe.MandatoryError,
			title=_("Missing Asset Usage"),
		)

	if doc.asset_category and doc.company and normalize(doc.get(USAGE_FIELD)) == PROJECT:
		check_project_row(doc.asset_category, doc.company, log=False, reference=doc.name)

	validate_purchase_account(doc)


def validate_purchase_account(doc):
	"""The purchase debited one row's account; the asset's type must use that same account."""
	if not doc.asset_category or not doc.company:
		return
	row = get_purchase_row(doc)
	if not row or not row.expense_account:
		return

	arbnb = frappe.get_cached_value("Company", doc.company, "asset_received_but_not_billed")
	if row.expense_account == arbnb:
		return

	expected = get_purchase_account(doc.asset_category, doc.company, doc.get(USAGE_FIELD))
	if expected and expected != row.expense_account:
		frappe.throw(
			_(
				"Asset Usage {0} books to {1}, but the purchase row debited {2} (Asset Usage {3}). "
				"Use the purchase's Asset Usage, or correct the purchase."
			).format(
				frappe.bold(normalize(doc.get(USAGE_FIELD))),
				frappe.bold(expected),
				frappe.bold(row.expense_account),
				frappe.bold(normalize(row.get(USAGE_FIELD))),
			),
			title=_("Asset Usage does not match the purchase"),
		)


def before_update_after_submit(doc, method=None):
	"""Changing a submitted asset to Project needs a complete Project row."""
	if not is_enabled() or not doc.has_value_changed(USAGE_FIELD):
		return
	if normalize(doc.get(USAGE_FIELD)) == PROJECT:
		check_project_row(doc.asset_category, doc.company, log=False, reference=doc.name)


def on_usage_change(doc, method=None):
	"""D7: a change applies to future entries; record it and warn when balances stay in other accounts."""
	if not is_enabled() or not doc.has_value_changed(USAGE_FIELD):
		return

	before = doc.get_doc_before_save()
	old = normalize(before.get(USAGE_FIELD) if before else None)
	new = normalize(doc.get(USAGE_FIELD))
	if old == new:
		return

	from erpnext.assets.doctype.asset_activity.asset_activity import add_asset_activity

	add_asset_activity(
		doc.name,
		_("Asset Usage changed from {0} to {1}; entries from now on use the {1} accounts").format(old, new),
	)

	old_accounts = get_accounts_for_usage(doc.asset_category, doc.company, old)
	new_accounts = get_accounts_for_usage(doc.asset_category, doc.company, new)
	differing = [
		f"{_(frappe.unscrub(f))}: {old_accounts[f]} → {new_accounts[f]}"
		for f in ("fixed_asset_account", "accumulated_depreciation_account")
		if old_accounts[f] != new_accounts[f]
	]
	if differing:
		frappe.msgprint(
			_(
				"Entries already posted stay in the {0} accounts. A later sale, scrap or value adjustment will "
				"post the full cost and accumulated depreciation to the {1} accounts. Move the balances with a "
				"Journal Entry if needed:"
			).format(old, new)
			+ "<br>"
			+ "<br>".join(differing),
			title=_("Asset Usage changed"),
			indicator="orange",
		)


def extend_bootinfo(bootinfo):
	bootinfo.omnieast_asset_usage_enabled = is_enabled()
