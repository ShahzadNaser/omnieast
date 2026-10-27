import frappe
from frappe import _

# Companies where every expense/income transaction must carry a Project.
PROJECT_MANDATORY_COMPANIES = {"Omni East Company"}

# System-generated Journal Entries that must not be blocked.
EXEMPT_JOURNAL_VOUCHER_TYPES = {
	"Depreciation Entry",
	"Asset Disposal",
	"Exchange Gain Or Loss",
	"Exchange Rate Revaluation",
	"Deferred Revenue",
	"Deferred Expense",
	"Periodic Accounting Entry",
	"Opening Entry",
}

# Payroll postings stay as they are.
EXEMPT_JOURNAL_REFERENCE_TYPES = {"Payroll Entry"}

# shared_finance_app (PWA / CPV) inserts and re-saves draft Journal / Payment Entries from code; those drafts
# may stay blank, they are checked on submit.
APP_GENERATED_REFERENCE_TYPES = {"Payment Request", "Cash Payment Voucher"}

# Fill run on save, also previewed by the form before its own mandatory check (get_filled_dimensions)
FILLERS = {
	"Journal Entry": "omnieast.overrides.journal_entry.before_validate",
	"Purchase Invoice": "omnieast.overrides.purchase_invoice.before_validate",
	"Payment Entry": "omnieast.overrides.payment_entry.before_validate",
	"Asset": "omnieast.overrides.asset.before_validate",
}

# Documents a Project / Cost Center can be fetched from, with the child table used when the header is blank.
DIMENSION_SOURCES = {
	"Sales Invoice": "Sales Invoice Item",
	"Purchase Invoice": "Purchase Invoice Item",
	"Sales Order": "Sales Order Item",
	"Purchase Order": "Purchase Order Item",
	"Purchase Receipt": "Purchase Receipt Item",
	"Journal Entry": "Journal Entry Account",
	"Payment Entry": None,
	"Payment Request": None,
	"Expense Claim": None,
	"Asset": None,
	"Cash Payment Voucher": None,
}


def validate_project(doc, method=None):
	if doc.get("company") not in PROJECT_MANDATORY_COMPANIES:
		return

	# Journal Entry, Purchase Invoice and Asset are checked on save (validate_* below).
	handler = {
		"Sales Invoice": _validate_item_rows,
		"Expense Claim": _validate_expense_rows,
	}.get(doc.doctype)

	if handler:
		handler(doc)


def _validate_item_rows(doc):
	missing = [str(row.idx) for row in doc.get("items") or [] if not (row.get("project") or doc.get("project"))]
	_throw_if_missing(doc, missing, _("Items"))


def _validate_expense_rows(doc):
	missing = [str(row.idx) for row in doc.get("expenses") or [] if not (row.get("project") or doc.get("project"))]
	_throw_if_missing(doc, missing, _("Expenses"))


def _throw_if_missing(doc, missing, table_label):
	if missing:
		frappe.throw(
			_("Project is mandatory. Please set Project in {0} row(s): {1}").format(
				table_label, ", ".join(missing)
			),
			title=_("Project Missing"),
		)


# Project and Cost Center mandatory on save, fetched from the linked document
# ------------------------------------------------------------------------------------------


def applies(doc):
	"""Project / Cost Center rules apply to this document (Omni only, system entries excluded)."""
	if doc.get("company") not in PROJECT_MANDATORY_COMPANIES:
		return False

	if doc.doctype == "Journal Entry":
		if doc.get("voucher_type") in EXEMPT_JOURNAL_VOUCHER_TYPES or doc.get("is_system_generated"):
			return False
		if any(row.get("reference_type") in EXEMPT_JOURNAL_REFERENCE_TYPES for row in doc.get("accounts") or []):
			return False

	return True


def default_cost_center(company):
	return frappe.get_cached_value("Company", company, "cost_center")


def is_blank_cost_center(cost_center, company):
	"""Cost Center is never empty in practice, the company default stands in for "not chosen"."""
	return not cost_center or cost_center == default_cost_center(company)


def set_cost_center_from_project(row, company):
	if not row.get("project") or not is_blank_cost_center(row.get("cost_center"), company):
		return

	project_cost_center = frappe.get_cached_value("Project", row.project, "cost_center")
	if project_cost_center:
		row.cost_center = project_cost_center


def fill(row, project, cost_center, company):
	"""Fill blanks only; the Project's own Cost Center wins over the linked document's."""
	if project and not row.get("project"):
		row.project = project

	set_cost_center_from_project(row, company)

	if cost_center and is_blank_cost_center(row.get("cost_center"), company):
		row.cost_center = cost_center


def single(values):
	"""The value when all non-empty values agree, else None."""
	values = {value for value in values if value}
	return values.pop() if len(values) == 1 else None


def shared(values):
	"""The value when every value is set and they are all the same, else None."""
	values = list(values)
	return single(values) if values and all(values) else None


def get_dimensions_of(doctype, name):
	"""(project, cost_center) of a linked document."""
	if doctype not in DIMENSION_SOURCES or not name or not frappe.db.exists(doctype, name):
		return None, None

	meta = frappe.get_meta(doctype)
	fields = [fieldname for fieldname in ("project", "cost_center") if meta.has_field(fieldname)]
	values = (frappe.db.get_value(doctype, name, fields, as_dict=True) if fields else None) or frappe._dict()
	project, cost_center = values.get("project"), values.get("cost_center")

	child_doctype = DIMENSION_SOURCES[doctype]
	if child_doctype and not (project and cost_center):
		rows = frappe.get_all(
			child_doctype,
			filters={"parent": name, "parenttype": doctype},
			fields=["project", "cost_center"],
		)
		project = project or single(row.project for row in rows)
		cost_center = cost_center or single(row.cost_center for row in rows)

	return project, cost_center


def payment_request_of(doc):
	"""PWA Payment Entries carry the Payment Request in reference_no (shared_finance_app)."""
	if doc.get("reference_no") and frappe.db.exists("Payment Request", doc.reference_no):
		return doc.reference_no


@frappe.whitelist()
def get_reference_dimensions(doctype, name):
	if doctype not in DIMENSION_SOURCES or not frappe.has_permission(doctype, "read", name):
		return {}

	project, cost_center = get_dimensions_of(doctype, name)
	return {"project": project, "cost_center": cost_center}


@frappe.whitelist()
def get_filled_dimensions(doc):
	"""Project / Cost Center the save would fill in, for the unsaved form; nothing is saved."""
	doc = frappe.get_doc(frappe.parse_json(doc))
	if doc.doctype not in FILLERS or not frappe.has_permission(doc.doctype, "create" if doc.is_new() else "write"):
		return {}

	frappe.get_attr(FILLERS[doc.doctype])(doc)

	values = {"project": doc.get("project"), "cost_center": doc.get("cost_center"), "rows": {}}
	for table_fieldname in ("accounts", "items", "taxes"):
		for row in doc.get(table_fieldname) or []:
			values["rows"][row.name] = {"project": row.get("project"), "cost_center": row.get("cost_center")}
	return values


def extend_bootinfo(bootinfo):
	bootinfo.omni_project_cc = {
		"companies": sorted(PROJECT_MANDATORY_COMPANIES),
		"exempt_voucher_types": sorted(EXEMPT_JOURNAL_VOUCHER_TYPES),
		"exempt_reference_types": sorted(EXEMPT_JOURNAL_REFERENCE_TYPES),
		"default_cost_center": {company: default_cost_center(company) for company in PROJECT_MANDATORY_COMPANIES},
	}


def _skip_mandatory(doc):
	if doc.flags.ignore_mandatory:
		return True

	# PWA / CPV drafts: checked on submit only
	if doc.docstatus != 0:
		return False

	if doc.doctype == "Journal Entry":
		return any(row.get("reference_type") in APP_GENERATED_REFERENCE_TYPES for row in doc.get("accounts") or [])

	if doc.doctype == "Payment Entry":
		return bool(payment_request_of(doc))

	return False


def _throw_if_blank(doc, fieldnames, table_fields=None):
	"""One message for every blank header field and every blank child field (with row numbers)."""
	messages = [
		_("{0} is mandatory").format(_(doc.meta.get_label(fieldname)))
		for fieldname in fieldnames
		if doc.meta.has_field(fieldname) and not doc.get(fieldname)
	]

	for table_fieldname, child_fieldnames in (table_fields or {}).items():
		child_meta = frappe.get_meta(doc.meta.get_field(table_fieldname).options)
		for fieldname in child_fieldnames:
			rows = [str(row.idx) for row in doc.get(table_fieldname) or [] if not row.get(fieldname)]
			if rows:
				messages.append(
					_("{0} is mandatory in {1} row(s): {2}").format(
						_(child_meta.get_label(fieldname)),
						_(doc.meta.get_label(table_fieldname)),
						", ".join(rows),
					)
				)

	if messages:
		frappe.throw("<br>".join(messages), title=_("Project / Cost Center Missing"))


def validate_journal_entry(doc, method=None):
	if applies(doc) and not _skip_mandatory(doc):
		_throw_if_blank(doc, (), {"accounts": ("project", "cost_center")})


def validate_purchase_invoice(doc, method=None):
	if applies(doc) and not _skip_mandatory(doc):
		_throw_if_blank(
			doc,
			("project", "cost_center"),
			{"items": ("project", "cost_center"), "taxes": ("cost_center",)},
		)


def validate_payment_entry(doc, method=None):
	if applies(doc) and not _skip_mandatory(doc):
		_throw_if_blank(doc, ("project", "cost_center"))


def validate_asset(doc, method=None):
	# Asset.project is a site customization (not standard in v16), _throw_if_blank skips it when absent
	if applies(doc) and not _skip_mandatory(doc):
		_throw_if_blank(doc, ("project", "cost_center"))
