# Copyright (c) 2026, Omnieast and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import add_days, getdate, today

from erpnext.accounts import deferred_revenue
from erpnext.accounts.deferred_revenue import (
	build_conditions,
	convert_deferred_expense_to_expense,
	convert_deferred_revenue_to_income,
)


class ProcessDeferredAccountingMixin:
	def on_submit(self):
		_original_get_booking_dates = deferred_revenue.get_booking_dates
		deferred_revenue.get_booking_dates = get_booking_dates
		try:
			conditions = build_conditions(self.type, self.account, self.company)
			if self.type == "Income":
				convert_deferred_revenue_to_income(
					self.name, self.start_date, self.end_date, conditions
				)
			else:
				convert_deferred_expense_to_expense(
					self.name, self.start_date, self.end_date, conditions
				)
		finally:
			deferred_revenue.get_booking_dates = _original_get_booking_dates


def get_booking_dates(doc, item, posting_date=None, prev_posting_date=None):
	if not posting_date:
		posting_date = add_days(today(), -1)

	last_gl_entry = False

	deferred_account = (
		"deferred_revenue_account" if doc.doctype == "Sales Invoice" else "deferred_expense_account"
	)

	if not prev_posting_date:
		prev_gl_entry = frappe.db.sql(
			"""
			select name, posting_date from `tabGL Entry` where company=%s and account=%s and
			voucher_type=%s and voucher_no=%s and voucher_detail_no=%s
			and is_cancelled = 0
			order by posting_date desc limit 1
		""",
			(doc.company, item.get(deferred_account), doc.doctype, doc.name, item.name),
			as_dict=True,
		)

		prev_gl_via_je = frappe.db.sql(
			"""
			SELECT p.name, p.posting_date FROM `tabJournal Entry` p, `tabJournal Entry Account` c
			WHERE p.name = c.parent and p.company=%s and c.account=%s
			and c.reference_type=%s and c.reference_name=%s
			and c.reference_detail_no=%s and c.docstatus < 2 order by posting_date desc limit 1
		""",
			(doc.company, item.get(deferred_account), doc.doctype, doc.name, item.name),
			as_dict=True,
		)

		if prev_gl_via_je:
			if (not prev_gl_entry) or (
				prev_gl_entry and prev_gl_entry[0].posting_date < prev_gl_via_je[0].posting_date
			):
				prev_gl_entry = prev_gl_via_je

		if prev_gl_entry:
			start_date = getdate(add_days(prev_gl_entry[0].posting_date, 1))
		else:
			# book remaining from today's posting_date forward, not retroactively from service_start_date
			start_date = (
				item.service_start_date
				if getdate(item.service_start_date) > getdate(posting_date)
				else getdate(posting_date)
			)
	else:
		start_date = getdate(add_days(prev_posting_date, 1))

	# book up to the Process posting_date, not month-end
	end_date = getdate(posting_date)
	if end_date >= getdate(item.service_end_date):
		end_date = item.service_end_date
		last_gl_entry = True
	elif item.service_stop_date and end_date >= getdate(item.service_stop_date):
		end_date = item.service_stop_date
		last_gl_entry = True

	if getdate(start_date) <= getdate(end_date):
		return start_date, end_date, last_gl_entry
	else:
		return None, None, None
