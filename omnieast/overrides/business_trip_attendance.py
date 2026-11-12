"""Business Trip days count as Present.

A Business Trip is a Leave Application with Leave Type "Business Trip". HRMS marks the leave days
"On Leave" when the leave is approved and submitted; the employee is working on those days, so they
are switched to "Present" here.

This used to run inside the Business Travel Request hook, which is retired: the Cash Payment Voucher
is now made from the approved leave (shared_finance_app "Create CPV").
"""

import frappe

BUSINESS_TRIP = "Business Trip"


def mark_present(doc, method=None):
	"""Leave Application on_submit: the trip's "On Leave" attendance becomes "Present"."""
	if doc.leave_type != BUSINESS_TRIP or doc.status != "Approved":
		return

	attendance = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"attendance_date": ["between", [doc.from_date, doc.to_date]],
			"status": "On Leave",
		},
		pluck="name",
	)
	if attendance:
		frappe.db.set_value("Attendance", {"name": ["in", attendance]}, "status", "Present", update_modified=False)
