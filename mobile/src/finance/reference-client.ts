/** Authenticated online-only reads. No financial SQLite writes or cached grant. */
import { z } from 'zod';
import type { AuthClient } from '../auth/client';
import { uuid, type StoreIdentity } from '../protocol';
import { parseFundingReferencePage } from './funding-references';
import { parseInvoiceReferenceDetail, parseInvoiceReferencePage } from './invoice-references';
import { referenceRoot, referenceCatalogPath, referenceInvoicePath } from './reference-paths';

const digest = z.string().length(64).regex(/^[0-9a-f]{64}$/);
const id = uuid.refine(value => value === value.toLowerCase());
export const referenceCapabilities = z.strictObject({ financial_reference_api_version: z.literal(1),
  deployment_id: id, device_id: id, actor_id: id,
  server_time: z.iso.datetime().max(27).regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/),
  access: z.literal('online_only_current_finance_writer'), offline_cache_seconds: z.literal(0),
  financial_uploads: z.literal(false), packs: z.array(z.never()).max(0),
  profiles: z.strictObject({ funding: z.literal(1), original_invoices: z.literal(1) }),
  scopes: z.strictObject({ funding: digest, original_invoices: digest }),
  limits: z.strictObject({ funding_rows: z.literal(1000), funding_page_rows: z.literal(50), funding_catalog_bytes: z.literal(524288),
    invoice_rows: z.literal(100), invoice_page_rows: z.literal(25), invoice_catalog_bytes: z.literal(524288),
    invoice_detail_bytes: z.literal(65536), invoice_lines: z.literal(50), cursor_seconds: z.literal(900) }),
});
type ReadAuth = Pick<AuthClient, 'readFinancialReference'>;

export class FinancialReferenceReader {
  private closed = false;
  private readonly scopes: Readonly<{ funding: string; original_invoices: string }>;
  private constructor(private readonly auth: ReadAuth, private readonly identity: Readonly<StoreIdentity>,
    capabilities: z.infer<typeof referenceCapabilities>) {
    this.scopes = Object.freeze({ ...capabilities.scopes });
  }

  static async open(auth: ReadAuth, identity: StoreIdentity) {
    const bound = Object.freeze({ deploymentId: id.parse(identity.deploymentId), deviceId: id.parse(identity.deviceId), actorId: id.parse(identity.actorId) });
    const value = referenceCapabilities.parse(await auth.readFinancialReference(`${referenceRoot}/capabilities`));
    if (value.deployment_id !== bound.deploymentId || value.device_id !== bound.deviceId || value.actor_id !== bound.actorId) {
      throw new Error('financial_reference_identity_mismatch');
    }
    return new FinancialReferenceReader(auth, bound, value);
  }

  /** Caller closes on screen exit/lock. Reopen explicitly after scope change;
   * never swap the selected parent/version or persist this as offline authority. */
  close() { this.closed = true; }
  private requireOpen() {
    if (this.closed) throw new Error('financial_reference_session_closed');
  }
  private async read(path: string) {
    this.requireOpen();
    const result = await this.auth.readFinancialReference(path);
    this.requireOpen();
    return result;
  }
  async fundingPage(cursor?: string) {
    return parseFundingReferencePage(await this.read(referenceCatalogPath('funding', cursor)),
      { identity: this.identity, scopeRevision: this.scopes.funding });
  }
  async invoicePage(cursor?: string) {
    return parseInvoiceReferencePage(await this.read(referenceCatalogPath('invoices', cursor)),
      { identity: this.identity, scopeRevision: this.scopes.original_invoices });
  }
  async invoiceDetail(invoiceId: string, invoiceVersion: string) {
    return parseInvoiceReferenceDetail(await this.read(referenceInvoicePath(invoiceId, invoiceVersion)),
      { identity: this.identity, scopeRevision: this.scopes.original_invoices, invoiceId, invoiceVersion });
  }
}
