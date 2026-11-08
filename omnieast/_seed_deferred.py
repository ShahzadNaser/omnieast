import datetime

import frappe
from frappe.utils import add_months, getdate


def run():
    company = "omnieast"
    abbr = frappe.db.get_value("Company", company, "abbr")

    deferred_acc = f"Deferred Revenue - {abbr}"
    if not frappe.db.exists("Account", deferred_acc):
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "account_name": "Current Liabilities", "is_group": 1},
        ) or frappe.db.get_value(
            "Account",
            {"company": company, "account_name": "Accounts Payable", "is_group": 1},
        )
        frappe.get_doc({
            "doctype": "Account",
            "account_name": "Deferred Revenue",
            "parent_account": parent,
            "company": company,
            "root_type": "Liability",
            "report_type": "Balance Sheet",
            "is_group": 0,
        }).insert(ignore_permissions=True)

    customer_name = "Test Deferred Customer"
    if not frappe.db.exists("Customer", customer_name):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Company",
            "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
            "territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
        }).insert(ignore_permissions=True)

    item_code = "DEFERRED-SVC-001"
    if not frappe.db.exists("Item", item_code):
        frappe.get_doc({
            "doctype": "Item",
            "item_code": item_code,
            "item_name": "Deferred Service 001",
            "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
            "is_stock_item": 0,
            "stock_uom": "Nos",
            "enable_deferred_revenue": 1,
            "deferred_revenue_account": deferred_acc,
            "no_of_months": 3,
        }).insert(ignore_permissions=True)

    today = getdate()
    service_start = today.replace(day=1)
    service_end = add_months(service_start, 3) - datetime.timedelta(days=1)

    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": customer_name,
        "company": company,
        "posting_date": service_start,
        "due_date": service_end,
        "debit_to": f"Debtors - {abbr}",
        "items": [{
            "item_code": item_code,
            "qty": 1,
            "rate": 3000,
            "income_account": f"Sales - {abbr}",
            "enable_deferred_revenue": 1,
            "deferred_revenue_account": deferred_acc,
            "service_start_date": service_start,
            "service_end_date": service_end,
        }],
    })
    si.insert(ignore_permissions=True)
    si.submit()
    frappe.db.commit()
    print(f"sales invoice: {si.name}  service {service_start} -> {service_end}  rate 3000")
