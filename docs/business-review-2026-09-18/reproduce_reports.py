"""Reproduce application reports using an isolated, read-only SQLite copy.
PostgreSQL dump SQL is never executed. Only decoded finance/poultry rows load.
"""
import os, sys, json, sqlite3, datetime
from pathlib import Path
from analyze_dump import tables, ROOT

repo = ROOT.parent.parent
sys.path.insert(0, str(repo / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.conf import settings
db_path = Path(os.environ['TEMP']) / 'farm_business_review_offline.sqlite3'
settings.DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':str(db_path)}}
import django
django.setup()
from django.apps import apps
from django.db import connection
from django.db.models import BooleanField
with connection.cursor() as cur:
    cur.execute('PRAGMA foreign_keys=OFF')
    for model in apps.get_models():
        name = model._meta.db_table
        if name not in tables: continue
        cur.execute(f'DROP TABLE IF EXISTS "{name}"')
        fields = {f.column:f for f in model._meta.local_fields}
        cols = list(tables[name][0]) if tables[name] else list(fields)
        defs = [f'"{c}" {fields[c].db_type(connection) if c in fields else "text"}' for c in cols]
        cur.execute(f'CREATE TABLE "{name}" ({",".join(defs)})')
        raw_rows = []
        for row in tables[name]:
            raw_rows.append([int(row[c]=='t') if isinstance(fields.get(c),BooleanField) and row[c] is not None else row[c] for c in cols])
        if raw_rows:
            colsql = ','.join('"'+c+'"' for c in cols)
            cur.executemany(f'INSERT INTO "{name}" ({colsql}) VALUES ({",".join(["%s"]*len(cols))})', raw_rows)
    cur.execute('PRAGMA query_only=ON')

# Fix the report's as-of date to the backup date, independent of execution date.
from unittest.mock import patch
from apps.poultry.models import Batch
from apps.finance.services.profitability import batch_portfolio_report
with patch('django.utils.timezone.localdate', return_value=datetime.date(2026,9,18)):
    report = batch_portfolio_report(Batch.objects.all())
(ROOT / 'application_batch_report.json').write_text(json.dumps(report,default=str,indent=2),encoding='utf-8')
print(json.dumps(report,default=str,indent=2))
