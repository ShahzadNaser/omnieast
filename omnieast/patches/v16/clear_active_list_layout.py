"""Remove the saved layout (List Filter) from every user's list settings, so lists open on Default Layout.

Frappe saved a layout as the user's own whenever their filters matched it; the user picks it again from
List View > layouts if they want it. Filters, columns and the Report settings are not touched.
"""

import json

import frappe
from frappe.model.utils.user_settings import sync_user_settings


def execute():
	# cached settings are written over the table later, so save them to the table first
	sync_user_settings()

	changed = 0
	for row in frappe.db.sql("select `user`, `doctype`, `data` from `__UserSettings`", as_dict=True):
		try:
			data = json.loads(row.data or "{}")
		except ValueError:
			continue
		if not isinstance(data, dict):
			continue

		found = False
		for view, settings in data.items():
			if view != "Report" and isinstance(settings, dict) and "active_layout_name" in settings:
				del settings["active_layout_name"]
				found = True

		if found:
			frappe.db.sql(
				"update `__UserSettings` set `data`=%s where `user`=%s and `doctype`=%s",
				(json.dumps(data), row.user, row.doctype),
			)
			changed += 1

	frappe.cache.delete_value("_user_settings")
	print(f"Removed the saved list layout from {changed} user settings row(s)")
