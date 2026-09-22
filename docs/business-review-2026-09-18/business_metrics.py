from analyze_dump import *
from datetime import date
exp = {r['id']:r for r in rows('expenditure')}
cats = {r['id']:r for r in rows('expenditurecategory')}
sources = {r['id']:r for r in rows('fundingsource')}
sales = [s for s in rows('sales') if s['payment_status']!='cancelled']
payments = [p for p in rows('salepayment') if p['status']=='posted']
valid_exp = [e for e in exp.values() if e['status']=='posted']
result = {'batches':[], 'costs_by_category':{}, 'funding':{}, 'exceptions':{}}
for b in sorted(rows('batch'),key=lambda b:b['entry_date']):
    bid=b['id']; ss=[s for s in sales if s['batch_id']==bid]
    for s in ss: s['revenue']=str(num(s['quantity_sold'])*num(s['unit_price']))
    alloc=[a for a in rows('costallocation') if a['batch_id']==bid]
    costcat=defaultdict(D); details=[]
    for a in alloc:
        e=exp.get(a['expenditure_id'])
        if e and e['status']=='posted':
            category=cats[e['category_id']]['name']; costcat[category]+=num(a['allocated_amount'])
            details.append({'id':e['id'],'date':e['expenditure_date'],'category':category,'amount':a['allocated_amount'],'description':e['description'],'nature':e['accounting_nature']})
    inputs=[i for i in rows('inputcosts') if i['batch_id']==bid]
    inputdetails=[{k:i[k] for k in ('id','item','category','quantity','unit','unit_measurement','unit_cost','purchase_date','expenditure_id')} for i in inputs]
    mortality=[{k:m[k] for k in ('mortality_date','quantity_dead','age_in_days','suspected_cause','description')} for m in rows('mortality') if m['batch_id']==bid]
    feeds=[{k:f[k] for k in ('feeding_start_date','feeding_end_date','feed_type','quantity_given','unit_of_measurement','current_number_of_birds')} for f in rows('feedusage') if f['batch_id']==bid]
    pricebins=defaultdict(lambda:{'birds':D(0),'revenue':D(0)})
    for s in ss:
        key=s['product_type']+' @ '+s['unit_price'];pricebins[key]['birds']+=num(s['quantity_sold']);pricebins[key]['revenue']+=num(s['revenue'])
    result['batches'].append({'batch':b['batch_id'],'id':bid,'revenue':total(ss,'revenue'),'sale_summary_collected':total(ss,'amount_paid'),
      'ledger_collected':sum((num(p['amount']) for p in payments if p['sale_id'] in {s['id'] for s in ss}),D(0)),
      'sales_by_price':dict(pricebins),'first_sale':min([s['sale_date'] for s in ss],default=None),'last_sale':max([s['sale_date'] for s in ss],default=None),
      'cost_categories':dict(costcat),'cost_details':details,'input_details':inputdetails,'mortality':mortality,'feed_usage':feeds})
for e in valid_exp:
    name=cats[e['category_id']]['name'];result['costs_by_category'].setdefault(name,D(0));result['costs_by_category'][name]+=num(e['amount'])
for src in sources.values():
    receipts=[r for r in rows('fundingreceipt') if r['funding_source_id']==src['id'] and r['status']=='posted']
    used=[a for a in rows('fundingallocation') if a['funding_source_id']==src['id'] and exp[a['expenditure_id']]['status']=='posted']
    result['funding'][src['id']]={'type':src['source_type'],'batch':src['batch_id'],'received':total(receipts,'amount'),'used':total(used,'amount')}
result['owner_withdrawals']=[{k:e[k] for k in ('id','expenditure_date','amount','description','payment_status')} for e in valid_exp if e['accounting_nature']=='owner_withdrawal']
result['receivables']=[{'sale':s['sale_id'],'date':s['sale_date'],'due':s['due_date'],'buyer':s['buyer_name'],'balance':s['balance'],'quantity':s['quantity_sold'],'unit_price':s['unit_price']} for s in sales if num(s['balance'])>0]
result['exceptions']['unlinked_inputs']=[i['id'] for i in rows('inputcosts') if not i['expenditure_id']]
result['exceptions']['funding_payment_total']=sum((num(a['amount']) for a in rows('fundingallocation') if exp[a['expenditure_id']]['status']=='posted'),D(0))
result['exceptions']['expenditure_payment_status']=group(valid_exp,'payment_status','amount')
result['exceptions']['void_expenditures']=[{k:e[k] for k in ('id','amount','description')} for e in exp.values() if e['status']!='posted']
(ROOT/'business_metrics.json').write_text(json.dumps(result,default=str,indent=2),encoding='utf-8')
output(result)
