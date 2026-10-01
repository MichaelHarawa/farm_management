# Phase 1 — command registry, schemas and dependencies

Protocol 1, payload version 1; finalized 1 October 2026. The initial registry has **one implementation candidate**, `poultry.mortality.record`, to be enabled only after Phase 2 checks pass. No command is enabled by this document. Later names are reserved and their payload field sets below define the intended contracts; their phase must add strict executable schemas, domain validators and writer coverage before capabilities advertise them. Inherited missing services are explicitly gated.

## Registry boundary

Backend location in Phase 2: `backend/apps/mobile_sync/commands/registry.py`. Each explicit registration supplies `(entity_type, action, payload_version)`, strict schema, capability, mode, reference resolver, domain handler, affected entities and result serializer. `poultry.mortality` + `record` is the name `poultry.mortality.record`. There is no arbitrary model name/serializer/save operation. Unknown or disabled names return `command_unavailable` with no domain effect.

The executable initial request contract is [push-v1.schema.json](contracts/push-v1.schema.json), with a valid [mortality example](contracts/mortality-record.example.json). JSONSchema validates shape; enable actual calendar/format validation explicitly (a nominal `format` keyword alone may not validate dates). UTC instants include seconds and optional 1–6 fractional digits. The server independently validates UUID ownership, dates, reference visibility, quantity limits and accounting locks. `base_version=null` is required for append commands. Later edit actions require the current entity revision and do not use last-write-wins.

The canonical hash is SHA-256 over UTF-8 JSON with lexically sorted object keys and no insignificant whitespace, after strict typed normalization. Include `deployment_id`, authenticated actor UUID, original device UUID and the **whole immutable operation**, including operation/entity IDs, type/action, payload/base versions, captured_at, dependency IDs, optional supersedes ID and payload. UTC instants normalize to `Z`; UUIDs to lowercase; money to canonical 2-decimal strings; quantity scales follow their schema. Normalize dependencies as a unique sorted set; preserve business list order such as funding splits because cent remainder rules can depend on order. Reject unknown fields, NaN/Infinity, excessive scale and number-valued money. Never hash only amount/source or generate a new key after a timeout.

Deduplication unique key: `(deployment_id, actor_id, operation_id)`; original device binding must match. Entity UUID is unique across registered entity types within a deployment. Receipt lookup/replay rechecks current user/device/scope before returning a result. Rejection receipt and supersession remain available to the original actor; cross-device recovery is a separate audited workflow, not transparent ownership reassignment.

## Exact initial mortality payload

| Field | Contract | Server mapping |
|---|---|---|
| `batch_uuid` | Required UUID, existing or dependency-resolved Batch | Resolve registered mapping and current poultry visibility |
| `mortality_date` | Required UTC RFC3339 instant (`Z`) | Existing Mortality.mortality_date; farm date is derived in Africa/Blantyre |
| `quantity_dead` | Required integer 1–2,147,483,647 | Positive quantity plus actual flock limit under lock |
| `suspected_cause` | Required nonblank text <=200 | Existing source field |
| `description` | Required nonblank text <=4,000 | Existing source TextField, explicit transport cap |
| `action_taken` | Required nonblank text <=4,000 | Existing source TextField, explicit transport cap |
| `reported_by_name` | Required nonblank text <=200 | Source's observed reporter, separate from authenticated audit actor |

Adapter supplies `created_by` from authentication and `age_in_days = event farm date - batch arrival farm date`; reject an event before confirmed arrival or an unjustified future instant (initial clock-skew tolerance 5 minutes). Never accept caller-supplied age, Batch PK, created_by, status, journal or calculated balance. Preserve `captured_at` separately in the receipt even when the event was captured late.

After acquiring the stream lock, lock owned device/session, user/role policy and the batch/domain rows in consistent order; validate production/finalized status, applicable period lock if one exists and all affected dated flock balances. A missing accounting period alone does not create a period or financial event for mortality. A closed/finalized date goes to `period_locked`/review. No mortality journal is created. Invoke `create_mortality_with_lifecycle` inside the enclosing transaction; publish Mortality, changed FeedUsage populations and refreshed Batch operational aggregate/membership with the accepted receipt. Remove the current negative-balance clamping as an acceptance shortcut by validating before mutation.

## Later payload field sets and modes

Notation: `UUID`, `Date` (YYYY-MM-DD), `Instant` (UTC Z), `Money` (2-decimal string), `Qty` (declared decimal-string scale), `Int`, `Text`, `Enum` refer to strict source-compatible types; `?` means optional. Fields not listed are rejected. Each candidate remains disabled until its listed phase validates its executable schema and source service gaps. Array row types are defined after the table. The table specifies mobile input, not unrestricted Django serializer fields.

| Command | Payload field set | Mode / capability / phase |
|---|---|---|
| `poultry.batch.book` | bird_type Enum, broiler_strain Enum, source Enum, source_other? Text, booking_date Date, estimated_chick_arrival_date Date, supplier_name? Text, booking_reference? Text, expected_quantity Int, entry_date Instant, expected_maturity_date Instant | Q / manage_batch / 5; server reference/status only |
| `poultry.batch.mark_delivered` | batch_uuid UUID | Q / manage_batch / 5; envelope expected revision |
| `poultry.batch.confirm_delivery` | batch_uuid UUID, entry_date Instant, expected_maturity_date? Instant, quantity Int | Q / manage_batch / 5; composite arrival/status |
| `poultry.feed.record` | batch_uuid UUID, feeding_start_date Instant, feeding_end_date Instant, feed_type Enum, feed_source Enum, quantity_given Int, unit_of_measurement Enum, notes Text, reported_by_name Text, stock_issue? StockIssue | Q / capture; stock block also inventory.capture / 5–6; derive initial age/population |
| `poultry.treatment.record` | batch_uuid UUID, vaccination_date Instant, drug_category Enum, drug_vaccination_type Enum, other_drug_vaccination? Text, quantity Int, description Text, timely_status Text, reported_by_name Text, stock_issue? StockIssue | Q / capture; stock capability too / 5–6; timely_status is source text, not an invented enum |
| `poultry.weight.record` | batch_uuid UUID, sampled_at Instant, average_weight_g Int, sample_size Int, notes? Text, reported_by_name Text | Q / capture / 5; derive age |
| `poultry.flock.adjust` | batch_uuid UUID, effective_at Instant, quantity_change Int signed/nonzero, reason Text | O / correct / 5; offline evidence does not auto-approve |
| `poultry.feed.recalculate` | batch_uuid UUID, reason Text | O / correct / 5 |
| `poultry.batch.set_forecast` | batch_uuid UUID, target_selling_price? Money/null, forecast_mortality_rate_percent? Qty/null, estimated_remaining_feed_cost? Money/null, estimated_remaining_other_cost? Money/null | O / finance write + expected revision / 8 |
| `poultry.sale.record` | batch_uuid UUID, sale_date Instant, product_type Enum, quantity_sold Int, unit_price Money, buyer_name Text, buyer_type Enum, buyer_type_other? Text, sold_by_name Text, receivable_follow_up_name? Text, due_date? Date, notes? Text, selling_costs SellingCost[], initial_receipt? InitialReceipt | Q / sales.capture / 6; linked source/costs/receipt in one transaction |
| `finance.sale_receipt.record` | sale_uuid UUID, amount Money, payment_date Instant, payment_method Enum, external_reference? Text, received_by_name? Text, notes? Text | Q / cash.capture / 6; SalePayment uses a timestamp, not an inferred sale month |
| `finance.sale_receipt.reverse` | payment_uuid UUID, reason Text | O / finance.reverse / 6 |
| `finance.expenditure.create` | expenditure_date Date, category_uuid UUID, description Text, amount Money, payee? Text, external_reference? Text, accounting_nature Enum, cost_allocations CostShare[], funding_allocations? FundingSplit[], payment_date? Date, allow_unpaid? boolean | Q / finance.capture/post / 6; draft+post composite only when requested and validated |
| `finance.expenditure.update` | expenditure_uuid UUID, description? Text, payee? Text, external_reference? Text, amount? Money, category_uuid? UUID, expenditure_date? Date, cost_allocations? CostShare[] | Q / finance.capture / 6; draft only, expected revision; unknown submission frozen |
| `finance.expenditure.post` | expenditure_uuid UUID, funding_allocations? FundingSplit[], cost_allocations? CostShare[], payment_date? Date, allow_unpaid boolean | Q / finance.post / 6 |
| `finance.expenditure.pay` | expenditure_uuid UUID, payment_date Date, funding_allocations FundingSplit[] | Q / cash.capture / 6; one dated payment group |
| `finance.expenditure.reverse` | expenditure_uuid UUID, reason Text | O / finance.reverse / 6 |
| `finance.batch_cost.record` | batch_uuid UUID, purchase_date Instant, item Text, category_uuid UUID, quantity Int, unit Int, unit_measurement Text, unit_cost Money, notes? Text, funding_allocations? FundingSplit[], payment_date? Date, allow_unpaid? boolean | Q / finance.capture/post / 6; map category UUID to service category_id; derive source payment_status from explicit intent; reuse expenditure once |
| `finance.funding_receipt.record` | funding_source_uuid UUID, receipt_date Instant, amount Money, reference? Text, notes? Text | Q / cash.capture / 6; non-owner/non-batch sources only |
| `finance.funding_receipt.reverse` | receipt_uuid UUID, reason Text | O / finance.reverse; OWNER additionally for owner receipt / 6 |
| `finance.owner_contribution.record` | owner_uuid UUID, funding_source_uuid UUID, receipt_date Instant, amount Money, reference? Text, notes? Text, designations? Designation[] | Q / owner.read_write / 6; one cash receipt; explicit owner source |
| `finance.owner_designation.add` | receipt_uuid UUID, designations Designation[] | O / owner.read_write / 6 |
| `finance.owner_designation.reverse` | designation_uuid UUID, reason Text | O / owner.read_write / 6 |
| `inventory.receipt.record` | item_uuid UUID, location_uuid UUID, purchase_date Date, quantity Qty, total_purchase_cost Money, supplier? Text, invoice_reference? Text, expiry_date? Date, batch_reference? Text, payable_uuid? UUID | Q / inventory.capture + finance.post / 6; missing payable/composite behavior must be completed |
| `inventory.issue.record` | lot_uuid UUID, accounting_period_uuid UUID, usage_date Date, usage_scope Enum, batch_uuid? UUID, quantity_used Qty, task_or_purpose Text | Q / inventory.capture / 6; backend cost computed, one movement |
| `inventory.return.record`, `inventory.transfer.record`, `inventory.waste.record`, `inventory.expiry.record`, `inventory.adjustment.record` | Separate registered schemas: lot_uuid UUID, movement_date Date, quantity Qty, reason Text; transfer adds from_location_uuid/to_location_uuid; return references original_issue_uuid; adjustment quantity signed and expected revision | Q capture; adjustment/expiry posting O / appropriate inventory capability / 6; **handlers missing**, never generic enum switch without explicit rules |
| `people.employee.update` | employee_uuid UUID, first_name? Text, last_name? Text, job_title? Text, department? Text, employment_start_date? Date, employment_end_date? Date/null, is_active? boolean | O / manage_profile / 7; no linked User/roles/account status or salary update |
| `people.work_log.record` | employee_uuid UUID, batch_uuid UUID, work_date Date, hours_worked Qty, task Text, notes? Text | Q / capture_work / 7; worker bound to own linked employee |
| `people.labour.draft` | worker_name Text, work_date Date, task_description Text, batch_uuid? UUID, accounting_period_uuid UUID, cost_scope Enum, payment_amount Money, linked_employee_uuid? UUID, hours_worked? Qty | Q / labour.capture / 7; no client paid/approved status |
| `people.labour.approve/post/pay/reverse` | Separate schemas: labour_uuid UUID; approve/post require reason? Text; pay adds payment_date Date + FundingSplit[]; reverse requires reason Text | O / labour.approve_post_pay or finance.reverse / 7 |
| `payroll.salary_adjustment.record` | employee_uuid UUID, effective_period_uuid UUID, new_salary Money, reason Text | O / adjust_salary / 7; existing period-effective history |
| `payroll.generate` | accounting_period_uuid UUID | O / generate_approve / 7 |
| `payroll.allocate` | payroll_entry_uuid UUID, cost_allocations CostShare[] | O / generate_approve / 7 |
| `payroll.payment.record` | payroll_entry_uuid UUID, amount Money, payment_date Date, payment_method Text, payment_kind Enum(advance,salary), funding_allocations FundingSplit[], external_reference? Text | O / payroll.pay / 7; no second wage expense |
| `payroll.payment.reverse` | payment_uuid UUID, reason Text | O / payroll.pay + finance.reverse / 7 |
| `asset.usage.record` | asset_uuid UUID, usage_date Date, accounting_period_uuid UUID, usage_unit Enum, quantity Qty, batch_uuid? UUID, notes? Text | Q / asset.capture / 7 |
| `asset.maintenance.record` | asset_uuid UUID, maintenance_date Date, description Text, accounting_period_uuid? UUID, next_due_date? Date, linked_expense_uuid? UUID, notes? Text | Q evidence / asset.capture / 7; monetary addition is separate online linked cost, not arbitrary duplicate expense |
| `asset.impair/dispose/transfer` | Separate O schemas: asset_uuid UUID, reason Text; impair adds event_date Date/amount Money; dispose adds disposal_date Date/proceeds Money; transfer adds event_date Date/location Text/custodian Text | O / asset.financial (transfer precise capability) / 7; financial handlers/journals gated |
| `period.close/reopen/recalculate/generate_depreciation/allocate_depreciation` | Separate O schemas: period_uuid UUID; reopen requires reason Text; close may include versioned reviewed checklist token | O / close_reopen or appropriate management action / 8 |

Other online masters/actions (employee creation, asset acquisition/capitalization/basis correction/plans/reserves, inventory item/location/conversion, owner/source edits, prepaid recognition, user administration) use explicitly authorized online service adapters with durable operation ID/hash/status; they are not enabled as generic sync CRUD. Their Phase 6–8 OpenAPI input schemas must include source-specific validation. The phase traceability names each requirement; missing backend features remain disabled prerequisites. No client sends journal lines, approval actors, generated references, computed cost or role values through farm event commands.

Array contracts: `SellingCost={entity_uuid UUID,category Enum(transport,packaging,commission,market_fee,other),amount Money,notes? Text}`; `InitialReceipt={entity_uuid UUID,amount Money,payment_method Enum,received_by_name? Text,external_reference? Text}` (same instant as sale unless a separate receipt command); `FundingSplit={funding_source_uuid UUID,amount Money,classification Enum}`; `CostShare={batch_uuid UUID,amount Money}`; `Designation={entity_uuid UUID,batch_uuid UUID,amount Money,notes? Text}`; `StockIssue={lot_uuid UUID,quantity_used Qty,usage_date Date,accounting_period_uuid UUID}`. Phase handlers validate source enum spellings, scale and bounds against source/model choices before enabling; an unsupported spelling is a validation error, not a guessed translation.

## Dependency and transaction map

| Parent / dependency | Child | Atomic accepted effect / gate |
|---|---|---|
| Confirmed Batch, or accepted batch/arrival command | Mortality/feed/treatment/weight | Child names Batch UUID and prerequisite operation IDs. Arrival must be confirmed, never guessed |
| Batch mortality append | FeedPopulation updates + Batch summary/status | One stream transaction group; no financial journal; 2 |
| Batch + sale command | SellingCost[] + initial SalePayment + source + feed recalculation | Nested child UUIDs included in sale command hash; one transaction; no independent outbox command for embedded children; 6 |
| Accepted sale | Later sale receipt | Receipt dependency names sale operation; check current outstanding under lock; 6 |
| Item/location + accepted receipt/lot | Stock issue / return | Issue cannot use unaccepted stock; cost computed once; return references original issue; 6 |
| Feed/treatment plus explicit stock evidence | Linked stock issue | Composite rejects entirely if required inventory effect fails; legacy informational usage must visibly differ, never charge twice; 5–6 |
| Expenditure/source + FundingSplit[] | Payment | Source cash and cost bearer remain separate; one payment group/source/cash effect; 6 |
| Owner/source | Contribution + optional designation[] | One receipt, analytical designation only; OWNER throughout; 6 |
| Employee + period | Payroll + salary expense/liability | Immutable salary/percentage snapshot; no payment until separate authorized command; 7 |
| PayrollEntry + source split | Advance or salary payment | Same liability balance, no extra expense; 7 |
| Labour draft → approval → posting | Labour payable → payment | One linked expenditure/journal and dated funding; approvals online; 7 |
| Asset | Usage/maintenance evidence → linked financial action | Observations cannot alter depreciation basis; online capitalization/impairment/disposal; 7 |
| Open period + reconciled sources | Close/versioned snapshot | Large change fragments stage/apply atomically; original snapshots retained; 8 |

Dependency graph max 20 direct prerequisites/operation and 50 operations/request; detect duplicates, cycles, foreign actor/device dependencies and UUID/type collisions. A parent in another request may be accepted already; resolve from durable receipts. Pending/missing parents give `dependency_blocked`, not a terminal child failure. A terminal rejected parent requires correction under a new operation and explicit child supersession; don't rewrite possibly submitted child content in place. Online actions cannot depend on an unaccepted offline financial parent until it is confirmed and reviewed.
