"""Resume Duty Request on return from leave (ISS-2026-00130, ISS-2026-00109).

A Leave Type with "Resume Duty Request Required on Return" ticked marks its leaves when they are
approved (Leave Application > Resume Duty Request Required). Once such a leave has ended, the
employee cannot apply for, or get approved, another leave until a Resume Duty Request for it has been
submitted; a daily email reminds the employee and the HR Managers.
Leaves approved before the Leave Type was ticked are not affected.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, get_link_to_form, getdate, today
from frappe.utils.user import get_users_with_role

from hrms.utils.holiday_list import get_holiday_dates_between_range

LEAVE_TYPE_FIELD = "custom_requires_resume_duty_request"
REQUIRED_FIELD = "custom_resume_required"
RESUMED_ON_FIELD = "custom_resumed_on"

# A business trip is work, not leave: it is never held back by a pending Resume Duty Request.
EXEMPT_LEAVE_TYPES = {"Business Trip"}

# ISS-2026-00109: asked on every vacation leave (Leave Type above ticked)
VACATION_FIELDS = ("custom_exit_reentry_visa_paid_by", "custom_flight_ticket_paid_by")

REMINDER_ROLE = "HR Manager"
REMINDER_LIMIT = 500


def leave_type_requires_resume(leave_type):
	if not leave_type or not frappe.get_meta("Leave Type").has_field(LEAVE_TYPE_FIELD):
		return False

	return bool(cint(frappe.get_cached_value("Leave Type", leave_type, LEAVE_TYPE_FIELD)))


def pending_resume_filters(**filters):
	"""Approved leaves that have ended and have no submitted Resume Duty Request yet."""
	return {
		"docstatus": 1,
		"status": "Approved",
		REQUIRED_FIELD: 1,
		RESUMED_ON_FIELD: ["is", "not set"],
		"to_date": ["<", today()],
		**filters,
	}


def get_leave_awaiting_resume(employee, exclude=None):
	"""The employee's earliest leave awaiting a Resume Duty Request."""
	if not employee or not frappe.get_meta("Leave Application").has_field(RESUMED_ON_FIELD):
		return None

	filters = pending_resume_filters(employee=employee)
	if exclude:
		filters["name"] = ["!=", exclude]

	leaves = frappe.get_all(
		"Leave Application",
		filters=filters,
		fields=["name", "from_date", "to_date"],
		order_by="to_date asc",
		limit=1,
	)
	return leaves[0] if leaves else None


def get_expected_resume_date(employee, leave_to_date):
	"""First working day after the leave, from the employee's Holiday List."""
	expected = add_days(getdate(leave_to_date), 1)
	holidays = get_holidays(employee, expected, add_days(expected, 60))
	while expected in holidays:
		expected = add_days(expected, 1)
	return getdate(expected)


def get_holidays(employee, from_date, to_date):
	return {
		getdate(day)
		for day in get_holiday_dates_between_range(
			employee, from_date, to_date, raise_exception_for_holiday_list=False
		)
	}


class LeaveApplicationResumeDutyMixin:
	def validate(self):
		super().validate()

		if self.is_new():
			self.validate_vacation_details()
			if self.leave_type not in EXEMPT_LEAVE_TYPES:
				self.validate_previous_leave_resumed()

	def before_submit(self):
		parent_before_submit = getattr(super(), "before_submit", None)
		if parent_before_submit:
			parent_before_submit()

		if self.status == "Approved" and self.leave_type not in EXEMPT_LEAVE_TYPES:
			# the leave may have been drafted before the previous one ended
			self.validate_previous_leave_resumed()

		if self.meta.has_field(REQUIRED_FIELD):
			required = self.status == "Approved" and leave_type_requires_resume(self.leave_type)
			self.set(REQUIRED_FIELD, 1 if required else 0)

	def validate_vacation_details(self):
		"""The form asks for these through mandatory_depends_on; this covers the API and the HR mobile app.

		New leaves only, so leaves already in their approval workflow are not held up.
		"""
		if not leave_type_requires_resume(self.leave_type):
			return

		missing = [
			_(self.meta.get_label(fieldname))
			for fieldname in VACATION_FIELDS
			if self.meta.has_field(fieldname) and not self.get(fieldname)
		]
		if missing:
			frappe.throw(
				_("Please fill in: {0}").format(", ".join(missing)), title=_("Vacation Details Missing")
			)

	def validate_previous_leave_resumed(self):
		leave = get_leave_awaiting_resume(self.employee, exclude=self.name)
		if not leave:
			return

		frappe.throw(
			_(
				"{0} has not resumed duty after leave {1} ({2} to {3}). Please submit a Resume Duty Request for that leave first."
			).format(
				frappe.bold(self.employee_name or self.employee),
				get_link_to_form("Leave Application", leave.name),
				formatdate(leave.from_date),
				formatdate(leave.to_date),
			),
			title=_("Resume Duty Request Pending"),
		)


def send_resume_duty_reminders():
	"""Daily: one email per employee whose leave ended, expected resume date passed, and no Resume Duty Request."""
	if not frappe.get_meta("Leave Application").has_field(RESUMED_ON_FIELD):
		return

	leaves = frappe.get_all(
		"Leave Application",
		filters=pending_resume_filters(),
		fields=["name", "employee", "employee_name", "leave_type", "from_date", "to_date"],
		order_by="employee asc, to_date asc",
		limit=REMINDER_LIMIT,
	)

	by_employee = {}
	for leave in leaves:
		leave.expected_resume_date = get_expected_resume_date(leave.employee, leave.to_date)
		if leave.expected_resume_date < getdate(today()):
			by_employee.setdefault(leave.employee, []).append(leave)

	hr_managers = [user for user in get_users_with_role(REMINDER_ROLE) if user not in ("Administrator", "Guest")]
	for employee, employee_leaves in by_employee.items():
		try:
			send_reminder(employee, employee_leaves, hr_managers)
		except Exception:
			frappe.log_error(title=f"Resume Duty Request reminder failed for {employee}")


def send_reminder(employee, leaves, hr_managers):
	if reminder_sent_today(employee):
		return

	employee_email = get_employee_email(employee)
	recipients = list(dict.fromkeys(([employee_email] if employee_email else []) + hr_managers))
	if not recipients:
		return

	rows = "".join(
		"<li>{0}: {1} {2} to {3}, {4} {5}</li>".format(
			get_link_to_form("Leave Application", leave.name),
			leave.leave_type,
			formatdate(leave.from_date),
			formatdate(leave.to_date),
			_("expected back on"),
			formatdate(leave.expected_resume_date),
		)
		for leave in leaves
	)
	frappe.sendmail(
		recipients=recipients,
		subject=_("Resume Duty Request pending: {0}").format(leaves[0].employee_name or employee),
		message=_(
			"<p>{0} has not submitted a Resume Duty Request after returning from:</p><ul>{1}</ul>"
			"<p>Please submit it from the leave (Create Resume Duty Request). No new leave can be approved until then.</p>"
		).format(frappe.bold(leaves[0].employee_name or employee), rows),
		header=[_("Resume Duty Request Reminder"), "orange"],
		reference_doctype="Employee",
		reference_name=employee,
	)


def reminder_sent_today(employee):
	"""One reminder per employee per day, also when the job is run again by hand.

	Only this reminder emails against the Employee record, so any such email queued today counts.
	"""
	return frappe.db.exists(
		"Email Queue",
		{"reference_doctype": "Employee", "reference_name": employee, "creation": [">=", today()]},
	)


def get_employee_email(employee):
	values = frappe.db.get_value(
		"Employee", employee, ["prefered_email", "user_id", "company_email", "personal_email"], as_dict=True
	)
	if not values:
		return None
	return values.prefered_email or values.user_id or values.company_email or values.personal_email
