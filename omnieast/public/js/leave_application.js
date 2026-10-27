// ISS-2026-00109: the approved vacation leave asks for its Resume Duty Request
frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		const doc = frm.doc;
		if (
			doc.docstatus !== 1 ||
			doc.status !== "Approved" ||
			!doc.custom_resume_required ||
			doc.custom_resume_duty_request ||
			!frappe.model.can_create("Resume Duty Request")
		) {
			return;
		}

		frm.add_custom_button(__("Create Resume Duty Request"), () => {
			frappe.new_doc("Resume Duty Request", { leave_application: doc.name, employee: doc.employee });
		});
	},
});
