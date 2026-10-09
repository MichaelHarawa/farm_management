"""Positive poultry projection2 schemas; legacy v1 shapes remain frozen.

Requests are generated from the explicit typed serializers, not source models.
No caller-controlled model name, cost or unrestricted CRUD is documented.
"""
from copy import deepcopy
from rest_framework import serializers as drf
from . import schema as v1
from .profiles import V2_COMMANDS

TEXT,UUID,INSTANT,COUNTER,INTEGER,BOOL=v1.TEXT,v1.UUID,v1.INSTANT,v1.COUNTER,v1.INTEGER,v1.BOOL
obj,array=v1.obj,v1.array
DECIMAL={'type':'string','pattern':r'^-?\d+(\.\d+)?$','maxLength':60}
def nullable(value):return {**value,'nullable':True}

SAMPLE=obj({'sampled_at':INSTANT,'sample_size':INTEGER,'average_weight_g':INTEGER,'age_in_days':INTEGER,
    'target_weight_g':nullable(INTEGER),'strain':nullable(TEXT),'deviation_percent':nullable(DECIMAL)})
SUMMARY=obj({'calculation_version':TEXT,'feed_record_count':INTEGER,'feed_total_kg':DECIMAL,'feed_per_bird_started_kg':nullable(DECIMAL),
    'feed_denominator':{'type':'string','enum':['actual_birds_received']},'feed_denominator_birds':INTEGER,
    'growth':obj({'state':{'type':'string','enum':['missing_sample','target_available','target_not_applicable']},'sample':nullable(SAMPLE)}),
    'mortality':obj({'dead_birds':INTEGER,'actual_arrivals':INTEGER,'rate_percent':nullable(DECIMAL),'threshold_percent':DECIMAL,'alert':nullable(BOOL),'formula':TEXT}),
    'stock_integration':{'type':'string','enum':['not_linked_phase6']},'fcr':{'type':'string','nullable':True,'enum':[None]}})
PAYLOADS={'poultry.batch':obj({**v1.BATCH_PAYLOAD['properties'],'supplier_name':TEXT,'booking_reference':TEXT,'operational_summary':SUMMARY}),
    'poultry.mortality':v1.MORTALITY_PAYLOAD,'poultry.feed_usage':v1.FEED_PAYLOAD,
    'poultry.treatment':obj({**v1.COMMON,'batch_uuid':UUID,'vaccination_date':INSTANT,'drug_category':TEXT,'drug_vaccination_type':TEXT,
        'other_drug_vaccination':TEXT,'quantity':INTEGER,'description':TEXT,'timely_status':TEXT,'reported_by_name':TEXT}),
    'poultry.weight_sample':obj({**v1.COMMON,'batch_uuid':UUID,'sampled_at':INSTANT,'age_in_days':INTEGER,'sample_size':INTEGER,
        'average_weight_g':INTEGER,'notes':TEXT,'reported_by_name':TEXT}),
    'poultry.flock_adjustment':obj({**v1.COMMON,'batch_uuid':UUID,'effective_at':INSTANT,'quantity_change':INTEGER,'reason':TEXT,'status':{'type':'string','enum':['approved','reversed']}}),
    'poultry.adjustment_proposal':obj({**v1.COMMON,'batch_uuid':UUID,'effective_at':INSTANT,'quantity_change':INTEGER,'reason':TEXT,
        'status':{'type':'string','enum':['pending','approved','rejected']},'review_reason':TEXT,'adjustment_server_id':nullable(COUNTER)})}
ENTITY={'oneOf':[obj({'entity_type':{'type':'string','enum':[kind]},'entity_uuid':UUID,'revision':COUNTER,'payload':payload}) for kind,payload in PAYLOADS.items()]}
PAGE=obj({**v1.PAGE['properties'],'entities':array(ENTITY)},optional=('delta_cursor',))
CHANGE=obj({**v1.CHANGE['properties'],'entity_type':{'type':'string','enum':list(PAYLOADS)},'payload':{'oneOf':list(PAYLOADS.values())}},optional=('payload','origin_operation_id'))
CHANGES=obj({**v1.CHANGES['properties'],'changes':array(CHANGE)})
MAPPING=obj({'entity_type':{'type':'string','enum':list(PAYLOADS)},'entity_uuid':UUID,'server_id':COUNTER,'revision':COUNTER})
RESULT=obj({'operation_id':UUID,'outcome':{'type':'string','enum':['accepted','replayed','conflict','validation_failed','period_locked','permission_denied','dependency_blocked','retry_later']},
    'code':TEXT,'message':TEXT,'field_errors':{'type':'object','additionalProperties':True},'recovery_action':TEXT,
    'canonical_entities':array({'anyOf':[v1.ENTITY,ENTITY]}),'entity_mappings':array(MAPPING),'transaction_id':UUID,'committed_at':INSTANT},
    optional=('canonical_entities','entity_mappings','transaction_id','committed_at'))
PUSH_RESPONSE=obj({'protocol_version':{'type':'integer','enum':[1]},'deployment_id':UUID,'device_id':UUID,'server_time':INSTANT,'results':array(RESULT)})

def input_field(field):
    from .serializers import StrictUUID,UTCInstant,FarmDate
    if isinstance(field,StrictUUID):value={**UUID,'pattern':r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$'}
    elif isinstance(field,UTCInstant):value={**INSTANT,'pattern':r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$'}
    elif isinstance(field,FarmDate):value={'type':'string','format':'date','pattern':r'^\d{4}-\d{2}-\d{2}$'}
    elif isinstance(field,drf.IntegerField):
        value={**INTEGER}
        for attribute,key in [('min_value','minimum'),('max_value','maximum')]:
            if getattr(field,attribute,None) is not None:value[key]=getattr(field,attribute)
    elif isinstance(field,drf.ChoiceField):value={'type':'string','enum':list(field.choices)+([''] if getattr(field,'allow_blank',False) and '' not in field.choices else [])}
    elif isinstance(field,drf.CharField):
        value={**TEXT}
        if field.max_length is not None:value['maxLength']=field.max_length
        if not field.allow_blank:value['pattern']=r'\S'
    else:raise TypeError('Explicit typed field schema required.')
    return value

def operation_schema():
    from .serializers import PAYLOAD_SERIALIZERS
    variants=[]
    for kind,action,_ in V2_COMMANDS:
        serializer=PAYLOAD_SERIALIZERS[(kind,action)]
        fields=serializer().fields
        payload=obj({key:input_field(field) for key,field in fields.items()},optional=[key for key,field in fields.items() if not field.required])
        if action=='propose':payload['properties']['quantity_change']['not']={'enum':[0]}
        revision=nullable({**COUNTER,'pattern':'^[1-9][0-9]{0,39}$'}) if action in {'mark_delivered','confirm_delivery','approve','reject','recalculate_feed'} else {'type':'string','nullable':True,'enum':[None]}
        variants.append(obj({'operation_id':UUID,'entity_uuid':UUID,'entity_type':{'type':'string','enum':[kind]},'action':{'type':'string','enum':[action]},
            'payload_version':{'type':'integer','enum':[1]},'base_version':revision,'captured_at':INSTANT,
            'depends_on':{'type':'array','items':UUID,'maxItems':20,'uniqueItems':True},'supersedes_operation_id':UUID,'payload':payload},optional=('supersedes_operation_id',)))
    return {'oneOf':variants}

def push_schema():return obj({'protocol_version':{'type':'integer','enum':[1]},'device_id':UUID,'operations':{'type':'array','items':operation_schema(),'minItems':1,'maxItems':50}})

def capabilities_schema():
    from .commands.registry import registry_for_version
    result=deepcopy(v1.CAPABILITIES)
    for key in ['schema_version','projection_version']:result['properties'][key]={'type':'integer','enum':[2]}
    result['properties']['commands']=obj({**{f'{kind}.{action}':obj({'available':BOOL,'payload_version':INTEGER,'capability':TEXT,
        'mode':{'type':'string','enum':[spec.mode]}}) for (kind,action,_),spec in registry_for_version(2).items()},'finance':obj({'available':BOOL,'reason':TEXT})})
    result['properties']['lookups']=obj({'version':INTEGER,'choices':{'type':'object','additionalProperties':array(obj({'value':TEXT,'label':TEXT}))},
        'treatment_quantity_unit':TEXT,'stock_linked_capture':{'type':'boolean','enum':[False]},'mortality_threshold_percent':DECIMAL})
    result['required'].append('lookups')
    return result
