# Copyright (c) 2026, Jawa Group and contributors
# For license information, please see license.txt
"""Related Party Balances: Finance's related-party sheet, live from the GL.

One row per line of the company's Related Party Mapping:
  - Customer / Supplier lines: every GL Entry of that party (any account except those
    under the company's Affiliate Accounts group, so nothing is counted twice).
  - Current Account lines: every GL Entry on that account under the group, whatever the party.
Accounts under the group that are not in the list at all show at the bottom as Unmapped.

Opening = everything posted before From Date, so balance-sheet history is carried in full.
A blank Finance Book means all books together; a chosen book filters on exactly that book.

Two grouped queries (party, account), on the indexed party / account / posting_date columns.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate, today

CURRENT_ACCOUNT = "Current Account"
UNMAPPED = "Unmapped"
MAPPING = "Related Party Mapping"
# Ageing buckets (days before To Date), the same as our Accounts Receivable: fieldname, label
AGEING = (
	("age_0_30", "0-30"),
	("age_31_60", "31-60"),
	("age_61_90", "61-90"),
	("age_91_120", "91-120"),
	("age_121_180", "121-180"),
	("age_181_360", "181-360"),
	("age_361_520", "361-520"),
	("age_over_520", "Above 520"),
)
NUMBERS = ("opening_dr", "opening_cr", "balance_from", "debit", "credit", "closing_dr", "closing_cr", "balance_to") + tuple(
	f for f, _label in AGEING
)

PARTY_SQL = """
	SELECT gle.party,
		SUM(CASE WHEN gle.posting_date < %(from_date)s THEN gle.debit - gle.credit ELSE 0 END) AS opening,
		SUM(CASE WHEN gle.posting_date >= %(from_date)s THEN gle.debit ELSE 0 END) AS debit,
		SUM(CASE WHEN gle.posting_date >= %(from_date)s THEN gle.credit ELSE 0 END) AS credit
	FROM `tabGL Entry` gle
	WHERE gle.is_cancelled = 0
		AND gle.company = %(company)s
		AND gle.posting_date <= %(to_date)s
		AND gle.party_type = %(party_type)s
		AND gle.party IN %(parties)s
		AND gle.account NOT IN %(group_accounts)s
		AND (%(finance_book)s = '' OR gle.finance_book = %(finance_book)s)
	GROUP BY gle.party
"""

# Ageing the same way as the Accounts Receivable / Payable reports: every invoice (or unallocated
# payment) still open at To Date, aged by its due date (posting date when it has none).
# v14 and later: the Payment Ledger. Open amounts in company currency; Dr positive.
OPEN_ITEMS_PLE_SQL = """
	SELECT ple.party,
		SUM(ple.amount) AS outstanding,
		MAX(CASE WHEN ple.voucher_type = ple.against_voucher_type AND ple.voucher_no = ple.against_voucher_no
			THEN COALESCE(ple.due_date, ple.posting_date) END) AS ref_date,
		MIN(ple.posting_date) AS first_date
	FROM `tabPayment Ledger Entry` ple
	WHERE ple.delinked = 0
		AND ple.company = %(company)s
		AND ple.posting_date <= %(to_date)s
		AND ple.party_type = %(party_type)s
		AND ple.party IN %(parties)s
		AND ple.account_type = %(account_type)s
		AND (%(finance_book)s = '' OR ple.finance_book = %(finance_book)s)
	GROUP BY ple.party, ple.against_voucher_type, ple.against_voucher_no
	HAVING ABS(SUM(ple.amount)) > 0.005
"""

# v13 has no Payment Ledger: the same from the GL (against_voucher, or the entry itself when unallocated)
OPEN_ITEMS_GL_SQL = """
	SELECT gle.party,
		COALESCE(NULLIF(gle.against_voucher_type, ''), gle.voucher_type) AS ref_type,
		COALESCE(NULLIF(gle.against_voucher, ''), gle.voucher_no) AS ref_no,
		SUM(gle.debit - gle.credit) AS outstanding,
		MIN(gle.posting_date) AS first_date
	FROM `tabGL Entry` gle
	INNER JOIN `tabAccount` acc ON acc.name = gle.account
	WHERE gle.is_cancelled = 0
		AND gle.company = %(company)s
		AND gle.posting_date <= %(to_date)s
		AND gle.party_type = %(party_type)s
		AND gle.party IN %(parties)s
		AND acc.account_type = %(account_type)s
		AND (%(finance_book)s = '' OR gle.finance_book = %(finance_book)s)
	GROUP BY gle.party, ref_type, ref_no
	HAVING ABS(SUM(gle.debit - gle.credit)) > 0.005
"""

ACCOUNT_SQL = """
	SELECT gle.account,
		SUM(CASE WHEN gle.posting_date < %(from_date)s THEN gle.debit - gle.credit ELSE 0 END) AS opening,
		SUM(CASE WHEN gle.posting_date >= %(from_date)s THEN gle.debit ELSE 0 END) AS debit,
		SUM(CASE WHEN gle.posting_date >= %(from_date)s THEN gle.credit ELSE 0 END) AS credit
	FROM `tabGL Entry` gle
	WHERE gle.is_cancelled = 0
		AND gle.company = %(company)s
		AND gle.posting_date <= %(to_date)s
		AND gle.account IN %(accounts)s
		AND (%(finance_book)s = '' OR gle.finance_book = %(finance_book)s)
	GROUP BY gle.account
"""


def execute(filters=None):
	filters = frappe._dict(filters or {})
	set_defaults(filters)
	data = get_data(filters)
	return get_columns(filters), data, None, get_chart(data, filters)


def balance_labels(filters=None):
	"""Finance wants the real dates in the headings, e.g. "Balance at 01-01-2026"."""
	filters = filters or {}
	from_date, to_date = filters.get("from_date"), filters.get("to_date")
	return (
		_("Balance at {0}").format(formatdate(from_date)) if from_date else _("Balance at From Date"),
		_("Balance at {0}").format(formatdate(to_date)) if to_date else _("Balance at To Date"),
	)


def get_chart(data, filters=None):
	"""Bar chart: balance at To Date per sister company, highest to lowest."""
	by_company = {}
	for r in data:
		if r.get("bold"):
			continue
		name = r.get("related_company") or ""
		by_company[name] = flt(by_company.get(name, 0) + flt(r.get("balance_to")), 2)
	items = sorted(((k, v) for k, v in by_company.items() if v), key=lambda kv: -kv[1])
	if not items:
		return None
	return {
		"data": {
			"labels": [k for k, v in items],
			"datasets": [{"name": balance_labels(filters)[1], "values": [v for k, v in items]}],
			"yRegions": headroom(items),
		},
		"type": "bar",
		"colors": ["#183058"],
		"fieldtype": "Currency",
		"currency": data[-1].get("currency"),
		"height": 320,
		"barOptions": {"spaceRatio": 0.4},
	}


def fiscal_year_start(date, company):
	from erpnext.accounts.utils import get_fiscal_year

	try:
		return get_fiscal_year(date, company=company)[1]
	except Exception:
		return getdate(date).replace(month=1, day=1)


def get_mapping(company):
	"""The company's list of lines (one Related Party Mapping per company)."""
	if not company or not frappe.db.exists(MAPPING, company):
		frappe.throw(
			_("There is no Related Party Mapping for {0} yet. Use Edit Lines to set one up.").format(
				frappe.bold(company or _("this company"))
			)
		)
	return frappe.get_cached_doc(MAPPING, company)


def set_defaults(filters):
	"""Blank dates roll with the calendar (used by the daily email)."""
	if not filters.company:
		filters.company = frappe.db.get_value(MAPPING, {}, "name")
	filters.to_date = getdate(filters.to_date or today())
	filters.from_date = getdate(filters.from_date or fiscal_year_start(filters.to_date, filters.company))
	filters.finance_book = filters.finance_book or ""
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date."))


def get_columns(filters=None):
	def amount(label, fieldname, width=150):
		return {"label": _(label), "fieldname": fieldname, "fieldtype": "Currency", "options": "currency", "width": width}

	ageing = [amount(label, fieldname, 130) for fieldname, label in AGEING] if cint((filters or {}).get("show_ageing")) else []
	from_label, to_label = balance_labels(filters)
	return [
		{"label": _("Code"), "fieldname": "code", "fieldtype": "Data", "width": 100},
		{"label": _("Account"), "fieldname": "account", "fieldtype": "Data", "width": 280},
		{"label": _("Company Name"), "fieldname": "related_company", "fieldtype": "Data", "width": 260},
		{"label": _("Type"), "fieldname": "line_type", "fieldtype": "Data", "width": 120},
		amount("Opening (Dr)", "opening_dr"),
		amount("Opening (Cr)", "opening_cr"),
		amount(from_label, "balance_from"),
		amount("Debit", "debit"),
		amount("Credit", "credit"),
		amount("Closing (Dr)", "closing_dr"),
		amount("Closing (Cr)", "closing_cr"),
		amount(to_label, "balance_to"),
		*ageing,
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "hidden": 1},
		{"label": _("GL Account"), "fieldname": "gl_account", "fieldtype": "Data", "hidden": 1},
	]


def get_lines(settings, company):
	"""Mapping lines to show (Include ticked), then the group's accounts missing from the list."""
	lines = [frappe._dict(l.as_dict()) for l in settings.lines if cint(l.include)]
	lines.sort(key=lambda l: (cint(l.sort_order), l.idx))

	lft, rgt = frappe.db.get_value("Account", settings.related_parties_group, ["lft", "rgt"]) or (0, 0)
	group_accounts = frappe.get_all(
		"Account",
		filters={"company": company, "lft": (">", lft), "rgt": ("<", rgt), "is_group": 0},
		fields=["name", "account_number", "account_name"],
		order_by="lft",
	)
	listed = {l.account for l in settings.lines if l.line_type == CURRENT_ACCOUNT}
	for acc in group_accounts:
		if acc.name not in listed:
			lines.append(frappe._dict(line_type=CURRENT_ACCOUNT, account=acc.name, related_company=UNMAPPED, unmapped=1))
	return lines, group_accounts


def get_data(filters):
	settings = get_mapping(filters.company)
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	lines, group_accounts = get_lines(settings, filters.company)

	if filters.related_company:
		needle = filters.related_company.strip().lower()
		lines = [l for l in lines if needle in (l.related_company or "").lower()]

	params = dict(
		company=filters.company,
		from_date=filters.from_date,
		to_date=filters.to_date,
		finance_book=filters.finance_book,
		group_accounts=tuple(a.name for a in group_accounts) or ("",),
	)

	balances = {}
	movements = {}
	names = {}
	for party_type, name_field in (("Customer", "customer_name"), ("Supplier", "supplier_name")):
		parties = tuple({l.party for l in lines if l.line_type == party_type and l.party})
		if not parties:
			continue
		for r in frappe.db.sql(PARTY_SQL, dict(params, party_type=party_type, parties=parties), as_dict=True):
			balances[(party_type, r.party)] = r
		if cint(filters.show_ageing):
			for party, buckets in open_item_ageing(params, party_type, parties).items():
				movements[(party_type, party)] = buckets
		for p in frappe.get_all(party_type, filters={"name": ("in", parties)}, fields=["name", name_field]):
			names[(party_type, p.name)] = (p.get(name_field) or p.name).strip()

	accounts = tuple({l.account for l in lines if l.line_type == CURRENT_ACCOUNT and l.account})
	if accounts:
		for r in frappe.db.sql(ACCOUNT_SQL, dict(params, accounts=accounts), as_dict=True):
			balances[(CURRENT_ACCOUNT, r.account)] = r
		for a in frappe.get_all("Account", filters={"name": ("in", accounts)}, fields=["name", "account_number", "account_name"]):
			names[(CURRENT_ACCOUNT, a.name)] = " ".join(x for x in (a.account_number, a.account_name) if x)

	rows = []
	for l in lines:
		if l.line_type == CURRENT_ACCOUNT:
			key = (CURRENT_ACCOUNT, l.account)
			row = frappe._dict(code="", account=names.get(key, l.account), gl_account=l.account)
		else:
			key = (l.line_type, l.party)
			row = frappe._dict(code=l.party, account=names.get(key, l.party), party_type=l.line_type)
		# v13: _dict.update() takes one dict, not keyword arguments
		row.update(dict(related_company=l.related_company, line_type=l.line_type, currency=currency, unmapped=l.get("unmapped", 0)))

		b = balances.get(key) or {}
		opening, debit, credit = flt(b.get("opening"), 2), flt(b.get("debit"), 2), flt(b.get("credit"), 2)
		closing = flt(opening + debit - credit, 2)
		row.update(dict(
			opening_dr=opening if opening > 0 else 0,
			opening_cr=-opening if opening < 0 else 0,
			balance_from=opening,
			debit=debit,
			credit=credit,
			closing_dr=closing if closing > 0 else 0,
			closing_cr=-closing if closing < 0 else 0,
			balance_to=closing,
		))
		if cint(filters.show_ageing) and l.line_type != CURRENT_ACCOUNT:
			row.update(movements.get(key) or {f: 0 for f, _label in AGEING})
		if cint(filters.hide_zero_rows) and not any((opening, debit, credit, closing)):
			continue
		rows.append(row)

	# highest balance first; accounts missing from the list stay at the bottom
	rows.sort(key=lambda r: (cint(r.unmapped), -flt(r.balance_to)))

	if cint(filters.group_by_related_company):
		rows = with_subtotals(rows, currency)

	rows.append(total_row(_("Total"), [r for r in rows if not r.get("is_subtotal")], currency, is_total_row=1))
	return rows


def with_subtotals(rows, currency):
	"""Rows grouped by sister company, highest company balance first, a subtotal row after each group."""
	groups = {}
	for r in rows:
		groups.setdefault(r.related_company or "", []).append(r)
	ordered = sorted(
		groups.items(),
		key=lambda kv: (max(cint(r.unmapped) for r in kv[1]), -sum(flt(r.balance_to) for r in kv[1])),
	)
	out = []
	for company, members in ordered:
		out.extend(members)
		out.append(total_row(_("Subtotal – {0}").format(company), members, currency, is_subtotal=1, related_company=company))
	return out


# Upper day of each AGEING bucket; the last bucket is everything older
AGEING_DAYS = (30, 60, 90, 120, 180, 360, 520)


def open_item_ageing(params, party_type, parties):
	"""{party: {bucket fieldname: amount}} from the open invoices, exactly like Accounts Receivable /
	Payable with Ageing Based On = Due Date: each open item is aged by its due date (posting date
	when it has none); an item not yet due goes in no bucket, as on that report."""
	args = dict(params, party_type=party_type, parties=parties,
		account_type="Receivable" if party_type == "Customer" else "Payable")
	to_date = getdate(params["to_date"])

	if frappe.db.table_exists("Payment Ledger Entry"):
		items = frappe.db.sql(OPEN_ITEMS_PLE_SQL, args, as_dict=True)
		# the Payment Ledger keeps payables as positive amounts; the report shows Dr positive
		sign = 1 if party_type == "Customer" else -1
		for i in items:
			i.outstanding = sign * flt(i.outstanding)
	else:
		items = frappe.db.sql(OPEN_ITEMS_GL_SQL, args, as_dict=True)
		due = {}
		for doctype in ("Sales Invoice", "Purchase Invoice"):
			names = list({i.ref_no for i in items if i.ref_type == doctype})
			if names:
				for d in frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["name", "due_date", "posting_date"]):
					due[(doctype, d.name)] = d.due_date or d.posting_date
		for i in items:
			i.ref_date = due.get((i.ref_type, i.ref_no))

	out = {}
	for i in items:
		ref_date = getdate(i.ref_date or i.first_date)
		buckets = out.setdefault(i.party, {f: 0 for f, _label in AGEING})
		if ref_date > to_date:
			continue  # not due yet: in the balance, in no bucket (as on Accounts Receivable)
		age = (to_date - ref_date).days
		index = next((n for n, days in enumerate(AGEING_DAYS) if age <= days), len(AGEING_DAYS))
		field = AGEING[index][0]
		buckets[field] = flt(buckets[field] + flt(i.outstanding), 2)
	return out


def headroom(items):
	"""An invisible region above the tallest bar: it lifts the chart's top so the hover box of
	the tallest bar (company name and amount) fits inside the chart instead of being cut off."""
	top = max(v for k, v in items)
	if top <= 0:
		return []
	top = flt(top * 1.3, 2)
	return [{"label": "", "start": top, "end": top}]


def total_row(label, rows, currency, **extra):
	total = frappe._dict(code="", account=label, related_company="", line_type="", currency=currency, bold=1)
	total.update(extra)
	for f in NUMBERS:
		total[f] = flt(sum(flt(r.get(f)) for r in rows), 2)
	return total
