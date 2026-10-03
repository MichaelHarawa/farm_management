import type { CredentialStore } from './client';

// Keep one wrapper per partition. A native write already in progress finishes
// before a new login's write; stale queued writes are skipped before execution.
export function serializedCredentials(storage: CredentialStore): CredentialStore {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    read() {
      const read = tail.then(() => storage.read());
      tail = read.catch(() => {});
      return read;
    },
    write(value, isCurrent = () => true) {
      const write = tail.then(async () => {
        if (!isCurrent()) throw new Error('session_locked');
        await storage.write(value);
      });
      tail = write.catch(() => {});
      return write;
    },
  };
}
