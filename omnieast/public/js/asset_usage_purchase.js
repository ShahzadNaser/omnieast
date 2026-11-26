// ISS-2026-00184: Asset Usage (Office / Project) on fixed-asset rows of Purchase Invoice / Purchase Receipt.
// The header value fills the fixed-asset rows; each row can be changed. The server checks and books it.
(() => {
	const enabled = () => !!frappe.boot.omnieast_asset_usage_enabled;
	const fixed_asset_rows = (frm) => (frm.doc.items || []).filter((d) => d.is_fixed_asset);

	const refresh_header = (frm) => {
		frm.toggle_display("custom_asset_usage", enabled() && fixed_asset_rows(frm).length > 0);
	};

	const default_row = (frm, cdt, cdn) => {
		const row = locals[cdt][cdn];
		if (enabled() && row.is_fixed_asset && !row.custom_asset_usage && frm.doc.custom_asset_usage) {
			frappe.model.set_value(cdt, cdn, "custom_asset_usage", frm.doc.custom_asset_usage);
		}
		refresh_header(frm);
	};

	const parent_events = {
		refresh: refresh_header,
		custom_asset_usage(frm) {
			if (!enabled() || !frm.doc.custom_asset_usage) return;
			fixed_asset_rows(frm).forEach((d) => {
				frappe.model.set_value(d.doctype, d.name, "custom_asset_usage", frm.doc.custom_asset_usage);
			});
		},
	};

	const child_events = {
		is_fixed_asset: default_row,
		item_code: default_row,
		items_remove: refresh_header,
	};

	frappe.ui.form.on("Purchase Invoice", parent_events);
	frappe.ui.form.on("Purchase Invoice Item", child_events);
	frappe.ui.form.on("Purchase Receipt", parent_events);
	frappe.ui.form.on("Purchase Receipt Item", child_events);
})();
