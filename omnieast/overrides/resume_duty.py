"""Resume Duty Request on return from leave (ISS-2026-00130).

A Leave Type with "Resume Duty Request Required on Return" ticked marks its leaves when they are
approved (Leave Application > Resume Duty Request Required). Once such a leave has ended, the
employee cannot apply for another leave until a Resume Duty Request for it has been submitted.
Leaves approved before the Leave Type was ticked are not affected.
"""

import frappe
from frappe import _
from frappe.utils import cint, formatdate, get_link_to_form, today

LEAVE_TYPE_FIELD = "custom_requires_resume_duty_request"
REQUIRED_FIELD = "custom_resume_required"
RESUMED_ON_FIELD = "custom_resumed_on"

# A business trip is work, not leave: it is never held back by a pending Resume Duty Request.
EXEMPT_LEAVE_TYPES = {"Business Trip"}


def leave_type_requires_resume(leave_type):
	if not leave_type or not frappe.get_meta("Leave Type").has_field(LEAVE_TYPE_FIELD):
		return False

	return bool(cint(frappe.get_cached_value("Leave Type", leave_type, LEAVE_TYPE_FIELD)))


def get_leave_awaiting_resume(employee):
	"""An approved leave of the employee that has ended and has no submitted Resume Duty Request yet."""
	if not employee or not frappe.get_meta("Leave Application").has_field(RESUMED_ON_FIELD):
		return None

	leaves = frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"docstatus": 1,
			"status": "Approved",
			REQUIRED_FIELD: 1,
			RESUMED_ON_FIELD: ["is", "not set"],
			"to_date": ["<", today()],
		},
		fields=["name", "from_date", "to_date"],
		order_by="to_date asc",
		limit=1,
	)
	return leaves[0] if leaves else None


class LeaveApplicationResumeDutyMixin:
	def validate(self):
		super().validate()

		if self.is_new() and self.leave_type not in EXEMPT_LEAVE_TYPES:
			self.validate_previous_leave_resumed()

	def before_submit(self):
		parent_before_submit = getattr(super(), "before_submit", None)
		if parent_before_submit:
			parent_before_submit()

		if self.meta.has_field(REQUIRED_FIELD):
			required = self.status == "Approved" and leave_type_requires_resume(self.leave_type)
			self.set(REQUIRED_FIELD, 1 if required else 0)

	def validate_previous_leave_resumed(self):
		leave = get_leave_awaiting_resume(self.employee)
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
