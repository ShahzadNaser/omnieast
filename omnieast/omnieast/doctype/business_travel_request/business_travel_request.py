# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

"""Retired: Business Trip vouchers are made from the approved leave ("Create CPV" in
shared_finance_app), and Business Trip attendance is handled in
omnieast/overrides/business_trip_attendance.py. The doctype is kept so existing requests can still
be opened; nothing creates new ones."""

from frappe.model.document import Document


class BusinessTravelRequest(Document):
	pass
