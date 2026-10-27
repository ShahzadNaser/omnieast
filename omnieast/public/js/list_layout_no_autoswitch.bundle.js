(() => {
  if (window.__omniLayoutNoAutoswitch) return;
  window.__omniLayoutNoAutoswitch = true;

  // Frappe v16 switches to a saved layout (List Filter) whenever the list's filters match its
  // route_signature: the user's filter is replaced by the layout's and the layout is saved as theirs.
  // Here a layout is only active when the user picked it from List View > layouts.
  const NEEDED = [
    "get_route_signature",
    "get_saved_active_layout_name",
    "find_layout_by_name",
    "get_layout_route_signature",
    "set_active_layout",
    "apply_saved_layout",
    "set_active_default_layout",
  ];

  function restore_layout_from_route_signature({ refresh = true } = {}) {
    const finish = () => {
      this._initial_layout_restored = true;
      // the view switcher's trigger shows the active layout name
      this.list_view.views_list?.refresh_trigger?.();
    };

    if (this._user_selected_layout) {
      finish();
      return Promise.resolve();
    }

    // the layout the user picked last, kept while the filters are still that layout's
    const signature = this.get_route_signature();
    const saved_name = this.get_saved_active_layout_name();
    const saved_layout = saved_name ? this.find_layout_by_name(saved_name) : null;
    if (
      saved_layout &&
      (!signature || this.get_layout_route_signature(saved_layout) === signature)
    ) {
      this.set_active_layout(saved_layout);
      return this.apply_saved_layout(saved_layout, { refresh }).then(finish, finish);
    }

    // anything else: Default Layout with the user's own filters, nothing saved
    this.set_active_default_layout();
    finish();
    return Promise.resolve();
  }

  let patched = false;
  const patch_list_filter = () => {
    const proto = frappe.views.ListFilter?.prototype;
    if (patched || !proto) return;
    patched = true;

    const missing = ["restore_layout_from_route_signature", ...NEEDED].filter(
      (fn) => typeof proto[fn] !== "function"
    );
    if (missing.length) {
      console.warn(
        `omnieast: ListFilter.${missing.join(", ")} not found, layouts still switch on matching filters`
      );
      return;
    }
    proto.restore_layout_from_route_signature = restore_layout_from_route_signature;
  };

  // ListFilter is lazy-loaded (list_filter.bundle.js) by setup_list_filter_by, and only used after it
  // resolves, so patch it there
  const wrap_setup = () => {
    const base = frappe.views?.BaseList?.prototype;
    if (!base) return false;
    if (typeof base.setup_list_filter_by !== "function") {
      console.warn("omnieast: BaseList.setup_list_filter_by not found, layouts still switch on matching filters");
      return true;
    }

    const setup_list_filter_by = base.setup_list_filter_by;
    base.setup_list_filter_by = function (...args) {
      return Promise.resolve(setup_list_filter_by.apply(this, args)).then((result) => {
        patch_list_filter();
        return result;
      });
    };
    return true;
  };

  let tries = 0;
  const run = () => {
    if (wrap_setup()) return;
    if (++tries > 50) {
      console.warn("omnieast: frappe.views.BaseList not loaded, layouts still switch on matching filters");
      return;
    }
    setTimeout(run, 100);
  };
  run();
})();
