"""Role "Related Party Balances": the only role that opens the Related Party Balances report and
its Related Party Mapping lists (only Musaddiq and the Finance Director, Shamim).
Created before the model sync so the report and the DocType can point to it.
"""

import frappe

ROLE = "Related Party Balances"


def execute():
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(ignore_permissions=True)
