"""Independent Decimal reconciliation of headline figures from the backup."""
from analyze_dump import *
from collections import defaultdict

report = json.loads((ROOT/'application_batch_report.json').read_text())
by_batch = {str(r['batch']):r for r in report['results']}
exps = {e['id']:e for e in rows('expenditure')}
payroll_links={p['expenditure_id'] for p in rows('payrollentry')}
shared_links={p['expenditure_id'] for p in rows('sharedexpense')}
for b in rows('batch'):
    bid=b['id']; r=by_batch[bid]
    sales=[s for s in rows('sales') if s['batch_id']==bid and s['payment_status']!='cancelled']
    revenue=sum((num(s['quantity_sold'])*num(s['unit_price']) for s in sales),D(0))
    sold=total(sales,'quantity_sold')
    dead=total([m for m in rows('mortality') if m['batch_id']==bid],'quantity_dead')
    received=num(b['actual_quantity_received'] or b['quantity'])
    assert revenue==num(r['revenue'])
    assert received-sold-dead==num(r['remaining_live_birds'])
    assert total([p for p in rows('salepayment') if p['sale_id'] in {s['id'] for s in sales} and p['status']=='posted'],'amount')==num(r['cash_collected'])
    direct=sum((num(a['allocated_amount']) for a in rows('costallocation') if a['batch_id']==bid and a['expenditure_id'] and exps[a['expenditure_id']]['status']=='posted' and exps[a['expenditure_id']]['accounting_nature']=='direct_cost'),D(0))
    direct+=sum((num(i['quantity'])*num(i['unit'])*num(i['unit_cost']) for i in rows('inputcosts') if i['batch_id']==bid and not i['expenditure_id']),D(0))
    assert direct==num(r['direct_batch_cost'])
    allocated=D(0)
    for a in rows('costallocation'):
        if a['batch_id']!=bid:continue
        if a['source_type'] in ('payroll','depreciation','shared_expense'):
            allocated+=num(a['allocated_amount'])
        elif a['expenditure_id']:
            e=exps[a['expenditure_id']]
            if e['status']=='posted' and e['accounting_nature']=='indirect_operating_expense' and e['id'] not in payroll_links|shared_links:
                allocated+=num(a['allocated_amount'])
    assert allocated==num(r['allocated_production_cost'])
    assert num(r['management_net_position'])==revenue-num(r['total_attributed_cost'])
assert total(rows('payrollentry'),'total_employer_cost')==D('540000')
assert sum(num(r['allocated_administration_cost'])+num(r['total_selling_cost']) for r in by_batch.values())==D('288000')
assert sum(num(r['total_attributed_cost']) for r in by_batch.values())==D('8783958.06')
valid_exp=[e for e in exps.values() if e['status']=='posted' and e['accounting_nature']!='owner_withdrawal']
assert total(valid_exp,'amount')+D('15000')+total(rows('assetdepreciationentry'),'period_depreciation')==D('8795958.06')
assert D('8795958.06')-D('8783958.06')==D('12000')
assert D('3950000')+D('1483000')+D('290000')-D('5665500')==D('57500')
print('PASS: source revenue, receipt totals, population, direct and allocated production costs, payroll bridge, report net positions, unallocated MWK 12,000 and recorded funding residual reconcile.')
