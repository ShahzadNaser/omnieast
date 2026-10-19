# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

"""Employee Contract Review (ISS-2026-00139): contract-ending and probation-ending approvals.

A daily job opens one review per employee two months before the contract end date and two months
before the probation end date, and sends a reminder one month before while the review is still
open. The line manager (Employee > Reports To) chooses renew/confirm or end; HR then approves.
Without a line manager the review goes straight to HR. Both act from the email buttons (each
button opens a confirmation page first) or from the review form.

OMNI: the contract end date is Employee > Contract End Date; the probation end date is Employee >
Confirmation Date when set, otherwise 3 months (90 days) from the date of joining.

On HR approval: a renewal with a New Contract End Date writes that date to the employee; a
probation confirmation sets the employee's Confirmation Date when it is empty. Ending a contract
or employment only records the decision; HR runs the separation as usual.
"""

from html import escape

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, cint, formatdate, get_url, get_url_to_form, getdate, now_datetime, strip_html, today
from frappe.utils.verified_command import get_signed_params, verify_request

# Site settings
# -------------
METHOD_PATH = "omnieast.omnieast.doctype.employee_contract_review.employee_contract_review"

# Employee field that holds the contract end date
CONTRACT_END_FIELD = "contract_end_date"
# Employee field with the probation length in months (None: DEFAULT_PROBATION_MONTHS for everyone)
PROBATION_MONTHS_FIELD = None
DEFAULT_PROBATION_MONTHS = 3
# Employee > Confirmation Date, when set after the date of joining, is the probation end date
USE_CONFIRMATION_DATE = True
# Companies covered (empty: all)
COMPANIES = []

# HR approvers: user IDs in this settings field; HR_DEFAULT when it is empty
SETTINGS_DOCTYPE = "HR Settings"
HR_FIELD = "custom_contract_review_hr_recipients"
HR_DEFAULT = []
# Also tell HR when the line manager is asked (False where HR already gets reminder Notifications)
SEND_HR_HEADS_UP = True

ERP_NAME = "OMNI East ERP"
SITE = "omnieast.k.frappe.cloud"
BRANDS = {
	"Services and Support Co. (SSC)": {
		"primary": "#2b5ca8",
		"grad": ["#14325f", "#4070c0"],
		"accent": "#4fb848",
		"accent2": "#6ccf5f",
		"tint": "#eef4fb",
		"logo": "https://omnieast.k.frappe.cloud/files/ssc_header1.png",
		"logo_w": 200,
		"logo_h": 37,
		"company": "Services and Support Co. (SSC)",
		"confidential": True,
	},
	"Omni East Company": {
		"primary": "#273785",
		"grad": ["#151d52", "#3346a6"],
		"accent": "#3f9d70",
		"accent2": "#56b185",
		"tint": "#eef0fa",
		"logo": "https://omnieast.k.frappe.cloud/files/OMNI%20LOGO.png",
		"logo_w": 162,
		"logo_h": 40,
		"company": "Omni East Company",
		"confidential": True,
	},
}
DEFAULT_BRAND = "Omni East Company"

# Review
# ------

DOCTYPE = "Employee Contract Review"
CONTRACT_END = "Contract End"
PROBATION_END = "Probation End"
PENDING_LINE_MANAGER = "Pending Line Manager"
PENDING_HR = "Pending HR"
CANCELLED = "Cancelled"
OPEN_STATUSES = [PENDING_LINE_MANAGER, PENDING_HR]
RENEW = "Renew / Confirm"
END = "End"
DECISIONS = (RENEW, END)
HR_ROLES = {"HR Manager", "System Manager"}

# Upper bound for one run of the daily job (the Employee table is small; this keeps it bounded).
JOB_LIMIT = 500


class EmployeeContractReview(Document):
	def onload(self):
		self.set_onload("is_hr_approver", is_hr_approver(frappe.session.user))

	def validate(self):
		self.validate_closed()
		self.set_employee_details()
		self.validate_duplicate()
		self.validate_new_contract_end_date()
		if self.is_new() or not self.status:
			self.status = PENDING_LINE_MANAGER if self.line_manager_user else PENDING_HR

	def after_insert(self):
		if self.line_manager_user:
			share_with(self, self.line_manager_user)

		send_stage_emails(self)
		self.db_set("first_reminder_on", today(), update_modified=False)
		if getdate(self.end_date) <= getdate(add_months(today(), 1)):
			# opened inside the last month: this first email is also the one-month reminder
			self.db_set("second_reminder_on", today(), update_modified=False)

	def validate_closed(self):
		if self.is_new() or self.flags.decision_update:
			return
		if frappe.db.get_value(DOCTYPE, self.name, "status") not in OPEN_STATUSES:
			frappe.throw(_("This review is closed and can no longer be changed."))

	def set_employee_details(self):
		employee = frappe.db.get_value(
			"Employee",
			self.employee,
			["employee_name", "department", "designation", "company", "date_of_joining", "reports_to"],
			as_dict=True,
		)
		if not employee:
			frappe.throw(_("Employee {0} not found.").format(self.employee))

		self.employee_name = employee.employee_name
		self.department = employee.department
		self.designation = employee.designation
		self.company = employee.company
		self.date_of_joining = employee.date_of_joining

		if not self.is_new():
			return

		self.line_manager = employee.reports_to if employee.reports_to != self.employee else None
		self.line_manager_name = None
		self.line_manager_user = None
		if self.line_manager:
			manager = frappe.db.get_value(
				"Employee", self.line_manager, ["employee_name", "user_id"], as_dict=True
			)
			if manager:
				self.line_manager_name = manager.employee_name
				if manager.user_id and cint(frappe.db.get_value("User", manager.user_id, "enabled")):
					self.line_manager_user = manager.user_id

	def validate_duplicate(self):
		filters = {
			"employee": self.employee,
			"review_type": self.review_type,
			"end_date": self.end_date,
			"status": ["!=", CANCELLED],
		}
		if not self.is_new():
			filters["name"] = ["!=", self.name]

		existing = frappe.db.get_value(DOCTYPE, filters, "name")
		if existing:
			frappe.throw(
				_("Review {0} already exists for {1} ({2}, {3}).").format(
					existing, self.employee_name or self.employee, _(self.review_type), formatdate(self.end_date)
				)
			)

	def validate_new_contract_end_date(self):
		if self.review_type != CONTRACT_END:
			self.new_contract_end_date = None
		elif self.new_contract_end_date and getdate(self.new_contract_end_date) <= getdate(self.end_date):
			frappe.throw(_("The new contract end date must be after the current one ({0}).").format(formatdate(self.end_date)))

	def apply_decision(self, decision, user, remarks=None):
		if decision not in DECISIONS:
			frappe.throw(_("Unknown decision."))
		if self.status not in OPEN_STATUSES:
			frappe.throw(_("This review is already closed ({0}).").format(_(self.status)))

		if self.status == PENDING_LINE_MANAGER and user == self.line_manager_user:
			self.line_manager_decision = decision
			self.line_manager_decided_on = now_datetime()
			self.status = PENDING_HR
			self.add_remarks(user, remarks)
			self.save_decision()
			send_stage_emails(self)
			return self.status

		if not is_hr_approver(user):
			frappe.throw(_("Only the line manager or HR can decide on this review."), frappe.PermissionError)

		self.hr_decision = decision
		self.hr_decided_by = user
		self.hr_decided_on = now_datetime()
		self.status = final_status(self.review_type, decision)
		self.add_remarks(user, remarks)
		self.save_decision()
		self.update_employee()
		send_outcome_email(self)
		return self.status

	def add_remarks(self, user, remarks):
		remarks = (remarks or "").strip()
		if not remarks:
			return
		line = "{0}: {1}".format(frappe.db.get_value("User", user, "full_name") or user, remarks)
		self.remarks = "{0}\n{1}".format(self.remarks, line) if self.remarks else line

	def save_decision(self):
		self.flags.decision_update = True
		self.flags.ignore_permissions = True
		self.save()

	def update_employee(self):
		if self.hr_decision == RENEW and self.review_type == CONTRACT_END and self.new_contract_end_date:
			frappe.db.set_value("Employee", self.employee, CONTRACT_END_FIELD, self.new_contract_end_date)
		elif (
			self.hr_decision == RENEW
			and self.review_type == PROBATION_END
			and not frappe.db.get_value("Employee", self.employee, "final_confirmation_date")
		):
			frappe.db.set_value("Employee", self.employee, "final_confirmation_date", self.end_date)

		frappe.get_doc("Employee", self.employee).add_comment(
			"Info",
			_("{0}: {1} ({2}).").format(
				_(self.review_type),
				decision_label(self.review_type, self.hr_decision),
				'<a href="{0}">{1}</a>'.format(get_url_to_form(DOCTYPE, self.name), self.name),
			),
		)


# Desk actions
# ------------


@frappe.whitelist()
def decide(name, decision, remarks=None, new_contract_end_date=None):
	doc = frappe.get_doc(DOCTYPE, name)
	user = frappe.session.user
	if user != doc.line_manager_user and not is_hr_approver(user):
		frappe.throw(_("Only the line manager or HR can decide on this review."), frappe.PermissionError)

	if new_contract_end_date and is_hr_approver(user):
		doc.new_contract_end_date = new_contract_end_date
	return doc.apply_decision(decision, user, remarks)


@frappe.whitelist()
def cancel_review(name, reason=None):
	if not is_hr_approver(frappe.session.user):
		frappe.throw(_("Only HR can cancel a review."), frappe.PermissionError)

	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in OPEN_STATUSES:
		frappe.throw(_("This review is already closed ({0}).").format(_(doc.status)))

	doc.status = CANCELLED
	doc.add_remarks(frappe.session.user, reason)
	doc.save_decision()
	return doc.status


# Email actions (signed links, like workflow approval emails)
# -------------


@frappe.whitelist(allow_guest=True)
def email_action(name, decision, user):
	"""First click from the email: show a confirmation page; nothing is recorded yet."""
	if not verify_request():
		return

	doc = get_open_review(name, decision)
	if not doc:
		return

	label = decision_label(doc.review_type, decision)
	frappe.respond_as_web_page(
		_("Confirm: {0}").format(label),
		_("{0} for {1}, {2} on {3}.").format(
			escape(label), escape(doc.employee_name or doc.employee), _(end_date_label(doc)).lower(), formatdate(doc.end_date)
		),
		indicator_color="blue",
		primary_action=action_url(doc, decision, user, "email_confirm"),
		primary_label=label,
	)


@frappe.whitelist(allow_guest=True)
def email_confirm(name, decision, user):
	"""Second click: record the decision as the user the email was sent to."""
	if not verify_request():
		return

	logged_in = frappe.session.user
	if logged_in not in ("Guest", user):
		return respond(
			_("Signed In as Another User"),
			_("You are signed in as {0}. Sign out, or open the review in the ERP, to record this decision.").format(escape(logged_in)),
			"red",
		)

	doc = get_open_review(name, decision)
	if not doc:
		return

	if logged_in == "Guest":
		frappe.set_user(user)
	try:
		status = doc.apply_decision(decision, user)
		frappe.db.commit()
	except (frappe.ValidationError, frappe.PermissionError) as e:
		frappe.db.rollback()
		frappe.clear_messages()
		return respond(_("Not Recorded"), escape(strip_html(str(e))) or _("The decision could not be recorded."), "red")
	finally:
		if logged_in == "Guest":
			frappe.set_user("Guest")

	message = _("{0} recorded for {1}.").format(escape(decision_label(doc.review_type, decision)), escape(doc.employee_name or doc.employee))
	if status == PENDING_HR:
		message += " " + _("HR has been asked to approve it.")
	respond(_("Decision Recorded"), message, "green")


def get_open_review(name, decision):
	if decision not in DECISIONS or not frappe.db.exists(DOCTYPE, name):
		respond(_("Not Found"), _("This review no longer exists."), "red")
		return None

	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status not in OPEN_STATUSES:
		respond(_("Already Closed"), _("{0} is already closed: {1}.").format(doc.name, _(doc.status)), "orange")
		return None
	return doc


def respond(title, message, indicator):
	frappe.respond_as_web_page(title, message, indicator_color=indicator)


def action_url(doc, decision, user, method="email_action"):
	params = get_signed_params({"name": doc.name, "decision": decision, "user": user})
	return get_url("/api/method/{0}.{1}?{2}".format(METHOD_PATH, method, params))


# Daily job
# ---------


def send_reminders():
	"""Daily: open reviews two months before the end date, remind one month before."""
	if not get_hr_approvers():
		return  # nobody to approve: set the HR approvers in HR Settings > Contract and Probation Approvals

	start, horizon = add_days(today(), 1), add_months(today(), 2)
	for employee, end_date in get_contracts_ending(start, horizon):
		open_review(employee, CONTRACT_END, end_date)
	for employee, end_date in get_probations_ending(start, horizon):
		open_review(employee, PROBATION_END, end_date)

	send_one_month_reminders()


def employee_filters():
	filters = {"status": "Active"}
	if COMPANIES:
		filters["company"] = ["in", COMPANIES]
	return filters


def get_contracts_ending(start, end):
	filters = employee_filters()
	filters[CONTRACT_END_FIELD] = ["between", [start, end]]
	rows = frappe.get_all("Employee", filters=filters, fields=["name", CONTRACT_END_FIELD], limit_page_length=JOB_LIMIT)
	return [(row.name, getdate(row.get(CONTRACT_END_FIELD))) for row in rows]


def get_probations_ending(start, end):
	fields = ["name", "date_of_joining", "final_confirmation_date"]
	if PROBATION_MONTHS_FIELD:
		fields.append(PROBATION_MONTHS_FIELD)

	filters = employee_filters()
	filters["date_of_joining"] = ["between", [add_months(today(), -12), today()]]
	rows = frappe.get_all("Employee", filters=filters, fields=fields, limit_page_length=JOB_LIMIT)

	start, end = getdate(start), getdate(end)
	result = []
	for row in rows:
		end_date = probation_end_date(row)
		if end_date and start <= end_date <= end:
			result.append((row.name, end_date))
	return result


def probation_end_date(row):
	if not row.date_of_joining:
		return None
	if (
		USE_CONFIRMATION_DATE
		and row.get("final_confirmation_date")
		and getdate(row.final_confirmation_date) > getdate(row.date_of_joining)
	):
		return getdate(row.final_confirmation_date)

	months = cint(row.get(PROBATION_MONTHS_FIELD)) if PROBATION_MONTHS_FIELD else 0
	return getdate(add_months(row.date_of_joining, months or DEFAULT_PROBATION_MONTHS))


def open_review(employee, review_type, end_date):
	# one review per employee, type and end date, whatever its status (a cancelled one is not reopened)
	if frappe.db.exists(DOCTYPE, {"employee": employee, "review_type": review_type, "end_date": end_date}):
		return

	try:
		doc = frappe.get_doc({"doctype": DOCTYPE, "employee": employee, "review_type": review_type, "end_date": end_date})
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Employee Contract Review: {0}".format(employee), message=frappe.get_traceback())


def send_one_month_reminders():
	reviews = frappe.get_all(
		DOCTYPE,
		filters={
			"status": ["in", OPEN_STATUSES],
			"end_date": ["between", [today(), add_months(today(), 1)]],
			"second_reminder_on": ["is", "not set"],
		},
		fields=["name"],
		limit_page_length=JOB_LIMIT,
	)
	for review in reviews:
		try:
			doc = frappe.get_doc(DOCTYPE, review.name)
			send_stage_emails(doc, reminder=True)
			doc.db_set("second_reminder_on", today(), update_modified=False)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title="Employee Contract Review: {0}".format(review.name), message=frappe.get_traceback())


# Recipients
# ----------


def get_hr_approvers():
	value = None
	if frappe.get_meta(SETTINGS_DOCTYPE).has_field(HR_FIELD):
		value = frappe.db.get_single_value(SETTINGS_DOCTYPE, HR_FIELD)

	users = [u.strip() for u in (value or "").replace("\n", ",").replace(";", ",").split(",") if u.strip()]
	users = list(dict.fromkeys(users or HR_DEFAULT))
	if not users:
		return []

	enabled = {u.name for u in frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, fields=["name"])}
	return [u for u in users if u in enabled]


def is_hr_approver(user):
	if not user or user == "Guest":
		return False
	return user in get_hr_approvers() or bool(HR_ROLES & set(frappe.get_roles(user)))


def share_with(doc, user):
	share = getattr(frappe.share, "add_docshare", None) or frappe.share.add
	share(doc.doctype, doc.name, user, read=1, write=0, flags={"ignore_share_permission": True}, notify=0)


# Wording
# -------


def decision_label(review_type, decision):
	if review_type == PROBATION_END:
		return _("Confirm employee") if decision == RENEW else _("End employment")
	return _("Renew contract") if decision == RENEW else _("End contract")


def final_status(review_type, decision):
	if decision == END:
		return "Ended"
	return "Confirmed" if review_type == PROBATION_END else "Renewed"


def end_date_label(doc):
	return "Probation End Date" if doc.review_type == PROBATION_END else "Contract End Date"


def subject_for(doc, prefix):
	what = _("Probation") if doc.review_type == PROBATION_END else _("Contract")
	return "{0}: {1} of {2} ends on {3}".format(prefix, what, doc.employee_name or doc.employee, formatdate(doc.end_date))


# Emails
# ------


def send_stage_emails(doc, reminder=False):
	hr = get_hr_approvers()
	prefix = _("Reminder") if reminder else _("Approval needed")
	name = escape(doc.employee_name or doc.employee)
	what = _("probation period") if doc.review_type == PROBATION_END else _("employment contract")
	ends = _("The {0} of <b>{1}</b> ends on <b>{2}</b>.").format(what, name, formatdate(doc.end_date))

	if doc.status == PENDING_LINE_MANAGER and doc.line_manager_user:
		choice = (
			_("Confirm the employee or end the employment.")
			if doc.review_type == PROBATION_END
			else _("Renew the contract or end it.")
		)
		send_action_email(doc, doc.line_manager_user, subject_for(doc, prefix), "{0} {1} {2}".format(ends, choice, _("HR approves next.")))

		heads_up = [u for u in hr if u != doc.line_manager_user]
		if SEND_HR_HEADS_UP and heads_up:
			send_email(
				doc,
				heads_up,
				subject_for(doc, _("Reminder") if reminder else _("For information")),
				_("Waiting for line manager"),
				"{0} {1}".format(
					ends,
					_("The line manager, <b>{0}</b>, has been asked to decide. The approval comes to HR after that.").format(
						escape(doc.line_manager_name or doc.line_manager_user)
					),
				),
			)

	elif doc.status == PENDING_HR:
		if doc.line_manager_decision:
			intro = "{0} {1}".format(
				ends,
				_("<b>{0}</b> recommends: <b>{1}</b>. Approve it, or choose the other option.").format(
					escape(doc.line_manager_name or doc.line_manager_user),
					escape(decision_label(doc.review_type, doc.line_manager_decision)),
				),
			)
		else:
			intro = "{0} {1}".format(ends, _("No line manager with an ERP user is set for this employee, so the decision is with HR."))
		for user in hr:
			send_action_email(doc, user, subject_for(doc, prefix), intro)


def send_action_email(doc, user, subject, intro):
	actions = [
		(decision_label(doc.review_type, RENEW), action_url(doc, RENEW, user), "ok"),
		(decision_label(doc.review_type, END), action_url(doc, END, user), "bad"),
	]
	note = None
	if doc.review_type == CONTRACT_END and doc.status == PENDING_HR:
		note = _("To renew with a new contract end date, enter it on the review before approving, or update the employee afterwards.")
	send_email(doc, [user], subject, _("Approval needed"), intro, actions=actions, note=note)


def send_outcome_email(doc):
	recipients = list(dict.fromkeys(get_hr_approvers() + ([doc.line_manager_user] if doc.line_manager_user else [])))
	if not recipients:
		return

	label = decision_label(doc.review_type, doc.hr_decision)
	intro = _("HR approved <b>{0}</b> for <b>{1}</b> ({2}: {3}).").format(
		escape(label), escape(doc.employee_name or doc.employee), _(end_date_label(doc)), formatdate(doc.end_date)
	)
	if doc.review_type == CONTRACT_END and doc.hr_decision == RENEW:
		if doc.new_contract_end_date:
			intro += " " + _("New contract end date: <b>{0}</b>.").format(formatdate(doc.new_contract_end_date))
		else:
			intro += " " + _("Update the contract end date on the employee record.")
	elif doc.hr_decision == END:
		intro += " " + _("HR to proceed with the separation.")

	send_email(doc, recipients, "{0}: {1}, {2}".format(_("Decision recorded"), label, doc.employee_name or doc.employee), _(doc.status), intro)


def send_email(doc, recipients, subject, badge, intro, actions=None, note=None):
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		message=render_email(doc, badge, intro, actions, note),
		reference_doctype=doc.doctype,
		reference_name=doc.name,
	)


def get_brand(company):
	return BRANDS.get(company) or BRANDS[DEFAULT_BRAND]


def render_email(doc, badge, intro, actions=None, note=None):
	b = get_brand(doc.company)
	font = "font-family:'Segoe UI', Tahoma, Arial, Helvetica, sans-serif;"
	tone = "#b45309;background:#fef3c7" if doc.status in OPEN_STATUSES else (
		"#b91c1c;background:#fee2e2" if doc.status in ("Ended", CANCELLED) else "#15803d;background:#dcfce7"
	)
	logo_size = 'width="{0}" height="{1}" style="display:block;width:{0}px;height:{1}px;'.format(b["logo_w"], b["logo_h"]) if b.get("logo_w") else 'height="{0}" style="display:block;height:{0}px;width:auto;max-width:200px;'.format(b["logo_h"])

	rows = [
		(_("Employee"), doc.employee_name),
		(_("Employee ID"), doc.employee),
		(_("Designation"), doc.designation),
		(_("Department"), doc.department),
		(_("Date of Joining"), formatdate(doc.date_of_joining) if doc.date_of_joining else None),
		(_(end_date_label(doc)), formatdate(doc.end_date)),
		(_("Line Manager"), doc.line_manager_name),
		(_("Line Manager Decision"), decision_label(doc.review_type, doc.line_manager_decision) if doc.line_manager_decision else None),
		(_("Review"), '<a href="{0}" style="color:{1};font-weight:700;text-decoration:none;">{2}</a>'.format(get_url_to_form(DOCTYPE, doc.name), b["primary"], doc.name)),
	]
	row_html = "".join(
		'<tr><td valign="top" style="padding:7px 12px 7px 0;width:38%;color:#64748b;border-bottom:1px solid #f1f5f9;">{0}</td>'
		'<td valign="top" style="padding:7px 0;color:#0f172a;font-weight:500;border-bottom:1px solid #f1f5f9;word-break:break-word;">{1}</td></tr>'.format(
			label, value if label == _("Review") else escape(str(value))
		)
		for label, value in rows
		if value not in (None, "")
	)

	buttons = ""
	if actions:
		cells = ""
		for label, url, kind in actions:
			if kind == "bad":
				bg, fg, border = "#ffffff", "#b91c1c", "border:2px solid #b91c1c;"
			else:
				bg, fg, border = b["primary"], "#ffffff", ""
			cells += (
				'<td style="padding:0 6px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;"><tr>'
				'<td align="center" bgcolor="{0}" style="background:{0};{2}border-radius:8px;padding:12px 28px;mso-padding-alt:12px 28px;font-size:14px;line-height:20px;font-weight:700;">'
				'<a href="{3}" target="_blank" style="color:{1};text-decoration:none;font-weight:700;display:inline-block;">{4}</a></td></tr></table></td>'
			).format(bg, fg, border, url, escape(label))
		buttons = (
			'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:22px auto 6px;border-collapse:separate;"><tr>{0}</tr></table>'
			'<div style="margin-top:22px;padding-top:12px;border-top:1px solid #e2e8f0;font-size:12px;line-height:18px;color:#94a3b8;">{1}</div>'
		).format(cells, _("Each button asks you to confirm before anything is recorded. The buttons act on your behalf; do not forward this email."))
	else:
		buttons = (
			'<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:22px auto 6px;"><tr>'
			'<td align="center" bgcolor="{0}" style="background:{0};border-radius:8px;"><a href="{1}" target="_blank" style="display:inline-block;padding:12px 30px;font-size:14px;line-height:20px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:8px;">{2}</a></td>'
			"</tr></table>"
		).format(b["primary"], get_url_to_form(DOCTYPE, doc.name), _("Open Review"))

	note_html = '<p style="margin:0 0 14px;font-size:13px;line-height:1.6;color:#475569;">{0}</p>'.format(note) if note else ""
	confidential = (
		'<div style="margin-top:12px;padding-top:10px;border-top:1px solid #dfe3eb;font-size:11px;line-height:16px;color:#8a93a3;">{0}</div>'.format(
			_("This email and any attachments are confidential and intended only for the named recipient. If you have received it in error, please notify the sender and delete it.")
		)
		if b.get("confidential")
		else ""
	)

	return (
		'<!-- brand-wrap:v1 --><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef1f6" style="background:#eef1f6;margin:0;padding:0;"><tr><td align="center" style="padding:28px 12px;">'
		'<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;border-collapse:separate;">'
		'<tr><td bgcolor="{p}" style="background:{p};background-image:linear-gradient(135deg,{g0} 0%,{p} 58%,{g2} 100%);border-radius:14px 14px 0 0;padding:20px 24px;">'
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td valign="middle" style="padding:0;">'
		'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td bgcolor="#ffffff" style="background:#ffffff;border-radius:10px;padding:8px 12px;">'
		'<img src="{logo}" alt="{co}" {logo_size}border:0;outline:none;text-decoration:none;{font}font-size:12px;font-weight:700;color:{p};"></td></tr></table></td>'
		'<td valign="middle" align="right" style="padding:0 0 0 12px;{font}font-size:11px;line-height:16px;letter-spacing:1.5px;text-transform:uppercase;color:#ffffff;">{dt}</td></tr></table></td></tr>'
		'<tr><td height="4" bgcolor="{a}" style="height:4px;line-height:4px;font-size:0;background:{a};background-image:linear-gradient(90deg,{a},{a2});">&nbsp;</td></tr>'
		'<tr><td dir="auto" bgcolor="#ffffff" style="background:#ffffff;padding:32px 32px 28px;{font}font-size:14px;line-height:1.65;color:#1f2937;">'
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-bottom:2px solid #e2e8f0;margin:0 0 18px;"><tr>'
		'<td valign="middle" style="padding:0 0 12px;font-size:19px;line-height:26px;font-weight:700;color:#0f172a;">{heading}</td>'
		'<td valign="middle" align="right" style="padding:0 0 12px 12px;"><span style="display:inline-block;font-size:12px;line-height:18px;font-weight:700;color:{tone};padding:3px 10px;border-radius:999px;white-space:nowrap;">{badge}</span></td></tr></table>'
		'<p style="margin:0 0 14px;font-size:14px;line-height:1.6;color:#1e293b;">{intro}</p>'
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 18px;"><tr><td bgcolor="{t}" style="background:{t};border-left:4px solid {a};border-radius:0 6px 6px 0;padding:13px 18px;">'
		'<div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:#64748b;">{date_label}</div>'
		'<div style="margin-top:3px;font-size:22px;line-height:28px;font-weight:800;color:{p};">{date}</div>'
		'<div style="margin-top:2px;font-size:12px;line-height:17px;color:#64748b;">{who}</div></td></tr></table>'
		'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:0 0 18px;font-size:13.5px;line-height:20px;">{rows}</table>'
		"{note}{buttons}</td></tr>"
		'<tr><td bgcolor="{t}" style="background:{t};border-top:1px solid #e3e7ef;border-radius:0 0 14px 14px;padding:18px 32px 20px;{font}font-size:12px;line-height:18px;color:#5b6475;">'
		'<strong style="color:{p};">{co}</strong><br>{sent} &middot; <a href="https://{site}" style="color:{p};text-decoration:none;">{site}</a>{confidential}</td></tr>'
		"</table></td></tr></table>"
	).format(
		p=b["primary"],
		g0=b["grad"][0],
		g2=b["grad"][1],
		a=b["accent"],
		a2=b["accent2"],
		t=b["tint"],
		logo=b["logo"],
		logo_size=logo_size,
		co=escape(b["company"]),
		font=font,
		dt=_("Employee Contract Review"),
		heading=_("Probation Period Ending") if doc.review_type == PROBATION_END else _("Employment Contract Ending"),
		tone=tone,
		badge=escape(badge),
		intro=intro,
		date_label=_(end_date_label(doc)),
		date=formatdate(doc.end_date),
		who=escape(" · ".join([v for v in (doc.employee_name, doc.designation) if v])),
		rows=row_html,
		note=note_html,
		buttons=buttons,
		sent=_("Sent automatically from {0}").format(ERP_NAME),
		site=SITE,
		confidential=confidential,
	)
