from datetime import date

from django.db import migrations


ACCOUNTS = [
    ("1000", "Farm cash and bank", "asset", "debit", "cash"),
    ("1100", "Customer receivables", "asset", "debit", "receivable"),
    ("1200", "Consumable inventory", "asset", "debit", "inventory"),
    ("1300", "Poultry work in progress", "asset", "debit", "biological_wip"),
    ("1500", "Fixed assets at cost", "asset", "debit", "fixed_asset"),
    ("1590", "Accumulated depreciation", "asset", "credit", "accumulated_depreciation"),
    ("2000", "Supplier payables", "liability", "credit", "payable"),
    ("2100", "Payroll payable", "liability", "credit", "payroll_payable"),
    ("2110", "Statutory payroll liabilities", "liability", "credit", "statutory_payable"),
    ("2200", "Loans payable", "liability", "credit", "loan"),
    ("3000", "Owner capital", "equity", "credit", "owner_equity"),
    ("3100", "Owner drawings", "equity", "debit", "owner_drawings"),
    ("4000", "Poultry sales revenue", "revenue", "credit", "sales"),
    ("5000", "Direct poultry costs", "expense", "debit", "direct_cost"),
    ("5100", "Production payroll", "expense", "debit", "production_payroll"),
    ("5200", "Production overhead", "expense", "debit", "production_overhead"),
    ("6000", "Selling and distribution", "expense", "debit", "selling"),
    ("6100", "Administration", "expense", "debit", "administration"),
    ("6200", "Depreciation and impairment", "expense", "debit", "depreciation"),
    ("7000", "Finance costs", "expense", "debit", "finance_cost"),
    ("7100", "Recorded tax", "expense", "debit", "tax"),
]


def seed(apps, schema_editor):
    ChartOfAccount = apps.get_model("finance", "ChartOfAccount")
    ReportingPolicy = apps.get_model("finance", "ReportingPolicy")
    AllocationPolicy = apps.get_model("finance", "AllocationPolicy")
    for code, name, account_type, normal_balance, control_type in ACCOUNTS:
        ChartOfAccount.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "normal_balance": normal_balance,
                "control_type": control_type,
                "is_active": True,
            },
        )
    ReportingPolicy.objects.get_or_create(
        code="MANAGEMENT_COST_V1",
        defaults={
            "name": "Lifecycle management-cost reporting",
            "version": 1,
            "effective_from": date(2026, 1, 1),
            "inventory_costing_method": "weighted_average",
            "biological_asset_basis": "management_cost",
            "administration_driver": "bird_days",
            "selling_driver": "revenue_share",
            "notes": "Internal management reporting only; not an IAS 41 fair-value policy.",
            "is_active": True,
        },
    )
    for pool, driver in [
        ("production", "bird_days"),
        ("administration", "bird_days"),
        ("selling", "revenue_share"),
        ("finance_cost", "revenue_share"),
        ("tax", "revenue_share"),
    ]:
        AllocationPolicy.objects.get_or_create(
            cost_pool=pool,
            version=1,
            defaults={
                "name": f"{pool.replace('_', ' ').title()} allocation",
                "driver": driver,
                "effective_from": date(2026, 1, 1),
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("finance", "0020_general_ledger_and_period_snapshots")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
