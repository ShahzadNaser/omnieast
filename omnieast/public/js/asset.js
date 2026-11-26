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

// ISS-2026-00184: Asset Usage (Office / Project). A draft from a purchase takes the purchase row's value;
// the server checks it books to the account the purchase debited.
const omni_asset_usage = {
	enabled: () => !!frappe.boot.omnieast_asset_usage_enabled,

	async refresh(frm) {
		const draft = frm.doc.docstatus === 0;
		frm.toggle_reqd("custom_asset_usage", omni_asset_usage.enabled() && draft);
		if (!omni_asset_usage.enabled() || !draft || frm.doc.custom_asset_usage) return;

		const sources = [
			["purchase_invoice_item", "Purchase Invoice Item"],
			["purchase_receipt_item", "Purchase Receipt Item"],
		];
		for (const [fieldname, doctype] of sources) {
			if (!frm.doc[fieldname]) continue;
			const { message } = await frappe.db.get_value(doctype, frm.doc[fieldname], "custom_asset_usage");
			if (message && message.custom_asset_usage) {
				frm.set_value("custom_asset_usage", message.custom_asset_usage);
				return;
			}
		}
	},
};

frappe.ui.form.on("Asset", { refresh: omni_asset_usage.refresh });
