"""User > Impersonate without notifying the impersonated user.

Replaces frappe.core.doctype.user.user.impersonate (see hooks.py, override_whitelisted_methods).
Compared to Frappe:
- no "Security Alert" email and no bell notification to the impersonated user;
- the Activity Log entry is kept, now with the reason, so admins can see who impersonated whom and why;
- nobody can impersonate the Administrator.

Who may impersonate is the "Impersonate" permission on User (role "User Impersonator", see
patches/v16/allow_user_impersonation.py). Compare with Frappe's impersonate() after upgrades.
"""

import frappe
from frappe import _


@frappe.whitelist(methods=["POST"])
def impersonate(user: str, reason: str):
	frappe.has_permission("User", "impersonate", throw=True)

	if user == "Administrator":
		frappe.throw(_("The Administrator cannot be impersonated."), frappe.PermissionError)

	impersonator = frappe.session.user
	frappe.get_doc(
		{
			"doctype": "Activity Log",
			"user": user,
			"status": "Success",
			"subject": _("User {0} impersonated as {1}").format(impersonator, user),
			"content": _("Reason: {0}").format(frappe.utils.escape_html(reason)),
			"operation": "Impersonate",
		}
	).insert(ignore_permissions=True, ignore_links=True)

	frappe.local.login_manager.impersonate(user)
