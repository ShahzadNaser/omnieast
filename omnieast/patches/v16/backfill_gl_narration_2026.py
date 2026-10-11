"""One-time backfill of GL Entry `custom_narration` for fiscal year 2026.

Follows the same per-voucher-type rules as the `before_insert` hook on GL Entry:
Journal Entry rows match on account/cost_center/debit/credit; Purchase Invoice
on expense_account/cost_center; everything else (incl. Payment Entry) falls
back to the voucher's header `remarks`. Cancelled rows are skipped.
"""

import frappe

YEAR = "2026"


def execute():
	_backfill_journal_entry()
	_backfill_purchase_invoice()
	_backfill_remaining_with_remarks()
	frappe.db.commit()


def _backfill_journal_entry():
	frappe.db.sql(
		"""
		UPDATE `tabGL Entry` gle
		SET gle.custom_narration = (
			SELECT REGEXP_REPLACE(
				GROUP_CONCAT(jea.user_remark SEPARATOR ', '),
				'<[^>]*>', ''
			)
			FROM `tabJournal Entry Account` jea
			WHERE jea.parent = gle.voucher_no
			  AND jea.account = gle.account
			  AND COALESCE(NULLIF(TRIM(jea.cost_center), ''), '') =
			      COALESCE(NULLIF(TRIM(gle.cost_center), ''), '')
			  AND jea.debit = gle.debit
			  AND jea.credit = gle.credit
			  AND jea.user_remark IS NOT NULL
			  AND TRIM(jea.user_remark) != ''
			GROUP BY jea.parent, jea.account, jea.cost_center, jea.debit, jea.credit
			LIMIT 1
		)
		WHERE gle.voucher_type = 'Journal Entry'
		  AND gle.fiscal_year = %(year)s
		  AND IFNULL(gle.is_cancelled, 0) = 0
		  AND IFNULL(TRIM(gle.custom_narration), '') = ''
		""",
		{"year": YEAR},
	)


def _backfill_purchase_invoice():
	frappe.db.sql(
		"""
		UPDATE `tabGL Entry` gle
		SET gle.custom_narration = (
			SELECT REGEXP_REPLACE(
				GROUP_CONCAT(pii.description SEPARATOR ', '),
				'<[^>]*>', ''
			)
			FROM `tabPurchase Invoice Item` pii
			WHERE pii.parent = gle.voucher_no
			  AND pii.expense_account = gle.account
			  AND COALESCE(NULLIF(TRIM(pii.cost_center), ''), '') =
			      COALESCE(NULLIF(TRIM(gle.cost_center), ''), '')
			  AND pii.description IS NOT NULL
			  AND TRIM(pii.description) != ''
			GROUP BY pii.expense_account
		)
		WHERE gle.voucher_type = 'Purchase Invoice'
		  AND gle.fiscal_year = %(year)s
		  AND IFNULL(gle.is_cancelled, 0) = 0
		  AND IFNULL(TRIM(gle.custom_narration), '') = ''
		""",
		{"year": YEAR},
	)


def _backfill_remaining_with_remarks():
	frappe.db.sql(
		"""
		UPDATE `tabGL Entry`
		SET custom_narration = remarks
		WHERE fiscal_year = %(year)s
		  AND IFNULL(is_cancelled, 0) = 0
		  AND IFNULL(TRIM(custom_narration), '') = ''
		  AND IFNULL(TRIM(remarks), '') != ''
		""",
		{"year": YEAR},
	)
