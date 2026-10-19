/** Storage fixtures only. Never creates a grant, session, accepted receipt or upload. */
import { z } from 'zod';
import { canonical } from '../db/repository';
import type { Database, SqlConnection } from '../db/sql';
import { uuid } from '../protocol';
import { byteLength } from '../sync/protocol';
import { FinancialEvidenceStore, financialEvidenceHashInput } from '../finance/evidence-store';
import { financialUUIDOperation } from '../finance/uuid-commands';

const digest = z.string().regex(/^[0-9a-f]{64}(?![\s\S])/);
export const financialProbeDescriptor = z.strictObject({ version: z.literal(1),
  kind: z.literal('owned-native-financial-storage-only'), nonce: uuid,
  identity: z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid }),
  operation: financialUUIDOperation, commandHash: digest,
}).superRefine((value, ctx) => {
  if (value.operation.payload.external_reference !== `SYNTHETIC-P6-${value.nonce}` ||
      value.operation.payload.payee !== 'Synthetic café 🐔 storage only' ||
      value.operation.payload.notes !== 'Native storage probe. No observed payment, grant or upload.' ||
      value.operation.payload.total_payment_amount !== '12.34' || value.operation.depends_on.length || value.operation.supersedes_operation_id) {
    ctx.addIssue({ code: 'custom', message: 'Not an owned financial storage fixture.' });
  }
});
export type FinancialProbeDescriptor = z.infer<typeof financialProbeDescriptor>;
const ensure = (condition: unknown) => { if (!condition) throw new Error('financial_scratch_integrity_failed'); };

export async function makeFinancialProbe(random: () => string, hash: (value: string) => Promise<string>): Promise<FinancialProbeDescriptor> {
  const nonce = uuid.parse(random());
  const identity = { actorId: random(), deploymentId: random(), deviceId: random() };
  const operation = financialUUIDOperation.parse({ financial_command_version: 2, operation_id: random(),
    command: 'inventory.supplier_payment.record', captured_at: '2026-10-16T06:00:00.123456Z', depends_on: [],
    payload: { currency: 'MWK', payee: 'Synthetic café 🐔 storage only', payment_method: 'cash',
      external_reference: `SYNTHETIC-P6-${nonce}`, payment_date: '2026-10-16', total_payment_amount: '12.34',
      invoices: [{ invoice_group_id: random(), invoice_version: 'b'.repeat(64), total_payment_amount: '12.34',
        lines: [{ invoice_line_index: 0, amount: '12.34', funding_allocations: [{ funding_source: random(),
          funding_version: 'c'.repeat(64), amount: '12.34' }] }] }],
      notes: 'Native storage probe. No observed payment, grant or upload.' } });
  return financialProbeDescriptor.parse({ version: 1, kind: 'owned-native-financial-storage-only', nonce, identity, operation,
    commandHash: await hash(financialEvidenceHashInput(identity, operation)) });
}

export async function validateFinancialProbe(value: unknown, hash: (value: string) => Promise<string>) {
  const descriptor = financialProbeDescriptor.parse(value);
  ensure(await hash(financialEvidenceHashInput(descriptor.identity, descriptor.operation)) === descriptor.commandHash);
  return descriptor;
}

async function insert(tx: SqlConnection, descriptor: FinancialProbeDescriptor) {
  const serialized = canonical(descriptor.operation);
  await tx.run('INSERT INTO financial_commands VALUES(?,?,?,?)', [descriptor.operation.operation_id, serialized,
    descriptor.commandHash, byteLength(serialized)]);
  await tx.run("INSERT INTO financial_delivery VALUES(?,'pending_local_evidence')", [descriptor.operation.operation_id]);
}

/** Called only on a checked-absent newly keyed scratch file, never on a user DB. */
export async function seedFinancialProbe(db: Database, descriptor: FinancialProbeDescriptor, hash: (value: string) => Promise<string>) {
  descriptor = await validateFinancialProbe(descriptor, hash);
  const store = await FinancialEvidenceStore.open(db, descriptor.identity, hash);
  ensure((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_commands'))?.count === 0);
  ensure((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_delivery'))?.count === 0);
  ensure((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_meta'))?.count === 2);
  // Deliberate SQL FIXTURE, NOT an authorized financial capture or fake grant.
  await db.transaction(async tx => {
    await tx.run('INSERT INTO financial_meta VALUES(?,?)', ['native-scratch-owner', descriptor.nonce]);
    await insert(tx, descriptor);
  });
  let locked = false;
  try { await store.page(); } catch (error) { locked = error instanceof Error && error.message === 'financial_storage_locked_retain_original'; }
  ensure(locked); // Possessing a keyed handle does not grant financial access.
  await verifyFinancialProbe(db, descriptor, hash);
}

/** Explicit continuation on an EXISTING owned scratch file, not replacement/recovery of a missing DB. */
export async function continueFinancialProbeSeed(db: Database, descriptor: FinancialProbeDescriptor, hash: (value: string) => Promise<string>) {
  descriptor = await validateFinancialProbe(descriptor, hash);
  ensure((await db.first<{ user_version: number }>('PRAGMA user_version'))?.user_version === 1); // Never initialize/recreate a blank or truncated retained file.
  await FinancialEvidenceStore.open(db, descriptor.identity, hash);
  const counts = await db.first<{ commands: number; delivery: number; metadata: number }>(`SELECT
    (SELECT COUNT(*) FROM financial_commands) commands, (SELECT COUNT(*) FROM financial_delivery) delivery,
    (SELECT COUNT(*) FROM financial_meta) metadata`);
  if (counts?.commands === 0 && counts.delivery === 0 && counts.metadata === 2) {
    await seedFinancialProbe(db, descriptor, hash); // Same retained operation/owner/hash, never generate a new one.
    return 'seeded_original' as const;
  }
  await verifyFinancialProbe(db, descriptor, hash); // Damaged/foreign/authorized/partial evidence refuses, not repairs.
  return 'retained_original' as const;
}

/** Exact SQL fixture proof, deliberately outside authorization UI/receipts. */
export async function verifyFinancialProbe(db: SqlConnection, descriptor: FinancialProbeDescriptor, hash: (value: string) => Promise<string>) {
  descriptor = await validateFinancialProbe(descriptor, hash);
  ensure((await db.first<{ value: string }>("SELECT value FROM financial_meta WHERE key='native-scratch-owner'"))?.value === descriptor.nonce);
  ensure((await db.first<{ value: string }>("SELECT value FROM financial_meta WHERE key='identity'"))?.value === canonical(descriptor.identity));
  const rows = await db.all<{ operation_id: string; operation_json: string; command_hash: string; byte_count: number; state: string }>(
    'SELECT c.*,d.state FROM financial_commands c LEFT JOIN financial_delivery d USING(operation_id) ORDER BY c.operation_id');
  const row = rows[0];
  ensure(rows.length === 1 && row && row.operation_id === descriptor.operation.operation_id &&
    row.operation_json === canonical(descriptor.operation) && row.command_hash === descriptor.commandHash &&
    row.byte_count === byteLength(row.operation_json) && row.state === 'pending_local_evidence');
  ensure((await db.first<{ count: number }>('SELECT COUNT(*) count FROM financial_delivery'))?.count === 1);
  ensure((await db.first<{ count: number }>("SELECT COUNT(*) count FROM financial_meta WHERE key='authorization'"))?.count === 0);
}

export async function financialProbeRollback(db: Database, descriptor: FinancialProbeDescriptor, random: () => string, hash: (value: string) => Promise<string>) {
  await verifyFinancialProbe(db, descriptor, hash); // Own marker/exact original BEFORE fault injection.
  const operation = financialUUIDOperation.parse({ ...descriptor.operation, operation_id: random() });
  const candidate = { ...descriptor, operation, commandHash: await hash(financialEvidenceHashInput(descriptor.identity, operation)) };
  await db.exec("CREATE TRIGGER native_financial_probe_abort BEFORE INSERT ON financial_delivery BEGIN SELECT RAISE(ABORT,'synthetic_probe_abort'); END");
  let rejected = false;
  try { await db.transaction(tx => insert(tx, candidate)); }
  catch (error) { rejected = error instanceof Error && /synthetic_probe_abort/.test(error.message); }
  finally { await db.exec('DROP TRIGGER native_financial_probe_abort'); }
  ensure(rejected);
  await verifyFinancialProbe(db, descriptor, hash); // Both tentative rows must roll back.
}

export function containsProbeAscii(bytes: Uint8Array, text: string): boolean {
  return bytes.some((_, index) => index + text.length <= bytes.length &&
    [...text].every((character, offset) => bytes[index + offset] === character.charCodeAt(0)));
}
