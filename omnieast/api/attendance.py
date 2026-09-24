# Copyright (c) 2026, Omnieast
# ZKT Biometric Checkin Sync API
# Ported from jawaerp.api.attendance (Frappe v14) for Omnieast on Frappe v16.

from __future__ import unicode_literals

import json

import frappe
from frappe import _


@frappe.whitelist(allow_guest=False)
def sync(attendance=None):
	"""Receive biometric check-in batch from ZKT device / middleware.

	Payload:
	{
	  "attendance_list": [
	    {"employee": "<attendance_device_id or emp id>",
	     "check_time": "YYYY-MM-DD HH:MM:SS",
	     "device_id": "<zkt device id>",
	     "reference_id": <int>}
	  ]
	}
	"""
	has_error = False

	try:
		if attendance:
			body = attendance if isinstance(attendance, dict) else frappe.parse_json(attendance)
		else:
			raw = frappe.request.get_data(as_text=True)
			body = json.loads(raw) if raw else {}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Attendance API - Invalid JSON")
		return {
			"error": True,
			"message": _("Invalid JSON payload.")
		}

	attendance_list = body.get("attendance_list", [])

	if not attendance_list:
		return {
			"error": True,
			"message": _("attendance_list is required."),
			"processed_records": []
		}

	now = frappe.utils.now_datetime()
	owner = frappe.session.user

	insert_data = []
	processed_records = []

	for att in attendance_list:
		try:
			attendance_time_id = frappe.generate_hash(length=10)

			insert_data.append((
				attendance_time_id,
				att.get("employee"),
				frappe.utils.get_datetime(att.get("check_time")),
				"Pending",
				att.get("device_id"),
				att.get("reference_id"),
				now,
				now,
				owner,
			))

			processed_records.append({
				"reference_id": att.get("reference_id"),
				"status": "SUCCESS",
				"attendance_id": attendance_time_id
			})

		except Exception:
			has_error = True

			processed_records.append({
				"reference_id": att.get("reference_id"),
				"status": "FAILED",
				"attendance_id": None
			})

			frappe.log_error(
				frappe.get_traceback(),
				f"Attendance API - Failed to prepare record ({att.get('reference_id')})"
			)

	if insert_data:
		try:
			frappe.db.sql("""
				INSERT INTO `tabAttendance Time`
				(`name`, `employee`, `check_time`, `status`,
				 `device_id`, `reference_id`,
				 `creation`, `modified`, `owner`)
				VALUES {}
			""".format(", ".join(["%s"] * len(insert_data))), tuple(insert_data))

			frappe.db.commit()

		except Exception:
			has_error = True

			frappe.log_error(
				frappe.get_traceback(),
				"Attendance API - Bulk Insert Failed"
			)

			for record in processed_records:
				if record["status"] == "SUCCESS":
					record["status"] = "FAILED"
					record["attendance_id"] = None

	return {
		"error": has_error,
		"processed_records": processed_records
	}


@frappe.whitelist(allow_guest=True)
def sync_att_time(time=False):
	"""Enqueue background job that turns Attendance Time rows into Employee Checkin."""
	frappe.enqueue(method="omnieast.api.attendance.mark_checkins", queue="long", timeout=1600)
	return True


@frappe.whitelist()
def mark_checkins(attendances=None):
	if not attendances:
		attendances = frappe.db.get_list(
			"Attendance Time",
			filters={"status": ["!=", "Success"], "error_counter": ["<", 2]},
			order_by="check_time asc",
			fields=["name", "employee", "check_time", "error_counter"],
			limit=200,
		)

	for att in attendances:
		try:
			employee = (
				frappe.db.get_value("Employee", {"attendance_device_id": att.get("employee")}, "name")
				or frappe.db.get_value("Employee", att.get("employee"), "name")
				or ""
			)
			if not employee:
				frappe.db.sql(
					"""update `tabAttendance Time`
					   set error_counter=%s, msg=%s, status=%s, modified=%s
					   where name=%s""",
					(att.get("error_counter") + 1, "Employee Not Found.", "Error",
					 frappe.utils.now_datetime(), att.get("name"))
				)
				continue

			if att.get("check_time"):
				checkin = mark_employee_checktime(employee, att["check_time"], "Auto")
				frappe.db.sql(
					"""update `tabAttendance Time`
					   set status=%s, employee_checkin=%s, modified=%s
					   where name=%s""",
					("Success", str(checkin.name) if checkin else None,
					 frappe.utils.now_datetime(), att.get("name"))
				)
				continue

		except Exception:
			frappe.db.sql(
				"""update `tabAttendance Time`
				   set error_counter=%s, msg=%s, status=%s, modified=%s
				   where name=%s""",
				(att.get("error_counter") + 1, "Server error please check error logs.",
				 "Error", frappe.utils.now_datetime(), att.get("name"))
			)
			frappe.log_error(frappe.get_traceback(), f"mark_checkins failed for {att.get('name')}")
			continue

	return True


def mark_employee_checktime(employee, check_time, attendance_device=None):
	from hrms.hr.doctype.employee_checkin.employee_checkin import add_log_based_on_employee_field
	from hrms.hr.doctype.shift_assignment.shift_assignment import (
		get_actual_start_end_datetime_of_shift,
	)

	_checkin_time = frappe.utils.get_datetime(check_time)

	if not employee:
		return False

	shift_details = get_actual_start_end_datetime_of_shift(employee, _checkin_time, True)

	existing = frappe.db.sql(
		"""SELECT name FROM `tabEmployee Checkin`
		   WHERE employee=%s AND log_type='IN'
		     AND time BETWEEN %s AND %s""",
		(employee,
		 shift_details.get("actual_start") if shift_details else _checkin_time,
		 shift_details.get("actual_end") if shift_details else _checkin_time),
		as_list=True,
	)

	if not existing:
		return add_log_based_on_employee_field(
			employee_field_value=employee,
			timestamp=_checkin_time,
			log_type="IN",
			employee_fieldname="name",
			device_id=attendance_device,
		)

	next_log_type = "OUT"
	shift_name = shift_details.shift_type.name if shift_details and shift_details.get("shift_type") else None

	if shift_name:
		checkins = frappe.db.sql(
			"""SELECT log_type FROM `tabEmployee Checkin`
			   WHERE employee=%s AND shift=%s
			   ORDER BY time DESC LIMIT 1""",
			(employee, shift_name),
			as_dict=True,
		)
		if checkins and checkins[0].get("log_type") == "OUT":
			next_log_type = "IN"

	return add_log_based_on_employee_field(
		employee_field_value=employee,
		timestamp=_checkin_time,
		log_type=next_log_type,
		employee_fieldname="name",
		device_id=attendance_device,
	)
