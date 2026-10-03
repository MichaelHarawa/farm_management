import { instant } from '../protocol';

// Display policy only. Django's historical UTC data/timezone are not changed.
export const farmTimezone = 'Africa/Blantyre';
const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: farmTimezone,
  year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23' });
export function farmEventFields(utc: string) {
  instant.parse(utc);
  const parts = Object.fromEntries(formatter.formatToParts(new Date(utc)).map(p=>[p.type,p.value]));
  const fraction = utc.match(/(\.\d{1,6})Z$/)?.[1] ?? '';
  return { event_day:`${parts.year}-${parts.month}-${parts.day}`, event_time:`${parts.hour}:${parts.minute}:${parts.second}${fraction}` };
}
export function farmEventUtc(day: string, time: string): string {
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  const clock = /^(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?$/.exec(time);
  if (!date || !clock || Number(date[1]) < 1900 || Number(clock[1]) > 23 || Number(clock[2]) > 59 || Number(clock[3]) > 59) throw new Error('invalid_farm_event_time');
  const naive = new Date(`${day}T${time.slice(0,8)}Z`);
  if (!Number.isFinite(naive.getTime()) || naive.toISOString().slice(0,10)!==day) throw new Error('invalid_farm_event_time');
  // Derive the IANA offset at this event, not the device timezone or its current date.
  const display = farmEventFields(naive.toISOString());
  const displayedMs = Date.parse(`${display.event_day}T${display.event_time.slice(0,8)}Z`);
  const resolved = new Date(naive.getTime()-(displayedMs-naive.getTime())).toISOString().replace(/\.000Z$/,`${clock[4]??''}Z`);
  const roundtrip = farmEventFields(resolved);
  if (roundtrip.event_day!==day || roundtrip.event_time!==time) throw new Error('invalid_farm_event_time');
  return instant.parse(resolved);
}
