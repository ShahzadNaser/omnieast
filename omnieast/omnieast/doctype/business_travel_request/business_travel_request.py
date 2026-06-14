# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now, today, get_url_to_form, add_days, getdate, cint


class BusinessTravelRequest(Document):
	pass

@frappe.whitelist()
def create_travel_request(doc, method):
	# Only proceed if the Leave Type is 'Business Trip'
	if doc.leave_type == "Business Trip" and doc.status == "Approved":
		
		# Check if a Travel Request already exists to avoid duplicates
		if frappe.db.exists("Business Travel Request", {"leave_application": doc.name}):
			return

		# 1. Parse Grade Number (Assuming format "Grade 9")
		grade_num = cint(doc.custom_grade.replace('Grade ', '')) if doc.custom_grade else 0
		
		diem_type = "Full Diem" if doc.custom_hotel_required == "Yes" else "Half Diem"

		# 2. Fetch all relevant policies
		policies = frappe.get_all("Travel Policy", 
			filters={
				"diem_type": diem_type, 
				"travel_type": doc.custom_travel_type
			},
			fields=["min_grade", "max_grade", "amount", "remarks", "flight_class"]
		)
		
		# 3. Find the matching policy
		matched_policy = None
		for p in policies:
			min_val = cint(p.min_grade)
			# Handle "above"
			max_val = 99 if str(p.max_grade).lower() == 'above' else cint(p.max_grade)
			
			if grade_num >= min_val and grade_num <= max_val:
				matched_policy = p
				break

		# Create the new document
		travel_req_data = {
			"doctype": "Business Travel Request",
			"employee": doc.employee,
			"employee_name": doc.employee_name,
			"position": doc.custom_position,
			"department": doc.department,
			"joining_date": doc.custom_joining_date,
			"grade": doc.custom_grade,
			"location": doc.custom_location,
			"request_date": today(),
			"departure_date": doc.from_date,
			"return_date": doc.to_date,
			"total_days": doc.total_leave_days - 1,
			"mode_of_travel": doc.custom_mode_of_travel,
			"re_entry_required": doc.custom_reentry_required,
			"reason_for_travel": doc.custom_reason_for_travel,
			"leave_application": doc.name,
			"diem_type": diem_type,
			"travel_type": doc.custom_travel_type,
			"diem_amount": ((doc.total_leave_days - 1) * matched_policy.amount) if matched_policy else 0,
			"total_amount": ((doc.total_leave_days - 1) * matched_policy.amount) if matched_policy else 0,
			"flight_class": matched_policy.flight_class if matched_policy else None,
			"remarks": matched_policy.remarks if matched_policy else ""
		}
		
		# Save and trigger hooks
		travel_req = frappe.get_doc(travel_req_data)
		travel_req.insert(ignore_permissions=True)


		# ---------------------------------------------------
		# UPDATE ATTENDANCE FROM "On Leave" TO "Present"
		# ---------------------------------------------------

		attendance_records = frappe.get_all(
			"Attendance",
			filters={
				"employee": doc.employee,
				"attendance_date": ["between", [doc.from_date, doc.to_date]],
				"status": "On Leave"
			},
			fields=["name"]
		)

		for att in attendance_records:
			attendance_doc = frappe.get_doc("Attendance", att.name)
			attendance_doc.db_set("status", "Present", update_modified=False)

		frappe.db.commit()