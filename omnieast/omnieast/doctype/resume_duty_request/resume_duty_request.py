# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

"""Resume Duty Request (ISS-2026-00130): the employee's return to work after a leave.

It can only be submitted when the employee has a check-in (Employee Checkin, fed by the biometric
devices) on the resume date. On submit the leave is marked as resumed (Leave Application >
Resumed On); the leave's own status and workflow are not touched.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, formatdate, get_link_to_form, getdate, today

from hrms.utils.holiday_list import get_holiday_dates_between_range

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
			["employee", "docstatus", "status", "leave_type", "from_date", "to_date"],
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

		self.leave_type = leave.leave_type
		self.leave_from_date = leave.from_date
		self.leave_to_date = leave.to_date

	def validate_resume_date(self):
		if getdate(self.resume_date) <= getdate(self.leave_to_date):
			frappe.throw(
				_(
					"The resume date must be after the last day of the leave ({0}). If the employee came back early, amend the leave first."
				).format(formatdate(self.leave_to_date))
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
		"""First working day after the leave, from the employee's Holiday List."""
		first_day = add_days(getdate(self.leave_to_date), 1)
		resume_date = getdate(self.resume_date)
		holidays = {
			getdate(day)
			for day in get_holiday_dates_between_range(
				self.employee,
				first_day,
				max(resume_date, add_days(first_day, 60)),
				raise_exception_for_holiday_list=False,
			)
		}

		expected = first_day
		while expected in holidays:
			expected = add_days(expected, 1)
		self.expected_resume_date = expected

		days_late = 0
		day = expected
		while day < resume_date:
			if day not in holidays:
				days_late += 1
			day = add_days(day, 1)
		self.working_days_late = days_late

	def set_checkin(self):
		first_checkin = None
		if self.employee and self.resume_date:
			day = getdate(self.resume_date)
			checkins = frappe.get_all(
				"Employee Checkin",
				filters=[
					["employee", "=", self.employee],
					["time", ">=", f"{day} 00:00:00"],
					["time", "<", f"{add_days(day, 1)} 00:00:00"],
				],
				fields=["time"],
				order_by="time asc",
				limit=1,
			)
			first_checkin = checkins[0].time if checkins else None

		self.first_checkin_time = first_checkin
		self.checkin_found = "Yes" if first_checkin else "No"
