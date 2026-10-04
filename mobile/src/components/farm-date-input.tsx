import { DateTimePickerAndroid } from '@react-native-community/datetimepicker';
import { Alert } from 'react-native';
import { farmEventFields, farmEventUtc, farmTimezone } from './event-time';
import { Body, Button } from './ui';

export function FarmDateInput({label,day,time,onChange,disabled=false,dateOnly=false}: {
  label:string; day:string; time:string; onChange(day:string,time:string):void; disabled?:boolean; dateOnly?:boolean;
}) {
  function choose(mode:'date'|'time') {
    // Never reinterpret farm intent in the handset timezone.
    let value:Date;
    try {value=new Date(farmEventUtc(day,time));}
    catch {Alert.alert('Original date needs review','The saved date/time is invalid. No event or date was changed. Clear this unsubmitted form only if you want to enter new values.');return;}
    DateTimePickerAndroid.open({ value, mode, is24Hour:true, timeZoneName:farmTimezone,
      onChange:(event,selected)=>{if(event.type!=='set'||!selected)return;
        const fields=farmEventFields(selected.toISOString());
        onChange(mode==='date'?fields.event_day:day,mode==='time'?fields.event_time:time);
      } });
  }
  return <><Body>{label}: {day}{!dateOnly&&` ${time}`} • {farmTimezone}</Body>
    <Button title={`Choose ${label} date`} disabled={disabled} onPress={()=>choose('date')}/>
    {!dateOnly&&<Button title={`Choose ${label} time`} disabled={disabled} onPress={()=>choose('time')}/>}</>;
}
