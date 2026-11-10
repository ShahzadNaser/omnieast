"""Live leave balance: where it joins Leave Application and Leave Allocation.

The rules and the reading/writing are in omnieast/leave/live_balance.py. The two classes here are added
in front of the standard classes through extend_doctype_class in hooks.py. They only change what happens
for Annual Leave from 2026 on (live.covers); every other leave type, and Annual Leave of earlier years,
goes to the standard code untouched.
"""

from frappe.utils import getdate

from omnieast.leave import live_balance as live
from omnieast.overrides.annual_leave_days import count_annual_leave_days


class LeaveApplicationLiveBalanceMixin:
	def validate_dates_across_allocation(self):
		# next year's balance opens on the spot, and a leave may run across New Year
		if live.covers(self.leave_type, self.from_date):
			live.ensure_years_for(self)
			if live.spans_two_open_years(self):
				return
		super().validate_dates_across_allocation()

	def validate_back_dated_application(self):
		# the standard check locks a year once the next year has carried its balance forward;
		# here the next year's carry-over is recalculated instead (live.after_leave_change)
		if live.covers(self.leave_type, self.to_date):
			return
		super().validate_back_dated_application()

	def validate_balance_leaves(self):
		# the standard part stays: who may apply for this employee, and no leave made of days off only
		super().validate_balance_leaves()
		if self.status in ("Rejected", "Cancelled") or not (self.from_date and self.to_date):
			return
		if live.covers(self.leave_type, self.from_date):
			# this year and the next are one pool of days, and with the HR Settings switch on only the
			# days earned by the start date can be used
			self.total_leave_days = count_annual_leave_days(
				self.employee, self.from_date, self.to_date, self.half_day, self.half_day_date
			)
			live.check_leave(self)

	def show_insufficient_balance_message(self, leave_balance_for_consumption):
		# the standard balance check looks at one year on its own; for these leaves the answer comes
		# from live.check_leave (validate_balance_leaves above)
		if live.covers(self.leave_type, self.from_date):
			return
		super().show_insufficient_balance_message(leave_balance_for_consumption)

	def create_leave_ledger_entry(self, submit=True):
		# one ledger row per calendar year, adding up to total_leave_days
		if live.covers(self.leave_type, self.from_date):
			if not submit:
				live.delete_ledger_entries(self)
			elif self.status == "Approved":
				live.create_ledger_entries(self)
			return
		super().create_leave_ledger_entry(submit)

	def on_submit(self):
		super().on_submit()
		live.after_leave_change(self)

	def on_cancel(self):
		super().on_cancel()
		live.after_leave_change(self)


class LeaveAllocationLiveBalanceMixin:
	def validate_back_dated_allocation(self):
		# a balance added in an earlier year rolls into the next year instead of being refused
		if live.covers(self.leave_type, self.to_date):
			return
		super().validate_back_dated_allocation()

	def on_submit(self):
		if live.covers(self.leave_type, self.from_date) and getdate(self.from_date).year >= live.FIRST_LIVE_YEAR:
			# the year before is still running: its balance rolls over live and is not expired here
			self.create_leave_ledger_entry()
		else:
			super().on_submit()
		live.after_allocation_change(self)

	def on_cancel(self):
		super().on_cancel()
		live.after_allocation_change(self)

	def on_update_after_submit(self):
		super().on_update_after_submit()
		live.after_allocation_change(self)
