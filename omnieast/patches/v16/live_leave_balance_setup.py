"""Live leave balance set-up (omnieast/leave/live_balance.py), run once:

  - an index for the leave ledger, which every leave save now reads per employee and leave type;
  - "Leave Eligible Days" on the employee master, filled for everyone who has an Annual Leave balance for 2026;
  - "Block Leave Beyond Earned Balance" in HR Settings, switched on;
  - any next-year balances HR has already opened by hand, brought onto the live carry-over.

Next year's balances themselves are opened by the nightly job (live_balance.open_next_year), not here.
"""

import json
import os
from datetime import date

import frappe
from frappe.modules.utils import sync_customizations_for_doctype
from frappe.utils import cint, flt, getdate

from omnieast.leave import live_balance as live


def execute():
	add_ledger_indexes()
	ensure_field("Employee", live.ENTITLEMENT_FIELD, "employee.json")
	ensure_field(live.SETTINGS_DOCTYPE, live.BLOCK_FIELD, "hr_settings.json")

	# a plain value write: nothing else in HR Settings is touched or re-validated
	frappe.db.set_single_value(live.SETTINGS_DOCTYPE, live.BLOCK_FIELD, 1, update_modified=False)
	fill_master()

	rows = frappe.get_all(
		"Leave Allocation",
		filters={"docstatus": 1, "from_date": (">=", date(live.FIRST_LIVE_YEAR, 1, 1))},
		fields=["employee", "leave_type"],
	)
	for employee, leave_type in sorted(set((r.employee, r.leave_type) for r in rows)):
		if live.is_live_type(leave_type):
			live.sync(employee, leave_type)


def add_ledger_indexes():
	"""Every leave save reads the ledger per employee and leave type; cancelling and carry-over updates
	find rows by the document they belong to."""
	frappe.db.add_index("Leave Ledger Entry", ["employee", "leave_type"], "employee_leave_type_index")
	if not frappe.db.get_column_index("tabLeave Ledger Entry", "transaction_name"):
		frappe.db.add_index("Leave Ledger Entry", ["transaction_name"], "transaction_name_index")


def ensure_field(doctype, fieldname, filename):
	"""Post-model-sync patches run before the app's customizations are synced; add the field first."""
	if frappe.get_meta(doctype).has_field(fieldname):
		return

	folder = frappe.get_app_path("omnieast", "omnieast", "custom")
	with open(os.path.join(folder, filename)) as f:
		sync_customizations_for_doctype(json.load(f), folder, filename)
	frappe.clear_cache(doctype=doctype)


def fill_master():
	"""Employee master, "Leave Eligible Days", for everyone who has an Annual Leave balance for the year
	before the first live one (2026):
	  - given exactly 21 or exactly 30 new days for that year: the same figure;
	  - given any other figure (joined during the year and so on): 30 with five or more years of
	    service on 1 January of the first live year, otherwise 21.
	Employees without a balance that year are left empty, and a figure already filled in is kept."""
	field = live.ENTITLEMENT_FIELD
	year = live.FIRST_LIVE_YEAR - 1
	given = {}
	for leave_type in live.live_leave_types():
		rows = frappe.get_all(
			"Leave Allocation",
			filters={"leave_type": leave_type, "docstatus": 1,
				"from_date": ("between", [date(year, 1, 1), date(year, 12, 31)])},
			fields=["employee", "new_leaves_allocated"],
			order_by="from_date asc, creation asc",
		)
		for row in rows:
			given.setdefault(row.employee, flt(row.new_leaves_allocated))

	set_to = {21: 0, 30: 0}
	kept = 0
	names = sorted(given)
	for i in range(0, len(names), 500):
		employees = frappe.get_all(
			"Employee", filters={"name": ("in", names[i:i + 500])}, fields=["name", "date_of_joining", field]
		)
		for employee in employees:
			if cint(employee.get(field)):
				kept += 1
				continue
			days = master_days_for(given[employee.name], employee.date_of_joining, date(year + 1, 1, 1))
			frappe.db.set_value("Employee", employee.name, field, days, update_modified=False)
			set_to[days] += 1
	print("Leave Eligible Days: {0} employees set to 21, {1} set to 30, {2} already filled in".format(
		set_to[21], set_to[30], kept))


def master_days_for(given_days, date_of_joining, on_date):
	"""21 or 30 days a year, from what the person was given and their years of service on a date."""
	for days in (21, 30):
		if abs(flt(given_days) - days) < 0.001:
			return days
	return 30 if years_of_service(date_of_joining, on_date) >= 5 else 21


def years_of_service(date_of_joining, on_date):
	if not date_of_joining:
		return 0
	joined = getdate(date_of_joining)
	return on_date.year - joined.year - (1 if (on_date.month, on_date.day) < (joined.month, joined.day) else 0)
