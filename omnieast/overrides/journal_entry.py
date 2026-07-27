import frappe
from collections import defaultdict
from frappe.utils import flt


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
