import {test} from 'node:test';
import assert from 'node:assert/strict';
import {z} from 'zod';
import {ApiError} from '../src/auth/client';
import {syncErrorMessage} from '../src/sync/errors';

test('snapshot quota gives useful recovery guidance without losing retained work',()=>{
  const message=syncErrorMessage(new ApiError(429,'snapshot_limit'),'batch_download');
  assert.match(message,/download limit/);
  assert.match(message,/resume|expire/);
  assert.match(message,/retained/);
});
test('authorization denial is not reported as an ordinary batch download error',()=>{
  assert.match(syncErrorMessage(new ApiError(403,'private-server-message'),'batch_download'),/Sign in again/);
  assert.doesNotMatch(syncErrorMessage(new ApiError(403,'private-server-message'),'batch_download',true),/private-server-message/);
});
test('native diagnostics classify integrity and protocol failures without exposing their content',()=>{
  const privateText='private-token-key-payload';
  const cases:[unknown,string][]=[
    [new Error('UNIQUE constraint failed: '+privateText),'local_integrity_conflict'],
    [new Error('database is locked '+privateText),'local_store_busy'],
    [new Error('snapshot_checksum_or_completion'),'snapshot_checksum_or_completion'],
    [z.strictObject({quantity:z.number()}).safeParse({quantity:privateText}).error,'protocol_validation'],
    [new SyntaxError(privateText),'invalid_json'],
    [new Error(privateText),'unclassified_failure'],
    [new ApiError(500,privateText),'backend_request'],
  ];
  for(const [error,code] of cases){
    const message=syncErrorMessage(error,'sync',true);
    assert.match(message,new RegExp('Check: '+code));
    assert.doesNotMatch(message,new RegExp(privateText));
    assert.doesNotMatch(syncErrorMessage(error,'sync'),/Check:/);
  }
});
