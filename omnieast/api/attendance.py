# Copyright (c) 2026, Omnieast
# ZKT Biometric Checkin Sync API
# Ported from jawaerp.api.attendance (Frappe v14) for Omnieast on Frappe v16.

from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.utils import cstr, get_datetime


class InvalidPunch(Exception):
	"""A punch that fails a check; its message is returned for that row."""


def _parse_reference_id(value):
	"""Positive whole number, or None."""
	try:
		number = int(cstr(value).strip())
	except ValueError:
		return None
	return number if number > 0 else None


def _get_employees(attendance_list):
	"""{payload employee value: Employee}, matched on Attendance Device ID first and then on
	Employee ID, the same order mark_checkins uses."""
	codes = list({
		cstr(att.get("employee")).strip()
		for att in attendance_list
		if isinstance(att, dict) and cstr(att.get("employee")).strip()
	})
	if not codes:
		return {}

	employees = {
		row.name: row
		for row in frappe.get_all("Employee", filters={"name": ["in", codes]}, fields=["name", "status"])
	}
	by_device = {}
	for row in frappe.get_all(
		"Employee",
		filters={"attendance_device_id": ["in", codes]},
		fields=["name", "status", "attendance_device_id"],
	):
		# an Active employee wins over an old record that kept the same device ID
		current = by_device.get(row.attendance_device_id)
		if not current or (row.status == "Active" and current.status != "Active"):
			by_device[row.attendance_device_id] = row
	employees.update(by_device)
	return employees


def _get_stored_reference_ids(attendance_list):
	"""The reference_ids of this batch that are already stored in Attendance Time."""
	reference_ids = {
		_parse_reference_id(att.get("reference_id")) for att in attendance_list if isinstance(att, dict)
	}
	reference_ids.discard(None)
	if not reference_ids:
		return set()
	return set(
		frappe.get_all(
			"Attendance Time",
			filters={"reference_id": ["in", list(reference_ids)]},
			pluck="reference_id",
		)
	)


def _validate_punch(att, employees, stored_reference_ids):
	"""Attendance Time values for a valid punch; raises InvalidPunch otherwise."""
	if not isinstance(att, dict):
		raise InvalidPunch(_("Invalid punch record."))

	employee = cstr(att.get("employee")).strip()
	if not employee or employee not in employees:
		raise InvalidPunch(_("Employee {0} not found.").format(employee or "-"))
	if employees[employee].status != "Active":
		raise InvalidPunch(_("Employee {0} is not Active.").format(employee))

	reference_id = _parse_reference_id(att.get("reference_id"))
	if not reference_id:
		raise InvalidPunch(_("reference_id must be a positive whole number."))
	if reference_id in stored_reference_ids:
		raise InvalidPunch(_("reference_id {0} is already stored.").format(reference_id))

	check_time = None
	if att.get("check_time"):
		try:
			check_time = get_datetime(att.get("check_time"))
		except Exception:
			check_time = None
	if not check_time:
		raise InvalidPunch(_("check_time must be a date and time (YYYY-MM-DD HH:MM:SS)."))

	device_id = cstr(att.get("device_id")).strip()
	if not device_id:
		raise InvalidPunch(_("device_id is required."))

	return {
		"employee": employee,
		"check_time": check_time,
		"device_id": device_id,
		"reference_id": reference_id,
	}


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

	Each punch is checked on its own: the employee must exist and be Active, the reference_id
	must not be stored yet and check_time must be a valid date and time. A valid punch is saved
	as an Attendance Time record (status Pending); a punch that fails is answered FAILED with a
	"message", and the other punches of the batch are still saved.
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

	attendance_list = body.get("attendance_list", []) if isinstance(body, dict) else []

	if not attendance_list:
		return {
			"error": True,
			"message": _("attendance_list is required."),
			"processed_records": []
		}

	if not frappe.has_permission("Attendance Time", "create"):
		return {
			"error": True,
			"message": _("Not permitted to create Attendance Time."),
			"processed_records": []
		}

	employees = _get_employees(attendance_list)
	stored_reference_ids = _get_stored_reference_ids(attendance_list)

	processed_records = []
	saved = False

	for att in attendance_list:
		reference_id = att.get("reference_id") if isinstance(att, dict) else None

		try:
			punch = _validate_punch(att, employees, stored_reference_ids)
		except InvalidPunch as e:
			has_error = True
			processed_records.append({
				"reference_id": reference_id,
				"status": "FAILED",
				"attendance_id": None,
				"message": str(e)
			})
			continue

		try:
			frappe.db.savepoint("attendance_punch")
			doc = frappe.get_doc({"doctype": "Attendance Time", "status": "Pending", **punch}).insert()
		except Exception as e:
			frappe.db.rollback(save_point="attendance_punch")
			frappe.clear_messages()
			has_error = True
			if isinstance(e, frappe.ValidationError):
				message = cstr(e) or _("Invalid punch.")
			else:
				message = _("Could not save this punch; see the Error Log.")
				frappe.log_error(
					frappe.get_traceback(),
					f"Attendance API - Failed to save record ({reference_id})"
				)
			processed_records.append({
				"reference_id": reference_id,
				"status": "FAILED",
				"attendance_id": None,
				"message": message
			})
			continue

		saved = True
		stored_reference_ids.add(punch["reference_id"])
		processed_records.append({
			"reference_id": reference_id,
			"status": "SUCCESS",
			"attendance_id": doc.name
		})

	if saved:
		frappe.db.commit()

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
