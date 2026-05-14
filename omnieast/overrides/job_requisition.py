import frappe


class CustomJobRequisitionMixin:
    
    def validate_duplicates(self):
        frappe.errprint("4th")
        return