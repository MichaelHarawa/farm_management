export interface ErrorAnnouncement { message: string | null; attempt?: number }

export function androidErrorMode(platform:string,version:string|number,announce=true) {
  if(!announce||platform!=='android')return 'quiet';
  return Number(version)>=36?'semantic':'legacy';
}

// An undelivered submission renders an empty persistent live-region node.
export function liveErrorText(delivered:ErrorAnnouncement|null,current:ErrorAnnouncement) {
  if(!current.message||delivered?.message!==current.message||!Object.is(delivered?.attempt,current.attempt))return '';
  const {message,attempt}=current;
  return typeof attempt==='number'&&Number.isSafeInteger(attempt)&&attempt>0?
    `Validation attempt ${attempt}. ${message}`:message;
}

// Keep visible text and spoken name identical. A changed name on identical
// native text did not pass API36 TalkBack's controlled repeated-submit check.
export function liveErrorLabel(delivered:ErrorAnnouncement|null,current:ErrorAnnouncement) {
  return liveErrorText(delivered,current);
}

// Keep the native live region mounted for delayed delivery, but never expose
// its empty placeholder as a silent TalkBack focus stop before Save.
export function liveErrorAccessibility(text:string) {
  const accessible=text.trim().length>0;
  return {accessible,importantForAccessibility:accessible?'yes' as const:'no-hide-descendants' as const};
}

// TalkBack's content-change handling is node-specific. The real submission
// counter replaces only this native summary node, initially empty and then
// populated by the cancelable delivery. Redraws/timer delivery retain its key.
// No random IDs, duplicate regions, synthetic retries or focus movement.
export function semanticErrorRegionKey(attempt?:number) {
  return typeof attempt==='number'&&Number.isSafeInteger(attempt)&&attempt>=0?
    `semantic-error:${attempt}`:'semantic-error';
}

// Canceling on replacement/unmount prevents an old account/screen's late text.
export function deferLiveError(message:string,setText:(text:string)=>void,later:(work:()=>void)=>()=>void) {
  let active=true;
  const cancel=later(()=>{if(active)setText(message);});
  return()=>{active=false;cancel();};
}

// A render of the same error is not a new announcement. A new failed submit
// must announce again even if React batches clearing/re-setting identical text.
export function announceErrorChange(
  previous: ErrorAnnouncement | null,
  current: ErrorAnnouncement,
  announce: (message: string) => void,
) {
  if (current.message && (previous?.message !== current.message || !Object.is(previous?.attempt,current.attempt))) {
    announce(current.message);
  }
  return current;
}
