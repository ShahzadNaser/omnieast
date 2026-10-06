"""Disable system users who have not signed in for 90 days.

Runs daily from the app's scheduler_events. A user is disabled when ALL of these hold:
  - user_type is "System User" and the account is enabled
  - it is not Administrator or Guest, and not in the site's exclusion list
  - it has no API key (integration users are kept)
  - the account is older than 90 days, and the last sign-in (last_active, or last_login) is
    more than 90 days ago or has never happened

Nothing is deleted; a disabled user is re-enabled by a System Manager when needed.
Each run writes one Comment on every user it disables and one summary e-mail to the
addresses in site_config "auto_disable_notify".

site_config.json keys:
  auto_disable_days      int, default 90
  auto_disable_exclude   list of user ids never to disable (e.g. shared API or kiosk logins)
  auto_disable_dry_run   1 = only report, change nothing (use for the first run)
  auto_disable_notify    list of e-mail addresses for the summary
"""
import frappe
from frappe.utils import add_days, now_datetime, get_datetime, get_url_to_form

ALWAYS_KEEP = {"Administrator", "Guest"}
DEFAULT_NOTIFY = ["sajjad.m@jawahr.com"]


def run():
    days = int(frappe.conf.get("auto_disable_days") or 90)
    exclude = set(frappe.conf.get("auto_disable_exclude") or []) | ALWAYS_KEEP
    dry_run = bool(frappe.conf.get("auto_disable_dry_run"))
    cutoff = add_days(now_datetime(), -days)

    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User", "creation": ("<", cutoff)},
        fields=["name", "full_name", "last_active", "last_login", "creation", "api_key"],
    )

    to_disable = []
    for u in users:
        if u.name in exclude or u.api_key:
            continue
        last = u.last_active or u.last_login
        if last and get_datetime(last) >= cutoff:
            continue
        to_disable.append(u)

    if not to_disable:
        return []

    for u in to_disable:
        if dry_run:
            continue
        frappe.db.set_value("User", u.name, "enabled", 0, update_modified=False)
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "User",
                "reference_name": u.name,
                "content": f"Disabled automatically: no sign-in for {days} days (last: {u.last_active or u.last_login or 'never'}).",
            }
        ).insert(ignore_permissions=True)
        # end any live sessions of the account
        frappe.db.sql("delete from `tabSessions` where user = %s", u.name)

    frappe.db.commit()
    _notify(to_disable, days, dry_run)
    return [u.name for u in to_disable]


def _notify(users, days, dry_run):
    recipients = frappe.conf.get("auto_disable_notify") or DEFAULT_NOTIFY
    site = frappe.local.site
    rows = "".join(
        f"<tr><td><a href='{get_url_to_form('User', u.name)}'>{frappe.utils.escape_html(u.name)}</a></td>"
        f"<td>{frappe.utils.escape_html(u.full_name or '')}</td>"
        f"<td>{u.last_active or u.last_login or 'never'}</td></tr>"
        for u in users
    )
    verb = "would be disabled (dry run)" if dry_run else "disabled"
    frappe.sendmail(
        recipients=recipients,
        subject=f"{site}: {len(users)} user account(s) {verb} - no sign-in for {days} days",
        message=(
            f"<p>{len(users)} system user account(s) on {site} {verb} because they had no sign-in for {days} days.</p>"
            f"<table border='1' cellpadding='4' cellspacing='0'><tr><th>User</th><th>Name</th><th>Last sign-in</th></tr>{rows}</table>"
            "<p>Re-enable any account that is still needed from its User record.</p>"
        ),
        now=True,
    )
