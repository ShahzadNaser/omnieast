// Copyright (c) 2026, Jawa Group and contributors
// For license information, please see license.txt

frappe.ui.form.on("Related Party Mapping", {
	setup(frm) {
		frm.set_query("related_parties_group", () => ({
			filters: { company: frm.doc.company, is_group: 1 },
		}));
		// Current Account lines: only accounts under the related parties group
		frm.set_query("account", "lines", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				parent_account: ["descendants of (inclusive)", frm.doc.related_parties_group],
			},
		}));
	},

	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Report"), () =>
				frappe.set_route("query-report", "Related Party Balances", { company: frm.doc.company })
			);
		}
		if (frm.doc.send_daily_email && !frm.is_new() && !frm.is_dirty()) {
			frm.add_custom_button(__("Send Email Now"), () =>
				frappe.call({
					method: "omnieast.omnieast.doctype.related_party_mapping.related_party_mapping.send_now",
					args: { company: frm.doc.company },
					freeze: true,
					freeze_message: __("Sending..."),
				})
			);
		}
	},
});

frappe.ui.form.on("Related Party Mapping Line", {
	line_type(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "party", null);
		frappe.model.set_value(cdt, cdn, "account", null);
	},
});
