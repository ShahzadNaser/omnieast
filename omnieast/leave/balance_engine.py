"""Leave balance arithmetic for the live leave flow. Nothing here touches the database, so it can be
tested on its own.

One employee and one leave type are described as a list of calendar years. Each year carries the days
allocated to it, the carry-over stored for it and the leaves booked in it. From that this module works out:

  - what each year's carry-over should be when the previous year's closing balance rolls into it,
  - whether a new leave leaves a shortage on its own start date or on any leave already booked later,
  - how many days can be taken from a given start date.

"Later" matters because the years are one pool of days: a leave booked for next February is paid from
this year's closing balance, so another leave this December eats into it.
"""

from datetime import date

# An allocation this large means the leave days are not tracked for the person (365 days a year)
UNLIMITED_DAYS = 360.0
EPS = 1e-6


class Year(object):
	"""One calendar year of one employee's leave type.

	base       days allocated for the year itself (carry-over not included)
	carry      carry-over stored for the year
	live       the carry-over is the previous year's closing balance, recalculated on every change
	rate_days  days earned per year for the "earned so far" rule; 0 switches the rule off for the year
	leaves     list of (start date, days, key) for every leave booked in the year
	"""

	__slots__ = ("year", "base", "carry", "live", "rate_days", "leaves")

	def __init__(self, year, base=0.0, carry=0.0, live=False, rate_days=0.0, leaves=None):
		self.year = int(year)
		self.base = float(base or 0)
		self.carry = float(carry or 0)
		self.live = bool(live)
		self.rate_days = float(rate_days or 0)
		self.leaves = list(leaves or [])

	@property
	def unlimited(self):
		return self.base >= UNLIMITED_DAYS

	def taken(self, upto=None):
		return sum(days for (start, days, _key) in self.leaves if upto is None or start <= upto)

	def copy(self):
		return Year(self.year, self.base, self.carry, self.live, self.rate_days, self.leaves)


def project(years, max_carry=0.0):
	"""{year: (carry-over, closing balance)}. A live year's carry-over is the closing balance of the year
	before it (limited to max_carry when the leave type sets one); other years keep what is stored."""
	out = {}
	previous = None
	for y in sorted(years, key=lambda r: r.year):
		carry = y.carry
		if y.live and previous is not None and previous.year == y.year - 1:
			carry = out[previous.year][1]
			if max_carry and carry > max_carry:
				carry = float(max_carry)
		out[y.year] = (carry, carry + y.base - y.taken())
		previous = y
	return out


def unearned(y, on_date):
	"""Days of the year's own allocation that are not earned yet on a date."""
	if y.rate_days <= 0 or y.unlimited or y.base <= 0:
		return 0.0
	rate = min(y.rate_days, y.base)
	remaining = (date(y.year, 12, 31) - on_date).days + 1
	return max(0.0, min(y.base, rate * remaining / 365.0))


def _points(years, earned_only, max_carry, from_date):
	"""Every date on which the balance is tested, from from_date on: the start of each leave and the end of
	each year. Yields (date, balance right after that date's leave, kind, key); kind is "leave" or "year"."""
	carried = project(years, max_carry)
	for y in sorted(years, key=lambda r: r.year):
		if y.year < from_date.year:
			continue
		carry, closing = carried[y.year]
		for (start, _days, key) in sorted(y.leaves, key=lambda r: r[0]):
			if start < from_date:
				continue
			balance = carry + y.base - y.taken(upto=start)
			if earned_only:
				balance -= unearned(y, start)
			yield (start, balance, "leave", key)
		yield (date(y.year, 12, 31), closing, "year", None)


def _limit(kind, earned_only):
	# Earned days are a fraction of a day; they count to the nearest whole day, like "Leave Balance as of Today"
	return -0.5 if (earned_only and kind == "leave") else -EPS


def check_new_leave(years, segments, earned_only=False, max_carry=0.0, key="new"):
	"""Test a leave that is not booked yet. segments is [(start date, days)], one per calendar year it covers.

	Returns None when the leave fits, else a dict about the first date left short:
	  date     the date that ends up short
	  short    days missing there
	  own      True when that date is the new leave itself, False when it is a leave already booked later
	             (or a year end)
	  kind     "leave" or "year"
	A date that was already short before and is not made worse by this leave does not block it.
	"""
	if not segments:
		return None
	first = min(start for (start, _days) in segments)
	by_year = dict((y.year, y) for y in years)
	if any(start.year not in by_year for (start, _days) in segments):
		return {"date": first, "short": sum(d for (_s, d) in segments), "own": True, "kind": "leave"}

	after = [y.copy() for y in years]
	after_by_year = dict((y.year, y) for y in after)
	for (start, days) in segments:
		after_by_year[start.year].leaves.append((start, days, key))

	before = dict(((d, kind, k), bal) for (d, bal, kind, k) in _points(years, earned_only, max_carry, first))
	for (d, bal, kind, k) in sorted(_points(after, earned_only, max_carry, first), key=lambda r: r[0]):
		if bal >= _limit(kind, earned_only):
			continue
		was = before.get((d, kind, k))
		if was is not None and bal >= was - EPS:
			continue  # already short and not touched by this leave
		return {"date": d, "short": -bal, "own": k == key, "kind": kind}
	return None


def available(years, on_date, earned_only=False, max_carry=0.0):
	"""Days that can still be taken by a leave starting on on_date: the lowest balance on that date, on every
	leave booked after it, and at each year end while the years stay linked by a live carry-over.
	None when the year has no allocation."""
	by_year = dict((y.year, y) for y in years)
	y = by_year.get(on_date.year)
	if y is None:
		return None
	carried = project(years, max_carry)
	carry, closing = carried[y.year]

	own = carry + y.base - y.taken(upto=on_date)
	if earned_only:
		own = whole_days(own - unearned(y, on_date))
	lowest = [own, closing]
	for (start, _days, _key) in y.leaves:
		if start > on_date:
			lowest.append(_at(y, carry, start, earned_only))

	nxt = y.year + 1
	while nxt in by_year and by_year[nxt].live:
		ny = by_year[nxt]
		ncarry, nclosing = carried[nxt]
		lowest.append(nclosing)
		for (start, _days, _key) in ny.leaves:
			lowest.append(_at(ny, ncarry, start, earned_only))
		nxt += 1
	return min(lowest)


def _at(y, carry, start, earned_only):
	balance = carry + y.base - y.taken(upto=start)
	if earned_only:
		balance = whole_days(balance - unearned(y, start))
	return balance


def whole_days(value):
	"""Nearest whole day, halves up."""
	import math
	return float(math.floor(value + 0.5))
