/* Breadcrumbs: put doctypes Frappe cannot place under the workspace the business chose.
   Display only, no records change. Works on v13 to v16.
   v13 to v15: draws the workspace crumb next to the logo.
   v16: opens the chosen sidebar when the page has no fitting one, and the crumb follows it.
   Per site: only MAP changes. */
(function () {
	const MAP = {
		"Employee": "HR Setup",
		"Sales Invoice": "Invoicing",
		"Business Travel Request": "HR Setup",
		"Travel Policy": "HR Setup",
		"Attendance Time": "HR Setup",
		"Grade Level": "HR Setup",
		"Cash Payment Voucher": "Payments",
		"Zatca ERPgulf Setting": "Invoicing",
		"ZATCA Multiple Setting": "Invoicing",
		"Omnieast Settings": "ERPNext Settings"
	};

	const fr = window.frappe;
	if (!fr || !fr.breadcrumbs || fr.breadcrumbs.__ws_map) return;
	fr.breadcrumbs.__ws_map = true;

	const major = () => parseInt(((frappe.boot && frappe.boot.versions) || {}).frappe) || 0;
	const sidebars = () => (frappe.boot && frappe.boot.workspace_sidebar_item) || {};
	const sidebar_label = (ws) => {
		const s = sidebars()[ws.toLowerCase()];
		return s ? s.label || ws : null;
	};
	// sidebars that list this doctype (v16)
	const homes_of = (doctype) => {
		const out = [];
		Object.entries(sidebars()).forEach(([key, s]) => {
			(s.items || []).forEach((i) => {
				if (i.link_to === doctype && !out.includes(s.label || key)) out.push(s.label || key);
			});
		});
		return out;
	};

	// crumb next to the logo
	const original = fr.breadcrumbs.set_workspace_breadcrumb;
	fr.breadcrumbs.set_workspace_breadcrumb = function (crumbs) {
		const ws = crumbs && crumbs.doctype && MAP[crumbs.doctype];
		if (ws) {
			try {
				if (!crumbs.workspace) this.set_workspace(crumbs);
				if (crumbs.module_info && crumbs.module_info.blocked) return;
				crumbs.workspace = ws;
				if (major() >= 16) {
					const sb = frappe.app && frappe.app.sidebar;
					const current = sb && sb.sidebar_title;
					// a sidebar the user came through that also lists the doctype stays; otherwise ours
					const title = current && homes_of(crumbs.doctype).includes(current) ? current : sidebar_label(ws) || ws;
					const icon = frappe.utils.get_desktop_icon_by_label && frappe.utils.get_desktop_icon_by_label(title);
					const route = icon && frappe.utils.get_route_for_icon ? frappe.utils.get_route_for_icon(icon) : null;
					this.append_breadcrumb_element(route || `/desk/${frappe.router.slug(title)}`, __(icon ? icon.label : title), "worksapce-breadcrumb");
					this.$breadcrumbs.find("li a.worksapce-breadcrumb").parent().addClass("ellipsis");
				} else {
					$(`<li><a href="/app/${frappe.router.slug(ws)}">${__(ws)}</a></li>`).appendTo(this.$breadcrumbs);
				}
				return;
			} catch (e) {
				/* never block the page over a breadcrumb; fall back to Frappe */
			}
		}
		return original.apply(this, arguments);
	};

	// v16: open the chosen sidebar when the user did not come through one that lists the doctype
	const Sidebar = fr.ui && fr.ui.Sidebar;
	if (Sidebar && Sidebar.prototype.set_workspace_sidebar && !Sidebar.prototype.__ws_map) {
		const set_workspace_sidebar = Sidebar.prototype.set_workspace_sidebar;
		Sidebar.prototype.set_workspace_sidebar = function () {
			const before = this.sidebar_title;
			const out = set_workspace_sidebar.apply(this, arguments);
			try {
				const route = frappe.get_route() || [];
				const doctype = ["List", "Form", "Report", "Tree", "Kanban", "Calendar", "Gantt", "Dashboard", "Image"].includes(route[0]) ? route[1] : null;
				const ws = doctype && MAP[doctype];
				const label = ws && sidebar_label(ws);
				if (label && this.sidebar_title !== label) {
					const kept = before && homes_of(doctype).includes(before) && this.sidebar_title === before;
					if (!kept) {
						this.setup(label);
						if (this.set_active_workspace_item) this.set_active_workspace_item();
					}
				}
			} catch (e) {
				/* leave Frappe's choice */
			}
			return out;
		};
		Sidebar.prototype.__ws_map = true;
	}
})();
