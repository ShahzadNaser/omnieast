frappe.provide("frappe.query_reports");

(function () {
	let _report;
	Object.defineProperty(frappe.query_reports, "Accounts Payable", {
		configurable: true,
		enumerable: true,
		get() {
			return _report;
		},
		set(val) {
			if (val && Array.isArray(val.filters)) {
				const pt = val.filters.find((f) => f && f.fieldname === "party_type");
				if (pt) pt.default = "Supplier";
			}
			_report = val;
		},
	});
})();
