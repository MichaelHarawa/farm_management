"""Read COPY data extracted with pg_restore; never execute dump SQL."""
import re, json, os
from pathlib import Path
from decimal import Decimal as D
from collections import defaultdict

ROOT = Path(__file__).parent
tables = {}
current = None
for line in (Path(os.environ['TEMP']) / 'farm_business_review_data.sql').read_text(encoding='utf-8').splitlines():
    m = re.match(r'COPY public\.(\w+) \((.*?)\) FROM stdin;', line)
    if m:
        current = m[1]; columns = m[2].split(', '); tables[current] = []
    elif line == r'\.': current = None
    elif current:
        cells = line.split('\t')
        assert len(cells) == len(columns), current
        def decode(v):
            if v == r'\N': return None
            return re.sub(r'\\([\\tnr])', lambda m: {'t':'\t','n':'\n','r':'\r','\\':'\\'}[m[1]], v)
        tables[current].append(dict(zip(columns, map(decode, cells))))

def rows(name): return tables.get('finance_'+name, tables.get('poultry_'+name, []))
def num(v): return D(v or '0')
def total(rs, field): return sum((num(r[field]) for r in rs), D(0))
def group(rs, key, field):
    result = defaultdict(D)
    for r in rs: result[r[key]] += num(r[field])
    return dict(result)
def brief(name, exclude=()):
    return [{k:v for k,v in r.items() if k not in {'created_by_id','updated_by_id','generated_by_id','created_at','updated_at',*exclude}} for r in rows(name)]
def output(value): print(json.dumps(value, default=str, indent=2))

if __name__ == '__main__':
    output({'counts':{k:len(v) for k,v in tables.items()},
      'batches':brief('batch'), 'snapshots':brief('batchprofitabilitysnapshot'),
      'periods':brief('accountingperiod'),
      'expenses_by_nature':group(rows('expenditure'),'accounting_nature','amount'),
      'expenses_by_status':group(rows('expenditure'),'status','amount'),
      'cost_allocations_by_type':group(rows('costallocation'),'source_type','allocated_amount'),
      'payroll':brief('payrollentry',('notes',)), 'shared_expenses':brief('sharedexpense'),
      'assets':brief('asset',('custodian','supplier','serial_number','notes'))})
