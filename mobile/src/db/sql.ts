export type SqlValue = string | number | null;
export interface SqlConnection {
  exec(sql: string): Promise<void>;
  run(sql: string, values?: SqlValue[]): Promise<{ changes: number }>;
  first<T>(sql: string, values?: SqlValue[]): Promise<T | null>;
  all<T>(sql: string, values?: SqlValue[]): Promise<T[]>;
}
export interface Database extends SqlConnection {
  transaction<T>(work: (tx: SqlConnection) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}
