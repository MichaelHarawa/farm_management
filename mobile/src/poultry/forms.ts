import type { Capabilities } from '../protocol';
import { farmEventFields, farmEventUtc } from '../components/event-time';
import { poultryCommand, type PoultryCommand } from './commands';

export type Workflow = 'mortality'|'feed'|'treatment'|'weight'|'proposal'|'book'|'mark_delivered'|'confirm_delivery';
export interface FormField { name:string; label:string; kind:'text'|'positive'|'signed'|'instant'|'date'|'choice'; choices?:string; optional?:boolean; max?:number }
export const workflows: Record<Workflow,{title:string;entity:string;action:string;fields:FormField[]}> = {
  mortality:{title:'Mortality',entity:'poultry.mortality',action:'record',fields:[
    {name:'mortality_date',label:'Farm mortality event',kind:'instant'},{name:'quantity_dead',label:'Dead birds (whole birds)',kind:'positive'},
    {name:'suspected_cause',label:'Suspected cause',kind:'text',max:200},{name:'description',label:'Description',kind:'text'},
    {name:'action_taken',label:'Action taken',kind:'text'},{name:'reported_by_name',label:'Observed reporter',kind:'text',max:200}]},
  feed:{title:'Feed',entity:'poultry.feed_usage',action:'record',fields:[
    {name:'feeding_start_date',label:'Feed start',kind:'instant'},{name:'feeding_end_date',label:'Feed end',kind:'instant'},
    {name:'feed_type',label:'Feed type',kind:'choice',choices:'feed_type'},{name:'feed_source',label:'Feed source',kind:'choice',choices:'feed_source'},
    {name:'quantity_given',label:'Quantity in selected unit (whole number)',kind:'positive'},
    {name:'unit_of_measurement',label:'Quantity unit',kind:'choice',choices:'unit_of_measurement'},
    {name:'notes',label:'Feed notes',kind:'text'},{name:'reported_by_name',label:'Observed reporter',kind:'text',max:200}]},
  treatment:{title:'Treatment / vaccination',entity:'poultry.treatment',action:'record',fields:[
    {name:'vaccination_date',label:'Treatment event',kind:'instant'},{name:'drug_category',label:'Treatment category',kind:'choice',choices:'drug_category'},
    {name:'drug_vaccination_type',label:'Treatment type',kind:'choice',choices:'drug_vaccination_type'},
    {name:'other_drug_vaccination',label:'Other treatment name',kind:'text',optional:true,max:200},
    {name:'quantity',label:'Quantity (record actual unit in description)',kind:'positive'},
    {name:'description',label:'Description including actual quantity unit',kind:'text'},
    {name:'timely_status',label:'Observed timing status',kind:'text',max:200},{name:'reported_by_name',label:'Observed reporter',kind:'text',max:200}]},
  weight:{title:'Weight sample',entity:'poultry.weight_sample',action:'record',fields:[
    {name:'sampled_at',label:'Weight sample event',kind:'instant'},{name:'average_weight_g',label:'Average live weight (grams)',kind:'positive'},
    {name:'sample_size',label:'Number of birds weighed',kind:'positive'},{name:'notes',label:'Sample notes',kind:'text',optional:true},
    {name:'reported_by_name',label:'Observed reporter',kind:'text',max:200}]},
  proposal:{title:'Flock adjustment proposal',entity:'poultry.adjustment_proposal',action:'propose',fields:[
    {name:'effective_at',label:'Original effective event',kind:'instant'},{name:'quantity_change',label:'Signed whole-bird change (+ arrivals / − removals)',kind:'signed'},
    {name:'reason',label:'Reason for proposed count correction',kind:'text',max:255}]},
  book:{title:'Book chicks',entity:'poultry.batch',action:'book',fields:[
    {name:'bird_type',label:'Bird type',kind:'choice',choices:'bird_type'},{name:'broiler_strain',label:'Broiler strain (if applicable)',kind:'choice',choices:'broiler_strain',optional:true},
    {name:'source',label:'Chick supplier source',kind:'choice',choices:'source'},{name:'source_other',label:'Other source name',kind:'text',optional:true,max:200},
    {name:'booking_date',label:'Booking farm date',kind:'date'},{name:'estimated_chick_arrival_date',label:'Estimated arrival farm date',kind:'date'},
    {name:'supplier_name',label:'Supplier name',kind:'text',optional:true,max:200},{name:'booking_reference',label:'Supplier booking reference (not official batch ID)',kind:'text',optional:true,max:120},
    {name:'expected_quantity',label:'Expected chicks (whole birds)',kind:'positive'},
    {name:'entry_date',label:'Planned entry',kind:'instant'},{name:'expected_maturity_date',label:'Expected maturity',kind:'instant'}]},
  mark_delivered:{title:'Mark delivered',entity:'poultry.batch',action:'mark_delivered',fields:[]},
  confirm_delivery:{title:'Confirm actual arrival',entity:'poultry.batch',action:'confirm_delivery',fields:[
    {name:'entry_date',label:'Actual arrival',kind:'instant'},{name:'expected_maturity_date',label:'Expected maturity',kind:'instant'},
    {name:'quantity',label:'Actual chicks received (whole birds)',kind:'positive'}]},
};
export function formDefaults(workflow:Workflow, now=new Date().toISOString()):Record<string,string> {
  const values:Record<string,string>={batch_uuid:''}; const parts=farmEventFields(now);
  for(const field of workflows[workflow].fields){values[field.name]='';
    if(field.kind==='date')values[field.name]=parts.event_day;
    if(field.kind==='instant'){const instant=field.name==='expected_maturity_date'?new Date(Date.parse(now)+46*86400000).toISOString():now;
      const date=farmEventFields(instant);values[`${field.name}:day`]=date.event_day;values[`${field.name}:time`]=date.event_time;}}
  return values;
}
export function formErrorSummary(workflow:Workflow, errors:Record<string,string>):string|null {
  const messages=Object.entries(errors).filter(([,message])=>message.trim()).map(([name,message])=>{
    const label=name==='form'?null:name==='batch_uuid'?'Batch':
      workflows[workflow].fields.find(field=>field.name===name)?.label??name.replaceAll('_',' ');
    return label?`${label}: ${message}`:message;
  });
  return messages.length?messages.join(' '):null;
}
export function buildFormCommand(workflow:Workflow,values:Record<string,string>,caps:Capabilities,envelope:{
  operation_id:string; entity_uuid:string; captured_at:string; depends_on:string[]; base_version:string|null; supersedes_operation_id?:string;
}): {command:PoultryCommand|null; errors:Record<string,string>} {
  const errors:Record<string,string>={},payload:Record<string,unknown>={};
  if(workflow!=='book')payload.batch_uuid=values.batch_uuid;
  for(const field of workflows[workflow].fields){
    const value=values[field.name]??'';
    if(field.kind==='instant'){try{payload[field.name]=farmEventUtc(values[`${field.name}:day`]??'',values[`${field.name}:time`]??'');}
      catch{errors[field.name]='Choose a valid farm date and time.';}continue;}
    if(!value.trim()&&!field.optional){errors[field.name]='Required.';continue;}
    if(field.optional&&!value)continue;
    if(field.kind==='positive'||field.kind==='signed'){
      const valid=(field.kind==='positive'?/^\d+$/:/^[+-]?\d+$/).test(value)&&Number.isSafeInteger(Number(value))&&Number(value)!==0&&
        Number(value)<=2147483647&&Number(value)>=-2147483648&&(field.kind==='signed'||Number(value)>0);
      if(!valid)errors[field.name]='Enter a nonzero whole number within the allowed range.';else payload[field.name]=Number(value);
    }else if(field.kind==='choice'&&!caps.lookups?.choices[field.choices!]?.some(c=>c.value===value))errors[field.name]='Choose a downloaded reference value.';
    else {if(value.length>(field.max??4000))errors[field.name]='Text exceeds the source field limit.';payload[field.name]=value;}
  }
  if(values.source==='other'&&!values.source_other?.trim())errors.source_other='Enter the source name.';
  if(values.drug_vaccination_type==='other'&&!values.other_drug_vaccination?.trim())errors.other_drug_vaccination='Enter the treatment name.';
  if(Object.keys(errors).length)return {command:null,errors};
  const definition=workflows[workflow];
  const parsed=poultryCommand.safeParse({...envelope,entity_type:definition.entity,action:definition.action,payload_version:1,payload});
  return parsed.success?{command:parsed.data,errors}:{command:null,errors:{form:'Check the selected batch, original dates and required fields.'}};
}

export function formFromCommand(workflow:Workflow,command:PoultryCommand):Record<string,string> {
  const definition=workflows[workflow];
  if(command.entity_type!==definition.entity||command.action!==definition.action)throw new Error('correction_workflow_mismatch');
  const values:Record<string,string>={batch_uuid:'batch_uuid' in command.payload?command.payload.batch_uuid:''};
  for(const field of definition.fields){const value=(command.payload as Record<string,unknown>)[field.name];
    if(field.kind==='instant'){const parts=farmEventFields(String(value));values[field.name]='';values[`${field.name}:day`]=parts.event_day;values[`${field.name}:time`]=parts.event_time;}
    else values[field.name]=value===undefined?'':String(value);
  }
  return values;
}
