# Copyright (c) 2026, Jawa Group and contributors
# For license information, please see license.txt
"""Related Party Mapping: the lines of the Related Party Balances report, one list per company.

Finance keeps the list here (sister-company customers, suppliers and the current accounts
under the company's Affiliate Accounts group) so a new sister company needs no developer.
The daily email of the report is sent from here too (hooks: cron 30 7 * * *): one email per
set of recipients, with one Excel file per company.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, fmt_money, formatdate, today

CURRENT_ACCOUNT = "Current Account"
MAPPING = "Related Party Mapping"


class RelatedPartyMapping(Document):
	def validate(self):
		self.validate_group()
		self.validate_lines()
		self.validate_emails()

	def validate_group(self):
		group = frappe.db.get_value(
			"Account", self.related_parties_group, ["company", "is_group"], as_dict=True
		)
		if not group or group.company != self.company or not group.is_group:
			frappe.throw(
				_("Related Parties Group Account must be a group account of {0}.").format(
					frappe.bold(self.company)
				)
			)

	def validate_lines(self):
		lft, rgt = frappe.db.get_value("Account", self.related_parties_group, ["lft", "rgt"])
		seen = {}
		for row in self.lines:
			if not cint(row.sort_order):
				row.sort_order = row.idx * 10
			if row.line_type == CURRENT_ACCOUNT:
				row.party = None
				if not row.account:
					frappe.throw(_("Row {0}: Account is required for a Current Account line.").format(row.idx))
				acc = frappe.db.get_value(
					"Account", row.account, ["company", "is_group", "lft", "rgt"], as_dict=True
				)
				if not acc or acc.company != self.company or acc.is_group or not (
					acc.lft > lft and acc.rgt < rgt
				):
					frappe.throw(
						_("Row {0}: {1} is not an account under {2}.").format(
							row.idx, frappe.bold(row.account), frappe.bold(self.related_parties_group)
						)
					)
				key = (CURRENT_ACCOUNT, row.account)
			else:
				row.account = None
				if not row.party:
					frappe.throw(_("Row {0}: Party is required for a {1} line.").format(row.idx, row.line_type))
				key = (row.line_type, row.party)

			if key in seen:
				frappe.throw(
					_("Row {0}: {1} is already on row {2}.").format(row.idx, frappe.bold(key[1]), seen[key])
				)
			seen[key] = row.idx

	def validate_emails(self):
		if cint(self.send_daily_email):
			emails = split_emails(self.daily_email_to)
			if not emails:
				frappe.throw(_("Add at least one email address to Send To."))
			for email in emails:
				frappe.utils.validate_email_address(email, throw=True)
			self.daily_email_to = "\n".join(emails)


def split_emails(text):
	return [e for e in re.split(r"[\s,;]+", text or "") if e]


def send_daily_email():
	"""Scheduler, 07:30 every day: the report as Excel files to Finance."""
	mappings = [
		frappe.get_doc(MAPPING, name)
		for name in frappe.get_all(MAPPING, filters={"send_daily_email": 1}, pluck="name", order_by="name")
	]
	send_reports([m for m in mappings if split_emails(m.daily_email_to)])


@frappe.whitelist()
def send_now(company):
	"""Button on the form: send today's email for this company now (to test the recipients)."""
	frappe.only_for("Related Party Balances")
	mapping = frappe.get_doc(MAPPING, company)
	mapping.check_permission("read")
	if not split_emails(mapping.daily_email_to):
		frappe.throw(_("Add at least one email address to Send To."))
	send_reports([mapping])
	frappe.msgprint(_("Sent to {0}.").format(", ".join(split_emails(mapping.daily_email_to))), alert=True)


def send_reports(mappings):
	"""One email per set of recipients: a summary per company and one Excel file per company."""
	by_recipients = {}
	for m in mappings:
		by_recipients.setdefault(tuple(sorted(split_emails(m.daily_email_to))), []).append(m)

	to_date = today()
	for recipients, group in by_recipients.items():
		companies, attachments = [], []
		for m in group:
			try:
				summary, xlsx = build_company(m.company, to_date)
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Related Party Balances email: " + m.company)
				continue
			companies.append(summary)
			attachments.append({"fname": "Related-Party-Balances-{0}-{1}.xlsx".format(file_label(m.company), to_date), "fcontent": xlsx})
		if not companies:
			continue
		frappe.sendmail(
			recipients=list(recipients),
			subject=_("Related Party Balances – {0}").format(formatdate(to_date)),
			message=frappe.render_template(EMAIL_TEMPLATE, {"companies": companies}),
			attachments=attachments,
			reference_doctype=MAPPING,
			reference_name=group[0].name,
		)


def build_company(company, to_date):
	from omnieast.omnieast.report.related_party_balances.related_party_balances import (
		execute,
		fiscal_year_start,
	)

	from_date = fiscal_year_start(to_date, company)
	columns, data = execute({
		"company": company, "from_date": from_date, "to_date": to_date,
		"group_by_related_company": 1, "show_ageing": 1,
	})[:2]

	total = next((r for r in data if r.get("is_total_row")), {})
	currency = frappe.get_cached_value("Company", company, "default_currency")
	summary = {
		"company": company,
		"period": "{0} to {1}".format(formatdate(from_date), formatdate(to_date)),
		"rows": [
			(_("Balance at {0}").format(formatdate(from_date)), money(total.get("balance_from"), currency)),
			(_("Debit"), money(total.get("debit"), currency)),
			(_("Credit"), money(total.get("credit"), currency)),
			(_("Balance at {0}").format(formatdate(to_date)), money(total.get("balance_to"), currency)),
		],
	}
	return summary, make_xlsx_file(columns, data)


def make_xlsx_file(columns, data):
	"""Visible columns only, numbers kept as numbers."""
	from frappe.utils.xlsxutils import make_xlsx

	visible = [c for c in columns if not c.get("hidden")]
	rows = [[c.get("label") for c in visible]]
	for r in data:
		rows.append([
			flt(r.get(c["fieldname"]), 2) if c.get("fieldtype") == "Currency" else (r.get(c["fieldname"]) or "")
			for c in visible
		])
	return make_xlsx(rows, "Related Party Balances").getvalue()


def file_label(company):
	return re.sub(r"[^A-Za-z0-9]+", "-", company).strip("-")[:40]


def money(value, currency):
	return fmt_money(flt(value, 2), precision=2, currency=currency)


EMAIL_TEMPLATE = """
<p>Related Party Balances, all finance books. The full report of each company is attached as an Excel file.</p>
{% for c in companies %}
<p style="margin:16px 0 4px;font-weight:600">{{ c.company }} &middot; {{ c.period }}</p>
<table style="border-collapse:collapse;font-size:13px">
{% for label, value in c.rows %}
<tr>
<td style="padding:4px 16px 4px 0;color:#555">{{ label }}</td>
<td style="padding:4px 0;text-align:right;font-weight:600">{{ value }}</td>
</tr>
{% endfor %}
</table>
{% endfor %}
"""
