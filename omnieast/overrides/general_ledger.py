from frappe import _

from erpnext.accounts.report.general_ledger import general_ledger as _gl


_original_get_columns = _gl.get_columns
_original_get_gl_entries = _gl.get_gl_entries
_original_get_result_as_list = _gl.get_result_as_list


def get_columns(filters):
    columns = _original_get_columns(filters)
    columns.append(
        {
            "label": _("Narration"),
            "fieldname": "custom_narration",
            "fieldtype": "Small Text",
            "width": 400,
        }
    )
    return columns


def get_gl_entries(filters, accounting_dimensions):
    entries = _original_get_gl_entries(filters, accounting_dimensions)
    if not entries:
        return entries

    names = [e.get("gl_entry") for e in entries if e.get("gl_entry")]
    narrations = {}
    if names:
        import frappe

        for row in frappe.db.get_all(
            "GL Entry",
            filters={"name": ["in", names]},
            fields=["name", "custom_narration"],
        ):
            narrations[row.name] = row.custom_narration

    for e in entries:
        e["custom_narration"] = narrations.get(e.get("gl_entry"))

    return entries


def get_result_as_list(data, filters):
    data = _original_get_result_as_list(data, filters)
    for d in data:
        if not _non_empty(d.get("custom_narration")) and _non_empty(d.get("remarks")):
            d["custom_narration"] = d.get("remarks")
    return data


def _non_empty(value):
    return bool(value and str(value).strip())


def apply():
    _gl.get_columns = get_columns
    _gl.get_gl_entries = get_gl_entries
    _gl.get_result_as_list = get_result_as_list
