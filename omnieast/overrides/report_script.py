import os

import frappe


REPORT_JS_OVERRIDES = {
    "Accounts Payable": "public/js/reports/accounts_payable.js",
}


def _load_omnieast_script(report_name):
    rel = REPORT_JS_OVERRIDES.get(report_name)
    if not rel:
        return None

    path = frappe.get_app_path("omnieast", rel)
    if not os.path.exists(path):
        return None

    with open(path) as f:
        return f.read()


def _wrap(original):
    def get_script(report_name):
        result = original(report_name)
        script = _load_omnieast_script(report_name)
        if script:
            from frappe.model.utils import render_include

            result["script"] = render_include(script)
        return result

    return get_script


def apply():
    from frappe.desk import query_report

    if not getattr(query_report.get_script, "_omnieast_wrapped", False):
        wrapped = _wrap(query_report.get_script)
        wrapped._omnieast_wrapped = True
        query_report.get_script = wrapped
