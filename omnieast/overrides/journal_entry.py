import frappe
from collections import defaultdict
from frappe.utils import flt

from omnieast.overrides.project_mandatory import (
    applies,
    fill,
    get_dimensions_of,
    set_cost_center_from_project,
    single,
)


def before_validate(doc, method=None):
    """fill blank Project / Cost Center from each row's reference document."""
    if doc.docstatus != 0 or not applies(doc):
        return

    for row in doc.accounts:
        if row.reference_type and row.reference_name:
            fill(row, *get_dimensions_of(row.reference_type, row.reference_name), doc.company)

    # one Project on the entry: it applies to every row
    project = single(row.project for row in doc.accounts)
    for row in doc.accounts:
        if project and not row.project:
            row.project = project
        set_cost_center_from_project(row, doc.company)


def on_submit(doc, method=None):
    _apply_indirect_cost_delta(doc, sign=1)


def on_cancel(doc, method=None):
    _apply_indirect_cost_delta(doc, sign=-1)


def _apply_indirect_cost_delta(doc, sign):
    deltas = defaultdict(float)

    for row in doc.accounts:
        if not row.project:
            continue

        root_type = frappe.db.get_value("Account", row.account, "root_type")
        if root_type != "Expense":
            continue

        deltas[row.project] += sign * (flt(row.debit) - flt(row.credit))

    for project, delta in deltas.items():
        if not delta:
            continue
        _update_project_indirect_cost(project, delta)


def _update_project_indirect_cost(project, delta):
    project_doc = frappe.get_doc("Project", project)
    project_doc.total_indirect_cost = flt(project_doc.get("total_indirect_cost")) + delta
    project_doc.calculate_gross_margin()
    project_doc.db_set("total_indirect_cost", project_doc.total_indirect_cost, update_modified=False)
    project_doc.db_set("gross_margin", project_doc.gross_margin, update_modified=False)
    project_doc.db_set("per_gross_margin", project_doc.per_gross_margin, update_modified=False)
