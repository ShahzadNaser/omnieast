import frappe
from frappe.utils import flt


class CustomProjectMixin:
    def update_costing(self):
        self.update_indirect_cost()
        super().update_costing()

    def update_indirect_cost(self):
        total = frappe.db.sql(
            """
            select coalesce(sum(jea.debit - jea.credit), 0)
            from `tabJournal Entry Account` jea
            inner join `tabJournal Entry` je on je.name = jea.parent
            inner join `tabAccount` a on a.name = jea.account
            where jea.project = %s
              and je.docstatus = 1
              and a.root_type = 'Expense'
            """,
            self.name,
        )
        self.total_indirect_cost = flt(total[0][0]) if total else 0

    def calculate_gross_margin(self):
        expense_amount = (
            flt(self.total_costing_amount)
            + flt(self.total_purchase_cost)
            + flt(self.get("total_consumed_material_cost", 0))
            + flt(self.get("total_indirect_cost", 0))
        )

        self.gross_margin = flt(self.total_billed_amount) - expense_amount
        if self.total_billed_amount:
            self.per_gross_margin = (self.gross_margin / flt(self.total_billed_amount)) * 100
        else:
            self.per_gross_margin = 0
