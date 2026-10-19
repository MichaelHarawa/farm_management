/** Phase6-only synthetic descriptor; actual capture/page authorization stays in SessionProvider. */
import * as Crypto from 'expo-crypto';
import { File, Paths } from 'expo-file-system';
import { phase6Evidence } from '../build-mode.native';
import { sha256 } from '../db/native';
import { financialNamespace } from '../finance/key-database';
import type { FinancialEvidence } from '../finance/evidence-store';
import { byteLength } from '../sync/protocol';
import { requireGrantedFinancialFixtureScope, type GrantedFinancialFixturePorts,
  type GrantedFinancialFixtureScope } from './granted-financial-fixture';

const MAX_DESCRIPTOR_BYTES = 16 * 1024;
export async function nativeGrantedFinancialFixturePorts(scope: GrantedFinancialFixtureScope, access: {
  current(): boolean;
  capture(value: unknown): Promise<FinancialEvidence>;
  page(): Promise<{ evidence: FinancialEvidence[]; next: string | null }>;
}): Promise<GrantedFinancialFixturePorts> {
  // A caller cannot opt another native package into this test via a JS boolean.
  if (!phase6Evidence) throw new Error('granted_financial_fixture_unavailable');
  const bound = requireGrantedFinancialFixtureScope(scope);
  function current() {
    if (!access.current()) throw new Error('session_locked');
  }
  current();
  const names = await financialNamespace({ environment: 'development', apiBaseUrl: bound.apiBaseUrl }, bound.identity, sha256);
  current();
  // Only synthetic, strictly validated test payload and identity are stored here.
  // Never store a grant, token, password, session ID or database key in this file.
  // Backup is disabled for this native acceptance package. No reset/delete path.
  function descriptorFile() { return new File(Paths.document, `phase6-granted-fixture-${names.partition}.json`); }
  return {
    current: access.current,
    randomUUID: Crypto.randomUUID,
    hash: sha256,
    capture: access.capture,
    page: access.page,
    descriptor: {
      async read() {
        current();
        const file = descriptorFile();
        if (!file.exists) return null;
        if (!Number.isSafeInteger(file.size) || file.size < 1 || file.size > MAX_DESCRIPTOR_BYTES) {
          throw new Error('granted_financial_fixture_review_required');
        }
        const text = file.textSync();
        if (byteLength(text) > MAX_DESCRIPTOR_BYTES) throw new Error('granted_financial_fixture_review_required');
        current();
        return text;
      },
      async createExclusive(text) {
        current();
        if (byteLength(text) < 1 || byteLength(text) > MAX_DESCRIPTOR_BYTES) throw new Error('granted_financial_fixture_review_required');
        const file = descriptorFile();
        // Native exclusive creation refuses an existing descriptor, including a
        // partial prior write. A failed write retains the file for review.
        // No await between create/write; this is not a power-loss/fsync claim.
        file.create({ overwrite: false });
        file.write(text);
        current();
      },
    },
  };
}
