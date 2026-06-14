import datetime

import frappe
from frappe.utils import (
	cint,
	flt
)
from hrms.hr.doctype.leave_application.leave_application import (
	validate_leave_access,
	get_leave_allocation_records,
	get_leave_balance_on,
	get_leaves_for_period,
	get_leaves_pending_approval_for_period,
	get_leave_approver
)

@frappe.whitelist()
def get_leave_details(employee: str, date: str | datetime.date, for_salary_slip: bool = False) -> dict:
	validate_leave_access(employee)

	allocation_records = get_leave_allocation_records(employee, date)
	leave_allocation = {}
	precision = cint(frappe.db.get_single_value("System Settings", "float_precision")) or 2

	for d in allocation_records:
		allocation = allocation_records.get(d, frappe._dict())
		to_date = date if for_salary_slip else allocation.to_date
		remaining_leaves = get_leave_balance_on(
			employee,
			d,
			date,
			to_date=to_date,
			consider_all_leaves_in_the_allocation_period=False if for_salary_slip else True,
		)

		leaves_taken = get_leaves_for_period(employee, d, allocation.from_date, to_date) * -1
		leaves_pending = get_leaves_pending_approval_for_period(employee, d, allocation.from_date, to_date)
		expired_leaves = allocation.total_leaves_allocated - (remaining_leaves + leaves_taken)

		leave_allocation[d] = {
			"total_leaves": flt(allocation.total_leaves_allocated, precision),
			"expired_leaves": flt(expired_leaves, precision) if expired_leaves > 0 else 0,
			"leaves_taken": flt(leaves_taken, precision),
			"leaves_pending_approval": flt(leaves_pending, precision),
			"remaining_leaves": flt(remaining_leaves, precision),
		}

	# is used in set query
	lwp = frappe.get_list("Leave Type", filters={"is_lwp": 1}, pluck="name")
	
    # add business trip in set query
	lwp.append("Business Trip")

	return {
		"leave_allocation": leave_allocation,
		"leave_approver": get_leave_approver(employee),
		"lwps": lwp,
	}