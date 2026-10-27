//Project / Cost Center on the asset for Omni East
const omni_asset_toggle_reqd = (frm) => omnieast.project_cc.toggle_reqd(frm, ["project", "cost_center"]);

frappe.ui.form.on("Asset", {
	refresh: omni_asset_toggle_reqd,
	company: omni_asset_toggle_reqd,

	validate(frm) {
		return omnieast.project_cc.apply_server_fill(frm);
	},

	project(frm) {
		omnieast.project_cc.set_cost_center_from_project(frm, frm.doc);
	},
});
