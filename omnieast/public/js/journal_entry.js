//Project / Cost Center on every row for Omni East
const omni_je_toggle_reqd = (frm) =>
	omnieast.project_cc.toggle_reqd(frm, [], { accounts: ["project", "cost_center"] });

frappe.ui.form.on("Journal Entry", {
	refresh: omni_je_toggle_reqd,
	company: omni_je_toggle_reqd,
	voucher_type: omni_je_toggle_reqd,

	validate(frm) {
		return omnieast.project_cc.apply_server_fill(frm);
	},
});

frappe.ui.form.on("Journal Entry Account", {
	project(frm, cdt, cdn) {
		omnieast.project_cc.set_cost_center_from_project(frm, locals[cdt][cdn]);
	},

	async reference_name(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		omni_je_toggle_reqd(frm);
		if (!omnieast.project_cc.applies(frm)) return;

		const values = await omnieast.project_cc.get_reference_dimensions(row.reference_type, row.reference_name);
		await omnieast.project_cc.fill(frm, row, values);
	},
});
