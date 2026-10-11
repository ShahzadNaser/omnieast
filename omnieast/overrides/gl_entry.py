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

    if voucher_type == "Payment Entry":
        return _payment_entry_narration(doc) or doc.get("remarks")

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


def _payment_entry_narration(doc):
    # In stock ERPNext v16, Payment Entry.custom_remarks is a Check flag; the
    # narration text sits in `remarks`. In some installs a custom text field
    # with the same name may exist — read it only if it's a text-typed field.
    try:
        meta = frappe.get_meta("Payment Entry")
    except Exception:
        return None

    field = meta.get_field("custom_remarks") if meta.has_field("custom_remarks") else None
    if field and field.fieldtype in ("Text", "Small Text", "Long Text", "Text Editor", "Data"):
        text = frappe.db.get_value("Payment Entry", doc.voucher_no, "custom_remarks")
        if _non_empty(text):
            return text
    return None


def _non_empty(value):
    return bool(value and str(value).strip())


def _clean(text):
    return HTML_TAG.sub("", str(text)).strip()
