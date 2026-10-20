// Copyright (c) 2026, Shahzad Naser and contributors
// For license information, please see license.txt

// Employee Contract Review (ISS-2026-00139): decision buttons for the line manager and HR.
const ECR_METHOD = "omnieast.omnieast.doctype.employee_contract_review.employee_contract_review";
const ECR_OPEN = ["Pending Line Manager", "Pending HR"];

frappe.ui.form.on("Employee Contract Review", {
	refresh(frm) {
		if (frm.is_new() || !ECR_OPEN.includes(frm.doc.status)) return;

		const is_line_manager =
			frm.doc.status === "Pending Line Manager" && frappe.session.user === frm.doc.line_manager_user;
		const is_hr = !!(frm.doc.__onload && frm.doc.__onload.is_hr_approver);
		if (!is_line_manager && !is_hr) return;

		const probation = frm.doc.review_type === "Probation End";
		const labels = probation
			? [__("Confirm employee"), __("End employment")]
			: [__("Renew contract"), __("End contract")];

		frm.add_custom_button(labels[0], () => ecr_decide(frm, "Renew / Confirm", labels[0], is_line_manager), __("Decide"));
		frm.add_custom_button(labels[1], () => ecr_decide(frm, "End", labels[1], is_line_manager), __("Decide"));

		if (is_hr) {
			frm.add_custom_button(__("Cancel Review"), () => ecr_cancel(frm));
		}
	},
});

function ecr_decide(frm, decision, label, is_line_manager) {
	const fields = [];
	if (decision === "Extend") {
		fields.push({
			fieldname: "extend_months",
			fieldtype: "Select",
			label: __("Extend By (Months)"),
			options: ["1", "2", "3", "6"],
			default: frm.doc.extend_months || "3",
			reqd: 1,
		});
	}
	if (decision === "Renew / Confirm" && frm.doc.review_type === "Contract End") {
		fields.push({
			fieldname: "renewal_note",
			fieldtype: "HTML",
			options: `<p class="text-muted small">${__("This only records the decision. HR updates the new contract end date on the employee once Qiwa is done.")}</p>`,
		});
	}
	fields.push({ fieldname: "remarks", fieldtype: "Small Text", label: __("Remarks") });

	frappe.prompt(
		fields,
		(values) => {
			frappe.call({
				method: `${ECR_METHOD}.decide`,
				args: {
					name: frm.doc.name,
					decision: decision,
					remarks: values.remarks,
					extend_months: values.extend_months,
				},
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		},
		label,
		__("Confirm")
	);
}

function ecr_cancel(frm) {
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
		(values) => {
			frappe.call({
				method: `${ECR_METHOD}.cancel_review`,
				args: { name: frm.doc.name, reason: values.reason },
				freeze: true,
				callback: () => frm.reload_doc(),
			});
		},
		__("Cancel Review"),
		__("Cancel Review")
	);
}
