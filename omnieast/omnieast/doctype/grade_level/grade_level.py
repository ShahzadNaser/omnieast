# Copyright (c) 2026, Shahzad Naser and contributors
# For license information, please see license.txt

from frappe import _
import frappe
from frappe.model.document import Document

class GradeLevel(Document):
    def autoname(self):
        # Explicitly check for None instead of using 'if not'
        if self.min_grade is None or self.max_grade is None:
            frappe.throw(_("Please enter both Min Grade and Max Grade to generate the record name."))
            
        self.combination = f"{self.min_grade}-to-{self.max_grade}"
        self.name = self.combination

    def validate(self):
        # Ensure we have numbers to compare
        if self.min_grade is None or self.max_grade is None:
            return
            
        self.combination = f"{self.min_grade}-to-{self.max_grade}"