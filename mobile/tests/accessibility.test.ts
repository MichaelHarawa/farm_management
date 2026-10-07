import { test } from 'node:test';
import assert from 'node:assert/strict';
import { announceErrorChange, type ErrorAnnouncement } from '../src/components/error-announcement';
import { formErrorSummary } from '../src/poultry/forms';

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

test('combined poultry field feedback produces one complete announcement per failed submission',()=>{
  const spoken:string[]=[];
  const message=formErrorSummary('feed',{feed_type:'Required.',feed_source:'Required.',reported_by_name:'Required.'});
  let previous=announceErrorChange(null,{message,attempt:1},text=>spoken.push(text));
  previous=announceErrorChange(previous,{message,attempt:1},text=>spoken.push(text));
  announceErrorChange(previous,{message,attempt:2},text=>spoken.push(text));
  assert.deepEqual(spoken,[message,message]);
});
