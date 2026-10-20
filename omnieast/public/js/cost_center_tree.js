// Cost Center tree: hide the top placeholder line (the company label that
// the tree draws above the real root cost center), so the real root
// "Omni East Company" shows at the top. Display only, no data changes.
(function () {
	const settings = frappe.treeview_settings["Cost Center"];
	if (!settings) return;

	if (!document.getElementById("omni-hide-tree-root-css")) {
		$(`<style id="omni-hide-tree-root-css">
			.tree.omni-hide-tree-root > .tree-link,
			.tree.omni-hide-tree-root > .tree-node-toolbar {
				display: none !important;
			}
			.tree.omni-hide-tree-root > .tree-children {
				padding-left: 0 !important;
				margin-left: 0 !important;
			}
			.tree.omni-hide-tree-root > .tree-children > li.tree-node::before,
			.tree.omni-hide-tree-root > .tree-children > li.tree-node::after {
				display: none !important;
			}
		</style>`).appendTo("head");
	}

	const original_post_render = settings.post_render;
	settings.post_render = function (treeview) {
		original_post_render && original_post_render(treeview);
		treeview.tree && treeview.tree.wrapper.addClass("omni-hide-tree-root");
	};
})();
