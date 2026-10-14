"""ZATCA override for the ERPGulf app (zatca_erpgulf 3.0.x): buyer ID (BT-46).

BR-KSA-F-08 warning: the app writes cac:PartyIdentification for the buyer even when the
customer's Buyer ID is empty or a placeholder "0" (and defaults the scheme to CRN), so ZATCA
reports an incorrect CRN. A missing buyer ID must be left out, not sent as CRN = 0.

This wraps the app's customer_data(): after it builds the buyer party, any buyer
PartyIdentification whose ID is empty or only zeros is removed. Everything else is unchanged.
The app imports customer_data by name in several modules, so each module's reference is replaced.
Imported from hooks.py. Check after any zatca_erpgulf upgrade that customer_data keeps its name
and signature.
"""
import importlib

CAC = "cac:"
CBC_ID = "cbc:ID"

_MODULES = (
    "zatca_erpgulf.zatca_erpgulf.createxml",
    "zatca_erpgulf.zatca_erpgulf.sign_invoice",
    "zatca_erpgulf.zatca_erpgulf.sales_invoice_withoutxml",
    "zatca_erpgulf.zatca_erpgulf.zatca_background_sched",
    "zatca_erpgulf.zatca_erpgulf.debug_xml",
)


def _is_blank(value):
    value = (value or "").strip()
    return not value or set(value) == {"0"}


def _children(element, tag):
    # The app builds tags as literal "cac:..." strings, so match by tag text
    # (ElementTree's find() would reject the prefix without a namespace map).
    return [child for child in list(element) if child.tag == tag]


def _strip_blank_buyer_id(invoice):
    for customer_party in _children(invoice, CAC + "AccountingCustomerParty"):
        for party in _children(customer_party, CAC + "Party"):
            for party_id in _children(party, CAC + "PartyIdentification"):
                ids = _children(party_id, CBC_ID)
                if not ids or _is_blank(ids[0].text):
                    party.remove(party_id)


def _wrap(original):
    if getattr(original, "_buyer_id_fix", False):
        return original

    def customer_data(invoice, sales_invoice_doc):
        result = original(invoice, sales_invoice_doc)
        if result is not None:
            _strip_blank_buyer_id(result)
        return result

    customer_data._buyer_id_fix = True
    return customer_data


_createxml = importlib.import_module(_MODULES[0])
_patched = _wrap(_createxml.customer_data)

for _name in _MODULES:
    try:
        _module = importlib.import_module(_name)
    except ImportError:
        continue
    if hasattr(_module, "customer_data"):
        _module.customer_data = _patched
