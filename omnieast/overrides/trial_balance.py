import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.report.trial_balance import trial_balance as _tb
from erpnext.accounts.utils import get_zero_cutoff


def get_columns():
    columns = _original_get_columns()
    is_group_col = {
        "fieldname": "is_group",
        "label": _("Is Group"),
        "fieldtype": "Check",
        "width": 80,
    }
    columns.insert(1, is_group_col)
    return columns


def prepare_data(accounts, filters, parent_children_map, company_currency):
    data = []

    for d in accounts:
        if parent_children_map.get(d.account) and filters.get("show_net_values"):
            _tb.prepare_opening_closing(d)

        has_value = False
        row = {
            "account": d.name,
            "is_group": d.is_group,
            "parent_account": d.parent_account,
            "indent": d.indent,
            "from_date": filters.from_date,
            "to_date": filters.to_date,
            "currency": company_currency,
            "is_group_account": d.is_group,
            "acc_name": d.account_name,
            "acc_number": d.account_number,
            "account_name": (
                f"{d.account_number} - {d.account_name}" if d.account_number else d.account_name
            ),
        }

        for key in _tb.value_fields:
            row[key] = flt(d.get(key, 0.0))

            if abs(row[key]) >= get_zero_cutoff(company_currency):
                has_value = True

        row["has_value"] = has_value
        data.append(row)

    if not filters.get("show_group_accounts"):
        data = _tb.hide_group_accounts(data)

    total_row = _tb.calculate_total_row(
        data, company_currency, show_group_accounts=filters.get("show_group_accounts")
    )

    data.extend([{}, total_row])

    return data


_original_get_columns = _tb.get_columns
_original_prepare_data = _tb.prepare_data


def apply():
    _tb.get_columns = get_columns
    _tb.prepare_data = prepare_data
