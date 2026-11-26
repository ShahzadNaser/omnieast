# ISS-2026-00184: Office / Project asset accounts (plan)

Status: **plan, waiting for "confirmed"**. No code has been written.
Target: production `omnieast.k.frappe.cloud`, Frappe 16.61.0 / ERPNext 16.61.0 / HRMS 16.60.0, app `omnieast` only.
All ERPNext references below are to tag **v16.61.0** (local bench is still 16.52.1; see section 9).

Revision 2: Office/Project is now chosen on the Purchase Invoice / Purchase Receipt and passed to the asset (D2, D6); account changes on categories with existing assets are allowed (D13). The transfer entry of revision 1 is no longer needed and has been removed.
Revision 3: per-row Asset Usage on PI / PR with a header default (D2); Asset Capitalization and Asset Repair fully covered (D14); deleting a row in use stays blocked; label and placement confirmed.

---

## 1. Decisions taken (from the Q&A)

| # | Decision |
|---|---|
| D1 | Asset Category > Accounts table holds up to **two rows per company**: one *Office*, one *Project*. Each row has its own Fixed Asset, Accumulated Depreciation and Depreciation Expense account (and CWIP). |
| D2 | The user selects **Office / Project on the Purchase Invoice / Purchase Receipt, per fixed-asset row**, with a header field that fills all rows (like *Set Target Warehouse*). A mixed purchase needs no split. The asset created from a row (automatically or by hand) takes that row's value. Assets without a purchase document (Existing Asset, Composite Asset) are marked by hand. Mandatory on new assets. |
| D3 | Existing assets are **left blank**. Blank means Office (today's accounting), until finance updates them. |
| D4 | Depreciation already posted stays where it is (61262). Only entries posted after go-live follow the type. No correction JEs. |
| D5 | Sale, scrap, restore, Asset Value Adjustment and capitalized Asset Repair also follow the asset's row. |
| D6 | The purchase books the Fixed Asset (or CWIP) account **of the row chosen on the PI / PR**. |
| D7 | A type change on a submitted asset applies to **future entries only**. |
| D8 | Works for any company that has Project rows configured. No company or account names in code. |
| D9 | Project asset with no usable Project row: **block** and write an **Error Log**. |
| D10 | Fixed Asset Register and Asset Depreciations and Balances must show Project depreciation correctly. |
| D11 | One row per company is still allowed (it is the Office row). With two rows: exactly one Office and one Project. |
| D12 | Local bench is upgraded to 16.61 before building, so tests run on production's code. |
| D13 | Accounts on a category row **may be changed even when active assets use it**; entries posted after the change use the new accounts. (ERPNext 16.61 blocks this today; omnieast replaces the block with a warning.) Deleting a row that active assets still use stays **blocked**. |
| D14 | **Asset Capitalization and Asset Repair** follow the type too: the composite (target) asset's row for the capitalized value, each consumed asset's own row for its disposal, the repaired asset's row for a capitalized repair. |
| D15 | **Nothing in the asset flow may break.** Two guarantees: (a) a Desk switch *Accounts Settings > Enable Office / Project Asset Accounts* (off after deploy); while off, every account lookup reads the **Office** row (identical to ERPNext while each company has one row; deterministic once Project rows exist, where ERPNext's own lookup would pick either row), the reports run ERPNext's originals and the new validations do nothing. (b) With the switch on but only Office rows / Office assets, every posting is identical to ERPNext's, proven line by line (section 10A). |

## 2. Facts that shape the design

1. **ERPNext never passes the asset to its account lookup.** `get_depreciation_accounts(asset_category, company)` (`erpnext/assets/doctype/asset/depreciation.py:783`) and `get_asset_category_account(fieldname, item, asset, account, asset_category, company)` (`asset_category/asset_category.py:204`) read **one** Asset Category Account row with `frappe.db.get_value(parent, company_name)`. With two rows per company the row they get is arbitrary.
2. **The names are imported by value.** `asset.py`, `asset_value_adjustment.py`, `purchase_invoice.py`, `asset_capitalization.py` do `from ... import get_depreciation_accounts / get_asset_category_account`, so each module's reference must be replaced, not only the defining module's (same approach as `omnieast/overrides/zatca_overrides.py`).
3. **16.61 blocks a second row per company, and blocks account changes.** `AssetCategory.validate_account_change_for_existing_assets` builds `{company_name: row}` and throws "Cannot change … since it has active assets in this category" when a filled account of a row with active assets changes. With an Office and a Project row it compares the wrong rows and throws on every save. omnieast replaces it (section 6, D13).
4. **Both reports join Asset Category Account on (category, company)** and match the GL account to that row's account. With two rows that share an account every GL line is counted twice; after an account change (D13) or a type change (D7) earlier entries drop out of the report.
5. **Purchase.** Both documents debit the fixed-asset row's `expense_account`: the Purchase Invoice resets it for fixed-asset rows in `set_expense_account` during validate (`purchase_invoice.py:698-751`); the Purchase Receipt takes it from item defaults (`get_item_details`, CWIP or Fixed Asset) and posts it in `purchase_receipt.py:849-850`. omnieast sets it after ERPNext's validate from the chosen type.
6. **Auto-created assets.** Assets are created on Purchase Receipt submit, or Purchase Invoice submit with *Update Stock*, for Items with *Auto Create Assets on Purchase* and an Asset Naming Series (`buying_controller.process_fixed_asset`). They are inserted as **Draft**, depreciation off, with validation and the mandatory check skipped. omnieast's existing `Asset.before_validate` already reads the purchase document on the first save. Local data: 22 assets from 14 PIs with Update Stock, none from PRs, 125 Existing Assets.
7. On an asset bought with a PI *with Update Stock*, `Asset.validate_make_gl_entry` checks whether the PI already booked the asset's Fixed Asset account; that check must use the asset's type, or a Project asset would be booked twice or not at all.
8. **Asset Capitalization** takes the target account from the composite asset's *Item* (`get_target_asset_details` → `target_fixed_asset_account`; CWIP in `get_target_account`), i.e. always the Office row. The target is a **draft** Composite Asset, so its Asset Usage is chosen by hand before capitalization. When the composite asset is submitted, `Asset.check_asset_capitalization_gl_entries` reads the `target_fixed_asset_account` saved on the capitalization, so that field must hold the usage's account. Consumed assets are disposed through `get_gl_entries_on_asset_disposal` → `get_asset_details` (already covered). **Asset Repair** reads the Fixed Asset account only in `get_gl_entries` (`get_asset_account(..., asset=self.asset)`).
9. ERPNext's daily job rolls back the transaction when an asset fails, so the Error Log must be written with `defer_insert=True` to survive.

## 3. Custom fields (shipped as fixtures in `hooks.py` → `fixtures`, Custom Field filter by name)

| Doctype | Fieldname | Type | Options / properties | Placement |
|---|---|---|---|---|
| Purchase Invoice | `custom_asset_usage` | Select | `\nOffice\nProject`; label "Asset Usage"; description "Sets Asset Usage on all fixed-asset rows"; `depends_on`: shown when any row is a fixed asset (client script) | after `supplier` (header) |
| Purchase Invoice Item | `custom_asset_usage` | Select | `\nOffice\nProject`; label "Asset Usage"; `depends_on` and `mandatory_depends_on: eval:doc.is_fixed_asset`; `in_list_view: 1`, `columns: 1` | after `is_fixed_asset` |
| Purchase Receipt | `custom_asset_usage` | Select | same as Purchase Invoice | after `supplier` (header) |
| Purchase Receipt Item | `custom_asset_usage` | Select | same as Purchase Invoice Item | after `is_fixed_asset` |
| Asset | `custom_asset_usage` | Select | `\nOffice\nProject`; label "Asset Usage"; `mandatory_depends_on: eval:doc.docstatus==0` (new and draft assets only, so the ~150 submitted assets stay valid while blank); `allow_on_submit: 1`; `in_standard_filter: 1`; `in_list_view: 1`; `search_index: 1` | Details tab, after `asset_category` |
| Asset Category Account | `custom_asset_usage` | Select | `\nOffice\nProject`; label "Asset Usage"; `in_list_view: 1`; `columns: 1`; blank = Office | after `company_name` |
| Accounts Settings | `custom_enable_asset_usage_accounts` | Check | label "Enable Office / Project Asset Accounts"; default 0; description "Book Project assets to the Project row of their Asset Category" | Assets section, after `book_asset_depreciation_entry_automatically` |

All Asset Usage fields have `no_copy: 0`, so *Duplicate*, *Amend*, Asset Split (`frappe.copy_doc`) and the PO → PR → PI / return mappers carry the value.

Same fieldname on header and rows, so ERPNext's mappers carry it automatically: Purchase Order → Purchase Receipt → Purchase Invoice, and returns / debit notes.

`custom_` prefix so a future ERPNext field can never collide (`asset_type` is already taken by ERPNext). No Property Setters, no new doctypes.

## 4. The central module: `omnieast/assets/depreciation_accounts.py`

All account choice lives here. Nothing else in omnieast decides which row to read.

| Function | Purpose |
|---|---|
| `OFFICE`, `PROJECT` | constants; blank is normalised to `OFFICE` |
| `get_asset_usage(asset) -> str` | asset doc or name → `"Office"` / `"Project"` (blank → Office) |
| `asset_usage_context(asset_or_usage)` | context manager; sets a `contextvars.ContextVar` with the usage for the code inside it |
| `current_usage() -> str` | usage from the context, Office when none is set |
| `get_category_row(asset_category, company, usage) -> dict \| None` | the one Asset Category Account row for (category, company, usage); blank rows count as Office |
| `get_depreciation_accounts(asset_category, company)` | same signature and return as ERPNext's; reads the row for `current_usage()`. Office: identical behaviour to ERPNext (Company default fallback). Project: rules below |
| `get_asset_category_account(fieldname, item=None, asset=None, account=None, asset_category=None, company=None)` | same signature as ERPNext's; resolves category / company exactly like ERPNext, then reads the row for `current_usage()` |
| `get_purchase_account(asset_category, company, usage) -> str` | CWIP account if CWIP accounting is on for the category, else Fixed Asset account, of the usage's row (used by the PI / PR hooks) |
| `throw_project_accounts_missing(asset_category, company, reference=None)` | writes the Error Log (`defer_insert=True`), then `frappe.throw` |

**Selection rules**

1. Usage = the document's `custom_asset_usage`, blank → Office.
2. Office → the Office row (or the only row with blank usage). Behaviour unchanged from ERPNext, including the Company default fallback for Accumulated Depreciation / Depreciation Expense / CWIP.
3. Project → the Project row of that category and company. If there is no Project row, or it lacks Fixed Asset, Accumulated Depreciation or (for a depreciable category) Depreciation Expense, or CWIP when the category uses CWIP: **block + Error Log**. No fallback to the Office row or Company defaults.
4. No context set (any other caller) → Office row, so all standard callers are deterministic.

## 5. Hooks and overrides

### 5.1 Function replacements (`omnieast/assets/patches.py`, imported from `hooks.py` like `zatca_overrides`)

Every wrapper first checks `is_enabled()` (omnieast installed on the site **and** the Accounts Settings switch on, cached per request) and otherwise calls the original unchanged, so other sites on a shared bench, and this site while the switch is off, run pure ERPNext. Mixins and doc_events use the same check.

| Module (ERPNext 16.61) | Name replaced | Replacement | Why |
|---|---|---|---|
| `assets.doctype.asset.depreciation` | `get_depreciation_accounts` | central `get_depreciation_accounts` | used by `get_credit_debit_accounts_for_asset`, `get_asset_details` |
| same | `_make_depreciation_entry` | wrapper: reads the schedule's asset, runs the original inside `asset_usage_context` | the scheduled job (`book_depreciation_entries`), the manual **Make Depreciation Entry** button and depreciation up to the disposal date |
| same | `get_asset_details` | wrapper: original inside `asset_usage_context(asset)` | sale and sales return (Sales Invoice), scrap, consumed assets in Asset Capitalization |
| `assets.doctype.asset.asset` | `get_depreciation_accounts`, `get_asset_category_account` | central functions | `get_manual_depreciation_entries`, `make_journal_entry`, `get_fixed_asset_account`, `get_asset_account` (Asset Repair, CWIP) |
| `assets.doctype.asset_value_adjustment.asset_value_adjustment` | `get_depreciation_accounts` | central function | revaluation JE |
| `assets.doctype.asset_category.asset_category` | `get_asset_category_account` | central function | `get_item_details` imports it at call time |
| `accounts.doctype.purchase_invoice.purchase_invoice` | `get_asset_category_account` | central function | deterministic Office default before the omnieast hook sets the chosen row |
| `assets.doctype.asset_capitalization.asset_capitalization` | `get_asset_category_account` | central function | deterministic target / consumed accounts |
| `assets.report.fixed_asset_register.fixed_asset_register` | `get_asset_depreciation_amount_map`, `get_asset_value_adjustment_map` | omnieast copies (section 7) | D10 |
| `accounts.report.asset_depreciations_and_balances.asset_depreciations_and_balances` | `get_assets_for_grouped_by_category`, `get_asset_value_adjustment_map_by_category`, `get_assets_for_grouped_by_asset`, `get_asset_value_adjustment_map` | omnieast copies (section 7) | D10 |

The scheduler job `post_depreciation_entries` is **not** replaced.

### 5.2 Class extensions (`hooks.py` → `extend_doctype_class`)

| Doctype | Class (file) | Methods |
|---|---|---|
| Asset Category | `omnieast.assets.asset_category.AssetCategoryUsageMixin` (`omnieast/assets/asset_category.py`) | `validate` → `super().validate()` then `validate_usage_rows()`; replaces `validate_account_change_for_existing_assets` with a warning (section 6, D13) |
| Asset | `omnieast.assets.asset.AssetUsageMixin` (`omnieast/assets/asset.py`) | `validate_make_gl_entry`, `make_gl_entries`, `get_manual_depreciation_entries` → `super()` inside `asset_usage_context(self)` |
| Asset Value Adjustment | `omnieast.assets.asset_value_adjustment.AssetValueAdjustmentUsageMixin` | `make_asset_revaluation_entry` → `super()` inside `asset_usage_context(self.asset)` |
| Asset Repair | `omnieast.assets.asset_repair.AssetRepairUsageMixin` | `get_gl_entries` → `super()` inside `asset_usage_context(self.asset)` (capitalized repair: Dr the repaired asset's Fixed Asset account) |
| Asset Capitalization | `omnieast.assets.asset_capitalization.AssetCapitalizationUsageMixin` | `set_missing_values` → `super()`, then `target_fixed_asset_account` = the target asset's row and each consumed-asset row's `fixed_asset_account` = that asset's row; `get_target_account` and `get_gl_entries` → `super()` inside `asset_usage_context(target asset)` (consumed assets switch to their own type inside `get_asset_details`); `validate` → target asset must have Asset Usage and a complete row |

### 5.3 doc_events (added to the existing entries in `hooks.py`)

| Doctype | Event | Function | What it does |
|---|---|---|---|
| Purchase Invoice | `before_validate` (appended) | `omnieast.assets.purchase.fill_row_usage` | blank fixed-asset rows take the header Asset Usage |
| Purchase Invoice | `validate` (appended after `project_mandatory.validate_purchase_invoice`) | `omnieast.assets.purchase.validate_purchase` | every fixed-asset row needs Asset Usage; a row billed against a Purchase Receipt row must have the same usage; for each fixed-asset row whose account is not *Asset Received But Not Billed*, set `expense_account` = `get_purchase_account(row.asset_category, company, row usage)`. Runs after ERPNext's `set_expense_account`, so only fixed-asset rows are touched |
| Purchase Receipt | `before_validate`, `validate` | same two functions | same (no PR-row check) |
| Asset | `before_validate` (existing `omnieast.overrides.asset.before_validate`, extended) | | on a draft linked to a purchase, copy Asset Usage from the purchase **row** (`purchase_invoice_item` / `purchase_receipt_item`), else the purchase header, when the asset's is blank |
| Asset | `validate` (appended after `project_mandatory.validate_asset`) | `omnieast.assets.asset.validate_asset_usage` | draft: Asset Usage required; draft linked to a purchase row: must equal that row's usage (the purchase booked that row's account); Project: the category must have a complete Project row for the company |
| Asset | `on_update_after_submit` | `omnieast.assets.asset.on_usage_change` | Asset Activity "Asset Usage changed from X to Y; entries from now on use the Y accounts"; orange warning if Fixed Asset or Accumulated Depreciation differ between the two rows (balances stay in the old accounts, D7) |

### 5.4 Whitelisted override (`hooks.py` → `override_whitelisted_methods`)

`erpnext.assets.doctype.asset.asset.make_journal_entry` → `omnieast.assets.asset.make_journal_entry`: the original inside `asset_usage_context(asset_name)` (Asset > Create > Depreciation Entry for manual-depreciation assets).

### 5.5 Client scripts (`doctype_js`, appended to the existing lists)

- Purchase Invoice / Purchase Receipt: header *Asset Usage* shown while any row is a fixed asset; changing it sets all fixed-asset rows; a new fixed-asset row takes the header value.
- Asset: *Asset Usage* read only on a draft linked to a purchase row (it comes from the purchase).

## 6. Validations

**Purchase Invoice / Purchase Receipt (on save)**
1. Every fixed-asset row needs Asset Usage (blank rows are first filled from the header).
2. Project row → its category needs a complete Project row for the company (block + Error Log, D9).
3. A Purchase Invoice row billed against a Purchase Receipt row must have the same usage.
4. Returns and debit notes copy Asset Usage from the original rows, so reversals hit the same accounts.

**Asset Capitalization (on save)**
1. The target (composite) asset needs Asset Usage and a complete row for it.
2. Target and consumed assets may have different types: each consumed asset is disposed from its own accounts, the capitalized value is debited to the target's row.

**Asset Category (on save)**
1. Per company: at most one Office row (blank counts as Office) and at most one Project row.
2. A Project row needs an Office row for the same company.
3. Project row: Accumulated Depreciation and Depreciation Expense required unless the category is Non Depreciable; CWIP required when *Enable Capital Work in Progress Accounting* is on. Standard account-type checks already apply (Depreciation Expense must be Account Type *Depreciation*).
4. **Account changes with active assets (D13).** ERPNext's block is replaced: the change is saved, and a warning lists, per company and type, the changed accounts and the number of active assets:
   - Depreciation Expense: later depreciation uses the new account; earlier entries stay in the old one.
   - Fixed Asset / Accumulated Depreciation: the existing cost and accumulated depreciation stay in the old accounts; a later sale, scrap or value adjustment posts the full amounts to the new accounts. The warning tells finance to move the balances with a Journal Entry.
   - The change is recorded in the category's version history (who, when, old and new account).
5. Deleting a row that active assets still use (by company and type) stays **blocked**, because their next depreciation would fail (D9).

Existing duplicate rows (local data: "Laundry Equipments" has two blank OMNI rows) are **not** changed by a patch. Rule 1 stops that category from being saved until one row is removed or marked Project.

**Asset**
1. Draft / new: Asset Usage required. Assets auto-created from PI / PR get it from the purchase on first save.
2. Draft linked to a PI / PR: must match the purchase's Asset Usage.
3. Project: the category must have a complete Project row for the company (user message at save).
4. Submitted: may be changed (D7).

**Posting time (block + Error Log, D9)**
Any posting for a Project asset without a usable Project row raises a clear error and writes an Error Log titled `ISS-2026-00184: Project accounts missing for {category} / {company}`, referencing the document. In the scheduled job ERPNext then marks the asset's Depreciation Entry Posting Status as *Failed* and notifies Accounts Managers as usual; other assets still post.

## 7. Reports (D10)

Both reports find an asset's depreciation and value adjustments by matching the GL account to one category row's account. The omnieast copies match by **Account Type** instead, which is independent of rows, account changes and type changes:

- depreciation: GL lines against the asset on an account with Account Type *Depreciation* (51230 and 61262 both are; Asset Category already enforces it);
- value adjustments: GL lines against the asset on an account with Account Type *Fixed Asset*.

Result: no double counting with two rows, and an asset whose accounts or type changed shows all of its entries. Everything else in the functions stays a line-for-line copy of 16.61, marked `# ISS-2026-00184` where it differs. The omnieast report *Asset Depreciation Schedules Summary* reads schedules, not accounts, and needs no change.

## 8. Patches / migration

- No data patch. Existing assets, purchase documents and category rows stay blank (= Office) by decision D3.
- `bench migrate` syncs the seven custom fields from fixtures. The switch stays off, so deploy alone changes nothing.
- Desk set-up after deploy (finance, per company): make sure **51230 - Depreciation-Project Assets** exists with Root Type *Expense* and Account Type *Depreciation*; on each Asset Category add the Project row; then mark Project assets.

## 9. Local environment before building (Phase 4, step 0)

1. `bench --site omnieast.local backup --with-files`.
2. Record current commits (frappe `e8d41dd006`, erpnext `ade850bbd6`, hrms current) for rollback.
3. Check out frappe v16.61.0, erpnext v16.61.0, hrms v16.60.0; `bench setup requirements`; `bench build`; `bench --site omnieast.local migrate`.
4. Only omnieast.local is migrated. jawacat.local, motoryv16.local and site16.local are on this bench too; they will run 16.61 code with an older schema until migrated, and jawacat / motory compatibility with 16.61 is not checked. A database migration cannot be undone except by restoring the backup.
5. jawacat (installed in this bench, not on production) replaces ERPNext's `post_depreciation_entries` in every bench process. Local tests therefore call ERPNext's `book_depreciation_entries(date)` directly, which jawacat does not touch. jawacat code is not changed.

## 10. Test plan (local, omnieast.local on 16.61)

Test set-up, local only, all names prefixed `ISS184`: in OMNI create `51230 - Depreciation-Project Assets` (Expense, Account Type Depreciation), a Project Fixed Asset account and a Project Accumulated Depreciation account; a fixed-asset Item with *Auto Create Assets* in category `ISS184 Equipment` with an Office row (11101 / 11190 / 61262) and a Project row (new accounts), monthly straight-line, 12 depreciations.

Every step lists the GL entries checked (voucher, account, debit, credit).

| # | Scenario | Expected |
|---|---|---|
| T1 | Category rules: two Office rows; Project row without expense; Project row added to a category with active assets; Office expense changed while assets are active; Project row deleted while a Project asset uses it | error / error / saved / **saved with warning** / blocked |
| T2 | PI with Update Stock, Asset Usage blank | blocked |
| T3 | PI with Update Stock, **Office** | Dr Office Fixed Asset; draft asset created; on first save Asset Usage = Office |
| T4 | PI with Update Stock, **Project** | Dr **Project** Fixed Asset; draft asset gets Project; changing it to Office on the draft is blocked; submit makes no extra GL (no double booking) |
| T5 | PI without Update Stock, Project; asset created by hand and linked | PI Dr Project Fixed Asset; asset takes Project |
| T6 | `book_depreciation_entries(date)` for the T3 and T4 assets | Office: Dr 61262 / Cr 11190. Project: Dr **51230** / Cr Project Accumulated |
| T7 | Manual "Make Depreciation Entry" on the Project schedule | Dr 51230 / Cr Project Accumulated |
| T8 | Asset Value Adjustment (decrease) on the Project asset | Dr 51230 / Cr Project Fixed Asset |
| T9 | Sell the Project asset (Sales Invoice) | depreciation to sale date in 51230; Cr Project Fixed Asset (gross), Dr Project Accumulated, gain/loss to the Company disposal account. Cancel: everything reversed |
| T10 | Scrap the Office asset, then restore | Cr Office Fixed Asset, Dr 11190, loss to disposal account; restore reverses |
| T11 | Capitalized Asset Repair on a Project asset | Dr Project Fixed Asset |
| T12 | Existing asset with blank type | depreciation still Dr 61262 / Cr 11190 |
| T13 | Change an Office asset to Project after submit | warning, Asset Activity, next depreciation Dr 51230; earlier entries untouched |
| T14 | Change the Project row's Depreciation Expense to another Depreciation account while the Project asset is active | saved with warning; next depreciation uses the new account; earlier ones unchanged |
| T15 | Project asset whose Project row is incomplete (DB, test only), run depreciation | entry not posted, Error Log written, posting status Failed, other assets still post |
| T16 | Purchase Receipt (Project) then Purchase Invoice against it | PR Dr Project Fixed Asset (or CWIP) / Cr Asset Received But Not Billed; PI clears Asset Received But Not Billed; PI row usage changed to Office is blocked |
| T18 | One PI with Update Stock, two fixed-asset rows: header Office, second row changed to Project | row 1 Dr Office Fixed Asset, row 2 Dr Project Fixed Asset; each auto-created asset gets its own row's type |
| T19 | Asset Capitalization: draft Composite Asset (Project), consuming one Office asset, one stock item and one service item; submit | Cr Office Fixed Asset / Dr 11190 for the consumed asset (its disposal), stock and service credits as standard, Dr **Project** Fixed Asset for the total; composite asset submitted with no duplicate GL. Cancel reverses |
| T20 | Capitalized Asset Repair on an Office asset (T11 covers Project) | Dr Office Fixed Asset |
| T17 | Fixed Asset Register and Asset Depreciations and Balances for the period | depreciation and value-adjustment figures equal the GL totals of T3–T14; no doubles; the T13 and T14 assets show all their entries |

The scenarios are also written as an automated test, `omnieast/assets/test_depreciation_accounts.py` (`FrappeTestCase`, run with `bench --site omnieast.local run-tests --module omnieast.assets.test_depreciation_accounts`). ERPNext's own asset tests (`test_asset`, `test_asset_value_adjustment`, `test_asset_category`, `test_fixed_asset_register`, purchase invoice / receipt asset cases) are run once with omnieast installed to catch regressions; tests that assert the 16.61 "cannot change accounts" block are expected to fail because of D13 and will be listed. The report back includes the GL lines of T2–T16.

## 10A. Whole asset-management regression (D15)

Run on omnieast.local (16.61), in this order. Each step must pass before the next.

**Step 1: baseline before any omnieast change.** Run ERPNext's asset-related test modules on 16.61 with today's omnieast and save the result (pass / fail per test; anything already failing is a pre-existing failure, e.g. from omnieast's Project mandatory hooks):
`assets/doctype/asset`, `asset_activity`, `asset_capitalization`, `asset_category`, `asset_depreciation_schedule`, `asset_maintenance`, `asset_maintenance_log`, `asset_maintenance_team`, `asset_movement`, `asset_repair`, `asset_shift_allocation`, `asset_shift_factor`, `asset_value_adjustment`, `location`; reports `fixed_asset_register`, `asset_depreciations_and_balances`, `asset_depreciation_ledger`, `asset_maintenance`; `purchase_invoice`, `purchase_receipt`, `sales_invoice`, `journal_entry`, `landed_cost_voucher`, `landed_cost_report`.
(They create `_Test …` records in the local database; the backup from section 9 is taken first.)

**Step 2: same suites, feature installed, switch OFF.** Result must be identical to step 1.

**Step 3: same suites, switch ON, no Project rows.** Result must be identical to step 1, except tests that assert ERPNext's "cannot change accounts with active assets" block (D13), which are listed by name in the report.

**Step 4: GL identity check.** One script runs the whole flow below twice on fresh `ISS184` records, once with the switch off and once on with Office assets only, and compares every GL Entry (account, debit, credit, cost center, project, against voucher). Must be identical.

**Step 5: flow matrix with Project assets** (sections 10 T1–T20, plus the rows below).

| Area | Flow | Touched by this feature? | Checked in |
|---|---|---|---|
| Purchase | PO → PR → PI, PI with Update Stock, PI without (asset by hand), PR return, PI debit note | yes (fixed-asset row account) | T2–T5, T16, T18, step 4 |
| Purchase | Landed Cost Voucher on a fixed-asset PR (asset value updated) | no (posts to Asset Received But Not Billed / expense; asset updated by ERPNext) | step 1–3 suites + one LCV on a Project asset: asset value updated, no change to Fixed Asset account choice |
| Asset | auto-creation (single and grouped), draft save, submit, cancel, amend, duplicate | yes (Asset Usage copied / validated) | T3–T5, T18 |
| Asset | Existing Asset with opening accumulated depreciation | yes (type by hand) | T12 + one new Project Existing Asset |
| Asset | Composite Asset / Composite Component | yes (capitalization) | T19 |
| Asset | Asset Split (from Sales Invoice partial sale and manual) | indirect (copy keeps type) | one split of a Project grouped asset: both assets Project, later depreciation 51230 |
| Depreciation | Straight Line, Written Down Value, Double Declining Balance, Manual; several finance books; shift-based (Asset Shift Allocation) | schedules: no; posting: yes | step 1–3 suites; T6 with two finance books on the Project asset |
| Depreciation | scheduled job, manual button, on sale/scrap, frozen accounts date, JE workflow, posting failure and re-post | yes (`_make_depreciation_entry`) | T6, T7, T15 |
| Disposal | sale, sales return (regain), scrap, restore, partial sale | yes (`get_asset_details`) | T9, T10 |
| Value | Asset Value Adjustment increase / decrease / cancel | yes | T8 |
| Repair | repair with and without capitalization, consumed stock, purchase-invoice costs | yes (capitalized only) | T11, T20 |
| Capitalization | consumed stock / asset / service items, cancel | yes | T19 |
| Not touched | Asset Movement, Location, Asset Maintenance (team, log, schedule), Asset Activity, Asset Shift Factor | no | step 1–3 suites |
| Reports | Fixed Asset Register, Asset Depreciations and Balances | yes (section 7) | T17 |
| Reports | Asset Depreciation Ledger | no (ERPNext already matches Account Type *Depreciation*) | T17 |
| omnieast | Project / Cost Center mandatory on Asset / PI / JE, Asset `before_validate`, GL narration, *Asset Depreciation Schedules Summary* | coexists | every scenario posts with Project and Cost Center; summary report unchanged before / after |
| Switch | turn off after Project entries exist | yes | next depreciation of a Project asset goes to the Office row (ERPNext behaviour); nothing errors |

**Step 6: rollback check.** Uninstall path is not needed; with the switch off, steps 2 and 4 already prove ERPNext behaviour is restored.

The report back lists for each step: tests run, passed, failed (with the baseline comparison) and the GL lines checked.

## 11. Risks, and what to re-check after every ERPNext upgrade

| Risk | Mitigation / check |
|---|---|
| ERPNext renames or changes the signature of `get_depreciation_accounts`, `get_asset_category_account`, `_make_depreciation_entry`, `get_asset_details` | `patches.py` checks at import that each target exists with the expected parameters and writes an Error Log if not (no crash). Re-run section 10 after each upgrade |
| A new ERPNext caller of the account lookup | `git grep -n "get_depreciation_accounts\|get_asset_category_account\|Asset Category Account" erpnext/` and compare with section 5.1 |
| ERPNext changes how the PI / PR choose the fixed-asset account (`set_expense_account`, PR GL) | omnieast hook runs after validate and only touches fixed-asset rows; T2–T5 and T16 catch a change |
| The replaced report functions drift from upstream | diff the four ADB and two FAR functions against the new tag; re-apply the `# ISS-2026-00184` lines |
| AssetCategory / Asset / AVA / Asset Repair method names change | the mixins call `super()`; check each method still exists |
| Account changed on a category with active assets (D13), or asset type changed mid-life (D7), with different Fixed Asset / Accumulated accounts | old balances stay in the old accounts; a later disposal posts full amounts to the new accounts. Warning on save; finance moves balances with a manual JE |
| ERPNext changes Asset Capitalization's target-account logic (`get_target_asset_details`, `get_target_account`, `check_asset_capitalization_gl_entries`) | T19 catches it; re-check the three functions after upgrades |
| Disposal gain/loss account | still the Company's *Gain/Loss Account on Asset Disposal*, not per type (unchanged ERPNext behaviour) |
| Other sites on the same Frappe Cloud bench | every replaced function checks that omnieast is installed on the site |

## 12. Deploy (Frappe Cloud)

1. Branch `iss-2026-00184-asset-usage-accounts` from `version-16`, PR, merge.
2. Frappe Cloud: back up the site, then deploy the bench group with the new omnieast commit (migrate runs and syncs the fixtures).
3. Deploy changes nothing yet (switch off). Desk set-up (section 8), then tick *Accounts Settings > Enable Office / Project Asset Accounts*; run *Fixed Asset Register* to confirm nothing changed for Office assets. If anything looks wrong, untick it: ERPNext's own behaviour returns at once, no redeploy.
4. From then on, purchases of fixed assets need Asset Usage. Finance marks existing Project assets; check the next depreciation run (Journal Entry, Voucher Type *Depreciation Entry*) shows 51230 for them.

## 13. Points confirmed

1. Label "Asset Usage" and placements: confirmed.
2. Per-row choice with a header default (D2).
3. Deleting a category row in use stays blocked (D13).
4. Asset Capitalization and capitalized Asset Repair fully covered (D14).

5. On / off switch in Accounts Settings and the regression in section 10A (D15), added on request "work without breaking the whole asset flow".

Nothing open. Next step: your "confirmed", then Phase 4 starting with section 9.

## 14. Implementation notes (Phase 4, 2026-11-26)

Where the build differs from, or adds to, the plan above:

1. **Module layout** (`omnieast/assets/`): `depreciation_accounts.py` (the only place that chooses accounts), `patches.py` (replaces ERPNext names), `reports.py` (report copies), `asset.py`, `asset_category.py`, `asset_documents.py` (Value Adjustment, Repair, Capitalization mixins), `purchase.py`, `test_depreciation_accounts.py`.
2. **How the patches are applied.** Not from an import in `hooks.py`: Frappe reads hooks from the Redis cache in production, so a worker may never import `hooks.py` (this also affects the existing `zatca_overrides` import, outside this ticket). They are applied by the `before_request` and `before_job` hooks and by `is_enabled()`, which every omnieast entry point calls first. Idempotent.
3. **Switch off** (D15): account lookups read the Office row instead of calling ERPNext's original, so turning the switch off after Project rows exist is a safe way back. Sites without omnieast get ERPNext's originals.
4. **Asset Value Adjustment in 16.61** posts Fixed Asset against a user-chosen *Difference Account* (not the depreciation expense account). The Fixed Asset side follows the asset's row.
5. **Asset Usage on an asset from a purchase** must book to the same account the purchase row debited (compared by account, not label), so a draft from an old purchase with a blank row can be marked Project as long as the Fixed Asset account is the same.
6. Purchase rows: the row field is not in the grid list view (the grid is already full); it is in the row form, and the header fills it.
7. **Pre-existing, not this feature:** on OMNI every Asset Value Adjustment is blocked by omnieast's Journal Entry "Project is mandatory" rule, with the switch off too. ERPNext submits the revaluation JE unsaved, so `overrides/journal_entry.before_validate` (draft only) never fills Project from the asset. Separate ticket recommended.
8. Local environment: frappe / erpnext v16.61.0 and hrms v16.60.0 checked out on branches `prod-v16.61.0` / `prod-v16.60.0`; `Asset.project` custom field added on omnieast.local to mirror production; the 16.61 patch `remove_modules_made_from_generated_sidebars` marked done in the local Patch Log (fails on this copy's old sidebar archive, case-insensitive module name clash). The first ERPNext test probe left `_Test Company` and `_Test Fiscal Year 2043–2050` in the local database.
