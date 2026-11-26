"""ISS-2026-00184: Asset Value Adjustment, Asset Repair and Asset Capitalization use each asset's own row."""

import frappe
from frappe import _

from omnieast.assets.depreciation_accounts import (
	USAGE_FIELD,
	asset_usage_context,
	get_asset_category_account,
	is_enabled,
	usage_scope,
)


class AssetValueAdjustmentUsageMixin:
	def make_asset_revaluation_entry(self):
		with usage_scope(self.asset):
			return super().make_asset_revaluation_entry()


class AssetRepairUsageMixin:
	def get_gl_entries(self):
		"""Capitalized repair: Dr the repaired asset's Fixed Asset account."""
		with usage_scope(self.asset):
			return super().get_gl_entries()


class AssetCapitalizationUsageMixin:
	"""Target (composite) asset: its own row for the capitalized value (Fixed Asset or CWIP).
	Consumed assets: disposed from their own rows (through depreciation.get_asset_details)."""

	def validate(self):
		super().validate()
		if (
			is_enabled()
			and self.target_asset
			and not frappe.db.get_value("Asset", self.target_asset, USAGE_FIELD)
		):
			frappe.throw(
				_("Set {0} on the target asset {1} before capitalizing it.").format(
					frappe.bold(_("Asset Usage")), frappe.bold(self.target_asset)
				),
				title=_("Missing Asset Usage"),
			)

	def set_missing_values(self, for_validate=False):
		super().set_missing_values(for_validate=for_validate)
		if not is_enabled():
			return

		if self.target_asset:
			account = _fixed_asset_account_of(self.target_asset, self.company)
			if account:
				self.target_fixed_asset_account = account

		for d in self.get("asset_items"):
			if d.asset:
				account = _fixed_asset_account_of(d.asset, self.company)
				if account:
					d.fixed_asset_account = account

	def get_target_account(self):
		with usage_scope(self.target_asset):
			return super().get_target_account()


def _fixed_asset_account_of(asset: str, company: str) -> str | None:
	asset_category = frappe.db.get_value("Asset", asset, "asset_category")
	if not asset_category:
		return None
	with asset_usage_context(asset):
		return get_asset_category_account(
			"fixed_asset_account", asset_category=asset_category, company=company
		)
