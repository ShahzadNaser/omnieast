/* Report a Problem: one tap to our helpdesk from every page.
   Display only, no records change. Adds a headset button beside the
   notification bell (desk navbar on v13 to v15, the home bar on v16),
   in the brand tier of every page header on v16 phones, and as an item
   under Search / Notification in the v16 sidebar. On the v16 home avatar
   menu it swaps Frappe's hard-coded "Frappe Support" for it.
   Per site: only HELP_URL changes. */
(function () {
	const HELP_URL = "/desk/issue/new";
	const LABEL = "Report a Problem";
	const ICON =
		'<svg class="icon icon-md jb-help-svg" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
		'<path d="M3 13a9 9 0 0 1 18 0"/>' +
		'<path d="M3 13v3a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-4a1 1 0 0 0-1-1H3"/>' +
		'<path d="M21 13v3a2 2 0 0 1-2 2h-1a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1h3"/>' +
		'<path d="M19 18v.5a3.5 3.5 0 0 1-3.5 3.5H13"/></svg>';

	const label = () => (typeof __ === "function" ? __(LABEL) : LABEL);
	const major = () => parseInt(((window.frappe && frappe.boot && frappe.boot.versions) || {}).frappe) || 0;

	function go(e) {
		if (e && e.preventDefault) e.preventDefault();
		const desk = HELP_URL.match(/^\/(app|desk)\/(.+)$/);
		if (desk && window.frappe && frappe.set_route) frappe.set_route(desk[2]);
		else window.location.assign(HELP_URL);
	}

	function link(cls) {
		const a = document.createElement("a");
		a.className = cls + " jb-help-link";
		a.href = HELP_URL;
		a.title = label();
		a.setAttribute("aria-label", label());
		a.innerHTML = ICON;
		a.addEventListener("click", go);
		return a;
	}

	// the headset takes the bell's own colour, so it matches every theme (day and night)
	function match_bell(a, bell) {
		const icon = bell && (bell.querySelector("svg") || bell);
		if (!icon) return;
		const c = getComputedStyle(icon);
		const colour = c.stroke && c.stroke !== "none" ? c.stroke : c.color;
		if (a.style.color !== colour) a.style.color = colour;
	}

	function place() {
		// v13 to v15: the desk navbar, just before the bell
		document.querySelectorAll("header.navbar .navbar-nav, header .navbar .navbar-nav").forEach((nav) => {
			const bell = nav.querySelector(":scope > .dropdown-notifications");
			if (!bell) return;
			let li = nav.querySelector(":scope > .jb-help-item");
			if (!li) {
				li = document.createElement("li");
				li.className = "nav-item jb-help-item";
				li.appendChild(link("nav-link"));
				nav.insertBefore(li, bell);
			}
			match_bell(li.firstChild, bell.querySelector(".nav-link, .dropdown-toggle") || bell);
		});
		// v16 home (/desk): the launcher bar, just before the bell (two markups
		// in v16 builds; where the bell is switched off it sits by the avatar)
		document.querySelectorAll(".desktop-navbar .desktop-notifications, #page-desktop header.navbar .desktop-notifications").forEach((bell) => {
			const row = bell.parentElement;
			let a = row.querySelector(":scope > .jb-help-link");
			if (!a) a = link("btn-reset nav-link jb-help-home");
			const btn = bell.querySelector("button");
			const shown = btn && btn.getClientRects().length;
			// bell shown: headset left of it; bell off (an empty slot): right of the slot, next to the avatar
			const want = shown ? bell : bell.nextElementSibling === a ? a.nextElementSibling : bell.nextElementSibling;
			if (a.parentElement !== row || (shown ? a.nextElementSibling !== bell : a.previousElementSibling !== bell)) row.insertBefore(a, want);
			match_bell(a, shown ? btn : row.closest(".navbar").querySelector(".desktop-search-icon svg, .search-bar svg"));
		});
		// v16 phones: brand tier of every page header, left of search
		if (major() >= 16) {
			document.querySelectorAll(".page-head").forEach((head) => {
				if (head.querySelector(":scope > .jb-help-link")) return;
				head.appendChild(link("jb-help-phone"));
			});
		}
	}

	function patch_v16() {
		if (!window.frappe || !frappe.ui) return;
		// home avatar menu: "Frappe Support" (hard-coded in v16) -> our helpdesk
		if (frappe.ui.create_menu && !frappe.ui.create_menu.__jb_help) {
			const create_menu = frappe.ui.create_menu;
			frappe.ui.create_menu = function (opts) {
				if (opts && Array.isArray(opts.menu_items) && opts.parent && $(opts.parent).is(".desktop-avatar")) {
					opts.menu_items = opts.menu_items.map((i) =>
						i && i.label === "Frappe Support" ? { icon: "support", label: label(), onClick: go } : i
					);
				}
				return create_menu.apply(this, arguments);
			};
			frappe.ui.create_menu.__jb_help = true;
		}
		// sidebar: an item under Search / Notification
		const Sidebar = frappe.ui.Sidebar;
		if (Sidebar && Sidebar.prototype.add_standard_items && !Sidebar.prototype.__jb_help) {
			const add_standard_items = Sidebar.prototype.add_standard_items;
			Sidebar.prototype.add_standard_items = function () {
				const first = !this.standard_items_setup;
				const out = add_standard_items.apply(this, arguments);
				if (first && this.$standard_items_sections && this.add_item) {
					this.add_item(this.$standard_items_sections, {
						label: label(),
						icon: "support",
						standard: true,
						type: "Button",
						class: "jb-help-sidebar",
						onClick: () => {
							go();
							if (window.frappe && frappe.is_mobile && frappe.is_mobile() && this.wrapper) this.wrapper.removeClass("expanded");
						},
					});
				}
				return out;
			};
			Sidebar.prototype.__jb_help = true;
		}
	}

	const CSS = `
.jb-help-link { display: inline-flex; align-items: center; justify-content: center; text-decoration: none !important; }
.jb-help-link .jb-help-svg { width: 20px; height: 20px; fill: none !important; stroke: currentColor; }
.jb-help-item .nav-link { display: flex; align-items: center; height: 100%; }
.jb-help-home { margin: 0; padding: 0; }
.jb-help-link:hover { opacity: .8; }
.jb-help-phone { display: none !important; }
@media (max-width: 767.98px) {
  .jb-help-home { margin-left: 6px; }
  body .page-head > .jb-help-phone {
    display: flex !important; position: absolute; top: 13px; right: 62px; z-index: 2;
    width: 34px; height: 34px; border-radius: 50%; color: #fff !important;
    background: rgba(255, 255, 255, .14); border: 1px solid rgba(255, 255, 255, .2);
  }
  body .page-head > .jb-help-phone .jb-help-svg { width: 18px; height: 18px; stroke: #fff !important; }
}
@media print { .jb-help-link, .jb-help-item { display: none !important; } }
`;

	function boot() {
		if (!document.getElementById("jb-help-style")) {
			const s = document.createElement("style");
			s.id = "jb-help-style";
			s.textContent = CSS;
			document.head.appendChild(s);
		}
		place();
		let queued = false;
		new MutationObserver(() => {
			if (queued) return;
			queued = true;
			setTimeout(() => {
				queued = false;
				place();
			}, 60);
		}).observe(document.body, { childList: true, subtree: true });
	}

	patch_v16();
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
	else boot();
})();
