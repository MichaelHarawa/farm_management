from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0011_expenditure_reversed_at_expenditure_reversed_by"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="costallocation",
            name="cost_allocation_exactly_one_source",
        ),
        migrations.AddConstraint(
            model_name="costallocation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        payroll_entry__isnull=False,
                        ad_hoc_labour_payment__isnull=True,
                        shared_expense__isnull=True,
                        consumable_usage__isnull=True,
                        depreciation_entry__isnull=True,
                        expenditure__isnull=True,
                    )
                    | models.Q(
                        payroll_entry__isnull=True,
                        ad_hoc_labour_payment__isnull=False,
                        shared_expense__isnull=True,
                        consumable_usage__isnull=True,
                        depreciation_entry__isnull=True,
                        expenditure__isnull=True,
                    )
                    | models.Q(
                        payroll_entry__isnull=True,
                        ad_hoc_labour_payment__isnull=True,
                        shared_expense__isnull=False,
                        consumable_usage__isnull=True,
                        depreciation_entry__isnull=True,
                        expenditure__isnull=True,
                    )
                    | models.Q(
                        payroll_entry__isnull=True,
                        ad_hoc_labour_payment__isnull=True,
                        shared_expense__isnull=True,
                        consumable_usage__isnull=False,
                        depreciation_entry__isnull=True,
                        expenditure__isnull=True,
                    )
                    | models.Q(
                        payroll_entry__isnull=True,
                        ad_hoc_labour_payment__isnull=True,
                        shared_expense__isnull=True,
                        consumable_usage__isnull=True,
                        depreciation_entry__isnull=False,
                        expenditure__isnull=True,
                    )
                    | models.Q(
                        payroll_entry__isnull=True,
                        ad_hoc_labour_payment__isnull=True,
                        shared_expense__isnull=True,
                        consumable_usage__isnull=True,
                        depreciation_entry__isnull=True,
                        expenditure__isnull=False,
                    )
                ),
                name="cost_allocation_exactly_one_source",
            ),
        ),
        migrations.AddConstraint(
            model_name="costallocation",
            constraint=models.UniqueConstraint(
                condition=models.Q(expenditure__isnull=False),
                fields=("accounting_period", "batch", "expenditure"),
                name="unique_expenditure_allocation_period_batch",
            ),
        ),
    ]
