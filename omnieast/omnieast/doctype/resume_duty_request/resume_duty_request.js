// Copyright (c) 2026, Shahzad Naser and contributors
// For license information, please see license.txt

frappe.ui.form.on("Resume Duty Request", {
	setup(frm) {
		// approved leaves that need a Resume Duty Request and have none yet (of the selected employee, when there is one)
		frm.set_query("leave_application", () => {
			const filters = {
				docstatus: 1,
				status: "Approved",
				custom_resume_required: 1,
				custom_resume_duty_request: ["is", "not set"],
			};
			if (frm.doc.employee) {
				filters.employee = frm.doc.employee;
			}
			return { filters };
		});
	},

	async onload(frm) {
		if (!frm.is_new()) return;

		if (frm.doc.leave_application) {
			// opened from the leave (button or Connections)
			frm.trigger("leave_application");
		} else if (!frm.doc.employee && window.hrms && hrms.get_current_employee) {
			const employee = await hrms.get_current_employee(frm);
			if (employee) {
				frm.set_value("employee", employee);
			}
		}
	},

	leave_application(frm) {
		frm.events.fill_resume_details(frm);
	},

	resume_date(frm) {
		frm.events.fill_resume_details(frm);
	},

	async fill_resume_details(frm) {
		if (!frm.doc.leave_application || frm.doc.docstatus !== 0) return;

		const { message } = await frappe.call({
			method: "omnieast.omnieast.doctype.resume_duty_request.resume_duty_request.get_resume_details",
			args: { leave_application: frm.doc.leave_application, resume_date: frm.doc.resume_date },
		});
		if (message) {
			await frm.set_value(message);
		}
	},
});
