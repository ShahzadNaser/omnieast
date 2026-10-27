"""ISS-2026-00109: Annual Leave needs a Resume Duty Request on return. Old leaves are not backfilled."""

import json
import os

import frappe
from frappe.modules.utils import sync_customizations_for_doctype

LEAVE_TYPE = "Annual Leave"
FIELD = "custom_requires_resume_duty_request"


def execute():
	if not frappe.db.exists("Leave Type", LEAVE_TYPE):
		return

	ensure_leave_type_field()

	if not frappe.db.get_value("Leave Type", LEAVE_TYPE, FIELD):
		frappe.db.set_value("Leave Type", LEAVE_TYPE, FIELD, 1)


def ensure_leave_type_field():
	"""Post-model-sync patches run before the app's customizations are synced; add the field first."""
	if frappe.get_meta("Leave Type").has_field(FIELD):
		return

	folder = frappe.get_app_path("omnieast", "omnieast", "custom")
	with open(os.path.join(folder, "leave_type.json")) as f:
		sync_customizations_for_doctype(json.load(f), folder, "leave_type.json")
	frappe.clear_cache(doctype="Leave Type")
