"""Role "User Impersonator": shows User > Impersonate (Frappe's "Impersonate" permission on User).

Given to the users below; more users can get the role from their User record later.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

ROLE = "User Impersonator"
USERS = ["usama.n@jawahr.com"]


def execute():
	# the "Impersonate" permission (Permission Type user_impersonate) exists from Frappe v16 on
	if not frappe.db.exists("Permission Type", {"perm_type": "impersonate", "doc_type": "User"}):
		return

	ensure_impersonate_field()

	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(ignore_permissions=True)

	# Frappe's Role Permission Manager helpers: they keep the User permissions already set up
	if not frappe.db.exists("Custom DocPerm", {"parent": "User", "role": ROLE, "permlevel": 0, "if_owner": 0}):
		add_permission("User", ROLE, 0, ptype="read")
	update_permission_property("User", ROLE, 0, "impersonate", 1)

	for user in USERS:
		add_role(user)

	frappe.clear_cache(doctype="User")


def ensure_impersonate_field():
	"""On some sites the Impersonate column exists but its Custom Field is missing, so Frappe (and Role
	Permission Manager) cannot see it. Recreate it the way the Permission Type itself does."""
	from frappe.core.doctype.permission_type.permission_type import CUSTOM_FIELD_TARGET

	permission_type = frappe.get_doc("Permission Type", {"perm_type": "impersonate", "doc_type": "User"})
	for target in CUSTOM_FIELD_TARGET:
		if not frappe.db.exists("Custom Field", {"dt": target, "fieldname": "impersonate"}):
			permission_type.create_custom_field(target)
		frappe.clear_cache(doctype=target)


def add_role(user):
	"""Only the role row; saving the whole User record would run all its hooks during migrate."""
	if not frappe.db.exists("User", user) or frappe.db.exists(
		"Has Role", {"parent": user, "parenttype": "User", "role": ROLE}
	):
		return

	frappe.get_doc(
		{
			"doctype": "Has Role",
			"name": frappe.generate_hash(length=10),
			"parent": user,
			"parenttype": "User",
			"parentfield": "roles",
			"role": ROLE,
			"idx": (frappe.db.count("Has Role", {"parent": user, "parenttype": "User"}) or 0) + 1,
		}
	).db_insert()
	frappe.clear_cache(user=user)
