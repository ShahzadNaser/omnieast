# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

"""Resume Duty Request (ISS-2026-00130): the employee's return to work after a leave.

It can only be submitted when the employee has a check-in (Employee Checkin, fed by the biometric
devices) on or after the resume date. On submit the leave is marked as resumed (Leave Application >
Resumed On); the leave's own status and workflow are not touched.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, formatdate, get_link_to_form, getdate, today

from omnieast.overrides.resume_duty import REQUIRED_FIELD, get_expected_resume_date, get_holidays

HR_ROLES = {"System Manager", "HR Manager", "HR User"}


class ResumeDutyRequest(Document):
	def validate(self):
		if not (self.employee and self.leave_application and self.resume_date):
			return  # the mandatory-field check reports what is missing

		self.validate_employee()
		self.validate_leave_application()
		self.validate_resume_date()
		self.validate_duplicate()
		self.set_expected_resume_date()
		self.set_checkin()

		if self.docstatus == 0:
			self.status = "Draft"

	def before_submit(self):
		if self.checkin_found != "Yes":
			frappe.throw(
				_(
					"No check-in found for {0} on {1}. The employee must check in on the attendance device (or the HR team adds the check-in) before this request can be submitted."
				).format(frappe.bold(self.employee_name or self.employee), formatdate(self.resume_date)),
				title=_("No Check-in on the Resume Date"),
			)

		self.status = "Resumed"

	def on_submit(self):
		frappe.db.set_value(
			"Leave Application",
			self.leave_application,
			{"custom_resumed_on": self.resume_date, "custom_resume_duty_request": self.name},
		)
		frappe.get_doc("Leave Application", self.leave_application).add_comment(
			"Info",
			_("Duty resumed on {0} ({1}).").format(
				formatdate(self.resume_date), get_link_to_form(self.doctype, self.name)
			),
		)

	def before_cancel(self):
		self.status = "Cancelled"

	def on_cancel(self):
		if frappe.db.get_value("Leave Application", self.leave_application, "custom_resume_duty_request") == self.name:
			frappe.db.set_value(
				"Leave Application",
				self.leave_application,
				{"custom_resumed_on": None, "custom_resume_duty_request": None},
			)

	def validate_employee(self):
		"""Employees can only file their own request; the HR team can file it for anyone."""
		if HR_ROLES & set(frappe.get_roles()):
			return

		own_employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")
		if not own_employee or self.employee != own_employee:
			frappe.throw(_("You can only submit a Resume Duty Request for yourself."), frappe.PermissionError)

	def validate_leave_application(self):
		leave = frappe.db.get_value(
			"Leave Application",
			self.leave_application,
			["employee", "docstatus", "status", "leave_type", "from_date", "to_date", REQUIRED_FIELD],
			as_dict=True,
		)
		if not leave:
			frappe.throw(_("Leave Application {0} not found.").format(self.leave_application))

		if leave.employee != self.employee:
			frappe.throw(
				_("Leave Application {0} belongs to another employee.").format(
					get_link_to_form("Leave Application", self.leave_application)
				)
			)

		if leave.docstatus != 1 or leave.status != "Approved":
			frappe.throw(
				_("Leave Application {0} is not approved, so there is no leave to return from.").format(
					get_link_to_form("Leave Application", self.leave_application)
				)
			)

		if not leave.get(REQUIRED_FIELD):
			frappe.throw(
				_("Leave Application {0} does not need a Resume Duty Request.").format(
					get_link_to_form("Leave Application", self.leave_application)
				)
			)

		self.leave_type = leave.leave_type
		self.leave_from_date = leave.from_date
		self.leave_to_date = leave.to_date

	def validate_resume_date(self):
		# an early return (before the last day of the leave) is allowed, 0 days late
		if getdate(self.resume_date) < getdate(self.leave_from_date):
			frappe.throw(
				_("The resume date cannot be before the first day of the leave ({0}).").format(
					formatdate(self.leave_from_date)
				)
			)

		if getdate(self.resume_date) > getdate(today()):
			frappe.throw(_("The resume date cannot be in the future."))

	def validate_duplicate(self):
		existing = frappe.db.get_value(
			"Resume Duty Request",
			{"leave_application": self.leave_application, "docstatus": ["<", 2], "name": ["!=", self.name]},
			"name",
		)
		if existing:
			frappe.throw(
				_("Resume Duty Request {0} already exists for this leave.").format(
					get_link_to_form("Resume Duty Request", existing)
				)
			)

	def set_expected_resume_date(self):
		self.expected_resume_date = get_expected_resume_date(self.employee, self.leave_to_date)
		self.working_days_late = get_working_days_late(self.employee, self.expected_resume_date, self.resume_date)

	def set_checkin(self):
		self.first_checkin_time = get_first_checkin(self.employee, self.resume_date)
		self.checkin_found = "Yes" if self.first_checkin_time else "No"


def get_working_days_late(employee, expected_resume_date, resume_date):
	"""Working days from the expected resume date up to (not including) the actual one; 0 if on time or early."""
	expected, resume_date = getdate(expected_resume_date), getdate(resume_date)
	if resume_date <= expected:
		return 0

	holidays = get_holidays(employee, expected, resume_date)
	days_late, day = 0, expected
	while day < resume_date:
		if day not in holidays:
			days_late += 1
		day = add_days(day, 1)
	return days_late


def get_first_checkin(employee, resume_date):
	"""First Employee Checkin on or after the resume date."""
	if not (employee and resume_date):
		return None

	checkins = frappe.get_all(
		"Employee Checkin",
		filters=[["employee", "=", employee], ["time", ">=", f"{getdate(resume_date)} 00:00:00"]],
		fields=["time"],
		order_by="time asc",
		limit=1,
	)
	return checkins[0].time if checkins else None


@frappe.whitelist()
def get_resume_details(leave_application, resume_date=None):
	"""Values the form shows as soon as the leave (and resume date) is picked; validate sets them again."""
	frappe.has_permission("Leave Application", "read", leave_application, throw=True)

	leave = frappe.db.get_value(
		"Leave Application",
		leave_application,
		["employee", "employee_name", "department", "company", "leave_type", "from_date", "to_date"],
		as_dict=True,
	)
	if not leave:
		return {}

	expected = get_expected_resume_date(leave.employee, leave.to_date)
	details = {
		"employee": leave.employee,
		"employee_name": leave.employee_name,
		"department": leave.department,
		"company": leave.company,
		"leave_type": leave.leave_type,
		"leave_from_date": leave.from_date,
		"leave_to_date": leave.to_date,
		"expected_resume_date": expected,
	}
	if resume_date:
		first_checkin = get_first_checkin(leave.employee, resume_date)
		details.update(
			working_days_late=get_working_days_late(leave.employee, expected, resume_date),
			first_checkin_time=first_checkin,
			checkin_found="Yes" if first_checkin else "No",
		)
	return details


def is_hr_user(user=None):
	return bool(HR_ROLES & set(frappe.get_roles(user)))


def get_permission_query_conditions(user=None):
	"""Without an HR role, only the user's own employee's requests (whatever their User Permissions are)."""
	user = user or frappe.session.user
	if user == "Administrator" or is_hr_user(user):
		return ""

	employee = frappe.db.get_value("Employee", {"user_id": user}, "name")
	return "`tabResume Duty Request`.`employee` = {0}".format(frappe.db.escape(employee or ""))


def has_permission(doc, ptype=None, user=None, debug=False):
	user = user or frappe.session.user
	if user == "Administrator" or is_hr_user(user) or not doc.get("employee"):
		return True

	return doc.employee == frappe.db.get_value("Employee", {"user_id": user}, "name")
