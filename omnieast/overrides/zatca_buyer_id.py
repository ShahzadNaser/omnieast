"""ZATCA override for the ERPGulf app (zatca_erpgulf 3.0.x): buyer ID (BT-46).

BR-KSA-F-08 warning: the app writes the customer's Buyer ID as cac:PartyIdentification with
whatever value and scheme the customer has, even when it is empty or a placeholder "0" (and
defaults the scheme to CRN), or when it is the VAT number sent as CRN. ZATCA then reports an
incorrect Other Buyer ID.

This wraps the app's customer_data(): after it builds the buyer party, a buyer
PartyIdentification is left out when:
* its ID is empty or only zeros; or
* the invoice carries the buyer's VAT number (BT-48) and the ID equals that VAT number or does
  not fit its scheme: CRN must be 10 digits, 700 must be 10 digits starting with 7.
When the invoice has no buyer VAT number a non-empty ID is kept: ZATCA then requires an Other
Buyer ID (BR-KSA-14 / BR-KSA-81), and a missing one rejects the invoice where a wrong one only
gives a warning. Everything else is unchanged.

The app imports customer_data by name in several modules, so each module's reference is replaced.
Imported from hooks.py. Check after any zatca_erpgulf upgrade that customer_data keeps its name
and signature.
"""
import importlib
import re

import frappe

CAC = "cac:"
CBC_ID = "cbc:ID"
CBC_COMPANY_ID = "cbc:CompanyID"

# Buyer ID schemes with a fixed format; an ID that does not fit its scheme is left out.
_SCHEME_FORMATS = {
    "CRN": re.compile(r"\d{10}"),  # Commercial Registration number
    "700": re.compile(r"7\d{9}"),  # unified number
}

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


def _buyer_vat_numbers(party):
    """The buyer VAT numbers (BT-48) written in the invoice."""
    numbers = set()
    for tax_scheme in _children(party, CAC + "PartyTaxScheme"):
        for company_id in _children(tax_scheme, CBC_COMPANY_ID):
            if (company_id.text or "").strip():
                numbers.add(company_id.text.strip())
    return numbers


def _customer_tax_ids(sales_invoice_doc):
    """The customer's Tax ID as on the invoice and on the Customer."""
    ids = {(sales_invoice_doc.get("tax_id") or "").strip()}
    if sales_invoice_doc.get("customer"):
        ids.add(
            (frappe.get_cached_value("Customer", sales_invoice_doc.get("customer"), "tax_id") or "").strip()
        )
    ids.discard("")
    return ids


def _fits_scheme(cbc_id, value):
    pattern = _SCHEME_FORMATS.get((cbc_id.get("schemeID") or "").strip().upper())
    return not pattern or bool(pattern.fullmatch(value))


def _strip_invalid_buyer_id(invoice, sales_invoice_doc):
    for customer_party in _children(invoice, CAC + "AccountingCustomerParty"):
        for party in _children(customer_party, CAC + "Party"):
            buyer_vat = _buyer_vat_numbers(party)
            vat_numbers = (buyer_vat | _customer_tax_ids(sales_invoice_doc)) if buyer_vat else set()
            for party_id in _children(party, CAC + "PartyIdentification"):
                ids = _children(party_id, CBC_ID)
                value = (ids[0].text or "").strip() if ids else ""
                if _is_blank(value):
                    party.remove(party_id)
                elif buyer_vat and (value in vat_numbers or not _fits_scheme(ids[0], value)):
                    # the buyer VAT number is in the invoice, so BT-46 is optional: leave out a wrong one
                    party.remove(party_id)


def _wrap(original):
    if getattr(original, "_buyer_id_fix", False):
        return original

    def customer_data(invoice, sales_invoice_doc):
        result = original(invoice, sales_invoice_doc)
        if result is not None:
            _strip_invalid_buyer_id(result, sales_invoice_doc)
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
