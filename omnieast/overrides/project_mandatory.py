import frappe
from frappe import _

# Companies where every expense/income transaction must carry a Project.
PROJECT_MANDATORY_COMPANIES = {"Omni East Company"}

# System-generated Journal Entries that must not be blocked.
EXEMPT_JOURNAL_VOUCHER_TYPES = {
	"Depreciation Entry",
	"Exchange Gain Or Loss",
	"Exchange Rate Revaluation",
	"Deferred Revenue",
	"Deferred Expense",
}


def validate_project(doc, method=None):
	if doc.get("company") not in PROJECT_MANDATORY_COMPANIES:
		return

	handler = {
		"Purchase Invoice": _validate_item_rows,
		"Sales Invoice": _validate_item_rows,
		"Expense Claim": _validate_expense_rows,
		"Journal Entry": _validate_journal_rows,
		"Asset": _validate_header,
	}.get(doc.doctype)

	if handler:
		handler(doc)


def _validate_header(doc):
	if not doc.get("project"):
		frappe.throw(_("Project is mandatory for {0} {1}").format(doc.doctype, doc.name))


def _validate_item_rows(doc):
	missing = [str(row.idx) for row in doc.get("items") or [] if not (row.get("project") or doc.get("project"))]
	_throw_if_missing(doc, missing, _("Items"))


def _validate_expense_rows(doc):
	missing = [str(row.idx) for row in doc.get("expenses") or [] if not (row.get("project") or doc.get("project"))]
	_throw_if_missing(doc, missing, _("Expenses"))


def _validate_journal_rows(doc):
	if doc.get("voucher_type") in EXEMPT_JOURNAL_VOUCHER_TYPES:
		return

	missing = []
	for row in doc.get("accounts") or []:
		if row.get("project"):
			continue
		root_type = frappe.get_cached_value("Account", row.account, "root_type")
		if root_type in ("Expense", "Income"):
			missing.append(str(row.idx))

	_throw_if_missing(doc, missing, _("Accounting Entries"))


def _throw_if_missing(doc, missing, table_label):
	if missing:
		frappe.throw(
			_("Project is mandatory. Please set Project in {0} row(s): {1}").format(
				table_label, ", ".join(missing)
			),
			title=_("Project Missing"),
		)
