# Proposed mobile synchronization contract

Status: protocol version `1`, initial mortality slice finalized by Phase 1 on 1 October 2026. Routes and models below are proposed additions, not existing endpoints. The selected identities, exact initial JSON schema, registry and implementation gates are in section 9 and the linked Phase 1 artifacts.

## 1. Identity and storage

Keep all existing primary keys. The selected strategy is a `SyncEntity` mapping (`deployment_id`, `entity_type`, existing PK as text, UUID, revision, deleted state), not new UUID fields on every business model. Enforce mapping uniqueness and instrument all writers. Server-generated display IDs remain authoritative. Revisions start at 1 and increment transactionally for confirmed projection changes/tombstones; transported revision and stream counters are decimal integer strings.

The device generates UUIDs for installation identity, new local entities and immutable operations. It receives a stable `deployment_id` from the server. This represents this installed backend, not a fabricated multi-tenant farm model. Register the installation to the authenticated user. An operation is bound to its original user and registered device.

Proposed server persistence:

| Record | Required purpose |
|---|---|
| `MobileDevice` / session | User, installation ID, revoked state, protocol/app version, last seen; device-bound authorization |
| `SyncStreamState` | Single-farm transactional change counter, stream epoch |
| `SyncEntity` mapping | Stable entity UUID, server PK mapping, revision |
| `SyncOperationReceipt` | Unique `(deployment, actor, operation_id)`, originating device, canonical command hash, outcome, canonical result, entity mappings, received/committed times |
| `SyncChange` | Immutable revision/change payload or tombstone, entity/type, sequence, origin operation, visibility classification |
| `SyncBootstrap` / pages | Authorized frozen data pack, watermark, scope revision, expiry, page manifest/checksums |
| Attachment metadata | Private owner/source binding, content hash, length, MIME, upload/finalization state |

Keep permanent finance deduplication keys/results or durable compact receipts; change-feed retention is a separate policy and must never permit an old money command to post twice. Do not use transient caches for operation receipts.

Local SQLite holds confirmed replicas, pending overlays, entity-ID mappings, immutable outbox commands, dependency edges, receipts, conflict records, attachment jobs, data-pack manifests, schema version, cursors and worker leases. Namespace all data by backend deployment and original user. Do not put credentials inside the replicated tables.

## 2. API surface

Use `/api/v1/mobile-sync/` for the adapter. The namespace makes sync semantics explicit while preserving existing REST consumers.

| Proposed route | Behavior |
|---|---|
| `POST devices` | Authenticated device registration; return deployment/device identity and policy |
| `GET capabilities` | Current permitted actions/entities/fields, scope revision, server time, offline window, supported protocol/schema versions and limits |
| `POST bootstrap` | Create/resume an authorized snapshot for specified packs; return snapshot ID, watermark and bounded page manifest |
| `GET bootstrap/{id}/pages?cursor=...` | Frozen, size-bounded pages with dependency ordering and checksums |
| `GET changes?cursor=...&limit=...` | Ordered, scoped changes through a fixed upper watermark; opaque continuation |
| `POST push` | Bounded list of typed commands, individual outcomes, explicit composite-command boundaries |
| `GET operations/{operation_id}` | Recover the outcome of an interrupted request, with actor/device checks |
| `POST devices/{id}/revoke` | Audited online revocation by permitted administrator or owner policy |

Use current JWT login/refresh where appropriate, extending mobile device-session binding without breaking existing web sessions. The device header alone is not authentication: check ownership/session binding. Mobile-issued tokens/session identity must be checked for revocation on every mobile-authorized API path, including normal REST reports, refresh, attachment access and push replay.

Bootstrap/pull must project only authorized fields before serialization; worker payloads must not contain payroll amounts hidden merely by the UI. Validate object-level references and current scope again on each push. Rate-limit login/registration/push and cap payloads. Define exact slash conventions in OpenAPI rather than relying on POST redirects.

## 3. Command envelope and outcomes

Initial mortality command (UUIDs below are examples; strict schema in `contracts/push-v1.schema.json`):

```json
{
  "protocol_version": 1,
  "device_id": "8d7455a0-92b1-451f-97d5-43d216d0a341",
  "operations": [{
    "operation_id": "9b7b91cb-0271-4be7-a0ee-22f4d775b473",
    "entity_type": "poultry.mortality",
    "entity_uuid": "31d8a2fb-fd4b-4998-a807-c2c173755fcf",
    "action": "record",
    "payload_version": 1,
    "base_version": null,
    "captured_at": "2026-09-30T06:35:00Z",
    "depends_on": [],
    "payload": {
      "batch_uuid": "6f2337e0-72bf-436c-a516-8657bc8fa870",
      "mortality_date": "2026-09-30T06:30:00Z",
      "quantity_dead": 2,
      "suspected_cause": "Unknown",
      "description": "Morning inspection",
      "action_taken": "Reported to supervisor",
      "reported_by_name": "Example field worker"
    }
  }]
}
```

The actor is derived from authentication, never trusted from payload. Capture time is device evidence; `received_at` and `committed_at` are server-generated. Derive age from verified event/batch dates where appropriate. Business date and capture time are distinct; reject unjustified future dates without silently rewriting either.

Every result includes operation ID, outcome, machine-readable reason, allowed recovery action and field errors when relevant. Accepted/replayed results include canonical entities, versions and local-to-server ID mappings. Do not infer acceptance from HTTP `200` for a batch: inspect every operation outcome.

Apply acknowledgments and pull changes monotonically by entity revision. A delayed accepted/replayed response cannot overwrite a newer confirmed row or resurrect a newer tombstone already downloaded. Store the operation receipt and retire only its corresponding overlay even when its returned entity revision is stale; preserve later confirmed data and unrelated newer local drafts. Store revision metadata for tombstones too.

| Outcome | Client handling |
|---|---|
| `accepted` / `replayed` | Atomically store receipt, canonical result and ID mappings; retire pending overlay |
| `conflict` | Retain local proposal; show permitted current version and conflict reason |
| `validation_failed` / `period_locked` / `permission_denied` | Preserve evidence; stop automatic retries until corrected/reviewed/reauthenticated as appropriate |
| `dependency_blocked` | Preserve child and wait for parent acceptance or resolution |
| `retry_later` | Retry the identical command with bounded exponential backoff/jitter |

Transport `401` pauses upload and starts one refresh/sign-in flow. `403` does not trigger endless refresh. `429` honors `Retry-After`; timeout/5xx leave the effect unknown and retry/query the same operation ID. Unsupported protocol or expired cursor has an explicit upgrade/reset response, not an empty successful page.

An unsent draft may be edited. Once a command may have reached the server, freeze its ID/content. Correcting a terminal rejected command creates a new operation with `supersedes_operation_id`; retrying an unknown-outcome command never does. A repeated ID with a different canonical payload returns `idempotency_mismatch` and no new effect.

Online-only mutations need the same durable operation ID/hash/result recovery, whether they use this command adapter or equivalent existing REST support. Persist the submitted intent before sending a salary payment, labour posting, reversal, close/reopen or asset financial action. Do not automatically run an unsubmitted approval when connectivity returns. After a timeout, query/replay the original ID; if it was not applied and its required online confirmation has expired, require a fresh foreground confirmation before the first effect. A new button click must not silently create a second payment while an earlier outcome is unknown.

## 4. Atomic application and dependencies

For each command, in one server transaction:

1. Recheck active user, mobile session/device, capability, scope and supported command.
2. Acquire the sync stream lock before domain locks in a documented consistent order.
3. Claim/check the operation receipt's uniqueness and canonical hash. Return the existing permitted result on a valid replay.
4. Resolve entity UUIDs/dependencies and validate expected revisions. Lock affected sale/batch/lot/source/payroll/period rows in deterministic order.
5. Invoke existing domain services for all source records, payments, stock/flock effects and required journals/audit events.
6. Write resulting versions, immutable changes and the successful receipt in the same transaction; commit before responding.

A business rejection must roll back domain effects but retain a durable terminal receipt/review submission in a controlled outer transaction/savepoint or equivalent design. Infrastructure failure must not leave a falsely successful receipt. Test both paths and racing submissions. Do not publish the change log only in `transaction.on_commit()`; a crash between business commit and callback would lose the change. Django transactions support the atomic boundary; callback execution is a separate lifecycle. [Django transaction documentation](https://docs.djangoproject.com/en/6.0/topics/db/transactions/).

Unrelated commands have separate atomic outcomes. A sale with selling-cost rows and an initial receipt is one explicit composite command if the workflow requires all-or-nothing acceptance. Cash/stock effects cannot partially survive a rejected composite.

Offline child records reference parent UUIDs and list prerequisite operation IDs. Process a bounded acyclic dependency graph; preserve blocked children. A rejected parent does not disappear from the queue or cause a child to attach to a guessed server row. Appending an independent observation need not conflict just because an unrelated batch description changed; the command still validates relevant current and dated invariants.

Cross-device commands with different UUIDs may describe the same real event. Exact idempotency does not detect this. Use supported unique receipt/external references plus explicit possible-duplicate review; do not drop apparently similar legitimate feed or mortality observations automatically.

## 5. Change ordering and all-writer coverage

Do not use `updated_at > last_sync` or a raw auto-increment change ID as the only cursor. Sequence allocation can precede transaction commit, allowing an earlier-numbered change to commit after the device has advanced past it. PostgreSQL documents sequence behavior separately from transactional row visibility. [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html).

Initial implementation choice for this single farm: every mutation affecting a published sync entity acquires the `SyncStreamState` row with `select_for_update`, allocates its sequence(s), writes domain and immutable change rows, and holds the lock through commit. Acquire stream before domain locks everywhere. This serializes participating writes; keep transactions short, measure contention and do not perform network/file uploads under the lock. A future higher-throughput publisher needs an equivalent proven commit-order guarantee, not a timestamp shortcut.

Cover ordinary web/REST writes, mobile commands, Django admin, management commands, backfills and bulk updates for every registered sync entity. A command type remains disabled until its writer matrix is covered. Signals alone miss bulk operations; protect or wrap unsupported mutation paths and test them. Raw privileged SQL is outside application guarantees and requires an explicit stream-epoch reset/reconciliation after a controlled import. Read-only report generation must not secretly mutate replicated rows.

Each pull run has a fixed high watermark. Cursor includes/encodes stream epoch, position, run watermark, protocol and visibility/data-pack scope revision, signed or opaque so the client cannot escalate scope. Changes have immutable payload/version or tombstones; returning a later mutable row for an earlier change must not violate page consistency.

Transactions such as payroll or period-close allocation can exceed one page. Carry `transaction_id`, fragment index and final-fragment metadata. Transport fragments remain within the page/byte limits. Persist received fragments and a download-resume position, but stage them outside visible confirmed tables. Apply the entire transaction and advance the applied cursor atomically only when its final fragment and dependencies are present. Keep download position separate from applied cursor; after a crash resume staged fragments or redownload from the applied cursor. Do not solve large transactions using unlimited responses or partial accounting visibility. Set and test a supported maximum transaction size and a recovery path for oversized groups.

Filtered streams must also make progress: advance the opaque scan position over inspected changes that are invisible to this user/pack, subject to bounded scan work. Return continuation/run-complete metadata even for an empty visible page. The client continues while the run is incomplete; it must not stop merely because `changes` is empty or spin on the same cursor. Never include restricted entity payloads just to explain cursor progress.

## 6. Bootstrap, retention and resync

Materialize the authorized data pack and matching committed watermark in one bounded consistent transaction coordinated with the same stream lock. Persist frozen pages/manifest and release the lock before network paging. For larger farms, replace this only with a demonstrated consistent-snapshot strategy and documented hosting/job infrastructure. Do not hold a DB transaction open across HTTP requests or page through mutable live tables.

The phone downloads into staging, validates pages/checksums, and swaps the completed replica in a local transaction. Then it pulls strictly after the snapshot watermark. Interrupted bootstrap resumes by snapshot ID; expiry restarts staging, keeping the active replica and all pending work.

Suggested initial policy: bootstrap TTL 24 hours; change/tombstone retention 90 days; protocol support for current and previous app release during rollout. These are configurable operational choices. Cursor older than retained history returns `resync_required`, never a silently incomplete delta. Full rebootstrap preserves outbox, unknown outcomes, pending attachments and identity mappings; query outstanding receipts and reconcile overlays before resubmission.

On scope/role change, increment visibility revision and force a reset/reprojection. Purge no-longer-authorized confirmed data as soon as connectivity reveals the change. Isolate/quarantine restricted pending evidence rather than exposing it or uploading under another identity. An old cursor cannot recover removed payroll data. Report snapshots and downloaded archives carry reporting cutoff/version and access scope.

Data-pack membership also changes without a role change. Publish entry into a requested pack with all required parent/reference records or an explicit refresh instruction. Publish departure as `evict_from_pack`, distinct from an entity's true deletion tombstone. A newly active batch must appear; closing it or settling an open receivable must update pack membership. Track membership/reference counts across overlapping packs, pending overlays and dependencies: evicting one pack must not delete an entity still needed by another or strand a pending child. If a membership transition cannot be represented safely, force a scoped pack rebuild while preserving outbox work. Test both newly in-scope and newly out-of-scope records.

## 7. Financial and operational conflicts

No last-write-wins for amounts, quantities, allocations or posted state. Use explicit revisions for editable drafts/descriptive fields. Return reviewable conflicts rather than silently merging concurrent changes. Append events where possible; reversals are linked new events.

Revalidate not only today's totals but dated invariants affected by a backdated event. A backdated sale or mortality must not make a later feed/flock history invalid. Two devices selling the last birds or issuing the same stock cannot both overdraw the confirmed balance. Recheck receipt amount against outstanding sale balance and funding against available confirmed source cash.

If a period closed during disconnection, preserve the proposed business date and explanation. Manager review can use the existing audited reopening or permitted adjustment process. The sync engine never chooses an alternative date/period automatically. A new cash receipt for an older sale is evaluated on its receipt date; the sale's older closed period alone must not prevent a valid current-period collection.

Cached financial totals are server snapshots. Local previews do not mutate them. The mobile command adapter must prove one source/cash/stock/journal effect per accepted command without activating historical ledger backfill or reimplementing accounting formulas in TypeScript.

## 8. Attachments and recovery

Files use a separate resumable queue with stable UUID, source UUID, private local path, byte length, content hash, MIME, retry/offset state and server upload ID. Validate size/type and authorization server-side; store privately, inspect content safely, and finalize checksum/link exactly once. Financial postings do not depend on a photo finishing unless an explicit business policy requires evidence before approval; show outstanding attachments separately.

Temporary object-upload credentials expire and are refreshed through authorized endpoints. Never expose private bucket keys. Rebootstrap and sign-out preserve the protected original user's attachment queue. Orphan cleanup must distinguish genuinely abandoned uploads from resumable work.

The same sync coordinator serves manual, foreground, reconnect and best-effort Android background triggers. Persist its lease/timeout so a terminated worker cannot hold the queue forever. Before retry, authenticate and acquire the lease. Background access to encrypted data must respect key availability/app-lock policy; if unavailable, defer to foreground rather than weakening encryption.

## 9. Phase 1 decisions required for Phase 2

Read [API_INVENTORY.md](API_INVENTORY.md), [CAPABILITY_MATRIX.md](CAPABILITY_MATRIX.md), [COMMAND_CATALOG.md](COMMAND_CATALOG.md), [TECHNICAL_DECISIONS.md](TECHNICAL_DECISIONS.md) and [the Phase 1 checkpoint](checkpoints/PHASE_01.md). The only Phase 2 mutation command is `poultry.mortality.record`; later commands stay unavailable. Its explicit operational replicated set is `poultry.batch`, `poultry.mortality`, `poultry.feed_usage`. Sales/FlockAdjustment and financial finalization are dependency writers for those projections even before they are replicated themselves. There is no worker financial projection in Phase 2.

### Exact routes and native session

All new paths omit a terminal slash, under the slash-terminated namespace `/api/v1/mobile-sync/`:

| Method/path suffix | Exact input / response responsibility |
|---|---|
| `POST devices` | Initial ordinary login access JWT; body `installation_id` UUID, `app_version` string <=40, `platform="android"`, `protocol_version=1`, `device_label` string <=120. Register owned installation, create a session and issue signed device/session-bound access+refresh tokens; return device/deployment UUIDs and policy. Reuse owned active installation; revoked installation requires explicit reinstatement, not registration as an automatic bypass |
| `GET devices` | Owned devices; ADMIN may explicitly request permitted global list, paginated |
| `GET capabilities` | Signed mobile access token; return deployment/device, server_time, protocol/schema/policy versions, supported names, field projection versions, scope_revision, offline limits, retention and budgets |
| `POST bootstrap` | `protocol_version=1`, `packs` unique list (max20), optional `resume_snapshot_id` UUID. Bind immutable snapshot to user/device/scope and the exact pack list |
| `GET bootstrap/{snapshot_id}/pages?cursor=...` | Opaque page cursor; frozen server-sized pages enforce byte/row budgets and ownership. No client `limit`/rechunking: changing page boundaries would invalidate the persisted manifest/checksums. Manifest includes watermark, epoch, scope revision, page hashes/counts and pack coverage |
| `GET changes?cursor=...&limit=...` | Signed/opaque scoped cursor; first pull uses completed snapshot cursor; return fixed run watermark and scan/run completion metadata |
| `POST push` | Strict initial JSON schema; authenticated device must equal body device_id; per-operation results. No action is dispatched from free-form fields |
| `GET operations/{operation_id}` | Original actor/device only; not found is a named 404, not acceptance or permission to create a new operation |
| `POST devices/{device_id}/revoke` | Owned device or ADMIN; `reason` nonblank <=255. Audited, repeat-safe; invalidates mobile sessions/refresh on next request |

Device-issued JWTs carry signed `mobile_device_id`, `mobile_session_id`, `deployment_id` claims. Phase 2's shared authentication checks them against active persisted user/device/session on all mobile-authorized endpoints, including existing REST and refresh. Registration headers never substitute for signed claims. Ordinary web tokens continue their existing flow and shared business capability rules. Mobile discards the initial unbound login pair after device registration; it persists only bound refresh/key material. Revoking an installation does not claim to revoke an account's independently authenticated web sessions.

`SyncStreamState` persists this database installation's deployment UUID and stream epoch; no hard-coded farm UUID. An optional deployment setting must match the persisted identity. Restore into staging/new installation requires a new deployment identity through a controlled setup/rotation process; silently changing only hostname/setting is insufficient. Namespace mappings and receipts by that identity.

### Mapping, projections and locking

Unique constraints: `(deployment, entity_type, source_pk_text)` and `(deployment, entity_uuid)`; receipt `(deployment, actor, operation_id)`. Enforce registered type/source resolution, no UUID rebinding/reuse of tombstones, and a no-op when repeated identical projection bytes require no new revision. Server integer PKs are strings on wire; keep private UUID→PK resolver on Django. Existing entity mappings are seeded in bounded batches before enabling devices; immutable projected bootstrap covers pre-existing records without a financial backfill.

All participating transactions acquire locks in this order: stream singleton; device/session/current access rows as needed; period rows sorted by PK; Batch rows sorted by PK; source/payment/lot/other domain rows in an explicit documented order; mapping/receipt/change rows. Account/role mutations that affect a published projection must acquire stream before user/M2M locks as well. Every service wrapper acquires stream before entering existing Batch/source locks, including web/admin/bulk finalization. This coarse single-farm stream lock avoids different command lock orders racing, but underlying finance services remain independently tested for existing web concurrency.

Mortality recalculation currently uses QuerySet.update for FeedUsage. Phase 2 replaces/wraps that writer and publishes the complete mortality+Batch+FeedUsage group before commit. It also covers admin save/delete/bulk delete and dependency Sales/adjustment writers. If one writer is uncovered, the corresponding capability remains unavailable. Authoritative Batch flock aggregate prevents a partial worker pack from reconstructing counts from hidden sales history.

Scope revision is a deterministic hash of current user state, effective roles/capabilities, projection/policy versions and supported set; recompute on every request. User scope changes force rebootstrap, even when ordinary role changes occurred through an M2M/admin path. Temporal Batch display status can be derived as of server_time during projection without silently writing on GET; persisted transitions require the same stream boundary. Sync metadata must not advertise stale lifecycle eligibility as authority.

### Packs, pagination and exact result shapes

Initial packs: `operational-current-v1` (BOOKED/DELIVERED/PLANNED/ACTIVE/MATURE/SELLING Batch operational projections plus complete permitted Mortality/FeedUsage history); optional `batch:<batch_uuid>` including a chosen closed batch. No payroll, financial cost, sale price, owner identity or customer-master pack in Phase 2. History may instead use explicitly labelled aggregate baselines only if sufficient to validate all supported previews. Lookup choices are versioned capability/schema metadata, not arbitrary database tables. All timestamps/counters/quantities follow the declared projection schema.

Bootstrap envelope: `snapshot_id`, `deployment_id`, `stream_epoch`, `scope_revision`, `watermark` string, `expires_at`, `packs`, `row_count`, `manifest`, `next_page_cursor`; a complete final page yields `delta_cursor`. Resume activates nothing until all page checksums/counts pass. Checksums cover deterministic page bytes; private payload pages remain user/device scoped in Postgres. A bootstrap over the initial row/time budget fails explicitly; no half-snapshot success.

Pull envelope: `deployment_id`, `stream_epoch`, `scope_revision`, `run_watermark` string, `changes`, `fragments`, `next_cursor`, `run_complete`, `server_time`. Each change includes `sequence` string, `transaction_id` UUID, `fragment_index` integer, `fragment_final` boolean, `entity_type`, `entity_uuid`, `revision` string, `kind` (`upsert`, `tombstone`, `evict_from_pack`), `pack_ids`, `payload` for authorized upserts and optional `origin_operation_id`. Fragment indices identify bounded page fragments of a whole transaction; the last marks completeness. `fragments` contains bounded `{transaction_id, fragment_index, fragment_final}` descriptors, including a hidden-only final fragment needed to complete a previously staged visible transaction. Descriptors expose no source identity or restricted payload. Treat these as authoritative completion metadata, not extra business rows. Hidden rows advance scan position without exposing payload, and a page with no visible changes may still have `run_complete=false`. Transactions crossing byte/row limits stage until complete; max transaction sizes are in Technical Decisions.

Phase 2's executable endpoint/projection schema is [sync-api-v1.openapi.json](contracts/sync-api-v1.openapi.json). Snapshot creation is additionally bounded to 32 MiB of canonical staged entities, 100,000 scanned rows and four unexpired snapshots per user. A quota error is `snapshot_limit` (429); resume an existing owned snapshot or wait for expiry rather than looping. `capabilities.limits` advertises these budgets. Change pages bound both visible rows and fragment descriptors, and scan at most 5,000 rows. Accepted mortality acknowledgements include canonical Batch and Mortality; changed FeedUsage populations arrive in the same transaction's delta group. Completing the acknowledgement does not substitute for pulling that group.

Dynamic pack entry emits current permitted parents/children (or a scoped refresh) even if those records were created before the current cursor. Closure/settlement emits pack-specific eviction and updates overlapping membership; a Batch closing due to this mortality retains the accepted result, original overlay/receipt and dependent records until reconciled. True deletion publishes revisioned tombstones for every published cascade child. Do not repurpose evictions as deletion.

Push result: `protocol_version`, `deployment_id`, `device_id`, `server_time`, `results`. Per-result fields: `operation_id`, `outcome`, `code`, `message`, `field_errors`, `recovery_action`, `canonical_entities`, `entity_mappings`, `transaction_id`, `committed_at`; no success fields for an uncommitted operation. Entity mappings carry UUID/type/server ID text/revision string. Conflict current values use the caller's allowed projection only. Store canonical accepted results durably; replay retires only its matching local overlay and respects newer revisions.

### Error and retention policy

HTTP 400: malformed envelope/UUID/schema, unsupported payload version; 401: invalid/expired token; 403: inactive/revoked/foreign device or route capability denied; 404: authorized operation/snapshot not found; 409: protocol/epoch/scope mismatch or required reset; 410: expired snapshot/history cursor (`resync_required`); 413: request too large; 429: rate limit; 503: transient infrastructure. Auth-denied requests do not persist or reveal restricted command contents. Never use a body-provided actor to own a receipt.

HTTP 200 push represents processed per-operation outcomes, including durable terminal `validation_failed`, `period_locked`, `permission_denied` (authorized envelope but denied action), `conflict` (`idempotency_mismatch`, `entity_uuid_conflict`, `insufficient_birds`, `revision_conflict`), nonterminal `dependency_blocked` or `retry_later`, and `accepted/replayed`. Missing prerequisite receipt and transient DB failure are not terminal deduplication outcomes. Invalid JSON without a trustworthy operation ID is an envelope error. `command_unavailable` has no business effect. Terminal rejected corrections use a new operation + supersedes link; unknown outcomes retain original IDs.

Retention selected for v1: snapshots expire after 24h; changes/tombstones retained >=90d; minimum history watermark and epoch are advertised; **compact accepted and terminal-rejection deduplication receipts retained indefinitely**, with no command reexecution after body compaction. Full receipts remain until all intended supported recovery windows are met; future retention changes require an explicit migration/policy. Cleanup uses bounded, dry-runnable management commands; no continuous scheduler prerequisite for Phase 2. Immutable database tombstone/UUID identity guards outlive transported change retention. A reset must preserve pending work and query outstanding receipts before any retry.
