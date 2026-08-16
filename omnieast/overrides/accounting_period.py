import frappe
from frappe import _
from erpnext.accounts.doctype.accounting_period.accounting_period import ClosedAccountingPeriod

import erpnext.accounts.doctype.accounting_period.accounting_period as accounting_period

def custom_validate_accounting_period_on_doc_save(doc, method=None):
    # --- CUSTOM LOGIC START ---
    # Check if the doctype is submittable. If it's a Draft (docstatus == 0), bypass validation.
    # When submitting, docstatus is set to 1 before this validate hook runs.
    is_submittable = frappe.get_meta(doc.doctype).is_submittable
    if is_submittable and doc.docstatus == 0:
        return
    # --- CUSTOM LOGIC END ---

    if doc.doctype == "Bank Clearance":
        return
    elif doc.doctype == "Asset":
        if doc.asset_type == "Existing Asset":
            return
        else:
            date = doc.available_for_use_date
    elif doc.doctype == "Asset Repair":
        date = doc.completion_date
    elif doc.doctype == "Period Closing Voucher":
        date = doc.period_end_date
    else:
        date = doc.posting_date

    ap = frappe.qb.DocType("Accounting Period")
    cd = frappe.qb.DocType("Closed Document")

    accounting_period = (
        frappe.qb.from_(ap)
        .from_(cd)
        .select(ap.name, ap.exempted_role)
        .where(
            (ap.name == cd.parent)
            & (ap.company == doc.company)
            & (ap.disabled == 0)
            & (cd.closed == 1)
            & (cd.document_type == doc.doctype)
            & (date >= ap.start_date)
            & (date <= ap.end_date)
        )
    ).run(as_dict=1)

    if accounting_period:
        if (
            accounting_period[0].get("exempted_role")
            and accounting_period[0].get("exempted_role") in frappe.get_roles()
        ):
            return
        
        # Change the text slightly to say "submit" instead of "create" for clarity
        action = "submit" if is_submittable else "create"
        frappe.throw(
            _("You cannot {0} a {1} within the closed Accounting Period {2}").format(
                action, doc.doctype, frappe.bold(accounting_period[0]["name"])
            ),
            ClosedAccountingPeriod,
        )

def apply():
    accounting_period.validate_accounting_period_on_doc_save = custom_validate_accounting_period_on_doc_save