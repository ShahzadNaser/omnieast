import re

import frappe

HTML_TAG = re.compile(r"<[^>]*>")


def before_insert(doc, method=None):
    """Fill `custom_narration` with a line-specific description.

    Only fills when custom_narration is empty. Cancellation (reversal) entries
    always fall back to the voucher's header remarks.
    """
    if _non_empty(doc.get("custom_narration")):
        return

    narration = _resolve_narration(doc)
    if _non_empty(narration):
        doc.custom_narration = _clean(narration)


def _resolve_narration(doc):
    if doc.get("is_cancelled"):
        return doc.get("remarks")

    voucher_type = doc.get("voucher_type")

    if voucher_type == "Journal Entry":
        return _journal_entry_narration(doc) or doc.get("remarks")

    if voucher_type == "Purchase Invoice":
        return _purchase_invoice_narration(doc) or doc.get("remarks")

    # Payment Entry (and everything else) uses the GL Entry's remarks, which
    # Frappe already copies from Payment Entry.remarks — whether that remark
    # was typed by the user (custom_remarks=1) or auto-generated.
    return doc.get("remarks")


def _journal_entry_narration(doc):
    rows = frappe.db.get_all(
        "Journal Entry Account",
        filters={
            "parent": doc.voucher_no,
            "account": doc.account,
            "cost_center": doc.cost_center or "",
            "debit": doc.debit,
            "credit": doc.credit,
        },
        pluck="user_remark",
    )
    return ", ".join(r for r in rows if _non_empty(r))


def _purchase_invoice_narration(doc):
    rows = frappe.db.get_all(
        "Purchase Invoice Item",
        filters={
            "parent": doc.voucher_no,
            "expense_account": doc.account,
            "cost_center": doc.cost_center or "",
        },
        pluck="description",
    )
    return ", ".join(r for r in rows if _non_empty(r))


def _non_empty(value):
    return bool(value and str(value).strip())


def _clean(text):
    return HTML_TAG.sub("", str(text)).strip()
