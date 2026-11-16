"""Related Party Balances (the Finance Director's related-party sheet in the ERP).

1. One Related Party Mapping per company, on its "Affiliate Accounts" group:
   - every account under the group as a Current Account line;
   - the sister-company customers and suppliers below, but only those with postings in that
     company (old duplicates and unused codes stay out); a company is never its own related party.
   Related Company names are only a first guess from the account / party name: Finance can
   rename, untick or add lines on the mapping without a developer.
2. Role "Related Party Balances" to Shamim (Musaddiq works as Administrator, who sees every report).
3. Shortcut on the Accounting workspace (users without the role don't see it).

Only creates a mapping that does not exist yet, so Finance's own changes are never overwritten.
Never stops the migrate: anything that fails is logged. Safe to run again.
"""

import json

import frappe

ROLE = "Related Party Balances"
MAPPING = "Related Party Mapping"
SHORTCUT = "Related Party Balances"
GROUP_NAME = "Affiliate Accounts"
USERS = ("shamim.k@jawahr.com", "shamim.k@omatrasa.com")
EMAIL_TO = "shamim.k@jawahr.com"

# (keywords in the account / party name, Related Company shown on the report); first match wins
NAME_RULES = (
	(("toleave", "to leave"), "Toleave Travel"),
	(("omni",), "Omni East Company"),
	(("lebanon", "liban"), "OMATRA Lebanon"),
	(("orient agent", "omatra"), "Orient Agents for Trading Co. (OMATRA)"),
	(("services and support", "service & support", "service and support", "ssc"), "Services and Support Company (SSC)"),
	(("strategic contracting",), "Strategic Contracting Co. (EuroFix)"),
	(("markaba",), "Markaba Al Shamila"),
	(("comprehensive vehicle", "(cvc)"), "Comprehensive Vehicle Co. (CVC)"),
	(("jecat", "gecat limited"), "Jecat Limited"),
	(("gecat", "jawacat"), "JAWA GECAT Equipment Rental Company"),
	(("bahrain",), "Jawa Logistics (Bahrain)"),
	(("jawa logistics", "jawalogistics"), "JAWA Logistics Services Company"),
	(("jawa clean",), "Jawa Clean"),
	(("jawahr", "jawa human"), "Jawa Human Resources Company"),
	((" mic ", "mic current", "(mic)", "middle east invest"), "Middle East Investments Company (MIC)"),
	(("advance invest", "adv. invest"), "Advance Investment Company"),
	(("yumna",), "Yumna East Trading"),
	(("ozee",), "OZEE Company Limited"),
	(("houdiny",), "Houdiny"),
	(("q salary", "quick salary"), "Quick Salary Company"),
	(("karim ghorayeb",), "Karim Ghorayeb"),
	(("creative telecom",), "Creative Telecom Co."),
	(("delma national",), "Delma National"),
	(("jawa communication",), "JAWA Communication and Information"),
	(("jawa petroleum",), "Jawa Petroleum Investment"),
	(("filsons",), "Filsons Services Co"),
)

# The company each ERP company is, in NAME_RULES terms (never its own related party)
OWN = {
	"Omni East Company": "Omni East Company",
	"Services and Support Co. (SSC)": "Services and Support Company (SSC)"
}

# Sister-company customers and suppliers on this ERP: (party type, code)
PARTIES = [
	("Customer", "C-OMN-1106"),
	("Customer", "C-SSC-0032"),
	("Customer", "C-SSC-0009"),
	("Customer", "C-OMN-1002"),
	("Customer", "C-OMN-1003"),
	("Supplier", "S-OMN-1213"),
	("Supplier", "S-SSC-0024"),
	("Supplier", "S-OMN-1014"),
	("Supplier", "S-OMN-1001"),
	("Supplier", "S-OMN-1012"),
	("Supplier", "S-OMN-1054"),
	("Supplier", "S-OMN-1096"),
	("Supplier", "S-OMN-1103"),
	("Supplier", "S-OMN-1127"),
]


def execute():
	for doctype, name in (
		("doctype", "related_party_mapping_line"),
		("doctype", "related_party_mapping"),
		("report", "related_party_balances"),
	):
		frappe.reload_doc("omnieast", doctype, name)

	for company in frappe.get_all("Company", pluck="name"):
		try:
			seed_mapping(company)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Related Party Balances setup: " + company)

	for user in USERS:
		if frappe.db.get_value("User", user, "enabled") and not frappe.db.exists(
			"Has Role", {"parent": user, "parenttype": "User", "role": ROLE}
		):
			frappe.get_doc("User", user).add_roles(ROLE)

	try:
		for name in ("Accounting", "Accounts"):
			if frappe.db.exists("Workspace", name):
				add_shortcut(name)
				break
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Related Party Balances setup: workspace shortcut")
	frappe.clear_cache()


def related_company(name, skip=None):
	"""Sister company for an account / party name; `skip` passes over a rule naming the company
	itself (e.g. "JAWAHR (Omni East Co)" in Omni East's books is JawaHR's account)."""
	text = " {0} ".format((name or "").lower())
	for keys, label in NAME_RULES:
		if label != skip and any(k in text for k in keys):
			return label
	return (name or "").strip()


def seed_mapping(company):
	if frappe.db.exists(MAPPING, company):
		return
	group = frappe.db.get_value("Account", {"company": company, "account_name": GROUP_NAME, "is_group": 1}, "name")
	if not group:
		return
	own = OWN.get(company)
	doc = frappe.new_doc(MAPPING)
	doc.company = company
	doc.related_parties_group = group
	doc.send_daily_email = 1
	doc.daily_email_to = EMAIL_TO

	order = 0
	for party_type, code in PARTIES:
		if not frappe.db.exists(party_type, code):
			continue
		label = related_company(frappe.db.get_value(party_type, code, "customer_name" if party_type == "Customer" else "supplier_name"))
		if label == own or not has_postings(company, party_type, code):
			continue
		order += 10
		doc.append("lines", {"line_type": party_type, "party": code, "related_company": label, "include": 1, "sort_order": order})

	lft, rgt = frappe.db.get_value("Account", group, ["lft", "rgt"])
	for acc in frappe.get_all(
		"Account",
		filters={"company": company, "lft": (">", lft), "rgt": ("<", rgt), "is_group": 0},
		fields=["name", "account_name"],
		order_by="lft",
	):
		order += 10
		doc.append("lines", {
			"line_type": "Current Account", "account": acc.name,
			"related_company": related_company(acc.account_name, skip=own), "include": 1, "sort_order": order,
		})

	doc.flags.ignore_permissions = True
	doc.insert()


def has_postings(company, party_type, party):
	return bool(frappe.db.get_value(
		"GL Entry", {"company": company, "party_type": party_type, "party": party, "is_cancelled": 0}, "name"
	))


def add_shortcut(name):
	ws = frappe.get_doc("Workspace", name)
	if not any(s.label == SHORTCUT for s in ws.get("shortcuts")):
		ws.append("shortcuts", {"label": SHORTCUT, "type": "Report", "link_to": SHORTCUT, "color": "Blue"})
	if ws.meta.has_field("content"):
		# v14+: the shortcut must also be placed in the page layout
		content = json.loads(ws.get("content") or "[]")
		if not any(b.get("type") == "shortcut" and b.get("data", {}).get("shortcut_name") == SHORTCUT for b in content):
			last = max((i for i, b in enumerate(content) if b.get("type") == "shortcut"), default=len(content) - 1)
			content.insert(last + 1, {"id": frappe.generate_hash(length=10), "type": "shortcut",
				"data": {"shortcut_name": SHORTCUT, "col": 3}})
		ws.content = json.dumps(content)
	ws.flags.ignore_permissions = True
	ws.save()
