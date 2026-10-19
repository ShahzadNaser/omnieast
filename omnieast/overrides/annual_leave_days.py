"""Annual Leave day count (Oct 2026).

Weekends inside an Annual Leave are part of the leave and come off the Annual Leave balance.
Public holidays (Eid, Saudi National Day: Holiday List rows not marked Weekly Off) are not counted.
Applies to leave types with "Annual" in the name, always (no switch); every other leave type keeps
the HRMS count and the optional "Count weekends as leave days" switch in HR Settings.
"""

import frappe
from frappe.utils import cint, date_diff, flt, getdate

from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.utils.holiday_list import get_holiday_list_for_employee


def applies(leave_type):
	if not leave_type or "annual" not in leave_type.lower():
		return False
	return not cint(frappe.get_cached_value("Leave Type", leave_type, "is_lwp"))


def count_annual_leave_days(employee, from_date, to_date, half_day=None, half_day_date=None, holiday_list=None):
	"""Calendar days of the leave minus the public holidays inside it."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if to_date < from_date:
		return 0

	days = date_diff(to_date, from_date) + 1
	if cint(half_day):
		if from_date == to_date:
			days = 0.5
		elif half_day_date and from_date <= getdate(half_day_date) <= to_date:
			days -= 0.5

	holiday_list = holiday_list or get_holiday_list_for_employee(employee, raise_exception=False, as_on=from_date)
	if holiday_list:
		days -= frappe.db.count(
			"Holiday",
			{
				"parent": holiday_list,
				"parenttype": "Holiday List",
				"weekly_off": 0,
				"holiday_date": ["between", [from_date, to_date]],
			},
		)

	return max(flt(days), 0)


def _should_apply(doc):
	if not (doc.employee and doc.leave_type and doc.from_date and doc.to_date):
		return False
	if doc.docstatus == 2 or doc.status in ("Rejected", "Cancelled"):
		return False
	return applies(doc.leave_type)


def validate(doc, method=None):
	"""Leave Application validate (runs after HRMS has worked out its own total)."""
	if not _should_apply(doc):
		return

	days = count_annual_leave_days(doc.employee, doc.from_date, doc.to_date, doc.half_day, doc.half_day_date)
	if flt(days) == flt(doc.total_leave_days):
		return

	doc.total_leave_days = days
	_validate_balance(doc)


def on_submit(doc, method=None):
	"""Book the weekend days in the leave ledger where HRMS booked fewer days.

	HRMS books Total Leave Days, except when the leave crosses an allocation or a carry-forward
	expiry; it then recounts each part itself, and the difference is booked here.
	"""
	if doc.status != "Approved" or not _should_apply(doc):
		return

	booked = -sum(
		flt(leaves)
		for leaves in frappe.get_all(
			"Leave Ledger Entry",
			filters={
				"transaction_type": "Leave Application",
				"transaction_name": doc.name,
				"docstatus": 1,
				"leaves": ["<", 0],
			},
			pluck="leaves",
		)
	)
	missing = flt(doc.total_leave_days) - booked
	if missing < 0.01:
		return

	create_leave_ledger_entry(
		doc,
		dict(
			leaves=missing * -1,
			from_date=doc.to_date,
			to_date=doc.to_date,
			is_lwp=0,
			holiday_list=get_holiday_list_for_employee(doc.employee, raise_exception=False, as_on=doc.to_date)
			or "",
		),
	)


def _validate_balance(doc):
	"""HRMS checked the balance against its own total; check it again with ours."""
	if doc.status == "Rejected":
		return

	precision = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 2
	leave_balance = get_leave_balance_on(
		doc.employee,
		doc.leave_type,
		doc.from_date,
		doc.to_date,
		consider_all_leaves_in_the_allocation_period=True,
		for_consumption=True,
		leave_application=None if doc.is_new() else doc.name,
	)
	doc.leave_balance = leave_balance.get("leave_balance")
	for_consumption = flt(leave_balance.get("leave_balance_for_consumption"), precision)

	if for_consumption < flt(doc.total_leave_days) or not for_consumption:
		doc.show_insufficient_balance_message(for_consumption)
