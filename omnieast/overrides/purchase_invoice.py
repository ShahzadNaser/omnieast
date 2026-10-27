import frappe

from omnieast.overrides.project_mandatory import applies, fill, get_dimensions_of, single

# Purchase Invoice Item link -> doctype of the row it was made from
SOURCE_ROWS = (
	("purchase_invoice_item", "Purchase Invoice Item"),  # debit note -> original invoice row
	("po_detail", "Purchase Order Item"),
	("pr_detail", "Purchase Receipt Item"),
)


def before_validate(doc, method=None):
	"""ISS-2026-00151: fill blank Project / Cost Center on the header, items and taxes."""
	if doc.docstatus != 0 or not applies(doc):
		return

	if doc.is_return and doc.return_against:
		fill(doc, *get_dimensions_of("Purchase Invoice", doc.return_against), doc.company)

	for item in doc.items:
		source = _source_row(item)
		if source:
			fill(item, source.project, source.cost_center, doc.company)
		fill(item, doc.project, None, doc.company)

	# header from the items when they all agree
	fill(
		doc,
		single(item.project for item in doc.items),
		single(item.cost_center for item in doc.items),
		doc.company,
	)

	for tax in doc.get("taxes") or []:
		fill(tax, doc.project, doc.cost_center, doc.company)


def _source_row(item):
	for fieldname, doctype in SOURCE_ROWS:
		if item.get(fieldname):
			row = frappe.db.get_value(doctype, item.get(fieldname), ["project", "cost_center"], as_dict=True)
			if row:
				return row
