// Project / Cost Center on header, items and taxes for Omni East
const omni_pi_toggle_reqd = (frm) =>
	omnieast.project_cc.toggle_reqd(frm, ["project", "cost_center"], {
		items: ["project", "cost_center"],
		taxes: ["cost_center"],
	});

frappe.ui.form.on("Purchase Invoice", {
	refresh: omni_pi_toggle_reqd,
	company: omni_pi_toggle_reqd,

	validate(frm) {
		return omnieast.project_cc.apply_server_fill(frm);
	},

	// buying.js already copies the header Project to items with none; give every row its Project's Cost Center
	async project(frm) {
		if (!omnieast.project_cc.applies(frm) || !frm.doc.project) return;

		await omnieast.project_cc.set_cost_center_from_project(frm, frm.doc);
		for (const row of [...(frm.doc.items || []), ...(frm.doc.taxes || [])]) {
			await omnieast.project_cc.fill(frm, row, { project: frm.doc.project });
		}
	},
});

frappe.ui.form.on("Purchase Invoice Item", {
	project(frm, cdt, cdn) {
		omnieast.project_cc.set_cost_center_from_project(frm, locals[cdt][cdn]);
	},
});

frappe.ui.form.on("Purchase Taxes and Charges", {
	taxes_add(frm, cdt, cdn) {
		if (!omnieast.project_cc.applies(frm)) return;
		omnieast.project_cc.fill(frm, locals[cdt][cdn], {
			project: frm.doc.project,
			cost_center: frm.doc.cost_center,
		});
	},

	project(frm, cdt, cdn) {
		omnieast.project_cc.set_cost_center_from_project(frm, locals[cdt][cdn]);
	},
});
