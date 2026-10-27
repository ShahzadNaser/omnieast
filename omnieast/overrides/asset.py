import frappe

from omnieast.overrides.project_mandatory import applies, fill, get_dimensions_of

# Asset link -> doctype, most specific first
SOURCES = (
	("purchase_invoice_item", "Purchase Invoice Item"),
	("purchase_receipt_item", "Purchase Receipt Item"),
	("purchase_invoice", "Purchase Invoice"),
	("purchase_receipt", "Purchase Receipt"),
)


def before_validate(doc, method=None):
	"""fill blank Project / Cost Center from the purchase row, else the purchase document.

	Assets auto-created on Purchase Invoice / Receipt submit are inserted without doc events, so this runs on
	the first save of that draft.
	"""
	if doc.docstatus != 0 or not applies(doc):
		return

	for fieldname, doctype in SOURCES:
		if not doc.get(fieldname):
			continue

		if doctype.endswith(" Item"):
			row = frappe.db.get_value(doctype, doc.get(fieldname), ["project", "cost_center"], as_dict=True) or {}
			fill(doc, row.get("project"), row.get("cost_center"), doc.company)
		else:
			fill(doc, *get_dimensions_of(doctype, doc.get(fieldname)), doc.company)
