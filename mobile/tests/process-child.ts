import { hostDatabase, identity, command } from './helpers';
import { migrate, Repository } from '../src/db/repository';
import { createHash } from 'node:crypto';
const path = process.env.OWNED_SQLITE_FILE;
if (!path || !process.send) throw new Error('Owned child test invocation required');
async function main() {
  const db = hostDatabase(path!); await migrate(db);
  const repo = new Repository(db, identity); await repo.bindIdentity();
  await db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)', ['poultry.batch', command.payload.batch_uuid, '1', '{}']);
  if (process.env.OWNED_TEST_MODE === 'committed') {
    await repo.saveDraftAndEnqueue(command, async (value) => createHash('sha256').update(value).digest('hex'));
    process.send!('committed');
  } else {
    await db.transaction(async (tx) => {
      await tx.run('INSERT INTO outbox(operation_id,entity_uuid,entity_type,actor_id,device_id,deployment_id,command_json,command_hash,captured_at) VALUES(?,?,?,?,?,?,?,?,?)', [command.operation_id, command.entity_uuid, command.entity_type, identity.actorId, identity.deviceId, identity.deploymentId, '{}', 'synthetic', command.captured_at]);
      process.send!('uncommitted');
      await new Promise(() => {}); // Parent terminates the owned process at this exact boundary.
    });
  }
  setInterval(() => {}, 1000);
}
void main();
