import { test } from 'node:test';
import assert from 'node:assert/strict';
import { farmEventFields, farmEventUtc } from '../src/components/event-time';
test('farm event entry roundtrips UTC across midnight independent of device timezone and preserves microseconds',()=>{
  for (const utc of ['2026-10-02T23:15:20Z','2024-02-29T22:00:00.123456Z']) {
    const fields=farmEventFields(utc);
    assert.equal(farmEventUtc(fields.event_day,fields.event_time),utc);
  }
  assert.deepEqual(farmEventFields('2026-10-02T23:15:20Z'),{event_day:'2026-10-03',event_time:'01:15:20'});
  for (const pair of [['2026-02-29','12:00:00'],['2026-04-31','12:00:00'],['2026-10-02','24:00:00'],['2026-10-02','12:60:00'],['2026-10-02','12:00'],['02/10/2026','12:00:00']])
    assert.throws(()=>farmEventUtc(pair[0]!,pair[1]!));
});
