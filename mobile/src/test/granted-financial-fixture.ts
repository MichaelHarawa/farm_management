/** Explicit Phase6 storage fixture. Uses protected capture/page ports, never SQL or invented authority. */
import { z } from 'zod';
import { canonical } from '../db/repository';
import { financialEvidenceHashInput, type FinancialEvidence } from '../finance/evidence-store';
import { financialUUIDOperation } from '../finance/uuid-commands';
import { uuid, type StoreIdentity } from '../protocol';
import { byteLength } from '../sync/protocol';

const API = 'http://10.0.2.2:7075/api/v1';
const MAX_DESCRIPTOR_BYTES = 16 * 1024;
const identitySchema = z.strictObject({ actorId: uuid, deploymentId: uuid, deviceId: uuid });
const digest = z.string().regex(/^[a-f0-9]{64}(?![\s\S])/);
type Operation = FinancialEvidence['operation'];

export interface GrantedFinancialFixtureScope {
  enabled: boolean;
  environment: string;
  apiBaseUrl: string;
  username: string;
  identity: StoreIdentity;
}
export interface GrantedFinancialFixturePorts {
  current(): boolean;
  descriptor: { read(): Promise<string | null>; createExclusive(text: string): Promise<void> };
  randomUUID(): string;
  hash(text: string): Promise<string>;
  capture(operation: Operation): Promise<FinancialEvidence>;
  page(): Promise<{ evidence: FinancialEvidence[]; next: string | null }>;
}
export type GrantedFinancialFixtureErrorCode =
  | 'granted_financial_fixture_unavailable' | 'granted_financial_fixture_stale'
  | 'granted_financial_fixture_descriptor_required' | 'granted_financial_fixture_descriptor_invalid'
  | 'granted_financial_fixture_scope_mismatch' | 'granted_financial_fixture_descriptor_changed'
  | 'granted_financial_fixture_evidence_mismatch' | 'granted_financial_fixture_failed';
class FixtureFailure extends Error {
  constructor(readonly code: GrantedFinancialFixtureErrorCode) { super(code); }
}
function requireFixture(value: unknown, code: GrantedFinancialFixtureErrorCode): asserts value {
  if (!value) throw new FixtureFailure(code);
}
function freeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Also used by native adapters BEFORE namespace derivation, hashing or constructing a file. */
export function requireGrantedFinancialFixtureScope(scope: GrantedFinancialFixtureScope): GrantedFinancialFixtureScope {
  const parsed = z.strictObject({ enabled: z.literal(true), environment: z.literal('development'),
    apiBaseUrl: z.literal(API), username: z.literal('mobile-finance-manager'), identity: identitySchema }).safeParse(scope);
  if (!parsed.success) throw new FixtureFailure('granted_financial_fixture_unavailable');
  return freeze(parsed.data);
}

function operationFor(operationId: string): Operation {
  return financialUUIDOperation.parse({ financial_command_version: 2, operation_id: operationId,
    command: 'inventory.supplier_payment.record', captured_at: '2026-10-17T06:00:00.123456Z', depends_on: [],
    payload: { currency: 'MWK', payee: 'FICTITIOUS café 🐔 local storage only', payment_method: 'cash',
      external_reference: 'SYNTHETIC-P6-GRANTED-LOCAL-STORAGE-ONLY', payment_date: '2026-10-17', total_payment_amount: '12.34',
      invoices: [{ invoice_group_id: '00000000-0000-4000-8000-000000000061', invoice_version: 'b'.repeat(64),
        total_payment_amount: '12.34', lines: [{ invoice_line_index: 0, amount: '12.34',
          funding_allocations: [{ funding_source: '00000000-0000-4000-8000-000000000062',
            funding_version: 'c'.repeat(64), amount: '12.34' }] }] }],
      notes: 'Synthetic local-storage fixture only. No observed payment, real invoice, funding authority, posting or upload.' } });
}
const fixtureOperation = financialUUIDOperation.refine(value => canonical(value) === canonical(operationFor(value.operation_id)));
const descriptorSchema = z.strictObject({ version: z.literal(1),
  kind: z.literal('owned-phase6-granted-financial-fixture-v1'),
  scope: z.strictObject({ apiBaseUrl: z.literal(API), identity: identitySchema }),
  operation: fixtureOperation, commandHash: digest });
export type GrantedFinancialFixtureDescriptor = z.infer<typeof descriptorSchema>;
export interface GrantedFinancialFixtureResult {
  descriptor: GrantedFinancialFixtureDescriptor;
  evidence: FinancialEvidence;
  outcome: 'captured' | 'retained' | 'verified';
}

function actions(scope: GrantedFinancialFixtureScope, ports: GrantedFinancialFixturePorts) {
  function current() {
    requireFixture(ports.current(), 'granted_financial_fixture_stale');
  }
  async function io<T>(work: () => Promise<T>): Promise<T> {
    current();
    let result: T;
    try { result = await work(); }
    catch (error) { current(); throw error; }
    current();
    return result;
  }
  async function read() {
    const raw = await io(() => ports.descriptor.read());
    requireFixture(raw === null || (typeof raw === 'string' && raw.length <= MAX_DESCRIPTOR_BYTES &&
      byteLength(raw) <= MAX_DESCRIPTOR_BYTES), 'granted_financial_fixture_descriptor_invalid');
    return raw;
  }
  async function parse(raw: string): Promise<GrantedFinancialFixtureDescriptor> {
    let decoded: unknown;
    try { decoded = JSON.parse(raw); }
    catch { throw new FixtureFailure('granted_financial_fixture_descriptor_invalid'); }
    const parsed = descriptorSchema.safeParse(decoded);
    requireFixture(parsed.success, 'granted_financial_fixture_descriptor_invalid');
    const value = parsed.data;
    requireFixture(canonical(value.scope) === canonical({ apiBaseUrl: scope.apiBaseUrl, identity: scope.identity }),
      'granted_financial_fixture_scope_mismatch');
    const hash = await io(() => ports.hash(financialEvidenceHashInput(value.scope.identity, value.operation)));
    requireFixture(hash === value.commandHash, 'granted_financial_fixture_descriptor_invalid');
    return freeze(value);
  }
  function evidence(value: unknown, descriptor: GrantedFinancialFixtureDescriptor): FinancialEvidence {
    const parsed = z.strictObject({ operation: fixtureOperation, commandHash: digest,
      status: z.literal('pending_local_evidence') }).safeParse(value);
    requireFixture(parsed.success && parsed.data.commandHash === descriptor.commandHash &&
      canonical(parsed.data.operation) === canonical(descriptor.operation), 'granted_financial_fixture_evidence_mismatch');
    return freeze(parsed.data);
  }
  async function page(descriptor?: GrantedFinancialFixtureDescriptor, emptyAllowed = false): Promise<FinancialEvidence | null> {
    const downloaded = await io(() => ports.page());
    requireFixture(downloaded && Array.isArray(downloaded.evidence) && downloaded.next === null && downloaded.evidence.length <= 1,
      'granted_financial_fixture_evidence_mismatch');
    if (downloaded.evidence.length === 0) {
      requireFixture(emptyAllowed, 'granted_financial_fixture_evidence_mismatch');
      return null;
    }
    requireFixture(descriptor, 'granted_financial_fixture_evidence_mismatch');
    return evidence(downloaded.evidence[0], descriptor);
  }
  return { current, io, read, parse, evidence, page };
}

async function safe<T>(work: () => Promise<T>): Promise<T> {
  try { return await work(); }
  catch (error) {
    if (error instanceof FixtureFailure) throw error;
    throw new FixtureFailure('granted_financial_fixture_failed');
  }
}

/** Creates once, retains ambiguous work, and retries ONLY the original protected capture. */
export function captureGrantedFinancialFixture(input: GrantedFinancialFixtureScope,
  ports: GrantedFinancialFixturePorts): Promise<GrantedFinancialFixtureResult> {
  return safe(async () => {
    const scope = requireGrantedFinancialFixtureScope(input), work = actions(scope, ports);
    let original = await work.read();
    let descriptor: GrantedFinancialFixtureDescriptor;
    if (original === null) {
      await work.page(undefined, true); // A missing descriptor NEVER adopts existing evidence or a cursor.
      work.current();
      const operation = operationFor(ports.randomUUID());
      work.current();
      const commandHash = await work.io(() => ports.hash(financialEvidenceHashInput(scope.identity, operation)));
      const candidate = descriptorSchema.safeParse({ version: 1, kind: 'owned-phase6-granted-financial-fixture-v1',
        scope: { apiBaseUrl: scope.apiBaseUrl, identity: scope.identity }, operation, commandHash });
      requireFixture(candidate.success, 'granted_financial_fixture_descriptor_invalid');
      descriptor = freeze(candidate.data);
      const serialized = canonical(descriptor);
      requireFixture(byteLength(serialized) <= MAX_DESCRIPTOR_BYTES, 'granted_financial_fixture_descriptor_invalid');
      original = serialized;
      await work.io(() => ports.descriptor.createExclusive(serialized));
      requireFixture(await work.read() === original, 'granted_financial_fixture_descriptor_changed');
    } else descriptor = await work.parse(original);
    const previous = await work.page(descriptor, true); // Exact original or an interrupted, still-empty capture only.
    requireFixture(await work.read() === original, 'granted_financial_fixture_descriptor_changed');
    const captured = await work.io(() => ports.capture(descriptor.operation));
    work.evidence(captured, descriptor);
    const evidence = await work.page(descriptor);
    requireFixture(await work.read() === original, 'granted_financial_fixture_descriptor_changed');
    requireFixture(evidence, 'granted_financial_fixture_evidence_mismatch');
    return freeze({ descriptor, evidence, outcome: previous ? 'retained' as const : 'captured' as const });
  });
}

/** Never generates IDs, creates descriptors or captures/replaces evidence. Protected pages advance authorization clocks. */
export function verifyGrantedFinancialFixture(input: GrantedFinancialFixtureScope,
  ports: GrantedFinancialFixturePorts): Promise<GrantedFinancialFixtureResult> {
  return safe(async () => {
    const scope = requireGrantedFinancialFixtureScope(input), work = actions(scope, ports);
    const original = await work.read();
    requireFixture(original !== null, 'granted_financial_fixture_descriptor_required');
    const descriptor = await work.parse(original), evidence = await work.page(descriptor);
    requireFixture(await work.read() === original, 'granted_financial_fixture_descriptor_changed');
    requireFixture(evidence, 'granted_financial_fixture_evidence_mismatch');
    return freeze({ descriptor, evidence, outcome: 'verified' as const });
  });
}
