# Phase 1 — capabilities and field visibility

Verified 1 October 2026. Existing role slugs are `general_worker`, `farm_supervisor`, `farm_manager`, `director`, `stake_holder`, `admin`. A superuser has administrator access. No existing user's roles were changed. This document distinguishes the source's broad permissions from the selected mobile policy; implementation must centralize the affected rules before enabling commands.

## What the backend currently enforces

Source: `accounts/models.py`, `accounts/views.py`, `finance/permissions.py`, `poultry/views.py`, `finance/views.py` and `finance/serializers.py`.

| Source group | Worker | Supervisor | Manager | Director | Stakeholder | Admin |
|---|---:|---:|---:|---:|---:|---:|
| AUTH poultry reads and ordinary writes | Yes | Yes | Yes | Yes | Yes | Yes |
| FR finance read | No | Yes | Yes | Yes | Yes | Yes |
| FW finance ordinary write | No | Yes | Yes | Yes | No | Yes |
| FM generation/recalculation/from-expense/impair/dispose | No | No | Yes | Yes | No | Yes |
| FC close/reopen | No | No | Yes | Yes | No | Yes |
| OWNER identities/contributions/designations/action audit/source use | No | No | No | Yes | No | Yes |
| ADMIN account create/edit/reset/audit | No | No | No | No | No | Yes |

Important current gaps:

1. AUTH is not a business capability. It currently permits worker/stakeholder sale, input-cost and flock-approval writes; AUTH read routes also expose prices/costs and sell-by economics. No batch assignment model exists.
2. FinancePermission gives all FR roles access to salary fields through employee/payroll serializers. Labour approval, payroll payment/reversal and salary-adjustment creation currently fall into ordinary FW, rather than a distinct sensitive action rule.
3. EmployeeProfileSerializer accepts login creation, `user_id`, `role_slugs` and linked-account identity changes for FW users. Activate/deactivate changes linked User status. This can bypass administrator-only account management and the last-admin guard.
4. Generic accounting-period update can change status outside close/reopen; generic CRUD remains on payroll, lots, asset usage and other registers. Mobile must not expose those routes as arbitrary queued edits.
5. User/role changes are not device revocations today. JWT tokens have no device session. Last-login updates are disabled. The last-admin check lacks a lock for concurrent demotions and is not enforced by all admin/employee writers.

These are source findings, not new grants or changes. Phase 2 fixes the paths needed by its published set and device authentication; later affected features remain capability-disabled until their precise authorization and service gates are implemented.

## Selected mobile policy

`C` = cached read; `Q` = permitted offline capture, pending server validation; `O` = foreground online action; `—` = unavailable. Every cell still requires an active account, owned/non-revoked device, current server capability and allowed object. A user with multiple roles receives the union of explicit positive capabilities, with the owner/payroll visibility constraints intact.

| Capability | Worker | Supervisor | Manager | Director | Stakeholder | Admin | Phase |
|---|---|---|---|---|---|---|---|
| `poultry.read` operational batches/health/feed/flock | C | C | C | C | C | C | 2–5 |
| `poultry.capture` mortality/feed/treatment/weight | Q | Q | Q | Q | — | Q | 2, 5 |
| `poultry.manage_batch` book/delivery | — | Q | Q | Q | — | Q | 5 |
| `poultry.correct` flock correction/metric recalculation | — | O | O | O | — | O | 5 |
| `sales.capture` sale and incremental selling costs | — | Q | Q | Q | — | Q | 6 |
| `cash.capture` customer receipts, permitted supplier payments/non-owner funds | — | Q | Q | Q | — | Q | 6 |
| `finance.read` non-owner financial detail | — | C | C | C | C | C | 6–8 |
| `finance.capture` payable/expense/batch cost | — | Q | Q | Q | — | Q | 6 |
| `finance.post` ordinary expense/cash intent after service gates | — | Q | Q | Q | — | Q | 6 |
| `inventory.read` operational item/lot/quantity projection | C | C | C | C | C | C | 6 |
| `inventory.capture` receipt/issue/return/etc. | — | Q | Q | Q | — | Q | 6 |
| `people.read` non-salary work directory | — | C | C | C | — | C | 7 |
| `people.capture_work` own work log/evidence | Q* | Q | Q | Q | — | Q | 7 |
| `people.manage_profile` employee identity/employment fields only | — | O | O | O | — | O | 7 |
| `payroll.read_sensitive` individual salary/history/payments | — | — | C | C | — | C | 7 |
| `payroll.adjust_salary` existing period-effective salary change | — | — | O | O | — | O | 7 |
| `payroll.generate_approve` generation/controlled approval | — | — | O | O | — | O | 7 |
| `payroll.pay` advance/salary/deduction payment | — | — | O | O | — | O | 7 |
| `labour.capture` draft worker/task/amount evidence | — | Q | Q | Q | — | Q | 7 |
| `labour.approve_post_pay` approval/post/payment | — | — | O | O | — | O | 7 |
| `finance.reverse` non-owner receipt/expense/payment/labour reversal | — | — | O | O | — | O | 6–7 |
| `owner.read_write` identities/capital/designations/protected funding | — | — | — | Q/O** | — | Q/O** | 6 |
| `asset.capture` operational usage/maintenance evidence | Q* | Q | Q | Q | — | Q | 7 |
| `asset.financial` acquisition/depreciation/impairment/disposal/reserves | — | — | O | O | — | O | 7 |
| `reports.read` dated server reports | — | C | C | C | C | C | 8 |
| `period.close_reopen` formal accounting lock/version | — | — | O | O | — | O | 8 |
| `users.manage` roles/link/reset/activation/audit | — | — | — | — | — | O | 8 |
| `devices.manage_all` list/revoke other users' devices | — | — | — | — | — | O | 2, 8 |
| `devices.manage_self` register/list/revoke own installation | O | O | O | O | O | O | 2 |

`*` Worker own-work access needs an explicit User↔Employee link and minimal operational asset projection. If missing, capability is false; never infer ownership from names. There is no self-service worker salary download in v1. `**` Owner receipt evidence may be queued after Phase 6 gates; owner master changes, designations, reversals and approvals are online. Rows marked Q do not grant the phone authority to post or spend confirmed cash.

The sensitive restrictions are deliberate mobile defaults. Implementing them requires shared checks on corresponding REST paths so a mobile token cannot bypass a disabled command by calling generic REST. Return `available=false` with a reason when the backend prerequisite is missing. Existing stakeholder finance read-only access and administrator account controls remain explicit. Do not run a migration that grants these roles to real accounts.

## Field projection policy

Use positive serializer allowlists per entity/capability, not filtering keys after a full serializer has exposed data. No bootstrap/pull/receipt/current-version response includes a restricted field.

| Projection | Allowed | Excluded |
|---|---|---|
| Phase 2 `poultry.batch` | UUID, revision, server ID text, reference, bird type/strain/source, status, booking/estimated-arrival dates, entry/maturity/delivery instants, expected/actual/initial birds, approved adjustment count, sold bird count, total mortality, remaining birds, summary cutoff, closed timestamp | Target sale price, forecast cost/margin, salary/allocation amounts, owner IDs/funding, nested full users, profitability finalization audit |
| Phase 2 `poultry.mortality` | UUID/revision/server ID, batch UUID, event timestamp, quantity, derived age, cause/description/action, reporter label, created/updated timestamps | User email, roles, tokens, nested account; actor audit UUID only in an authorized management audit projection |
| Phase 2 `poultry.feed_usage` | UUID/revision/server ID, batch UUID, dates/age, feed type/source, integer quantity/unit, derived decimal kg, dated bird count, calculation version/time, notes/reporter | Unit prices/purchase cost, supplier/owner funding, unauthorized nested account |
| Operational inventory (6) | SKU/item/category/unit, usable quantity/location/expiry, permitted stock movement identifiers | Costs, invoices and supplier money unless finance.read; owner source identity never implied by stock visibility |
| Work directory (7) | Employee UUID/number/display name, job/task fields where needed | Salary, deductions, percentages, account credentials/roles/email unless separately authorized |
| Payroll (7) | Explicit salary/history/payment projection only with payroll.read_sensitive; financial fields decimal strings | Worker/supervisor/stakeholder packs omit individual payroll entirely; aggregate P&L may include total payroll cost |
| Owner (6–8) | Private projection only for OWNER | Owner identity/source balances/receipt details omitted for all other roles, including report drill-downs/errors |
| Users/admin (8) | Minimal own identity for login; user list/audit only ADMIN online | No password hash, raw reset password, refresh token or global user directory in replicated farm entities |

There is no invented tenant or assigned-batch ACL. Initial operational visibility covers the farm's permitted batch data. Download-pack selection narrows caching, not server authorization. Actor labels in submitted evidence are display text; the authenticated UUID remains the audit actor.

## Scope and action enforcement contract

Capabilities carry a deterministic `scope_revision` hash over deployment policy version, active user state, sorted effective roles/capabilities, field-projection versions and supported entity/command set. On each request the server recomputes/validates it; role/M2M changes cannot leave a cursor usable. Device revocation is checked even on replay, refresh and direct REST access. Deleted/deactivated users fail server authentication without erasing unknown-outcome device work.

Phase 2 needs role tests on both mortality REST and sync, cross-device ownership tests, worker payload field checks, stakeholder mutation rejection and object reference validation. Later phases add every sensitive action and generic bypass test. Proposals requiring approval are stored as evidence without approving themselves. Online approvals require fresh foreground confirmation plus durable operation recovery; they do not auto-run on reconnect.
