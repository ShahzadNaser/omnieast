import frappe


def run():
    pda = frappe.get_doc({
        "doctype": "Process Deferred Accounting",
        "company": "omnieast",
        "type": "Income",
        "account": "Deferred Revenue - O",
        "posting_date": "2026-11-15",
        "start_date": "2026-11-01",
        "end_date": "2026-11-30",
    })
    pda.insert(ignore_permissions=True)
    pda.submit()
    frappe.db.commit()
    print(f"pda: {pda.name}")

    gl = frappe.db.sql(
        """
        SELECT voucher_type, voucher_no, account, debit, credit, posting_date
        FROM `tabGL Entry`
        WHERE voucher_no='ACC-SINV-2026-00008' OR against_voucher='ACC-SINV-2026-00008'
           OR voucher_no=%s
        ORDER BY posting_date, creation
        """,
        (pda.name,),
    )
    print(f"GL after PDA:")
    for row in gl:
        print(" ", row)

    jes = frappe.db.sql(
        """
        SELECT je.name, je.posting_date, je.total_debit
        FROM `tabJournal Entry` je
        JOIN `tabJournal Entry Account` jea ON jea.parent = je.name
        WHERE jea.reference_name = 'ACC-SINV-2026-00008'
        """
    )
    print(f"JEs linked to SI: {jes}")
