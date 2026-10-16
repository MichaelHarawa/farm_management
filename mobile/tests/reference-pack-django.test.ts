/** Actual Django-generated OWNED-PG adapter output, not HTTP or native evidence. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { z } from 'zod';
import { uuid } from '../src/protocol';
import { verifyReferencePackPages, parseReferencePackDelta } from '../src/finance/reference-pack';

const generated = z.strictObject({ owned_database: z.string().regex(/^test_mobile_phase02_[0-9a-f]{12}$/),
  http_or_native: z.literal(false), financial_effects_unchanged: z.literal(true),
  expected: z.strictObject({ identity: z.strictObject({ deploymentId: uuid, actorId: uuid, deviceId: uuid }),
    epoch: uuid, scopeRevision: z.string().length(64).regex(/^[0-9a-f]{64}$/) }),
  manifest: z.unknown(), pages: z.array(z.unknown()).min(1), deltas: z.array(z.unknown()).length(2),
}).parse(JSON.parse(readFileSync(new URL('../../docs/mobile/evidence/phase06-reference-pack-cross-language-20261015.json', import.meta.url), 'utf8')));
const hash = async (value: string) => createHash('sha256').update(value).digest('hex');

test('actual owned PostgreSQL/Django multi-page reference pack passes TypeScript hashes and identity validation', async () => {
  const result = await verifyReferencePackPages(generated.manifest, generated.pages, generated.expected, hash);
  assert.equal(result.rows.length, 3);
  assert.equal(result.manifest.manifest.length, 3);
  assert.equal(result.manifest.offline_cache_seconds, 0);
  assert.equal(result.manifest.financial_uploads, false);
  const upsert = parseReferencePackDelta(generated.deltas[0], generated.expected, result.manifest.watermark);
  assert.equal(upsert.changes.length, 1);
  const entry = upsert.changes[0];
  assert.ok(entry && entry.kind === 'upsert' && entry.entity_type === 'finance.funding_selection');
  assert.equal(entry.payload.reference.label, 'Synthetic café 🐔 loan');
  const tombstone = parseReferencePackDelta(generated.deltas[1], generated.expected, entry.sequence);
  assert.equal(tombstone.changes[0]?.kind, 'tombstone');
  assert.equal(tombstone.changes[0]?.entity_uuid, entry.entity_uuid);
  assert.equal(tombstone.changes[0]?.revision, '2');
});

test('actual Django reference pages cannot cross actor scope or activate incomplete/reordered staging', async () => {
  await assert.rejects(verifyReferencePackPages(generated.manifest, generated.pages,
    { ...generated.expected, identity: { ...generated.expected.identity, actorId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa' } }, hash));
  await assert.rejects(verifyReferencePackPages(generated.manifest, generated.pages.slice(0, -1), generated.expected, hash));
  await assert.rejects(verifyReferencePackPages(generated.manifest, [...generated.pages].reverse(), generated.expected, hash));
});
