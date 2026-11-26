"""ISS-2026-00184: Asset Category with an Office and a Project accounts row per company."""

import frappe
from frappe import _
from frappe.query_builder.functions import IfNull

from omnieast.assets.depreciation_accounts import (
	ACCOUNT_FIELDS,
	OFFICE,
	PROJECT,
	USAGE_FIELD,
	is_enabled,
	normalize,
)

DISPOSED_ASSET_STATUSES = ("Sold", "Scrapped", "Capitalized")


class AssetCategoryUsageMixin:
	def validate(self):
		super().validate()
		self.validate_usage_rows()

	def uses_usage_rows(self) -> bool:
		"""Pure ERPNext while the switch is off and no row is marked Project."""
		return is_enabled() or any(normalize(d.get(USAGE_FIELD)) == PROJECT for d in self.accounts)

	def validate_usage_rows(self):
		if not self.uses_usage_rows():
			return

		seen = {}
		for d in self.accounts:
			key = (d.company_name, normalize(d.get(USAGE_FIELD)))
			if key in seen:
				frappe.throw(
					_(
						"Row #{0}: company {1} already has a {2} row (row #{3}). Keep one {2} row per company."
					).format(d.idx, frappe.bold(d.company_name), frappe.bold(key[1]), seen[key]),
					title=_("Duplicate Accounts Row"),
				)
			seen[key] = d.idx

		required = self.required_project_fields()
		for d in self.accounts:
			if normalize(d.get(USAGE_FIELD)) != PROJECT:
				continue
			if (d.company_name, OFFICE) not in seen:
				frappe.throw(
					_(
						"Row #{0}: add an Office row for company {1} too; purchases and Office assets use it."
					).format(d.idx, frappe.bold(d.company_name)),
					title=_("Office Row Missing"),
				)
			missing = [_(frappe.unscrub(f)) for f in required if not d.get(f)]
			if missing:
				frappe.throw(
					_("Row #{0} (Project, {1}): please set {2}.").format(
						d.idx, frappe.bold(d.company_name), ", ".join(missing)
					),
					title=_("Project Accounts Missing"),
				)

	def required_project_fields(self):
		"""Same rule as depreciation_accounts.required_project_fields, on the values being saved."""
		fields = ["fixed_asset_account"]
		if not self.non_depreciable_category:
			fields += ["accumulated_depreciation_account", "depreciation_expense_account"]
		if self.enable_cwip_accounting:
			fields.append("capital_work_in_progress_account")
		return fields

	def validate_account_change_for_existing_assets(self):
		"""ERPNext 16.61's check, by (company, usage) instead of company.

		Switch off: ERPNext's rule (changing a filled account of a row in use is blocked).
		Switch on (D13): the change is saved with a warning. Removing a row in use is blocked either way.
		"""
		previous_doc = self.get_doc_before_save()
		if not previous_doc:
			return

		current_rows = {(row.company_name, normalize(row.get(USAGE_FIELD))): row for row in self.accounts}
		warnings = []
		for previous_row in previous_doc.accounts:
			key = (previous_row.company_name, normalize(previous_row.get(USAGE_FIELD)))
			current_row = current_rows.get(key)
			changed_fields = [
				fieldname
				for fieldname in ACCOUNT_FIELDS
				if previous_row.get(fieldname)
				and (current_row or {}).get(fieldname) != previous_row.get(fieldname)
			]
			if not changed_fields:
				continue

			active = self.count_active_assets(*key)
			if not active:
				continue

			if not current_row:
				frappe.throw(
					_(
						"Cannot remove the {0} row of company {1}: {2} active {0} asset(s) in this category use it"
					).format(frappe.bold(key[1]), frappe.bold(key[0]), active),
					title=_("Invalid Account"),
				)

			if not is_enabled():
				frappe.throw(
					_("Cannot change {0} for company {1} since it has active assets in this category").format(
						", ".join(frappe.bold(_(frappe.unscrub(fieldname))) for fieldname in changed_fields),
						frappe.bold(previous_row.company_name),
					),
					title=_("Invalid Account"),
				)

			for fieldname in changed_fields:
				warnings.append(
					_("{0} ({1}) {2}: {3} → {4}").format(
						key[0],
						key[1],
						_(frappe.unscrub(fieldname)),
						previous_row.get(fieldname),
						current_row.get(fieldname) or _("(blank)"),
					)
				)
			warnings.append(_("{0} ({1}): {2} active asset(s) affected").format(key[0], key[1], active))

		if warnings:
			frappe.msgprint(
				"<br>".join(warnings)
				+ "<br><br>"
				+ _(
					"Entries posted from now on use the new accounts; entries already posted stay where they are. "
					"For Fixed Asset or Accumulated Depreciation, the existing balances stay in the old accounts and "
					"a later sale, scrap or value adjustment posts the full amounts to the new ones: move the "
					"balances with a Journal Entry."
				),
				title=_("Accounts changed for assets in use"),
				indicator="orange",
			)

	def has_active_assets(self, company: str) -> bool:
		return bool(self.count_active_assets(company))

	def count_active_assets(self, company: str, usage: str | None = None) -> int:
		"""ERPNext's 'active assets' (submitted and not disposed, or a draft whose purchase is booked),
		of one usage when given (blank counts as Office)."""
		asset = frappe.qb.DocType("Asset")
		query = (
			frappe.qb.from_(asset)
			.select(asset.name)
			.where(asset.asset_category == self.name)
			.where(asset.company == company)
			.where(asset.docstatus < 2)
			.where(asset.status.notin(DISPOSED_ASSET_STATUSES))
			.where(
				(asset.docstatus == 1)
				| (IfNull(asset.purchase_receipt, "") != "")
				| (IfNull(asset.purchase_invoice, "") != "")
			)
		)
		if usage and frappe.get_meta("Asset").has_field(USAGE_FIELD):
			usage_field = IfNull(asset[USAGE_FIELD], "")
			query = query.where(usage_field == PROJECT if usage == PROJECT else usage_field != PROJECT)
		return len(query.run())
