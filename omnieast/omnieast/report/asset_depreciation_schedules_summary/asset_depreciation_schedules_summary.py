# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

"""ISS-2026-00154: Asset Depreciation Schedules Summary, ported from JAWA Logistics (v13).

Opening: depreciation accumulated before the Start Date. Depreciated: the scheduled depreciation from the
Start to the End Date, booked or not, as on v13. Asset Value: Gross Purchase Amount less the accumulated.
Only assets with a scheduled depreciation in the period are listed.
"""

import frappe
from frappe import _
from frappe.query_builder import DocType, Order
from frappe.query_builder.functions import Sum
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_data(filters):
	assets = get_assets(filters)
	if not assets:
		return []

	opening = get_opening_depreciation([d.schedule for d in assets], filters.from_date)
	suppliers = get_suppliers(assets)

	data = []
	for d in assets:
		opening_accumulated_depreciation = opening.get(d.schedule, flt(d.opening_accumulated_depreciation))
		accumulated_depreciation_amount = opening_accumulated_depreciation + flt(d.depreciated_amount)
		data.append(
			{
				"asset_id": d.asset_id,
				"asset_name": d.asset_name,
				"asset_category": d.asset_category,
				"purchase_date": d.purchase_date,
				"available_for_use_date": d.available_for_use_date,
				"status": d.status,
				"gross_purchase_amount": d.net_purchase_amount,
				"opening_accumulated_depreciation": opening_accumulated_depreciation,
				"depreciated_amount": flt(d.depreciated_amount),
				"accumulated_depreciation_amount": accumulated_depreciation_amount,
				"asset_value": flt(d.net_purchase_amount) - accumulated_depreciation_amount,
				"cost_center": d.cost_center,
				"vendor_name": suppliers["Purchase Receipt"].get(d.purchase_receipt)
				or suppliers["Purchase Invoice"].get(d.purchase_invoice),
				"location": d.location,
			}
		)

	return data


def get_assets(filters):
	"""Submitted assets with their scheduled depreciation in the period, one row per asset."""
	asset = DocType("Asset")
	ads = DocType("Asset Depreciation Schedule")
	ds = DocType("Depreciation Schedule")

	query = (
		frappe.qb.from_(asset)
		.join(ads)
		.on(ads.asset == asset.name)
		.join(ds)
		.on((ds.parent == ads.name) & (ds.parenttype == "Asset Depreciation Schedule"))
		.select(
			asset.name.as_("asset_id"),
			asset.asset_name,
			asset.asset_category,
			asset.purchase_date,
			asset.available_for_use_date,
			asset.status,
			asset.net_purchase_amount,
			asset.cost_center,
			asset.location,
			asset.purchase_receipt,
			asset.purchase_invoice,
			ads.name.as_("schedule"),
			ads.opening_accumulated_depreciation,
			Sum(ds.depreciation_amount).as_("depreciated_amount"),
		)
		.where(asset.docstatus == 1)
		# the asset's schedule for the book; a sale, repair or value adjustment cancels it and submits a new one
		.where((ads.docstatus == 1) & (ads.status == "Active"))
		.where(asset.company == filters.company)
		.where(ds.schedule_date.between(filters.from_date, filters.to_date))
		.groupby(ads.name)
		.orderby(asset.name)
	)

	if filters.asset:
		query = query.where(asset.name == filters.asset)
	if filters.asset_category:
		query = query.where(asset.asset_category == filters.asset_category)
	if filters.cost_center:
		query = query.where(asset.cost_center == filters.cost_center)

	return query.run(as_dict=True)


def get_opening_depreciation(schedules, from_date):
	"""Accumulated depreciation of each schedule's last row before from_date."""
	ds = DocType("Depreciation Schedule")
	rows = (
		frappe.qb.from_(ds)
		.select(ds.parent, ds.accumulated_depreciation_amount)
		.where(ds.parenttype == "Asset Depreciation Schedule")
		.where(ds.parent.isin(schedules))
		.where(ds.schedule_date < from_date)
		.orderby(ds.schedule_date, order=Order.asc)
		.orderby(ds.idx, order=Order.asc)
		.run(as_dict=True)
	)
	# a later row replaces the earlier one
	return {d.parent: flt(d.accumulated_depreciation_amount) for d in rows}


def get_suppliers(assets):
	"""Supplier of the assets' Purchase Receipts and Purchase Invoices: submitted, not a return,
	with a fixed asset item."""
	suppliers = {}
	for doctype, field in (
		("Purchase Receipt", "purchase_receipt"),
		("Purchase Invoice", "purchase_invoice"),
	):
		suppliers[doctype] = {}
		names = list({d[field] for d in assets if d[field]})
		if not names:
			continue

		parent = DocType(doctype)
		item = DocType(f"{doctype} Item")
		suppliers[doctype] = dict(
			frappe.qb.from_(parent)
			.join(item)
			.on((item.parent == parent.name) & (item.parenttype == doctype))
			.select(parent.name, parent.supplier)
			.distinct()
			.where(parent.name.isin(names))
			.where(parent.docstatus == 1)
			.where(parent.is_return == 0)
			.where(item.is_fixed_asset == 1)
			.run()
		)

	return suppliers


def get_columns():
	return [
		{
			"label": _("Asset Id"),
			"fieldtype": "Link",
			"fieldname": "asset_id",
			"options": "Asset",
			"width": 160,
		},
		{
			"label": _("Asset Name"),
			"fieldtype": "Data",
			"fieldname": "asset_name",
			"width": 140,
		},
		{
			"label": _("Asset Category"),
			"fieldtype": "Link",
			"fieldname": "asset_category",
			"options": "Asset Category",
			"width": 100,
		},
		{
			"label": _("Purchase Date"),
			"fieldtype": "Date",
			"fieldname": "purchase_date",
			"width": 90,
		},
		{
			"label": _("Available For Use Date"),
			"fieldtype": "Date",
			"fieldname": "available_for_use_date",
			"width": 90,
		},
		{
			"label": _("Status"),
			"fieldtype": "Data",
			"fieldname": "status",
			"width": 100,
		},
		{
			"label": _("Gross Purchase Amount"),
			"fieldname": "gross_purchase_amount",
			"fieldtype": "Currency",
			"options": "company:currency",
			"width": 130,
		},
		{
			"label": _("Opening Accumulated Depreciation"),
			"fieldname": "opening_accumulated_depreciation",
			"fieldtype": "Currency",
			"options": "company:currency",
			"width": 130,
		},
		{
			"label": _("Depreciated Amount"),
			"fieldname": "depreciated_amount",
			"fieldtype": "Currency",
			"options": "company:currency",
			"width": 100,
		},
		{
			"label": _("Accumulated Depreciation Amount"),
			"fieldname": "accumulated_depreciation_amount",
			"fieldtype": "Currency",
			"options": "company:currency",
			"width": 130,
		},
		{
			"label": _("Asset Value"),
			"fieldname": "asset_value",
			"fieldtype": "Currency",
			"options": "company:currency",
			"width": 100,
		},
		{
			"label": _("Cost Center"),
			"fieldtype": "Link",
			"fieldname": "cost_center",
			"options": "Cost Center",
			"width": 100,
		},
		{
			"label": _("Vendor Name"),
			"fieldtype": "Data",
			"fieldname": "vendor_name",
			"width": 100,
		},
		{
			"label": _("Location"),
			"fieldtype": "Link",
			"fieldname": "location",
			"options": "Location",
			"width": 100,
		},
	]
