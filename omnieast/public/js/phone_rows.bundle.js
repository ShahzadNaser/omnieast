// Phones: important fields on list rows (shared on every company site).
// On phones Frappe shows at most one or two list columns under the title.
// For the transactions below, phone rows show the listed fields instead,
// as a two-column block with short labels. Fields a site does not have,
// empty values and restricted (permlevel > 0) fields are skipped.
// The desktop list is unchanged. Display only: no records or settings change.

(function () {
	var PHONE_ROW_FIELDS = {
		"Sales Invoice": [["posting_date", "Date"], ["outstanding_amount", "Outstanding"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Purchase Invoice": [["posting_date", "Date"], ["bill_no", "Bill No"], ["net_total", "Net"], ["grand_total", "Grand"], ["outstanding_amount", "Outstanding"]],
		"Sales Order": [["transaction_date", "Date"], ["delivery_date", "Delivery"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Purchase Order": [["transaction_date", "Date"], ["schedule_date", "Required By"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Quotation": [["transaction_date", "Date"], ["valid_till", "Valid Till"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Supplier Quotation": [["transaction_date", "Date"], ["valid_till", "Valid Till"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Delivery Note": [["posting_date", "Date"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Purchase Receipt": [["posting_date", "Date"], ["net_total", "Net"], ["grand_total", "Grand"]],
		"Material Request": [["transaction_date", "Date"], ["schedule_date", "Required By"], ["material_request_type", "Type"]],
		"Stock Entry": [["posting_date", "Date"], ["stock_entry_type", "Type"], ["total_amount", "Value"]],
		"Payment Entry": [["posting_date", "Date"], ["payment_type", "Type"], ["paid_amount", "Amount"], ["mode_of_payment", "Mode"], ["reference_no", "Ref No"]],
		"Journal Entry": [["posting_date", "Date"], ["total_debit", "Amount"], ["cheque_no", "Ref No"], ["user_remark", "Remark"]],
		"Expense Claim": [["posting_date", "Date"], ["total_claimed_amount", "Claimed"], ["total_sanctioned_amount", "Sanctioned"]],
		"Employee Advance": [["posting_date", "Date"], ["advance_amount", "Advance"], ["paid_amount", "Paid"]],
		"Leave Application": [["from_date", "From"], ["to_date", "To"], ["leave_type", "Type"], ["total_leave_days", "Days"]],
		"Salary Slip": [["start_date", "From"], ["end_date", "To"], ["gross_pay", "Gross"], ["net_pay", "Net Pay"]],
	};

	var LV = window.frappe && frappe.views && frappe.views.ListView && frappe.views.ListView.prototype;
	if (!LV || LV.__phone_row_fields) return;
	LV.__phone_row_fields = true;

	function fields_for(lv) {
		var list = PHONE_ROW_FIELDS[lv.doctype];
		if (!list) return null;
		var meta = frappe.get_meta(lv.doctype);
		if (!meta) return null;
		var out = [];
		list.forEach(function (pair) {
			var df = frappe.meta.get_docfield(lv.doctype, pair[0]);
			if (!df || (df.permlevel || 0) > 0 || pair[0] === meta.title_field) return;
			out.push({ df: df, label: pair[1] });
		});
		return out.length ? out : null;
	}

	function add_field(lv, fieldname) {
		var df = frappe.meta.get_docfield(lv.doctype, fieldname);
		if (df && (df.permlevel || 0) === 0) lv._add_field(fieldname);
	}

	// Fetch the fields (and the currency / company they format with).
	var set_fields = LV.set_fields;
	LV.set_fields = function () {
		var me = this;
		var ret = set_fields.apply(this, arguments);
		var extend = function () {
			var fields = fields_for(me);
			if (!fields) return;
			fields.forEach(function (f) { add_field(me, f.df.fieldname); });
			["currency", "company"].forEach(function (f) { add_field(me, f); });
		};
		if (ret && typeof ret.then === "function") return ret.then(function (v) { extend(); return v; });
		extend();
		return ret;
	};

	function value_html(df, doc) {
		var v = doc[df.fieldname];
		if (v === null || v === undefined || v === "") return "";
		if (["Check"].indexOf(df.fieldtype) !== -1) return "";
		// Long text (remarks etc.) on one line: no HTML, no line breaks.
		if (["Small Text", "Text", "Long Text", "Text Editor", "Data"].indexOf(df.fieldtype) !== -1) {
			var plain = String(v).replace(/<br\s*\/?>/gi, " ").replace(/<[^>]*>/g, " ");
			plain = plain.replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
			return plain ? frappe.utils.escape_html(plain) : "";
		}
		var html = frappe.format(v, df, { inline: true }, doc);
		return html === null || html === undefined ? "" : String(html);
	}

	var get_left_html = LV.get_left_html;
	LV.get_left_html = function (doc) {
		var html = get_left_html.apply(this, arguments);
		var fields = frappe.is_mobile() && fields_for(this);
		if (!fields) return html;

		var cells = "";
		fields.forEach(function (f) {
			var val = value_html(f.df, doc);
			if (!val || !val.replace(/<[^>]*>/g, "").trim()) return;
			// Amounts, numbers and dates are never cut short; long text is.
			var fit = ["Currency", "Float", "Int", "Percent", "Date", "Datetime"].indexOf(f.df.fieldtype) !== -1;
			cells +=
				'<div class="ph-field' + (fit ? " ph-fit" : "") + '">' +
				'<span class="ph-label">' + frappe.utils.escape_html(__(f.label)) + "</span>" +
				'<span class="ph-value">' + val + "</span></div>";
		});
		if (!cells) return html;

		var wrap = document.createElement("div");
		wrap.innerHTML = html;
		// Frappe's own phone meta items are replaced by the block below.
		wrap.querySelectorAll(".mobile-layout").forEach(function (el) { el.remove(); });
		var block = document.createElement("div");
		block.className = "ph-meta";
		block.innerHTML = cells;
		var subject = wrap.querySelector(".list-subject");
		if (subject && subject.parentNode === wrap) subject.after(block);
		else wrap.appendChild(block);
		return wrap.innerHTML;
	};
})();
