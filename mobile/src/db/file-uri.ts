/** SQLite exposes an Android absolute path; FileSystem requires a file URI. */
export function databaseFileUri(directory: string, name: string): string {
  if (!/^farm-[a-f0-9]{64}\.db$/.test(name)) throw new Error('invalid_database_filename');
  const base = directory.replace(/\/+$/, '');
  if (base.startsWith('file:///')) return `${base}/${name}`;
  if (!base.startsWith('/') || base.includes('://')) throw new Error('invalid_database_directory');
  // Encode path segments, not slashes. The native directory is already an
  // absolute filesystem path (not a percent-encoded URL).
  return `file://${base.split('/').map(encodeURIComponent).join('/')}/${name}`;
}

/** Separate closed allowlist: financial main/WAL/SHM files, never arbitrary paths. */
export function financialDatabaseFileUri(directory: string, name: string): string {
  if (!/^farm-finance-v1-[a-f0-9]{64}\.db(?:-wal|-shm)?(?![\s\S])/.test(name)) throw new Error('invalid_financial_database_filename');
  const base = directory.replace(/\/+$/, '');
  if (base.startsWith('file:///')) return `${base}/${name}`;
  if (!base.startsWith('/') || base.includes('://')) throw new Error('invalid_database_directory');
  return `file://${base.split('/').map(encodeURIComponent).join('/')}/${name}`;
}
