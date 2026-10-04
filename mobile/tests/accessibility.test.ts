import { test } from 'node:test';
import assert from 'node:assert/strict';
import { announceErrorChange, type ErrorAnnouncement } from '../src/components/error-announcement';

test('Android error announcements skip empty/repeated renders but announce new errors and repeated failed submissions', () => {
  const spoken:string[] = [];
  const announce = (text:string) => { spoken.push(text); };
  let previous:ErrorAnnouncement|null = null;
  previous = announceErrorChange(previous,{message:null,attempt:0},announce);
  previous = announceErrorChange(previous,{message:'Could not save.',attempt:1},announce);
  previous = announceErrorChange(previous,{message:'Could not save.',attempt:1},announce);
  previous = announceErrorChange(previous,{message:'Could not save.',attempt:2},announce);
  previous = announceErrorChange(previous,{message:null,attempt:2},announce);
  previous = announceErrorChange(previous,{message:'Could not save.',attempt:2},announce);
  previous = announceErrorChange(previous,{message:'Sign in required.'},announce);
  announceErrorChange(previous,{message:'Sign in required.'},announce);
  assert.deepEqual(spoken,['Could not save.','Could not save.','Could not save.','Sign in required.']);
});
