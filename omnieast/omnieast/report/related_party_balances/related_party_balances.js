// Copyright (c) 2026, Jawa Group and contributors
// For license information, please see license.txt
/* Related Party Balances: Finance's related-party sheet, live from the GL.
 * The lines come from the company's Related Party Mapping (button "Edit Lines").
 * Code and Account open the General Ledger of that party or account. */

// fiscal year start from the user defaults (works on every ERPNext version)
const rpb_year_start = () =>
	frappe.defaults.get_user_default("year_start_date") || `${frappe.datetime.get_today().slice(0, 4)}-01-01`;

frappe.query_reports["Related Party Balances"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: rpb_year_start(),
			description: __("Opening balance is everything posted before this date. Blank: 1 Jan of the fiscal year."),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			description: __("Blank: today"),
		},
		{
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book",
			description: __("Blank: all books together"),
		},
		{
			fieldname: "related_company",
			label: __("Related Company"),
			fieldtype: "Data",
		},
		{
			fieldname: "group_by_related_company",
			label: __("Group by Related Company"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "hide_zero_rows",
			label: __("Hide Zero Rows"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_ageing",
			label: __("Show Ageing"),
			fieldtype: "Check",
			default: 1,
			description: __("Customer and supplier balances split by age at To Date"),
		},
	],

	onload(report) {
		report.page.add_inner_button(__("Edit Lines"), () => {
			const company = frappe.query_report.get_filter_value("company");
			frappe.db.exists("Related Party Mapping", company).then((exists) => {
				if (exists) {
					frappe.set_route("Form", "Related Party Mapping", company);
				} else {
					frappe.new_doc("Related Party Mapping", { company: company });
				}
			});
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if ((column.fieldname === "code" || column.fieldname === "account") && !data.bold && (data.party_type || data.gl_account)) {
			const args = encodeURIComponent(JSON.stringify({
				party_type: data.party_type || "",
				party: data.party_type ? data.code : "",
				account: data.gl_account || "",
			}));
			value = `<a href="#" onclick="frappe.query_reports['Related Party Balances'].open_gl('${args}'); return false;">${value}</a>`;
		}
		if (data.unmapped && column.fieldname === "related_company") {
			value = `<span style="color: var(--orange-600, #c87818); font-weight: 600;">${value}</span>`;
		}
		if (data.bold) {
			value = `<b>${value}</b>`;
		}
		return value;
	},

	open_gl(args) {
		const d = JSON.parse(decodeURIComponent(args));
		const f = frappe.query_report.get_filter_values();
		const options = {
			company: f.company,
			from_date: f.from_date || rpb_year_start(),
			to_date: f.to_date || frappe.datetime.get_today(),
			group_by: "Group by Voucher (Consolidated)",
		};
		if (f.finance_book) options.finance_book = f.finance_book;
		if (d.party_type) {
			options.party_type = d.party_type;
			options.party = [d.party];
		} else {
			options.account = [d.account];
		}
		frappe.set_route("query-report", "General Ledger", options);
	},
};
