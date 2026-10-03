import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fork } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { hostDatabase, identity } from './helpers';
import { migrate, Repository } from '../src/db/repository';
for (const mode of ['committed', 'uncommitted']) {
  test(`host process termination: ${mode} draft/outbox recovery (NOT Android evidence)`, async () => {
    const directory = mkdtempSync(join(tmpdir(), 'farm-mobile-crash-owned-'));
    const file = join(directory, 'owned.db');
    const child = fork(fileURLToPath(new URL('./process-child.ts', import.meta.url)), [], {
      execArgv: ['--import', 'tsx'], env: { ...process.env, OWNED_SQLITE_FILE: file, OWNED_TEST_MODE: mode }, stdio: ['ignore', 'ignore', 'inherit', 'ipc'],
    });
    let db: ReturnType<typeof hostDatabase> | null = null;
    try {
      const message = await Promise.race([once(child, 'message'), once(child, 'exit').then(() => { throw new Error('Child exited before test boundary'); }),
        new Promise<never>((_resolve, reject) => { const timer = setTimeout(() => reject(new Error('Child boundary timeout')), 10000); timer.unref(); })]);
      assert.equal(message[0], mode);
      const exited = once(child, 'exit'); child.kill(); await exited;
      db = hostDatabase(file); await migrate(db); const repo = new Repository(db, identity); await repo.bindIdentity();
      assert.equal(await repo.queueCount(), mode === 'committed' ? 1 : 0);
      assert.equal((await db.first<{ count: number }>('SELECT COUNT(*) count FROM pending_overlays'))!.count, mode === 'committed' ? 1 : 0);
    } finally {
      if (child.exitCode === null && child.signalCode === null) { const exited = once(child, 'exit'); child.kill(); await exited; }
      await db?.close(); rmSync(directory, { recursive: true });
    }
  });
}
