# Copyright (c) 2026, Shahzad Naser and Contributors
# See license.txt

import unittest

from omnieast.omnieast.doctype.employee_contract_review.employee_contract_review import PROBATION_END, decision_label, final_status


class TestEmployeeContractReview(unittest.TestCase):
	def test_labels(self):
		self.assertEqual(final_status(PROBATION_END, "Renew / Confirm"), "Confirmed")
		self.assertEqual(final_status("Contract End", "Renew / Confirm"), "Renewed")
		self.assertEqual(final_status("Contract End", "End"), "Ended")
		self.assertTrue(decision_label(PROBATION_END, "End"))
