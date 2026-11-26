"""ISS-2026-00184: Fixed Asset Register and Asset Depreciations and Balances with Office / Project rows.

Copies of six ERPNext 16.61 query functions. ERPNext joins Asset Category Account on (category, company) and
matches the GL account to that row's account; with an Office and a Project row the join doubles GL lines that
share an account, and entries made before an account or type change drop out.

The only change: the GL account is matched by its Account Type instead of the category row:
  depreciation       → Account Type "Depreciation" (Asset Category already requires it for the expense account;
                       ERPNext's own Asset Depreciation Ledger report matches depreciation the same way)
  value adjustments  → Account Type "Fixed Asset"
Changed lines are marked `# ISS-2026-00184`. Everything else is line for line 16.61; re-diff after upgrades.
Used only while the feature is on (see patches.py).
"""

import frappe
from frappe.query_builder.functions import IfNull, Sum
from frappe.utils import cstr, flt

DEPRECIATION = "Depreciation"
FIXED_ASSET = "Fixed Asset"


def _account_of_type(gl_account_field, account_type):
	"""GL account is of this Account Type (sub-query, no join, so no duplicated GL lines)."""  # ISS-2026-00184
	account = frappe.qb.DocType("Account")
	return gl_account_field.isin(
		frappe.qb.from_(account).select(account.name).where(account.account_type == account_type)
	)


# --- Fixed Asset Register (erpnext/assets/report/fixed_asset_register/fixed_asset_register.py) ---------


def far_depreciation_amount_map(filters, finance_book):
	start_date = filters.from_date if filters.filter_based_on == "Date Range" else filters.year_start_date
	end_date = filters.to_date if filters.filter_based_on == "Date Range" else filters.year_end_date

	asset = frappe.qb.DocType("Asset")
	gle = frappe.qb.DocType("GL Entry")
	company = frappe.qb.DocType("Company")

	query = (
		frappe.qb.from_(gle)
		.join(asset)
		.on(gle.against_voucher == asset.name)
		.join(company)
		.on(company.name == asset.company)
		.select(asset.name.as_("asset"), Sum(gle.debit - gle.credit).as_("depreciation_amount"))
		.where(_account_of_type(gle.account, DEPRECIATION))  # ISS-2026-00184
		.where(gle.is_cancelled == 0)
		.where(gle.is_opening == "No")
		.where(company.name == filters.company)
		.where(asset.docstatus == 1)
	)

	if filters.only_existing_assets:
		query = query.where(asset.asset_type == "Existing Asset")
	if filters.asset_category:
		query = query.where(asset.asset_category == filters.asset_category)
	if filters.cost_center:
		query = query.where(asset.cost_center == filters.cost_center)
	if filters.status:
		if filters.status == "In Location":
			query = query.where(asset.status.notin(["Sold", "Scrapped", "Capitalized"]))
		else:
			query = query.where(asset.status.isin(["Sold", "Scrapped", "Capitalized"]))
	if finance_book:
		query = query.where((gle.finance_book.isin([cstr(finance_book), ""])) | (gle.finance_book.isnull()))
	else:
		query = query.where((gle.finance_book.isin([""])) | (gle.finance_book.isnull()))
	if filters.filter_based_on in ("Date Range", "Fiscal Year"):
		query = query.where(gle.posting_date >= start_date)
		query = query.where(gle.posting_date <= end_date)

	query = query.groupby(asset.name)

	asset_depr_amount_map = query.run()

	return dict(asset_depr_amount_map)


def far_value_adjustment_map(filters, finance_book):
	start_date = filters.from_date if filters.filter_based_on == "Date Range" else filters.year_start_date
	end_date = filters.to_date if filters.filter_based_on == "Date Range" else filters.year_end_date

	asset = frappe.qb.DocType("Asset")
	gle = frappe.qb.DocType("GL Entry")
	company = frappe.qb.DocType("Company")

	query = (
		frappe.qb.from_(gle)
		.join(asset)
		.on(gle.against_voucher == asset.name)
		.join(company)
		.on(company.name == asset.company)
		.select(asset.name.as_("asset"), Sum(gle.debit - gle.credit).as_("adjustment_amount"))
		.where(_account_of_type(gle.account, FIXED_ASSET))  # ISS-2026-00184
		.where(gle.is_cancelled == 0)
		.where(gle.is_opening == "No")
		.where(company.name == filters.company)
		.where(asset.docstatus == 1)
	)

	if filters.only_existing_assets:
		query = query.where(asset.asset_type == "Existing Asset")
	if filters.asset_category:
		query = query.where(asset.asset_category == filters.asset_category)
	if filters.cost_center:
		query = query.where(asset.cost_center == filters.cost_center)
	if filters.status:
		if filters.status == "In Location":
			query = query.where(asset.status.notin(["Sold", "Scrapped", "Capitalized"]))
		else:
			query = query.where(asset.status.isin(["Sold", "Scrapped", "Capitalized"]))
	if finance_book:
		query = query.where((gle.finance_book.isin([cstr(finance_book), ""])) | (gle.finance_book.isnull()))
	else:
		query = query.where((gle.finance_book.isin([""])) | (gle.finance_book.isnull()))
	if filters.filter_based_on in ("Date Range", "Fiscal Year"):
		query = query.where(gle.posting_date >= start_date)
		query = query.where(gle.posting_date <= end_date)

	query = query.groupby(asset.name)

	asset_adjustment_map = query.run()

	return dict(asset_adjustment_map)


# --- Asset Depreciations and Balances
# (erpnext/accounts/report/asset_depreciations_and_balances/asset_depreciations_and_balances.py) ----------


def _depreciation_columns(asset, gl_entry, filters):
	"""The four depreciation sums, identical in both groupings of 16.61."""
	return (
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(gl_entry.posting_date < filters.from_date)
					& ((asset.disposal_date.isnull()) | (asset.disposal_date >= filters.from_date)),
					gl_entry.debit - gl_entry.credit,
				)
				.else_(0)
			),
			0,
		).as_("accumulated_depreciation_as_on_from_date"),
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(gl_entry.posting_date >= filters.from_date)
					& (gl_entry.posting_date <= filters.to_date)
					& ((asset.disposal_date.isnull()) | (gl_entry.posting_date <= asset.disposal_date)),
					gl_entry.credit,
				)
				.else_(0)
			),
			0,
		).as_("depreciation_eliminated_via_reversal"),
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(IfNull(asset.disposal_date, 0) != 0)
					& (asset.disposal_date >= filters.from_date)
					& (asset.disposal_date <= filters.to_date)
					& (gl_entry.posting_date <= asset.disposal_date),
					gl_entry.debit - gl_entry.credit,
				)
				.else_(0)
			),
			0,
		).as_("depreciation_eliminated_during_the_period"),
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(gl_entry.posting_date >= filters.from_date)
					& (gl_entry.posting_date <= filters.to_date)
					& (
						(IfNull(asset.disposal_date, 0) == 0) | (gl_entry.posting_date <= asset.disposal_date)
					),
					gl_entry.debit,
				)
				.else_(0)
			),
			0,
		).as_("depreciation_amount_during_the_period"),
	)


def _opening_depreciation_columns(asset, filters):
	return (
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(IfNull(asset.disposal_date, 0) != 0) & (asset.disposal_date < filters.from_date),
					0,
				)
				.else_(asset.opening_accumulated_depreciation)
			),
			0,
		).as_("accumulated_depreciation_as_on_from_date"),
		IfNull(
			Sum(
				frappe.qb.terms.Case()
				.when(
					(asset.disposal_date >= filters.from_date) & (asset.disposal_date <= filters.to_date),
					asset.opening_accumulated_depreciation,
				)
				.else_(0)
			),
			0,
		).as_("depreciation_eliminated_during_the_period"),
	)


def _assets_depreciation(filters, group_field: str):
	"""16.61 get_assets_for_grouped_by_category / _by_asset; `group_field` is "asset_category" or "asset"."""
	from erpnext.accounts.report.asset_depreciations_and_balances.asset_depreciations_and_balances import (
		get_finance_book_condition,
	)

	asset = frappe.qb.DocType("Asset")
	gl_entry = frappe.qb.DocType("GL Entry")
	asset_depreciation_schedule = frappe.qb.DocType("Asset Depreciation Schedule")
	group_column = asset.asset_category if group_field == "asset_category" else asset.name.as_("asset")
	group_by = asset.asset_category if group_field == "asset_category" else asset.name

	assets_with_finance_book = None
	if filters.get("finance_book"):
		assets_with_finance_book = (
			frappe.qb.from_(asset_depreciation_schedule)
			.select(asset_depreciation_schedule.asset)
			.where(asset_depreciation_schedule.finance_book == filters.get("finance_book"))
		)

	from_gl_entries_query = (
		frappe.qb.from_(gl_entry)
		.join(asset)
		.on(gl_entry.against_voucher == asset.name)
		.select(group_column, *_depreciation_columns(asset, gl_entry, filters))
		.where(asset.docstatus == 1)
		.where(asset.company == filters.company)
		.where(asset.purchase_date <= filters.to_date)
		.where(gl_entry.is_cancelled == 0)
		.where(_account_of_type(gl_entry.account, DEPRECIATION))  # ISS-2026-00184
		.groupby(group_by)
	)

	from_opening_depreciation_query = (
		frappe.qb.from_(asset)
		.select(group_column, *_opening_depreciation_columns(asset, filters))
		.where(asset.docstatus == 1)
		.where(asset.company == filters.company)
		.where(asset.purchase_date <= filters.to_date)
		.groupby(group_by)
	)

	if group_field == "asset_category" and filters.get("asset_category"):
		from_gl_entries_query = from_gl_entries_query.where(
			asset.asset_category == filters.get("asset_category")
		)
		from_opening_depreciation_query = from_opening_depreciation_query.where(
			asset.asset_category == filters.get("asset_category")
		)
	if group_field == "asset" and filters.get("asset"):
		from_gl_entries_query = from_gl_entries_query.where(asset.name == filters.get("asset"))
		from_opening_depreciation_query = from_opening_depreciation_query.where(
			asset.name == filters.get("asset")
		)

	from_gl_entries_query = from_gl_entries_query.where(get_finance_book_condition(gl_entry, filters))
	if assets_with_finance_book is not None:
		from_gl_entries_query = from_gl_entries_query.where(asset.name.isin(assets_with_finance_book))
		from_opening_depreciation_query = from_opening_depreciation_query.where(
			asset.name.isin(assets_with_finance_book)
		)

	combined = {}

	for row in from_gl_entries_query.run(as_dict=True):
		combined[row[group_field]] = {
			group_field: row[group_field],
			"accumulated_depreciation_as_on_from_date": flt(row.accumulated_depreciation_as_on_from_date),
			"depreciation_eliminated_via_reversal": flt(row.depreciation_eliminated_via_reversal),
			"depreciation_eliminated_during_the_period": flt(row.depreciation_eliminated_during_the_period),
			"depreciation_amount_during_the_period": flt(row.depreciation_amount_during_the_period),
		}

	for row in from_opening_depreciation_query.run(as_dict=True):
		if row[group_field] not in combined:
			combined[row[group_field]] = {
				group_field: row[group_field],
				"accumulated_depreciation_as_on_from_date": 0.0,
				"depreciation_eliminated_via_reversal": 0.0,
				"depreciation_eliminated_during_the_period": 0.0,
				"depreciation_amount_during_the_period": 0.0,
			}

		combined[row[group_field]]["accumulated_depreciation_as_on_from_date"] += flt(
			row.accumulated_depreciation_as_on_from_date
		)
		combined[row[group_field]]["depreciation_eliminated_during_the_period"] += flt(
			row.depreciation_eliminated_during_the_period
		)

	return list(combined.values())


def adb_assets_for_grouped_by_category(filters):
	return _assets_depreciation(filters, "asset_category")


def adb_assets_for_grouped_by_asset(filters):
	return _assets_depreciation(filters, "asset")


def _value_adjustments(filters, group_field: str):
	"""16.61 get_asset_value_adjustment_map_by_category / get_asset_value_adjustment_map."""
	from erpnext.accounts.report.asset_depreciations_and_balances.asset_depreciations_and_balances import (
		get_finance_book_condition,
		get_value_adjustment_columns,
	)

	asset = frappe.qb.DocType("Asset")
	gl_entry = frappe.qb.DocType("GL Entry")
	group_column = (
		asset.asset_category.as_("asset_category")
		if group_field == "asset_category"
		else asset.name.as_("asset")
	)
	group_by = asset.asset_category if group_field == "asset_category" else asset.name

	rows = (
		frappe.qb.from_(gl_entry)
		.join(asset)
		.on(gl_entry.against_voucher == asset.name)
		.select(group_column, *get_value_adjustment_columns(asset, gl_entry, filters))
		.where(gl_entry.is_cancelled == 0)
		.where(asset.docstatus == 1)
		.where(asset.company == filters.company)
		.where(asset.purchase_date <= filters.to_date)
		.where(_account_of_type(gl_entry.account, FIXED_ASSET))  # ISS-2026-00184
		.where(gl_entry.is_opening == "No")
		.where(get_finance_book_condition(gl_entry, filters))
		.groupby(group_by)
	).run(as_dict=True)

	return {row.pop(group_field): row for row in rows}


def adb_value_adjustment_map_by_category(filters):
	return _value_adjustments(filters, "asset_category")


def adb_value_adjustment_map(filters):
	return _value_adjustments(filters, "asset")
