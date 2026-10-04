// All business payloads use protocol decimal strings; no REAL money column exists.
export const migrations = [String.raw`
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE confirmed_entities (
 entity_type TEXT NOT NULL, entity_uuid TEXT NOT NULL, revision TEXT NOT NULL,
 payload_json TEXT NOT NULL, tombstone INTEGER NOT NULL DEFAULT 0 CHECK(tombstone IN (0,1)),
 PRIMARY KEY(entity_type,entity_uuid));
CREATE TABLE outbox (
 operation_id TEXT PRIMARY KEY, entity_uuid TEXT NOT NULL, entity_type TEXT NOT NULL,
 actor_id TEXT NOT NULL, device_id TEXT NOT NULL, deployment_id TEXT NOT NULL,
 command_json TEXT NOT NULL, command_hash TEXT NOT NULL, captured_at TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','unknown','accepted','rejected','conflict','quarantined')),
 attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT, supersedes_operation_id TEXT REFERENCES outbox(operation_id));
CREATE TABLE pending_overlays (
 operation_id TEXT PRIMARY KEY REFERENCES outbox(operation_id), entity_uuid TEXT NOT NULL,
 entity_type TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE operation_dependencies (
 operation_id TEXT NOT NULL REFERENCES outbox(operation_id), depends_on TEXT NOT NULL REFERENCES outbox(operation_id),
 CHECK(operation_id <> depends_on), PRIMARY KEY(operation_id,depends_on));
CREATE TABLE receipts (operation_id TEXT PRIMARY KEY REFERENCES outbox(operation_id), result_json TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE entity_mappings (entity_type TEXT NOT NULL, entity_uuid TEXT NOT NULL, server_id TEXT NOT NULL, revision TEXT NOT NULL,
 PRIMARY KEY(entity_type,entity_uuid), UNIQUE(entity_type,server_id));
CREATE TABLE conflicts (operation_id TEXT PRIMARY KEY REFERENCES outbox(operation_id), reason TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sync_lease (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, expires_ms INTEGER NOT NULL);
CREATE TABLE pack_manifests (pack_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, scope_revision TEXT NOT NULL, as_of TEXT NOT NULL, complete INTEGER NOT NULL CHECK(complete IN (0,1)));
CREATE TABLE pack_membership (pack_id TEXT NOT NULL REFERENCES pack_manifests(pack_id), entity_type TEXT NOT NULL, entity_uuid TEXT NOT NULL,
 PRIMARY KEY(pack_id,entity_type,entity_uuid));
CREATE TABLE attachment_jobs (attachment_id TEXT PRIMARY KEY, operation_id TEXT REFERENCES outbox(operation_id),
 source_uuid TEXT NOT NULL, private_path TEXT NOT NULL, content_hash TEXT NOT NULL, byte_length INTEGER NOT NULL,
 mime TEXT NOT NULL, state TEXT NOT NULL, offset_bytes INTEGER NOT NULL DEFAULT 0, upload_id TEXT);
CREATE INDEX entity_list ON confirmed_entities(entity_type,entity_uuid);
CREATE INDEX outbox_queue ON outbox(state,captured_at,operation_id);
CREATE TRIGGER immutable_command BEFORE UPDATE OF operation_id,entity_uuid,entity_type,actor_id,device_id,deployment_id,command_json,command_hash,captured_at,supersedes_operation_id ON outbox
BEGIN SELECT RAISE(ABORT,'immutable_operation'); END;
CREATE TRIGGER immutable_dependency_update BEFORE UPDATE ON operation_dependencies BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;
CREATE TRIGGER immutable_dependency_delete BEFORE DELETE ON operation_dependencies BEGIN SELECT RAISE(ABORT,'immutable_dependency'); END;
CREATE TRIGGER immutable_operation_delete BEFORE DELETE ON outbox BEGIN SELECT RAISE(ABORT,'retain_operation_evidence'); END;
`, String.raw`
-- Additive v2: immutable Phase3 commands/keys/receipts survive upgrade.
ALTER TABLE confirmed_entities ADD COLUMN visible INTEGER NOT NULL DEFAULT 1 CHECK(visible IN (0,1));
CREATE TABLE deliveries (
 operation_id TEXT PRIMARY KEY REFERENCES outbox(operation_id),
 status TEXT NOT NULL CHECK(status IN ('queued','sending','retry_wait','dependency_blocked','conflict','rejected','confirmed','discarded','quarantined')),
 reason TEXT, next_ms INTEGER NOT NULL DEFAULT 0, ever_sent INTEGER NOT NULL DEFAULT 0 CHECK(ever_sent IN (0,1)));
INSERT INTO deliveries(operation_id,status,ever_sent)
 SELECT operation_id,CASE state WHEN 'pending' THEN 'queued' WHEN 'unknown' THEN 'retry_wait' WHEN 'accepted' THEN 'confirmed' ELSE state END,
 CASE WHEN state IN ('unknown','accepted','rejected','conflict') OR attempts>0 THEN 1 ELSE 0 END FROM outbox;
CREATE TABLE bootstrap_entities (
 entity_type TEXT NOT NULL,entity_uuid TEXT NOT NULL,revision TEXT NOT NULL,payload_json TEXT NOT NULL,
 PRIMARY KEY(entity_type,entity_uuid));
CREATE TABLE bootstrap_pages (page INTEGER PRIMARY KEY,sha256 TEXT NOT NULL,row_count INTEGER NOT NULL);
CREATE TABLE delta_fragments (
 transaction_id TEXT NOT NULL,fragment_index INTEGER NOT NULL,final INTEGER NOT NULL CHECK(final IN (0,1)),
 changes_json TEXT NOT NULL,byte_count INTEGER NOT NULL,row_count INTEGER NOT NULL,
 PRIMARY KEY(transaction_id,fragment_index));
CREATE INDEX delivery_queue ON deliveries(status,next_ms,operation_id);
`, String.raw`
-- Additive Phase5; never rewrite existing IDs, payloads, hashes or deliveries.
CREATE TABLE form_drafts (draft_key TEXT PRIMARY KEY, values_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE online_intents (operation_id TEXT PRIMARY KEY REFERENCES outbox(operation_id), submitted INTEGER NOT NULL DEFAULT 0 CHECK(submitted IN (0,1)));
CREATE TABLE offline_batch_exclusions (batch_uuid TEXT PRIMARY KEY);
CREATE INDEX batch_history ON confirmed_entities(entity_type,json_extract(payload_json,'$.batch_uuid'),entity_uuid);
`];
