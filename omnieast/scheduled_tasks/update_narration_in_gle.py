import frappe
from frappe.utils import now_datetime

def update_narration_in_gl_entry():
    try:

        update_purchase_invoice()
        update_journal_entry()
        update_sales_invoice()
        update_fallback_remarks()

        frappe.db.commit()

    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            frappe.get_traceback(),
            "Updating GL Narration Failed"
        )


def update_purchase_invoice():
    frappe.db.sql("""
        UPDATE `tabGL Entry` gle
        SET gle.custom_narration = (
            SELECT REGEXP_REPLACE(
                GROUP_CONCAT(pii.description SEPARATOR ', '),
                '<[^>]*>', ''
            )
            FROM `tabPurchase Invoice Item` pii
            WHERE pii.parent = gle.voucher_no
              AND pii.expense_account = gle.account
              AND pii.cost_center = gle.cost_center
            GROUP BY pii.expense_account
        )
        WHERE gle.voucher_type = 'Purchase Invoice'
          AND IFNULL(TRIM(gle.custom_narration), '') = ''
    """)

def update_journal_entry():
    frappe.db.sql("""
        UPDATE `tabGL Entry` gle
        SET gle.custom_narration = (
            SELECT REGEXP_REPLACE(
                GROUP_CONCAT(jea.user_remark SEPARATOR ', '),
                '<[^>]*>', ''
            )
            FROM `tabJournal Entry Account` jea
            WHERE jea.parent = gle.voucher_no
              AND jea.account = gle.account
              AND jea.cost_center = gle.cost_center
              AND jea.debit = gle.debit
              AND jea.credit = gle.credit
              AND COALESCE(NULLIF(TRIM(jea.party), ''), '') =
                  COALESCE(NULLIF(TRIM(gle.party), ''), '')
              AND COALESCE(NULLIF(TRIM(jea.reference_type), ''), '') =
                  COALESCE(NULLIF(TRIM(gle.against_voucher_type), ''), '')
              AND COALESCE(NULLIF(TRIM(jea.reference_name), ''), '') =
                  COALESCE(NULLIF(TRIM(gle.against_voucher), ''), '')
            GROUP BY jea.parent, jea.account, jea.cost_center, jea.party, jea.reference_name
        )
        WHERE gle.voucher_type = 'Journal Entry'
          AND IFNULL(TRIM(gle.custom_narration), '') = ''
    """)


def update_sales_invoice():
    frappe.db.sql("""
        UPDATE `tabGL Entry` gle
        SET gle.custom_narration = (
            SELECT REGEXP_REPLACE(
                GROUP_CONCAT(sii.description SEPARATOR ', '),
                '<[^>]*>', ''
            )
            FROM `tabSales Invoice Item` sii
            WHERE sii.parent = gle.voucher_no
              AND sii.income_account = gle.account
              AND sii.cost_center = gle.cost_center
            GROUP BY sii.income_account
        )
        WHERE gle.voucher_type = 'Sales Invoice'
          AND IFNULL(TRIM(gle.custom_narration), '') = ''
    """)

def update_fallback_remarks():
    frappe.db.sql("""
        UPDATE `tabGL Entry`
        SET custom_narration = remarks
        WHERE IFNULL(TRIM(custom_narration), '') = ''
          AND remarks != 'No Remarks'
    """)