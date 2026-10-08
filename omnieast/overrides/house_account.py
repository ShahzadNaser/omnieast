import frappe
from frappe import _
from frappe.utils import getdate

# JawaHR house account — one customer record per company.
HOUSE_ACCOUNT_CUSTOMERS = {
	"C-OMN-1003",  # Omni East Company
	"C-SSC-0032",  # Services and Support Co. (SSC)
}

# Only these users may create, edit or submit invoices / credit notes for the house account.
AUTHORIZED_USERS = {
	"basheer.c@omni-fm.com",  # Basheer Challayil
	"khaja.a@omni-fm.com",  # Mohammed Abubaker Khaja
	"sajid.c@omni-fm.com",  # Sajid Pottanam Chalil
	"shamim.k@jawahr.com",  # Shamim Khan
	"shahid.a@jawahr.com",  # Shahid Akhtar
	"alsaadani.a@omni-fm.com",  # Ahmed Al Saadani
	"Administrator",
}


def validate(doc, method=None):
	if doc.get("customer") not in HOUSE_ACCOUNT_CUSTOMERS:
		return
	if frappe.flags.in_migrate or frappe.flags.in_patch or frappe.flags.in_install:
		return

	_validate_user(doc)
	_validate_due_date(doc)


def _validate_user(doc):
	if frappe.session.user not in AUTHORIZED_USERS:
		frappe.throw(
			_("Only the designated finance team can create or edit invoices for {0}.").format(
				doc.get("customer_name") or doc.customer
			),
			title=_("Not Allowed"),
		)


def _validate_due_date(doc):
	"""The due date is fixed once the invoice is first saved.
	A change needs a written reason from the user who created the invoice; it is logged on the invoice."""
	if doc.is_new() or doc.get("is_return"):
		return

	before = doc.get_doc_before_save()
	if not before or not before.get("due_date") or not doc.get("due_date"):
		return

	old_due, new_due = getdate(before.due_date), getdate(doc.due_date)
	if old_due == new_due:
		return

	if frappe.session.user not in (doc.owner, "Administrator"):
		frappe.throw(
			_("The due date can only be changed by the user who created this invoice ({0}).").format(doc.owner),
			title=_("Due Date Locked"),
		)

	reason = (doc.get("due_date_change_reason") or "").strip()
	if not reason or reason == (before.get("due_date_change_reason") or "").strip():
		frappe.throw(
			_("The original due date ({0}) cannot be changed without a written reason. Please fill in Due Date Change Reason.").format(
				frappe.format(old_due, {"fieldtype": "Date"})
			),
			title=_("Due Date Locked"),
		)

	doc.add_comment(
		"Info",
		_("Due date changed from {0} to {1}. Reason: {2}").format(
			frappe.format(old_due, {"fieldtype": "Date"}),
			frappe.format(new_due, {"fieldtype": "Date"}),
			frappe.bold(reason),
		),
	)
