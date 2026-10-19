export interface SessionResource {
  client: { lock(): void };
  repository: { db: { close(): Promise<void> } };
  sensitive?: { lock(): void; close(): Promise<void> };
}

// A late callback may retire only its generation, never a newly opened account.
export class SessionLifecycle<T extends SessionResource> {
  current: T | null = null;
  generation = 0;
  private pending: Promise<void> = Promise.resolve();

  constructor(private changed: (session: T | null) => void) {}

  isCurrent(generation: number) { return generation === this.generation; }
  async settled() {
    let pending: Promise<void>;
    do { pending = this.pending; await pending; }
    while (pending !== this.pending);
  }

  publish(session: T, generation: number) {
    if (!this.isCurrent(generation)) throw new Error('session_locked');
    this.current = session;
    this.changed(session);
  }

  retire(generation: number, cleanup?: (previous: T | null) => Promise<void>): Promise<void> {
    if (!this.isCurrent(generation)) return Promise.resolve();
    this.generation++;
    const previous = this.current;
    this.current = null;
    previous?.client.lock();
    const sensitive = previous?.sensitive;
    sensitive?.lock();
    this.changed(null);
    // Detach synchronously, even if secure persistence is slow or fails. Auth
    // actions await settled() before reading any cached session pointer.
    const task = this.pending.then(async () => {
      try { await cleanup?.(previous); }
      finally {
        try { await sensitive?.close(); }
        finally { await previous?.repository.db.close(); }
      }
    });
    this.pending = task.catch(() => {});
    return task;
  }

  async failClosed<R>(generation: number, work: () => Promise<R>): Promise<R> {
    try { return await work(); }
    catch (error) {
      try { await this.retire(generation); }
      catch { /* Preserve the authorization failure; local work is retained. */ }
      throw error;
    }
  }

  /** Auth denial may originate INSIDE a sensitive resource's current request.
   * Resolve after durable denial, not after closing that same in-flight request.
   * settled() still waits for ALL resource closes before a new account opens.
   */
  retireAfterPersistence(generation: number, persist: (previous: T | null) => Promise<void>): Promise<void> {
    if (!this.isCurrent(generation)) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      const retirement = this.retire(generation, async previous => {
        try { await persist(previous); resolve(); }
        catch (error) { reject(error); throw error; }
      });
      void retirement.catch(reject);
    });
  }
}
