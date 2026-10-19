"""Weekend inside leave (ISS-2026-00130).

Switched on in HR Settings > Leaves > "Count weekends as leave days". It can only be switched on
together with the acknowledgement that it may not comply with the Saudi Labor Law. HR Settings
tracks changes, so its Version log shows who switched it on or off and when; the form also shows
"Enabled By" and "Enabled On".

While it is on, for leave types other than Business Trip, leave without pay and optional leave:
1. A leave that ends on the last working day before the weekend runs through the weekend
   (Wednesday-Thursday becomes Wednesday-Saturday, duty resumes Sunday).
2. Weekly offs inside a leave count as leave days. Public holidays still follow the Leave Type's
   "Include holidays within leaves as leaves".
3. A leave cannot be split around a weekend: it is refused when the employee has a leave of the
   same type on the other side of the weekend; they must apply for one leave instead.
The weekend is read from the employee's Holiday List (rows marked Weekly Off), not hard-coded.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, get_link_to_form, get_weekday, getdate, now_datetime

from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.utils.holiday_list import get_holiday_dates_between_range, get_holiday_list_for_employee

# HR Settings custom fields (omnieast/omnieast/custom/hr_settings.json)
ENABLE_FIELD = "custom_count_weekend_in_leave"
ACK_FIELD = "custom_weekend_leave_acknowledged"
ENABLED_BY_FIELD = "custom_weekend_leave_enabled_by"
ENABLED_ON_FIELD = "custom_weekend_leave_enabled_on"

# A business trip is not leave; its per diem is also worked out from the leave days.
EXCLUDED_LEAVE_TYPES = {"Business Trip"}

# How far around a leave to read the Holiday List when looking for its weekend.
SEARCH_WINDOW_DAYS = 31


# Settings
# --------


def is_enabled():
	meta = frappe.get_meta("HR Settings")
	if not (meta.has_field(ENABLE_FIELD) and meta.has_field(ACK_FIELD)):
		return False

	return bool(
		cint(frappe.db.get_single_value("HR Settings", ENABLE_FIELD))
		and cint(frappe.db.get_single_value("HR Settings", ACK_FIELD))
	)


def validate_hr_settings(doc, method=None):
	"""HR Settings: the rule can only be switched on with the acknowledgement ticked."""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return
	if not doc.meta.has_field(ENABLE_FIELD):
		return

	if not cint(doc.get(ENABLE_FIELD)):
		# switched off: whoever switches it on again must acknowledge again
		doc.set(ACK_FIELD, 0)
		doc.set(ENABLED_BY_FIELD, None)
		doc.set(ENABLED_ON_FIELD, None)
		return

	if not cint(doc.get(ACK_FIELD)):
		frappe.throw(
			_(
				"To count weekends as leave days, tick the acknowledgement that this may not comply with the Saudi Labor Law and that you take responsibility for enabling it."
			),
			title=_("Acknowledgement Required"),
		)

	before = doc.get_doc_before_save()
	if not (before and cint(before.get(ENABLE_FIELD))) or not doc.get(ENABLED_BY_FIELD):
		doc.set(ENABLED_BY_FIELD, frappe.session.user)
		doc.set(ENABLED_ON_FIELD, now_datetime())


def rule_applies(leave_type):
	if not leave_type or leave_type in EXCLUDED_LEAVE_TYPES:
		return False

	flags = frappe.get_cached_value("Leave Type", leave_type, ["is_lwp", "is_optional_leave"], as_dict=True)
	if not flags:
		return False

	return not (cint(flags.is_lwp) or cint(flags.is_optional_leave))


def get_holiday_map(employee, start_date, end_date):
	"""{date: 1 for a weekly off, 0 for any other holiday} from the employee's Holiday List."""
	holidays = get_holiday_dates_between_range(
		employee, start_date, end_date, raise_exception_for_holiday_list=False, as_dict=True
	)

	holiday_map = {}
	for holiday in holidays:
		day = getdate(holiday.holiday_date)
		holiday_map[day] = max(holiday_map.get(day, 0), cint(holiday.weekly_off))

	return holiday_map


def get_weekend_days_to_add(employee, leave_type, from_date, to_date):
	"""Weekly offs inside the leave that HRMS leaves out of the leave days; 0 while the rule is off."""
	if not (employee and leave_type and from_date and to_date):
		return 0
	if not (rule_applies(leave_type) and is_enabled()):
		return 0
	from omnieast.overrides.annual_leave_days import applies as annual_leave_applies
	if annual_leave_applies(leave_type):
		# Annual Leave already counts its weekends (annual_leave_days.py)
		return 0
	if cint(frappe.get_cached_value("Leave Type", leave_type, "include_holiday")):
		# HRMS already counts every holiday inside a leave of this type
		return 0

	from_date, to_date = getdate(from_date), getdate(to_date)
	if to_date < from_date:
		return 0

	holiday_map = get_holiday_map(employee, from_date, to_date)
	return sum(1 for day, weekly_off in holiday_map.items() if weekly_off and from_date <= day <= to_date)


# Leave Application
# -----------------


def before_validate(doc, method=None):
	"""Run the leave through the weekend and refuse a leave split around a weekend."""
	if not _should_apply(doc):
		return

	from_date, to_date = getdate(doc.from_date), getdate(doc.to_date)
	if to_date < from_date:
		return  # HRMS reports the wrong dates

	holiday_map = get_holiday_map(
		doc.employee, add_days(from_date, -SEARCH_WINDOW_DAYS), add_days(to_date, SEARCH_WINDOW_DAYS)
	)
	if not holiday_map:
		return

	_extend_through_weekend(doc, from_date, to_date, holiday_map)
	_refuse_split_around_weekend(doc, holiday_map)


def validate(doc, method=None):
	"""Count the weekly offs inside the leave as leave days (HRMS has worked out the total by now)."""
	if not _should_apply(doc):
		return

	weekend_days = get_weekend_days_to_add(doc.employee, doc.leave_type, doc.from_date, doc.to_date)
	if not weekend_days:
		return

	doc.total_leave_days = flt(doc.total_leave_days) + weekend_days
	_validate_balance(doc)

	before = doc.get_doc_before_save()
	if not before or flt(before.total_leave_days) != flt(doc.total_leave_days):
		frappe.msgprint(
			_("{0} weekend day(s) inside this leave are counted as leave days.").format(weekend_days),
			indicator="blue",
			alert=True,
		)


def on_submit(doc, method=None):
	"""Book the counted weekend days in the leave ledger where HRMS booked fewer days.

	HRMS books Total Leave Days, except when the leave crosses an allocation or a carry-forward
	expiry; it then recounts each part without the weekend, and the difference is booked here.
	Cancelling the leave removes this entry together with the HRMS ones.
	"""
	if doc.status != "Approved" or not _should_apply(doc):
		return
	if not get_weekend_days_to_add(doc.employee, doc.leave_type, doc.from_date, doc.to_date):
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


def _should_apply(doc):
	if not (doc.employee and doc.leave_type and doc.from_date and doc.to_date):
		return False
	if doc.docstatus == 2 or doc.status in ("Rejected", "Cancelled"):
		return False

	return rule_applies(doc.leave_type) and is_enabled()


def _extend_through_weekend(doc, from_date, to_date, holiday_map):
	last_working_day = _last_working_day(to_date, from_date, holiday_map)
	if last_working_day in holiday_map:
		return  # the leave has no working day

	if cint(doc.half_day) and doc.half_day_date and getdate(doc.half_day_date) == last_working_day:
		return  # only half of the last working day is leave: the employee is back at work that day

	day_after = add_days(last_working_day, 1)
	if not holiday_map.get(day_after):
		return  # the last working day is not followed by a weekend

	new_to_date = day_after
	while add_days(new_to_date, 1) in holiday_map:
		new_to_date = add_days(new_to_date, 1)

	if new_to_date <= to_date:
		return

	doc.to_date = new_to_date
	resume_date = add_days(new_to_date, 1)
	frappe.msgprint(
		_(
			"{0} {1} is the last working day before the weekend, so the weekend is part of this leave. The leave now ends on {2} {3} and duty resumes on {4} {5}."
		).format(
			_(get_weekday(last_working_day)),
			formatdate(last_working_day),
			_(get_weekday(new_to_date)),
			formatdate(new_to_date),
			_(get_weekday(resume_date)),
			formatdate(resume_date),
		),
		title=_("Weekend Added to Leave"),
		indicator="orange",
	)


def _refuse_split_around_weekend(doc, holiday_map):
	from_date, to_date = getdate(doc.from_date), getdate(doc.to_date)

	# Weekend just before the leave: no leave may end on it or on the working day before it.
	first_working_day = from_date
	while first_working_day in holiday_map and first_working_day < to_date:
		first_working_day = add_days(first_working_day, 1)
	working_day_before = add_days(first_working_day, -1)
	while working_day_before in holiday_map:
		working_day_before = add_days(working_day_before, -1)

	if _has_weekly_off(add_days(working_day_before, 1), add_days(first_working_day, -1), holiday_map):
		other = _find_leave(doc, "to_date", working_day_before, add_days(from_date, -1))
		if other:
			_throw_split(doc, other)

	# Weekend just after the leave: no leave may start on it or on the working day after it.
	last_working_day = _last_working_day(to_date, from_date, holiday_map)
	working_day_after = add_days(last_working_day, 1)
	while working_day_after in holiday_map:
		working_day_after = add_days(working_day_after, 1)

	if _has_weekly_off(add_days(last_working_day, 1), add_days(working_day_after, -1), holiday_map):
		other = _find_leave(doc, "from_date", add_days(to_date, 1), working_day_after)
		if other:
			_throw_split(doc, other)


def _last_working_day(to_date, from_date, holiday_map):
	"""Last day of the leave that is not a holiday (from_date when every day is a holiday)."""
	day = to_date
	while day in holiday_map and day > from_date:
		day = add_days(day, -1)
	return day


def _has_weekly_off(start_date, end_date, holiday_map):
	day = start_date
	while day <= end_date:
		if holiday_map.get(day):
			return True
		day = add_days(day, 1)
	return False


def _find_leave(doc, fieldname, start_date, end_date):
	if start_date > end_date:
		return None

	filters = {
		"employee": doc.employee,
		"leave_type": doc.leave_type,
		"docstatus": ["<", 2],
		"status": ["in", ["Open", "Approved"]],
		fieldname: ["between", [start_date, end_date]],
	}
	if not doc.is_new():
		filters["name"] = ["!=", doc.name]

	leaves = frappe.get_all(
		"Leave Application", filters=filters, fields=["name", "from_date", "to_date"], limit=1
	)
	return leaves[0] if leaves else None


def _throw_split(doc, other):
	frappe.throw(
		_(
			"{0} already has {1} leave {2} from {3} to {4}, on the other side of this weekend. Please combine them into one leave application instead of splitting the leave around the weekend."
		).format(
			frappe.bold(doc.employee_name or doc.employee),
			doc.leave_type,
			get_link_to_form("Leave Application", other.name),
			formatdate(other.from_date),
			formatdate(other.to_date),
		),
		title=_("Leave Split Around the Weekend"),
	)


def _validate_balance(doc):
	"""HRMS checked the balance against the total without the weekend; check it again with it."""
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
	leave_balance_for_consumption = flt(leave_balance.get("leave_balance_for_consumption"), precision)

	if leave_balance_for_consumption < flt(doc.total_leave_days) or not leave_balance_for_consumption:
		doc.show_insufficient_balance_message(leave_balance_for_consumption)
