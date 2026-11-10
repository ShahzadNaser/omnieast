"""Live leave balance: next year is open while this year is still running.

What this module does for Annual Leave:

  1. Next year's balance is opened automatically (every night from October, and on the spot when someone
     applies for a date in a year that is not open yet). There is no year-end closing run.
     The days of the new year come from the employee master (Leave Eligible Days). Where the master is
     empty the year opens with the carry-over only, and follows the master once HR fills it in.
  2. The carry-over into a year is the closing balance of the year before it and is recalculated every
     time a leave is approved or cancelled or a balance is changed in that earlier year.
  3. The years are one pool of days: a leave is refused when it would leave a shortage on its own dates
     or on a leave already booked later (also in the next year).
  4. With "Block Leave Beyond Earned Balance" ticked in HR Settings, a leave can only use the
     carried-over balance plus the days earned up to its start date.
  5. A leave that runs across New Year is one application; its days are split per year in the ledger.

Years before FIRST_LIVE_YEAR keep the carry-over they were given and are never recalculated.
People with 365 days a year (leave not tracked) get 365 again, with no carry-over and no earned rule.
Leave days are counted as everywhere else for Annual Leave: calendar days less public holidays
(omnieast/overrides/annual_leave_days.py). Every other leave type is left to the standard code.
The arithmetic is in balance_engine.py; this file reads and writes the documents. It is wired in through
omnieast/overrides/live_leave_balance.py and hooks.py.
"""

import time
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate

from hrms.hr.doctype.leave_application.leave_application import InsufficientLeaveBalanceError
from hrms.hr.doctype.leave_ledger_entry.leave_ledger_entry import create_leave_ledger_entry
from hrms.utils.holiday_list import get_holiday_list_for_employee

from omnieast.leave import balance_engine as engine
from omnieast.overrides.annual_leave_days import applies as is_annual_leave
from omnieast.overrides.annual_leave_days import count_annual_leave_days

# Carry-over INTO this year and later is live. The year before it is the first one whose leaves are
# re-read on every change; anything older stays as it was closed.
FIRST_LIVE_YEAR = 2027

SETTINGS_DOCTYPE = "HR Settings"
BLOCK_FIELD = "custom_block_leave_beyond_earned_balance"
# Employee master: days of Annual Leave a year
ENTITLEMENT_FIELD = "leave_eligible_days"
# The nightly job opens next year for everyone from this month on
OPEN_FROM_MONTH = 10
# Employees who get next year opened by the nightly job (anyone else gets it when they apply)
OPEN_FOR_STATUS = ("Active",)
AUTO_NOTE = "Opened automatically from the previous year"
# written after AUTO_NOTE with the days the year was opened with, e.g. " (21 days from the employee master)"
MASTER_NOTE = " ({0} days from the employee master)"
JOB = "omnieast.leave.live_balance.open_next_year"
# Ledger rows that add to (or reduce) a year's balance; every other row that takes days out is leave used
BALANCE_DOCTYPES = ("Leave Allocation", "Leave Adjustment")


# ------------------------------------------------------------------ what is covered

def is_live_type(leave_type):
	"""Annual Leave (the same test as for its day count) that is set to carry forward."""
	if not is_annual_leave(leave_type):
		return False
	return bool(cint(frappe.get_cached_value("Leave Type", leave_type, "is_carry_forward")))


def live_leave_types():
	names = frappe.get_all("Leave Type", filters={"is_carry_forward": 1, "is_lwp": 0}, pluck="name")
	return sorted(name for name in names if is_live_type(name))


def covers(leave_type, on_date):
	"""True when a leave or balance on this date takes part in the live flow."""
	return bool(on_date) and getdate(on_date).year >= FIRST_LIVE_YEAR - 1 and is_live_type(leave_type)


def block_beyond_earned():
	"""HR Settings > Block Leave Beyond Earned Balance. The rule is on until HR unticks it."""
	if not frappe.get_meta(SETTINGS_DOCTYPE).has_field(BLOCK_FIELD):
		return 1
	return cint(frappe.db.get_single_value(SETTINGS_DOCTYPE, BLOCK_FIELD))


def earned_only(leave_type):
	return is_live_type(leave_type) and bool(block_beyond_earned())


def master_days(employee):
	if not frappe.get_meta("Employee").has_field(ENTITLEMENT_FIELD):
		return 0.0
	return flt(frappe.db.get_value("Employee", employee, ENTITLEMENT_FIELD))


# ------------------------------------------------------------------ reading

def load(employee, leave_type, exclude=None):
	"""Everything about one employee's leave type from FIRST_LIVE_YEAR - 1 on.
	exclude: a Leave Application whose own ledger rows are left out."""
	start = date(FIRST_LIVE_YEAR - 1, 1, 1)
	allocations = frappe.get_all(
		"Leave Allocation",
		filters={"employee": employee, "leave_type": leave_type, "docstatus": 1, "to_date": (">=", start)},
		fields=["name", "from_date", "to_date", "new_leaves_allocated", "unused_leaves", "carry_forward",
			"total_leaves_allocated"],
		order_by="from_date asc, creation asc",
	)
	ledger = frappe.get_all(
		"Leave Ledger Entry",
		filters={"employee": employee, "leave_type": leave_type, "docstatus": 1, "is_expired": 0,
			"to_date": (">=", start)},
		fields=["name", "transaction_type", "transaction_name", "from_date", "leaves", "is_carry_forward"],
	)
	rate = master_days(employee)

	by_year = {}
	alloc_by_year = {}
	for a in allocations:
		y = getdate(a.from_date).year
		alloc_by_year.setdefault(y, []).append(a)
		by_year.setdefault(y, engine.Year(y, rate_days=rate))
	for row in ledger:
		y = getdate(row.from_date).year
		if y not in by_year:
			continue  # no balance that year: nothing to test a leave against
		if row.transaction_type in BALANCE_DOCTYPES:
			# the year's own days, the carry-over, and any Leave Adjustment made to the year
			if cint(row.is_carry_forward):
				by_year[y].carry += flt(row.leaves)
			else:
				by_year[y].base += flt(row.leaves)
		elif flt(row.leaves) < 0:
			# days taken out of the balance: a leave, or days paid out (Leave Encashment)
			if exclude and row.transaction_type == "Leave Application" and row.transaction_name == exclude:
				continue
			by_year[y].leaves.append((getdate(row.from_date), abs(flt(row.leaves)), row.transaction_name))

	years = [by_year[y] for y in sorted(by_year)]
	for y in years:
		previous = by_year.get(y.year - 1)
		y.live = bool(y.year >= FIRST_LIVE_YEAR and previous and not previous.unlimited and not y.unlimited)

	max_carry = flt(frappe.get_cached_value("Leave Type", leave_type, "maximum_carry_forwarded_leaves"))
	return frappe._dict(years=years, by_year=by_year, allocations=alloc_by_year, max_carry=max_carry)


# ------------------------------------------------------------------ carry-over, recalculated

def sync(employee, leave_type):
	"""Bring the stored carry-over of every live year in line with the closing balance of the year before
	it. Returns [(year, old, new)] for the years that changed."""
	if not is_live_type(leave_type):
		return []
	data = load(employee, leave_type)
	carried = engine.project(data.years, data.max_carry)
	changed = []
	for y in data.years:
		if not y.live:
			continue
		target = flt(carried[y.year][0], 3)
		rows = data.allocations[y.year]
		first = rows[0]
		in_line = (abs(target - y.carry) < engine.EPS and abs(flt(first.unused_leaves) - target) < engine.EPS
			and cint(first.carry_forward) == 1)
		if in_line:
			continue
		_write_carry(rows, data.allocations.get(y.year - 1) or [], target)
		changed.append((y.year, y.carry, target))
	return changed


def _write_carry(rows, previous_rows, target):
	"""Store a year's carry-over: on its ledger row and on the balance (Leave Allocation) it belongs to."""
	first = rows[0]
	names = [r.name for r in rows]
	entries = frappe.get_all(
		"Leave Ledger Entry",
		filters={"transaction_type": "Leave Allocation", "transaction_name": ("in", names),
			"is_carry_forward": 1, "is_expired": 0, "docstatus": 1},
		fields=["name", "transaction_name"],
		order_by="creation asc",
	)
	keep = next((e for e in entries if e.transaction_name == first.name), None)
	for e in entries:
		value = target if (keep and e.name == keep.name) else 0
		frappe.db.set_value("Leave Ledger Entry", e.name, "leaves", value, update_modified=False)
	if not keep and target:
		allocation = frappe.get_doc("Leave Allocation", first.name)
		create_leave_ledger_entry(allocation, dict(
			leaves=target, from_date=allocation.from_date, to_date=allocation.to_date, is_carry_forward=1,
		))

	for r in rows:
		carry = target if r.name == first.name else 0
		frappe.db.set_value("Leave Allocation", r.name, {
			"unused_leaves": carry,
			"carry_forward": 1 if r.name == first.name else cint(r.carry_forward),
			"total_leaves_allocated": flt(r.new_leaves_allocated) + carry,
		}, update_modified=False)
	if previous_rows:
		frappe.db.set_value("Leave Allocation", previous_rows[-1].name, "carry_forwarded_leaves_count", target,
			update_modified=False)


def after_leave_change(doc):
	"""Leave approved or cancelled: later years' carry-over follows."""
	if covers(doc.leave_type, doc.from_date):
		sync(doc.employee, doc.leave_type)


def after_allocation_change(doc):
	"""Balance added, changed or cancelled: later years' carry-over follows."""
	if covers(doc.leave_type, doc.from_date):
		sync(doc.employee, doc.leave_type)


def after_balance_document(doc, method=None):
	"""Leave Adjustment or Leave Encashment submitted or cancelled (hooks.py): both change the year's
	closing balance, so later years' carry-over follows."""
	on_date = doc.get("from_date") or doc.get("encashment_date") or doc.get("posting_date")
	if doc.get("employee") and covers(doc.get("leave_type"), on_date):
		sync(doc.employee, doc.leave_type)


# ------------------------------------------------------------------ opening a year

def entitlement(employee, previous_days):
	"""Days a person gets for a new year: the employee master, also when it is empty (0 days until HR
	fills it). People whose days are not tracked keep what they had."""
	if flt(previous_days) >= engine.UNLIMITED_DAYS:
		return flt(previous_days)
	if not frappe.get_meta("Employee").has_field(ENTITLEMENT_FIELD):
		return flt(previous_days)
	return master_days(employee)


def ensure_year(employee, leave_type, year):
	"""Open the year's balance for one person when it is missing. Returns the new Leave Allocation or None.
	Only a year right after one the person already has, and never further ahead than next year."""
	year = cint(year)
	if year < FIRST_LIVE_YEAR or year > getdate().year + 1 or not is_live_type(leave_type):
		return None
	start, end = date(year, 1, 1), date(year, 12, 31)
	if frappe.db.exists("Leave Allocation", {"employee": employee, "leave_type": leave_type, "docstatus": 1,
			"from_date": ("<=", end), "to_date": (">=", start)}):
		return None
	previous = frappe.get_all(
		"Leave Allocation",
		filters={"employee": employee, "leave_type": leave_type, "docstatus": 1,
			"from_date": ("between", [date(year - 1, 1, 1), date(year - 1, 12, 31)])},
		fields=["name", "new_leaves_allocated"],
		order_by="from_date desc",
		limit_page_length=1,
	)
	if not previous:
		return None  # no balance the year before: the first year is still given by HR
	days = max(0.0, entitlement(employee, previous[0].new_leaves_allocated))
	if not days:
		# nothing in the master: open the year for the carry-over alone, if there is any
		data = load(employee, leave_type)
		closing = engine.project(data.years, data.max_carry).get(year - 1, (0, 0))[1]
		if closing <= 0:
			return None

	doc = frappe.new_doc("Leave Allocation")
	doc.employee = employee
	doc.leave_type = leave_type
	doc.from_date = start
	doc.to_date = end
	doc.new_leaves_allocated = days
	doc.carry_forward = 0  # the carry-over is written, and kept up to date, by sync()
	doc.description = AUTO_NOTE + (MASTER_NOTE.format(_days(days)) if days < engine.UNLIMITED_DAYS else "")
	doc.flags.ignore_permissions = True
	if not days:
		# the standard checks refuse a balance of 0 days; here the carry-over is added right after submit
		doc.employee_name = frappe.db.get_value("Employee", employee, "employee_name")
		doc.unused_leaves = 0
		doc.total_leaves_allocated = 0
		doc.flags.ignore_validate = True
	doc.insert()
	doc.submit()
	return doc.name


def ensure_years_for(doc):
	"""Leave Application: open any year its dates touch that is not open yet."""
	if not (doc.employee and doc.from_date and doc.to_date and covers(doc.leave_type, doc.from_date)):
		return
	for year in range(getdate(doc.from_date).year, getdate(doc.to_date).year + 1):
		ensure_year(doc.employee, doc.leave_type, year)


def open_next_year(budget_seconds=1200):
	"""Nightly from October: open next year's balance for everyone who has one this year, and keep the
	balances it opened in line with the employee master until the year starts. Runs for a limited time
	and queues itself again until nobody is left."""
	today = getdate()
	year = today.year + 1
	if today.month < OPEN_FROM_MONTH or year < FIRST_LIVE_YEAR:
		return
	started = time.time()
	left = False
	for leave_type in live_leave_types():
		for employee in _waiting_for(leave_type, year):
			if time.time() - started > budget_seconds:
				left = True
				break
			try:
				ensure_year(employee, leave_type, year)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title="Leave year {0} not opened for {1}".format(year, employee),
					message=frappe.get_traceback())
				frappe.db.commit()
		if left:
			break
		follow_master(leave_type, year)
	if left:
		frappe.enqueue(JOB, queue="long", timeout=budget_seconds + 600, enqueue_after_commit=True)
		frappe.db.commit()


def _waiting_for(leave_type, year):
	"""Employees with a balance this year and none for `year` yet. Three plain lookups, no joins."""
	def having(y):
		return set(frappe.get_all(
			"Leave Allocation",
			filters={"leave_type": leave_type, "docstatus": 1,
				"from_date": ("between", [date(y, 1, 1), date(y, 12, 31)])},
			pluck="employee",
		))
	waiting = sorted(having(year - 1) - having(year))
	out = []
	for i in range(0, len(waiting), 500):
		out.extend(frappe.get_all(
			"Employee", filters={"name": ("in", waiting[i:i + 500]), "status": ("in", OPEN_FOR_STATUS)}, pluck="name"
		))
	return sorted(out)


def follow_master(leave_type, year):
	"""Until a year starts, the balances this module opened for it follow the employee master: when a
	person's yearly days are corrected there, next year's balance is corrected with it. A balance HR has
	adjusted by hand, or created themselves, is left alone."""
	if year <= getdate().year or not frappe.get_meta("Employee").has_field(ENTITLEMENT_FIELD):
		return
	rows = frappe.get_all(
		"Leave Allocation",
		filters={"leave_type": leave_type, "docstatus": 1, "from_date": date(year, 1, 1),
			"description": ("like", AUTO_NOTE + " (%")},
		fields=["name", "employee", "new_leaves_allocated", "description"],
	)
	master = {}
	employees = sorted(set(r.employee for r in rows))
	for i in range(0, len(employees), 500):
		for e in frappe.get_all("Employee", filters={"name": ("in", employees[i:i + 500])},
				fields=["name", ENTITLEMENT_FIELD]):
			master[e.name] = flt(e.get(ENTITLEMENT_FIELD))
	for r in rows:
		days = master.get(r.employee) or 0
		current = flt(r.new_leaves_allocated)
		untouched = r.description == AUTO_NOTE + MASTER_NOTE.format(_days(current))
		if days <= 0 or not untouched or abs(days - current) < engine.EPS:
			continue
		try:
			doc = frappe.get_doc("Leave Allocation", r.name)
			doc.new_leaves_allocated = days
			doc.flags.ignore_permissions = True
			doc.save()
			frappe.db.set_value("Leave Allocation", r.name, "description",
				AUTO_NOTE + MASTER_NOTE.format(_days(days)), update_modified=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Leave year {0} not updated for {1}".format(year, r.employee),
				message=frappe.get_traceback())
			frappe.db.commit()


# ------------------------------------------------------------------ testing a leave

def split_by_year(doc):
	"""[(start date, end date, days)] for each calendar year the leave covers. The parts always add up to
	the leave's total days."""
	start, end = getdate(doc.from_date), getdate(doc.to_date)
	if start.year == end.year:
		return [(start, end, flt(doc.total_leave_days))]
	half = getdate(doc.half_day_date) if (cint(doc.get("half_day")) and doc.get("half_day_date")) else None
	parts = []
	left = flt(doc.total_leave_days)
	for year in range(start.year, end.year + 1):
		s = max(start, date(year, 1, 1))
		e = min(end, date(year, 12, 31))
		if year == end.year:
			days = left  # whatever is left, so the parts always add up to the leave's total
		else:
			in_part = bool(half and s <= half <= e)
			days = flt(count_annual_leave_days(doc.employee, s, e, 1 if in_part else 0, half if in_part else None))
			days = max(0.0, min(days, left))
		left -= days
		if days:
			parts.append((s, e, days))
	return parts


def check_leave(doc):
	"""Leave Application: refuse a leave that leaves a shortage on its own dates or on a later leave."""
	data = load(doc.employee, doc.leave_type, exclude=doc.name)
	parts = split_by_year(doc)
	only_earned = earned_only(doc.leave_type)
	short = engine.check_new_leave(
		data.years, [(s, days) for (s, _e, days) in parts], only_earned, data.max_carry, key=doc.name or "new"
	)
	if not short:
		return

	if short["own"]:
		year_part = next(((s, days) for (s, _e, days) in parts if s == short["date"]), None)
		can_take = max(0.0, (year_part[1] if year_part else flt(doc.total_leave_days)) - short["short"])
		if only_earned:
			can_take = engine.whole_days(can_take)
		msg = _("Not enough {0} balance. Available for a leave starting on {1}: {2} day(s).").format(
			frappe.bold(doc.leave_type), formatdate(short["date"]), _days(can_take))
		if only_earned:
			msg += "<br>" + _("Only the balance carried over plus the days earned up to the start date can be used.")
	elif short["kind"] == "leave":
		msg = _("This leave cannot be taken: the days are already booked for the {0} starting on {1}.").format(
			frappe.bold(doc.leave_type), formatdate(short["date"]))
	else:
		msg = _("Not enough {0} balance for {1}: short by {2} day(s).").format(
			frappe.bold(doc.leave_type), short["date"].year, _days(short["short"]))
	frappe.throw(msg, exc=InsufficientLeaveBalanceError, title=_("Insufficient Leave Balance"))


def spans_two_open_years(doc):
	"""A leave from one year into the next, with a balance open in both."""
	start, end = getdate(doc.from_date), getdate(doc.to_date)
	if end.year != start.year + 1:
		return False
	for year in (start.year, end.year):
		if not frappe.db.exists("Leave Allocation", {"employee": doc.employee, "leave_type": doc.leave_type,
				"docstatus": 1, "from_date": ("<=", date(year, 12, 31)), "to_date": (">=", date(year, 1, 1))}):
			return False
	return True


def create_ledger_entries(doc):
	"""Leave approved: one ledger row per calendar year the leave covers, so the rows always add up to
	the leave's total days."""
	for (s, e, days) in split_by_year(doc):
		create_leave_ledger_entry(doc, dict(
			leaves=days * -1,
			from_date=s,
			to_date=e,
			is_lwp=0,
			holiday_list=get_holiday_list_for_employee(doc.employee, raise_exception=False, as_on=s) or "",
		))


def delete_ledger_entries(doc):
	"""Leave cancelled: take all of its ledger rows out."""
	frappe.db.delete("Leave Ledger Entry", {"transaction_type": doc.doctype, "transaction_name": doc.name})


def _days(value):
	value = flt(value, 2)
	return cint(value) if value == cint(value) else value
