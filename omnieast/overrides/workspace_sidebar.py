import frappe

class CustomWorkspaceSidebar:

	def is_item_allowed(self, name, item_type, allowed_workspaces):
		if frappe.session.user == "Administrator":
			return True

		item_type = item_type.lower()

		if item_type == "doctype":
			return (
				name in (self.can_read or [])
				and name in (self.restricted_doctypes or [])
				and frappe.has_permission(name)
			)
		if item_type == "page":
			return (
                        name in (self.allowed_pages or [])
                        and name in (self.restricted_pages or [])
                    )
		if item_type == "report":
			return name in self.allowed_reports
		if item_type == "help":
			return True
		if item_type == "dashboard":
			return True
		if item_type == "url":
			return True
		if item_type == "workspace":
			return name in allowed_workspaces