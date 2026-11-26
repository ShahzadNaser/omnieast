# Account Restriction (plan, simple approach)

Status: **confirmed ("simple approach, go ahead"), being built.**
Target: Frappe / ERPNext v16.61.0, app `omnieast` only. Replaces the 7 temporary Server Scripts
"Hide Salaries & Benefits - <DocType>" (Account, GL Entry, Journal Entry, Payment Entry, Purchase Invoice,
Cash Payment Voucher, Payment Request).

## What it does

A rule in Desk (**Account Restriction**) names accounts and roles. Every user who has one of the roles:

- does not see those accounts (and, with *Include Child Accounts*, everything under them) in the Account
  list, the Chart of Accounts tree or any account search;
- does not see any document of the covered doctypes that posts to one of them: not in lists, counts,
  Report Builder, exports, link searches, and not when opening it by URL, API or print;
- in GL Entry, does not see any line of a voucher that touches a hidden account (so the bank / payable
  side of a salary entry is hidden too).

Removing the role lifts the restriction. Administrator is never restricted.

**Reports are not filtered by code.** Financial reports read the ledger directly and ignore permissions,
so the restricted role is given no access to them in Desk (*Role Permission for Page and Report*, or a
Role Profile). If a restricted user needs General Ledger, a filter can be added to omnieast's existing
General Ledger override later.

## Covered doctypes (one list in `hooks.py`)

Account, GL Entry, Journal Entry, Payment Entry, Purchase Invoice, Cash Payment Voucher, Payment Request.
Account fields are read from each doctype's meta, on the main form and in its tables (custom fields
included: Payment Request `pay_for`, `party_account`, Payment Request Item `account`, Cash Payment Voucher
Account `ledger_account`). Adding a doctype later is one line in the list.

## Files

| File | Content |
|---|---|
| `omnieast/omnieast/doctype/account_restriction/` | doctype: Title, Enabled, Include Child Accounts, Accounts (Table MultiSelect), Roles (Table MultiSelect), Description; validation; clears the cache on save / delete |
| `omnieast/omnieast/doctype/account_restriction_account/`, `account_restriction_role/` | the two multi-select tables |
| `omnieast/permissions/account_restriction.py` | rules (cached in `frappe.client_cache`), hidden accounts per user, the two hooks |
| `omnieast/permissions/test_account_restriction.py` | tests |
| `hooks.py` | the doctype list → `permission_query_conditions` and `has_permission`; Account events clear the cache |

## Rules and checks

- A rule needs at least one account and one role; Administrator, System Manager, Guest and All cannot be
  restricted.
- Account Restriction: read / write for System Manager and Accounts Manager only.
- Cache cleared when a rule is saved or deleted and when an Account is added, moved, renamed or deleted
  (a sub-account added under 61100 later is hidden at once).
- `has_permission` returns `True` when allowed (Frappe treats `None` as a denial).
- Users without a restricted role: one cached lookup, no SQL added.

## Known limits (accepted)

- Reports and dashboard charts: controlled by report access in Desk.
- A document someone deliberately shares with the user stays visible to that user (Frappe rule).
- Doctypes outside the list (e.g. Expense Claim, Sales Invoice) are not filtered until added.

## Tests (local)

Test role with a rule on 61100 OMNI + SSC (with children), a test user with that role, a control user
without it: Account list and tree, account search, Journal Entry / Payment Entry / Purchase Invoice /
Cash Payment Voucher / Payment Request / GL Entry lists and counts, opening a salary JE (has_permission),
list export path, cache clear on a new sub-account, removing the role, disabling the rule.

## Rollout on Frappe Cloud

1. Deploy (migrate creates the doctypes; no rule, nothing changes).
2. Role, e.g. *Restricted - Salaries & Benefits*; rule "Salaries & Benefits" with 61100 OMNI and 61100
   SSC, Include Child Accounts, that role.
3. Assign the role to basheer.c@omni-fm.com; remove his access to the financial reports.
4. Check by impersonating him; then disable the 7 Server Scripts and check again.
