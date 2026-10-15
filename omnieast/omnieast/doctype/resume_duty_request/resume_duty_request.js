// Copyright (c) 2026, Shahzad Naser and contributors
// For license information, please see license.txt

frappe.ui.form.on("Resume Duty Request", {
	setup(frm) {
		// approved leaves that are not resumed yet (of the selected employee, when there is one)
		frm.set_query("leave_application", () => {
			const filters = { docstatus: 1, status: "Approved", custom_resumed_on: ["is", "not set"] };
			if (frm.doc.employee) {
				filters.employee = frm.doc.employee;
			}
			return { filters };
		});
	},

	async onload(frm) {
		if (!frm.is_new() || frm.doc.employee) return;

		if (frm.doc.leave_application) {
			// opened from the leave's Connections
			frm.trigger("leave_application");
		} else if (window.hrms && hrms.get_current_employee) {
			const employee = await hrms.get_current_employee(frm);
			if (employee) {
				frm.set_value("employee", employee);
			}
		}
	},

	async leave_application(frm) {
		if (!frm.doc.leave_application) return;

		const { message } = await frappe.db.get_value(
			"Leave Application",
			frm.doc.leave_application,
			"employee",
		);
		if (message && message.employee && message.employee !== frm.doc.employee) {
			frm.set_value("employee", message.employee);
		}
	},
});
