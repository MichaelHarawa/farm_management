import {test} from 'node:test';
import assert from 'node:assert/strict';
import {leaveUnsubmittedForm,recordMenuParams} from '../src/poultry/form-navigation';
import {Repository,migrate} from '../src/db/repository';
import {hostDatabase,identity,command} from './helpers';
import {createHash} from 'node:crypto';

test('return to workflow menu waits for durable form write and retains exact form and operation',async()=>{
  const db=hostDatabase();await migrate(db);const repository=new Repository(db,identity);await repository.bindIdentity();
  try {
    await db.run('INSERT INTO confirmed_entities(entity_type,entity_uuid,revision,payload_json) VALUES(?,?,?,?)',
      ['poultry.batch',command.payload.batch_uuid,'1','{"batch_id":"SYNTHETIC-FORM-NAVIGATION"}']);
    await repository.saveDraftAndEnqueue(command,async value=>createHash('sha256').update(value).digest('hex'));
    const original=await db.first('SELECT * FROM outbox');
    const values={batch_uuid:command.payload.batch_uuid,quantity_given:'1500',unit_of_measurement:'g'};
    let release!:()=>void,visited=false;
    const pending=new Promise<void>(resolve=>{release=resolve;}).then(()=>repository.saveForm('poultry:feed:new',values));
    const navigation=leaveUnsubmittedForm(pending,()=>{visited=true;});
    await Promise.resolve();assert.equal(visited,false);
    release();await navigation;assert.equal(visited,true);
    assert.deepEqual(await repository.form('poultry:feed:new'),values);
    assert.deepEqual(await db.first('SELECT * FROM outbox'),original);
    assert.deepEqual(recordMenuParams,{workflow:'',batch:'',supersedes:''});
  } finally {await db.close();}
});

test('failed form write refuses navigation, allowing recovery on the original screen',async()=>{
  let visited=false;
  await assert.rejects(leaveUnsubmittedForm(Promise.reject(new Error('disk_full')),()=>{visited=true;}),/disk_full/);
  assert.equal(visited,false);
});
