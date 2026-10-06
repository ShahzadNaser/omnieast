"""OMNI overrides for the ERPGulf ZATCA app (zatca_erpgulf 3.0.x).

The app sends the invoice *due date* as the supply date (cbc:ActualDeliveryDate), so an invoice
with payment terms tells ZATCA the goods were supplied on the due date (validation warning D3).
The supply date must be the posting date.

The app imports delivery_and_payment_means by name in several modules, so each module's
reference is replaced; patching createxml alone would not reach them.
Imported from omnieast/hooks.py so it runs when the app loads.
Check after any zatca_erpgulf upgrade that the function keeps its name and signature.
"""
import frappe
from frappe import _
import xml.etree.ElementTree as ET

from zatca_erpgulf.zatca_erpgulf import createxml
from zatca_erpgulf.zatca_erpgulf import sign_invoice, sales_invoice_withoutxml, zatca_background_sched, debug_xml


def delivery_and_payment_means(invoice, sales_invoice_doc, is_return):
    """Same as zatca_erpgulf.createxml.delivery_and_payment_means, with the supply date = posting date."""
    try:
        cac_delivery = ET.SubElement(invoice, "cac:Delivery")
        cbc_actual_delivery_date = ET.SubElement(cac_delivery, "cbc:ActualDeliveryDate")
        cbc_actual_delivery_date.text = str(sales_invoice_doc.posting_date)

        cac_payment_means = ET.SubElement(invoice, "cac:PaymentMeans")
        cbc_payment_means_code = ET.SubElement(cac_payment_means, "cbc:PaymentMeansCode")
        cbc_payment_means_code.text = "30"

        if is_return == 1:
            cbc_instruction_note = ET.SubElement(cac_payment_means, "cbc:InstructionNote")
            cbc_instruction_note.text = sales_invoice_doc.custom_credit_note_reasoninstruction_note

        if sales_invoice_doc.is_debit_note == 1:
            cbc_instruction_note = ET.SubElement(cac_payment_means, "cbc:InstructionNote")
            cbc_instruction_note.text = "Price adjustment or Additional charges"

        return invoice
    except (ET.ParseError, AttributeError, ValueError) as e:
        frappe.throw(_(f"Delivery and payment means failed: {e}"))
        return None


for _module in (createxml, sign_invoice, sales_invoice_withoutxml, zatca_background_sched, debug_xml):
    _module.delivery_and_payment_means = delivery_and_payment_means
