# Copyright (c) 2026, Shahzad Naser and Contributors
# See license.txt

"""ISS-2026-00109: Resume Duty Request validations and the hold on new leaves.

The records are built here (inserted without their own validations, rolled back after the class),
so no standard test records are generated on the site.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from omnieast.overrides import resume_duty

# Do not generate test records for the linked doctypes (they would be committed to the site)
EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = [
	"Employee",
	"Department",
	"Company",
	"Leave Application",
	"Leave Type",
	"Resume Duty Request",
]

COMPANY = "Omni East Company"
VACATION = "Annual Leave"
HOLIDAY_LIST = "_Test RDR Holidays"

# Tue 1 - Thu 3 Sep 2026; Fri 4 and Sat 5 are holidays, so the employee is expected back on Sun 6
FROM_DATE, TO_DATE = "2026-09-01", "2026-09-03"
EXPECTED = "2026-09-06"


class IntegrationTestResumeDutyRequest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

		if not frappe.db.exists("Holiday List", HOLIDAY_LIST):
			frappe.get_doc(
				{
					"doctype": "Holiday List",
					"holiday_list_name": HOLIDAY_LIST,
					"from_date": "2026-08-01",
					"to_date": "2026-12-31",
					"holidays": [
						{"holiday_date": "2026-09-04", "description": "Friday", "weekly_off": 1},
						{"holiday_date": "2026-09-05", "description": "Saturday", "weekly_off": 1},
					],
				}
			).insert()

		frappe.db.set_value("Leave Type", VACATION, resume_duty.LEAVE_TYPE_FIELD, 1)
		frappe.db.set_value("Leave Type", "Business Trip", resume_duty.LEAVE_TYPE_FIELD, 0)
		cls.employee = make_employee("_T-RDR-EMP-1")
		cls.other_employee = make_employee("_T-RDR-EMP-2")

	def setUp(self):
		frappe.set_user("Administrator")
		# each test on its own: undo its rows afterwards (the class is rolled back as a whole at the end)
		frappe.db.savepoint("rdr_test")
		self.addCleanup(frappe.db.rollback, save_point="rdr_test")
		self.leave = make_leave(self.employee)

	# Resume Duty Request
	# -------------------

	def test_fills_leave_and_expected_resume_date(self):
		rdr = make_rdr(self.leave, resume_date="2026-09-08")  # Tue: Sun 6 and Mon 7 missed
		rdr.validate()

		self.assertEqual(rdr.leave_type, VACATION)
		self.assertEqual(str(rdr.leave_from_date), FROM_DATE)
		self.assertEqual(str(rdr.expected_resume_date), EXPECTED)
		self.assertEqual(rdr.working_days_late, 2)

	def test_on_time_and_early_return_not_late(self):
		for resume_date in (EXPECTED, "2026-09-02"):
			rdr = make_rdr(self.leave, resume_date=resume_date)
			rdr.validate()
			self.assertEqual(rdr.working_days_late, 0, resume_date)

	def test_resume_date_before_leave_start(self):
		self.assertRaises(frappe.ValidationError, make_rdr(self.leave, resume_date="2026-08-31").validate)

	def test_leave_of_another_employee(self):
		rdr = make_rdr(self.leave)
		rdr.employee = self.other_employee
		self.assertRaises(frappe.ValidationError, rdr.validate)

	def test_leave_not_submitted(self):
		draft = make_leave(self.employee, docstatus=0, status="Open")
		self.assertRaises(frappe.ValidationError, make_rdr(draft).validate)

	def test_leave_not_requiring_resume(self):
		leave = make_leave(self.employee, custom_resume_required=0)
		self.assertRaises(frappe.ValidationError, make_rdr(leave).validate)

	def test_duplicate(self):
		existing = make_rdr(self.leave)  # an existing request for the same leave
		existing.name, existing.docstatus = "_T-RDR-1", 1
		existing.db_insert()
		self.assertRaises(frappe.ValidationError, make_rdr(self.leave).validate)

	def test_checkin_on_or_after_resume_date(self):
		rdr = make_rdr(self.leave, resume_date=EXPECTED)
		rdr.validate()
		self.assertEqual(rdr.checkin_found, "No")

		make_checkin(self.employee, "2026-09-07 08:15:00")
		rdr.validate()
		self.assertEqual(rdr.checkin_found, "Yes")
		self.assertEqual(str(rdr.first_checkin_time), "2026-09-07 08:15:00")

	def test_submit_without_checkin(self):
		rdr = make_rdr(self.leave, resume_date=EXPECTED).insert()
		self.assertRaises(frappe.ValidationError, rdr.submit)

	def test_submit_and_cancel_update_leave(self):
		make_checkin(self.employee, "2026-09-06 07:55:00")
		rdr = make_rdr(self.leave, resume_date=EXPECTED).insert()
		rdr.submit()

		self.assertEqual(rdr.status, "Resumed")
		values = frappe.db.get_value(
			"Leave Application", self.leave.name, ["custom_resumed_on", "custom_resume_duty_request"], as_dict=True
		)
		self.assertEqual(str(values.custom_resumed_on), EXPECTED)
		self.assertEqual(values.custom_resume_duty_request, rdr.name)

		rdr.cancel()
		self.assertEqual(rdr.status, "Cancelled")
		values = frappe.db.get_value(
			"Leave Application", self.leave.name, ["custom_resumed_on", "custom_resume_duty_request"], as_dict=True
		)
		self.assertIsNone(values.custom_resumed_on)
		self.assertIsNone(values.custom_resume_duty_request)

	# Hold on new leaves
	# ------------------

	def test_new_leave_blocked_until_resumed(self):
		new_leave = make_new_leave(self.employee)
		self.assertRaises(frappe.ValidationError, new_leave.validate_previous_leave_resumed)

		new_leave.status = "Approved"
		self.assertRaises(frappe.ValidationError, new_leave.before_submit)

		frappe.db.set_value(
			"Leave Application", self.leave.name, {"custom_resumed_on": EXPECTED, "custom_resume_duty_request": "x"}
		)
		new_leave.validate_previous_leave_resumed()  # no longer blocked

	def test_new_leave_not_blocked(self):
		other = make_new_leave(self.other_employee)
		other.validate_previous_leave_resumed()  # nothing pending for this employee

		trip = make_new_leave(self.employee, leave_type="Business Trip", status="Approved")
		trip.before_submit()  # a business trip is never held back

		rejected = make_new_leave(self.employee, status="Rejected")
		rejected.before_submit()  # rejecting is not held back

	def test_leave_not_ended_does_not_block(self):
		frappe.db.set_value("Leave Application", self.leave.name, "to_date", frappe.utils.add_days(frappe.utils.today(), 1))
		make_new_leave(self.employee).validate_previous_leave_resumed()

	def test_resume_required_set_on_approval(self):
		approved = make_new_leave(self.other_employee, status="Approved")
		approved.before_submit()
		self.assertEqual(approved.custom_resume_required, 1)

		trip = make_new_leave(self.other_employee, leave_type="Business Trip", status="Approved")
		trip.before_submit()
		self.assertEqual(trip.custom_resume_required, 0)

	def test_vacation_details_mandatory(self):
		new_leave = make_new_leave(self.other_employee, custom_exit_reentry_visa_paid_by=None)
		self.assertRaises(frappe.ValidationError, new_leave.validate_vacation_details)

		new_leave.custom_exit_reentry_visa_paid_by = "Employee Paid"
		new_leave.validate_vacation_details()

		trip = make_new_leave(self.other_employee, leave_type="Business Trip", custom_flight_ticket_paid_by=None)
		trip.validate_vacation_details()  # only vacation leave types ask

	# Daily reminder
	# --------------

	def test_reminder_once_per_employee(self):
		make_leave(self.employee)  # a second pending leave: still one email for the employee

		with patch.object(resume_duty.frappe, "sendmail") as sendmail:
			with patch.object(resume_duty, "reminder_sent_today", return_value=False):
				resume_duty.send_resume_duty_reminders()

		emails = [call for call in sendmail.call_args_list if call.kwargs["reference_name"] == self.employee]
		self.assertEqual(len(emails), 1)
		self.assertIn("_t-rdr-emp-1@example.com", emails[0].kwargs["recipients"])

		with patch.object(resume_duty.frappe, "sendmail") as sendmail:
			with patch.object(resume_duty, "reminder_sent_today", return_value=True):
				resume_duty.send_resume_duty_reminders()
		sendmail.assert_not_called()

	def test_reminder_sent_today(self):
		self.assertFalse(resume_duty.reminder_sent_today(self.employee))
		frappe.get_doc(
			{
				"doctype": "Email Queue",
				"name": frappe.generate_hash(length=10),
				"reference_doctype": "Employee",
				"reference_name": self.employee,
				"status": "Not Sent",
			}
		).db_insert()
		self.assertTrue(resume_duty.reminder_sent_today(self.employee))


def make_employee(name):
	frappe.get_doc(
		{
			"doctype": "Employee",
			"name": name,
			"first_name": name,
			"employee_name": name,
			"company": COMPANY,
			"status": "Active",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2020-01-01",
			"holiday_list": HOLIDAY_LIST,
			"prefered_email": f"{name.lower()}@example.com",
		}
	).db_insert()
	return name


def make_leave(employee, **values):
	"""An approved vacation leave that ended (inserted as it is, like after approval)."""
	leave = frappe.get_doc(
		{
			"doctype": "Leave Application",
			"name": f"_T-RDR-LA-{frappe.generate_hash(length=6)}",
			"employee": employee,
			"employee_name": employee,
			"company": COMPANY,
			"leave_type": VACATION,
			"from_date": FROM_DATE,
			"to_date": TO_DATE,
			"posting_date": FROM_DATE,
			"status": "Approved",
			"docstatus": 1,
			"custom_resume_required": 1,
			**values,
		}
	)
	leave.db_insert()
	return leave


def make_new_leave(employee, **values):
	"""A leave that is being applied for (not saved)."""
	return frappe.get_doc(
		{
			"doctype": "Leave Application",
			"employee": employee,
			"employee_name": employee,
			"company": COMPANY,
			"leave_type": VACATION,
			"from_date": "2026-10-01",
			"to_date": "2026-10-05",
			"status": "Open",
			"custom_exit_reentry_visa_paid_by": "Company Paid",
			"custom_flight_ticket_paid_by": "Company Paid",
			**values,
		}
	)


def make_rdr(leave, resume_date=EXPECTED):
	return frappe.get_doc(
		{
			"doctype": "Resume Duty Request",
			"employee": leave.employee,
			"company": COMPANY,
			"leave_application": leave.name,
			"resume_date": resume_date,
		}
	)


def make_checkin(employee, time):
	frappe.get_doc(
		{
			"doctype": "Employee Checkin",
			"name": frappe.generate_hash(length=10),
			"employee": employee,
			"time": time,
			"log_type": "IN",
		}
	).db_insert()
