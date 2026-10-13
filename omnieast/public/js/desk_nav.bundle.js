// OMNI desk: two small display-only fixes for Frappe 16.50+ ("polished")
// 1. A "Desk" item at the top of every sidebar (desktop and phone drawer),
//    so there is always a way back to the desk icons - the per-module
//    sidebar and the workspaces without a module (Executive Tracker) lost it.
// 2. Attachments open in a new tab again, instead of the in-form preview pane.
// Display only: nothing here touches records or settings.
(function () {
	function desk_item_html() {
		return `
			<div class="standard-sidebar-item">
				<a class="item-anchor" href="/desk" data-link-type="" title="${__("Desk")}">
					<span class="sidebar-item-icon" item-icon="layout-grid">
						<svg class="icon current-color icon-sm" stroke="currentColor" aria-hidden="true">
							<use href="#icon-layout-grid"></use>
						</svg>
					</span>
					<span class="sidebar-item-label">${__("Desk")}</span>
					<div class="sidebar-item-control"></div>
				</a>
			</div>
			<div class="sidebar-child-item nested-container"></div>`;
	}

	function ensure_desk_item() {
		const band = document.querySelector(".body-sidebar .standard-items-band");
		if (!band || band.querySelector(".jb-desk-home")) return;
		const el = document.createElement("div");
		el.className = "jb-desk-home";
		el.setAttribute("item-name", "Desk");
		el.dataset.id = "Desk";
		el.innerHTML = desk_item_html();
		band.insertBefore(el, band.firstChild);
	}

	let scheduled = false;
	function schedule() {
		if (scheduled) return;
		scheduled = true;
		requestAnimationFrame(() => {
			scheduled = false;
			ensure_desk_item();
		});
	}

	function watch_sidebar() {
		const container = document.querySelector(".body-sidebar-container");
		if (!container) return false;
		ensure_desk_item();
		new MutationObserver(schedule).observe(container, { childList: true, subtree: true });
		return true;
	}

	$(document).ready(() => {
		if (!watch_sidebar()) {
			// the sidebar is built after boot on some routes: wait for it
			const body_observer = new MutationObserver(() => {
				if (watch_sidebar()) body_observer.disconnect();
			});
			body_observer.observe(document.body, { childList: true });
		}
		$(document).on("page-change", schedule);
	});

	// attachments: open in a new tab, as before 16.50
	function patch_attachments() {
		const Attachments = frappe.ui && frappe.ui.form && frappe.ui.form.Attachments;
		if (!Attachments || Attachments.prototype.__jb_new_tab) return;
		Attachments.prototype.show_attachment_preview = function (attachment, file_url) {
			window.open(file_url, "_blank", "noopener");
		};
		Attachments.prototype.__jb_new_tab = true;
	}
	patch_attachments();
	$(document).on("form-load form-refresh", patch_attachments);
})();
