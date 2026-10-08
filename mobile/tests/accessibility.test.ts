import { test } from 'node:test';
import assert from 'node:assert/strict';
import { announceErrorChange, androidErrorMode, deferLiveError, liveErrorAccessibility, liveErrorLabel, liveErrorText, semanticErrorRegionKey, type ErrorAnnouncement } from '../src/components/error-announcement';
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

test('Android36 uses semantic error changes without deprecated announcements; legacy and quiet paths remain separate',()=>{
  assert.equal(androidErrorMode('android',36,true),'semantic');
  assert.equal(androidErrorMode('android','37',true),'semantic');
  assert.equal(androidErrorMode('android',24,true),'legacy');
  assert.equal(androidErrorMode('android',35,true),'legacy');
  assert.equal(androidErrorMode('android',36,false),'quiet');
  assert.equal(androidErrorMode('ios','19',true),'quiet');
});

test('semantic errors clear before each full summary and cancel stale speech on replacement or unmount',()=>{
  const rendered:string[]=[],scheduled:{run:()=>void;canceled:boolean}[]=[];
  const later=(run:()=>void)=>{const task={run,canceled:false};scheduled.push(task);return()=>{task.canceled=true;};};
  const summary=formErrorSummary('weight',{average_weight_g:'Required.',sample_size:'Required.',reported_by_name:'Required.'})!;
  assert.equal(liveErrorText(null,{message:summary,attempt:1}),'');
  assert.equal(liveErrorText({message:summary,attempt:1},{message:summary,attempt:2}),'');
  assert.equal(liveErrorText({message:summary,attempt:1},{message:null,attempt:1}),'');
  assert.equal(liveErrorText({message:summary,attempt:1},{message:'New error',attempt:1}),'');
  assert.equal(liveErrorText({message:summary,attempt:1},{message:summary,attempt:1}),`Validation attempt 1. ${summary}`);
  const stale=deferLiveError('Obsolete error',text=>rendered.push(text),later);
  stale();scheduled[0]!.run();assert.equal(rendered.length,0);assert.equal(scheduled[0]!.canceled,true);
  const current=deferLiveError(summary,text=>rendered.push(text),later);
  assert.equal(rendered.length,0);scheduled[1]!.run();assert.equal(rendered.at(-1),summary);
  current();const repeat=deferLiveError(summary,text=>rendered.push(text),later);
  scheduled[2]!.run();assert.equal(rendered.at(-1),summary);
  repeat();assert.deepEqual(rendered,[summary,summary]);
});

test('repeated semantic validation has a changed meaningful label, not only a transient blank',()=>{
  const message=formErrorSummary('weight',{average_weight_g:'Required.',sample_size:'Required.',reported_by_name:'Required.'})!;
  const first={message,attempt:1},second={message,attempt:2};
  assert.equal(liveErrorLabel(first,first),`Validation attempt 1. ${message}`);
  assert.equal(liveErrorLabel(second,second),`Validation attempt 2. ${message}`);
  assert.notEqual(liveErrorLabel(first,first),liveErrorLabel(second,second));
  assert.equal(liveErrorLabel(second,second),liveErrorLabel(second,second));
  assert.equal(liveErrorLabel(null,second),'');
  assert.equal(liveErrorLabel(first,second),'');
  assert.equal(liveErrorLabel(second,{message:null,attempt:2}),'');
  assert.equal(liveErrorText(second,second),`Validation attempt 2. ${message}`);
});

test('unsubmitted and non-form semantic errors do not invent a validation attempt',()=>{
  for(const attempt of [undefined,0,-1,Number.NaN,Number.POSITIVE_INFINITY,1.5]) {
    const current={message:'Could not recover the draft.',attempt};
    assert.equal(liveErrorLabel(current,current),current.message);
  }
});

test('semantic retry changes the actual live-region text as well as its name',()=>{
  const message=formErrorSummary('weight',{average_weight_g:'Required.',sample_size:'Required.',reported_by_name:'Required.'})!;
  const first={message,attempt:1},second={message,attempt:2};
  assert.equal(liveErrorText(first,first),`Validation attempt 1. ${message}`);
  assert.equal(liveErrorText(second,second),`Validation attempt 2. ${message}`);
  assert.notEqual(liveErrorText(first,first),liveErrorText(second,second));
  assert.equal(liveErrorText(second,second),liveErrorLabel(second,second));
  assert.equal(liveErrorText(first,second),'');
  assert.equal(liveErrorText(second,{message:null,attempt:2}),'');
});

test('each real failed submission replaces its semantic native node, not every redraw or timer delivery',()=>{
  assert.equal(semanticErrorRegionKey(1),'semantic-error:1');
  assert.equal(semanticErrorRegionKey(1),semanticErrorRegionKey(1));
  assert.notEqual(semanticErrorRegionKey(1),semanticErrorRegionKey(2));
  assert.notEqual(semanticErrorRegionKey(0),semanticErrorRegionKey(1));
  // Non-submission messages have no invented counters/notification identity.
  for(const attempt of [undefined,-1,Number.NaN,Number.POSITIVE_INFINITY,1.5,Number.MAX_SAFE_INTEGER+1]) {
    assert.equal(semanticErrorRegionKey(attempt),'semantic-error');
  }
});

test('empty or undelivered semantic summaries are not silent focus stops; delivered errors stay readable',()=>{
  const first={message:'Average live weight (grams): Required.',attempt:1};
  const repeat={...first,attempt:2};
  for(const text of ['', '   ',liveErrorText(null,first),liveErrorText(first,repeat),liveErrorText(first,{message:null,attempt:1})]) {
    assert.deepEqual(liveErrorAccessibility(text),{accessible:false,importantForAccessibility:'no-hide-descendants'});
  }
  for(const current of [first,repeat,{message:'Could not recover the draft.'}]) {
    assert.deepEqual(liveErrorAccessibility(liveErrorText(current,current)),{accessible:true,importantForAccessibility:'yes'});
    assert.equal(liveErrorText(current,current),liveErrorLabel(current,current));
  }
});
