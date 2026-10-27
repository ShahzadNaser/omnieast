from omnieast.overrides.project_mandatory import (
	applies,
	fill,
	get_dimensions_of,
	payment_request_of,
	shared,
)


def before_validate(doc, method=None):
	""" fill blank Project / Cost Center from the referenced documents."""
	if doc.docstatus != 0 or not applies(doc):
		return

	references = doc.get("references") or []
	dimensions = [get_dimensions_of(ref.reference_doctype, ref.reference_name) for ref in references]
	# only when every reference carries the same Project / Cost Center
	fill(
		doc,
		shared(project for project, _cost_center in dimensions),
		shared(cost_center for _project, cost_center in dimensions),
		doc.company,
	)

	payment_requests = {ref.payment_request for ref in references if ref.payment_request}
	if payment_request_of(doc):
		payment_requests.add(doc.reference_no)
	if len(payment_requests) == 1:
		fill(doc, *get_dimensions_of("Payment Request", payment_requests.pop()), doc.company)
