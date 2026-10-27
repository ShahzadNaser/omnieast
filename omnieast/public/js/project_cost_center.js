// Project / Cost Center mandatory for Omni East, Cost Center follows the Project.
// Mirrors omnieast/overrides/project_mandatory.py; the server check is the one that counts.
frappe.provide("omnieast.project_cc");

$.extend(omnieast.project_cc, {
	settings() {
		return (
			frappe.boot.omni_project_cc || {
				companies: [],
				exempt_voucher_types: [],
				exempt_reference_types: [],
				default_cost_center: {},
			}
		);
	},

	applies(frm) {
		const settings = this.settings();
		const doc = frm.doc;

		if (!settings.companies.includes(doc.company)) return false;

		if (doc.doctype === "Journal Entry") {
			if (settings.exempt_voucher_types.includes(doc.voucher_type) || doc.is_system_generated) return false;
			if ((doc.accounts || []).some((row) => settings.exempt_reference_types.includes(row.reference_type))) {
				return false;
			}
		}
		return true;
	},

	// header_fields: ["project", ...]; table_fields: {items: ["project", ...]}
	toggle_reqd(frm, header_fields, table_fields) {
		const on = this.applies(frm) && frm.doc.docstatus === 0;

		// only ever undo what was switched on here, so other companies keep the site's own mandatory fields
		if (!on && !frm.__omni_project_cc_reqd) return;
		frm.__omni_project_cc_reqd = on;

		const reqd = (doctype, fieldname) =>
			on ? 1 : cint(frappe.get_meta(doctype)?.fields.find((df) => df.fieldname === fieldname)?.reqd);

		header_fields.forEach((fieldname) => {
			if (frm.get_field(fieldname)) frm.toggle_reqd(fieldname, reqd(frm.doctype, fieldname));
		});

		Object.entries(table_fields || {}).forEach(([table_fieldname, fieldnames]) => {
			const grid = frm.get_field(table_fieldname)?.grid;
			if (grid) fieldnames.forEach((fieldname) => grid.toggle_reqd(fieldname, reqd(grid.doctype, fieldname)));
		});
	},

	// The browser checks mandatory fields before the server can fill them, so apply the server's fill first.
	// Any failure here leaves the form as it is; the server check still applies on save.
	async apply_server_fill(frm) {
		if (!this.applies(frm) || frm.doc.docstatus !== 0) return;

		try {
			const { message } = await frappe.call({
				method: "omnieast.overrides.project_mandatory.get_filled_dimensions",
				args: { doc: frm.doc },
			});
			if (!message) return;

			const apply = (doc, values) => {
				["project", "cost_center"].forEach((fieldname) => {
					if (values?.[fieldname] && values[fieldname] !== doc[fieldname] && frappe.meta.has_field(doc.doctype, fieldname)) {
						doc[fieldname] = values[fieldname];
					}
				});
			};

			apply(frm.doc, message);
			frappe.model.get_all_docs(frm.doc).forEach((doc) => {
				if (doc.parentfield) apply(doc, message.rows?.[doc.name]);
			});
			frm.refresh_fields();
		} catch (e) {
			console.error(e);
		}
	},

	// the company default stands in for "not chosen"
	is_blank_cost_center(frm, cost_center) {
		return !cost_center || cost_center === this.settings().default_cost_center[frm.doc.company];
	},

	// doc is frm.doc or a child row
	async set_cost_center_from_project(frm, doc) {
		if (!this.applies(frm) || !doc.project || !this.is_blank_cost_center(frm, doc.cost_center)) return;

		const { message } = await frappe.db.get_value("Project", doc.project, "cost_center");
		if (message?.cost_center && this.is_blank_cost_center(frm, doc.cost_center)) {
			await frappe.model.set_value(doc.doctype, doc.name, "cost_center", message.cost_center);
		}
	},

	// fill blanks only, the Project's own Cost Center wins
	async fill(frm, doc, { project, cost_center } = {}) {
		if (project && !doc.project) {
			await frappe.model.set_value(doc.doctype, doc.name, "project", project);
		}
		await this.set_cost_center_from_project(frm, doc);
		if (cost_center && this.is_blank_cost_center(frm, doc.cost_center)) {
			await frappe.model.set_value(doc.doctype, doc.name, "cost_center", cost_center);
		}
	},

	async get_reference_dimensions(doctype, name) {
		if (!doctype || !name) return {};

		const { message } = await frappe.call({
			method: "omnieast.overrides.project_mandatory.get_reference_dimensions",
			args: { doctype, name },
		});
		return message || {};
	},
});
