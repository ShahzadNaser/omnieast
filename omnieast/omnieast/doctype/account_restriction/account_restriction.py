# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from omnieast.permissions.account_restriction import PROTECTED_ROLES, clear_cache


class AccountRestriction(Document):
	"""Hide accounts, and every entry posted to them, from the users of some roles.

	The rules are applied by omnieast/permissions/account_restriction.py.
	"""

	def validate(self):
		protected = [d.role for d in self.roles if d.role in PROTECTED_ROLES]
		if protected:
			frappe.throw(
				_("{0} cannot be restricted.").format(", ".join(frappe.bold(r) for r in protected)),
				title=_("Invalid Role"),
			)

	def on_update(self):
		clear_cache()

	def on_trash(self):
		clear_cache()

	def after_rename(self, old, new, merge=False):
		clear_cache()
