/** Exact GET-only surface; never use this allowlist for financial commands. */
import { uuid } from '../protocol';

export const referenceRoot = '/mobile-sync/finance/references';
const lowerId = (value: string) => {
  if (value !== value.toLowerCase()) throw new Error('invalid_invoice_identity');
  return uuid.parse(value);
};

export function referenceCatalogPath(kind: 'funding' | 'invoices', cursor?: string) {
  if (kind !== 'funding' && kind !== 'invoices') throw new Error('invalid_reference_catalog');
  if (cursor !== undefined && (typeof cursor !== 'string' || cursor.length < 1 || cursor.length > 2048)) {
    throw new Error('invalid_reference_cursor');
  }
  return `${referenceRoot}/${kind}${cursor === undefined ? '' : `?cursor=${encodeURIComponent(cursor)}`}`;
}

export function referenceInvoicePath(invoiceId: string, invoiceVersion: string) {
  if (!/^[0-9a-f]{64}$/.test(invoiceVersion) || invoiceVersion.length !== 64) throw new Error('invalid_invoice_version');
  return `${referenceRoot}/invoices/${lowerId(invoiceId)}?invoice_version=${invoiceVersion}`;
}

export function isFinancialReferencePath(path: string): boolean {
  if (typeof path !== 'string' || path.length > 6200) return false;
  if ([`${referenceRoot}/capabilities`, `${referenceRoot}/funding`, `${referenceRoot}/invoices`].includes(path)) return true;
  for (const kind of ['funding', 'invoices'] as const) {
    const prefix = `${referenceRoot}/${kind}?cursor=`;
    if (path.startsWith(prefix)) {
      try {
        const cursor = decodeURIComponent(path.slice(prefix.length));
        return referenceCatalogPath(kind, cursor) === path;
      } catch { return false; }
    }
  }
  const match = /^\/mobile-sync\/finance\/references\/invoices\/([0-9a-f-]{36})\?invoice_version=([0-9a-f]{64})$/.exec(path);
  try {
    return match !== null && referenceInvoicePath(match[1]!, match[2]!) === path;
  } catch { return false; }
}
