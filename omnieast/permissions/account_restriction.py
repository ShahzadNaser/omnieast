"""Account Restriction: hide accounts, and every entry posted to them, from the users of some roles.

Rules are kept in Desk (doctype Account Restriction: accounts + roles). A user who has one of a rule's roles
does not see the rule's accounts (with their sub-accounts when "Include Child Accounts" is set) nor any
document of the covered doctypes that posts to them:

- `get_permission_query_conditions`: lists, counts, Report Builder, exports, link searches, the account tree;
- `has_permission`: opening a single document (form, URL, API, print).

The covered doctypes are listed in hooks.py (`permission_query_conditions` / `has_permission`). Their
Account fields are read from the meta, on the main form and in child tables, custom fields included.
GL Entry hides every line of a voucher that touches a hidden account.

Reports read the ledger directly and are not filtered here: give the restricted role no access to them.
"""

import frappe

CACHE_KEY = "omnieast:account_restriction:rules"
PROTECTED_ROLES = ("Administrator", "System Manager", "Guest", "All")


# --- rules ------------------------------------------------------------------------------------------------


def get_rules() -> list[dict]:
	"""Enabled rules as [{"roles": [...], "accounts": [...]}], group accounts expanded. Cached in Redis."""
	return frappe.cache.get_value(CACHE_KEY, generator=_load_rules) or []


def clear_cache(*args, **kwargs):
	"""Rule saved / deleted, or an Account added, moved, renamed or deleted."""
	frappe.cache.delete_value(CACHE_KEY)


def _load_rules() -> list[dict]:
	if not frappe.db.table_exists("Account Restriction"):
		return []

	rules = []
	for name in frappe.get_all("Account Restriction", filters={"enabled": 1}, pluck="name"):
		rule = frappe.get_doc("Account Restriction", name)
		roles = sorted({d.role for d in rule.roles if d.role and d.role not in PROTECTED_ROLES})
		accounts = {d.account for d in rule.accounts if d.account}
		if rule.include_child_accounts:
			accounts |= _descendants(accounts)
		if roles and accounts:
			rules.append({"roles": roles, "accounts": sorted(accounts)})
	return rules


def _descendants(accounts: set[str]) -> set[str]:
	result = set()
	for row in frappe.get_all("Account", filters={"name": ["in", list(accounts)]}, fields=["lft", "rgt"]):
		result.update(
			frappe.get_all("Account", filters={"lft": [">", row.lft], "rgt": ["<", row.rgt]}, pluck="name")
		)
	return result


def get_hidden_accounts(user: str | None = None) -> tuple[str, ...]:
	"""Accounts hidden from `user` (empty for Administrator and for users without a restricted role)."""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return ()

	rules = get_rules()
	if not rules:
		return ()

	roles = set(frappe.get_roles(user))
	hidden = set()
	for rule in rules:
		if roles.intersection(rule["roles"]):
			hidden.update(rule["accounts"])
	return tuple(sorted(hidden))


# --- which Account fields a doctype has -------------------------------------------------------------------


def _account_fields(doctype: str) -> list[str]:
	return [
		df.fieldname
		for df in frappe.get_meta(doctype).get_link_fields()
		if df.options == "Account" and not df.get("is_virtual")
	]


def get_account_fields(doctype: str) -> tuple[list[str], dict[str, list[str]]]:
	"""(Account fields on the main form, {child doctype: its Account fields})."""
	meta = frappe.get_meta(doctype)
	children = {}
	for table in meta.get_table_fields():
		fields = _account_fields(table.options)
		if fields:
			children[table.options] = fields
	return _account_fields(doctype), children


# --- hooks ------------------------------------------------------------------------------------------------


def get_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	hidden = get_hidden_accounts(user)
	if not hidden or not doctype:
		return ""

	values = "(" + ", ".join(frappe.db.escape(a) for a in hidden) + ")"
	table = f"`tab{doctype}`"

	if doctype == "Account":
		return f"{table}.`name` not in {values}"

	if doctype == "GL Entry":
		# the whole voucher: its bank / payable lines would otherwise show the amount and the account
		return (
			"not exists (select 1 from `tabGL Entry` hidden_gle"
			f" where hidden_gle.`voucher_type` = {table}.`voucher_type`"
			f" and hidden_gle.`voucher_no` = {table}.`voucher_no`"
			f" and hidden_gle.`account` in {values})"
		)

	parent_fields, children = get_account_fields(doctype)
	conditions = [f"ifnull({table}.`{field}`, '') not in {values}" for field in parent_fields]
	for child, fields in children.items():
		matches = " or ".join(f"hidden_row.`{field}` in {values}" for field in fields)
		conditions.append(
			f"not exists (select 1 from `tab{child}` hidden_row"
			f" where hidden_row.`parent` = {table}.`name`"
			f" and hidden_row.`parenttype` = {frappe.db.escape(doctype)}"
			f" and ({matches}))"
		)
	return " and ".join(conditions)


def has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	"""False when the document posts to a hidden account; True otherwise (never None: Frappe reads None as
	a denial)."""
	hidden = get_hidden_accounts(user)
	if not hidden:
		return True

	if doc.doctype == "Account":
		return doc.name not in hidden

	if doc.doctype == "GL Entry":
		return not frappe.db.exists(
			"GL Entry",
			{"voucher_type": doc.voucher_type, "voucher_no": doc.voucher_no, "account": ["in", hidden]},
		)

	hidden_set = set(hidden)
	parent_fields, children = get_account_fields(doc.doctype)
	if any(doc.get(field) in hidden_set for field in parent_fields):
		return False

	meta = frappe.get_meta(doc.doctype)
	for table in meta.get_table_fields():
		fields = children.get(table.options)
		if not fields:
			continue
		for row in doc.get(table.fieldname) or []:
			if any(row.get(field) in hidden_set for field in fields):
				return False
	return True
