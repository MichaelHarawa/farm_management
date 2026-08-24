from __future__ import annotations


WARNING_GUIDANCE: dict[str, dict[str, str]] = {
    "high_mortality": {
        "solution": (
            "Review the mortality register, confirm the recorded cause and action "
            "taken, and record any veterinary or husbandry intervention."
        ),
        "action_label": "Open mortality records",
        "action_href": "/poultry",
    },
    "past_maturity_no_sales": {
        "solution": (
            "Confirm whether the flock is ready for sale. Record the first valid sale, "
            "or correct the maturity plan if the expected date has changed."
        ),
        "action_label": "Open batch sales",
        "action_href": "/poultry",
    },
    "stale_batch_updates": {
        "solution": (
            "Record the latest feed, mortality, health, or flock activity so bird "
            "balances and cost projections use current operating data."
        ),
        "action_label": "Open flock record",
        "action_href": "/poultry",
    },
    "overdue_receivables": {
        "solution": (
            "Review each outstanding sale and follow up with the buyer. Do not overwrite "
            "a historical sale to recognize later cash: this system still needs a dated "
            "receipt ledger, so use the farm's controlled receipt process until it is added."
        ),
        "action_label": "Review receivables",
        "action_href": "/finance/receivables",
    },
    "unallocated_shared_expenses": {
        "solution": (
            "Review the expense scope and allocation driver. Existing source fields "
            "are not editable in the UI, so escalate any correction; after review, "
            "recalculate the open period under Payroll."
        ),
        "action_label": "Review shared expenses",
        "action_href": "/finance/expenses#expense-ledger",
    },
    "unallocated_payroll": {
        "solution": (
            "Verify employee production percentages, generate payroll if required, "
            "and recalculate the open period before closing it. Existing percentages "
            "are not yet editable in the UI, so escalate any correction."
        ),
        "action_label": "Review payroll allocation",
        "action_href": "/finance/payroll#period-actions",
    },
    "unallocated_shared_labour": {
        "solution": (
            "Review the labour scope and period. Existing labour entries are read-only "
            "in the UI, so escalate any correction; after review, recalculate the open "
            "period under Payroll."
        ),
        "action_label": "Review labour costs",
        "action_href": "/finance/labour#labour-ledger",
    },
    "unallocated_production_consumables": {
        "solution": (
            "Review the usage scope, batch details, and allocation driver. Existing "
            "usage entries are read-only in the UI, so escalate any correction; then "
            "recalculate the open period under Payroll."
        ),
        "action_label": "Review consumable usage",
        "action_href": "/finance/consumables#usage-recognition",
    },
    "unallocated_selling_labour": {
        "solution": (
            "Review the selling-labour scope and batch. Existing entries are read-only "
            "in the UI, so escalate any reassignment; after review, recalculate the "
            "open period under Payroll."
        ),
        "action_label": "Review labour costs",
        "action_href": "/finance/labour#labour-ledger",
    },
    "unallocated_selling_expenses": {
        "solution": (
            "Review the selling-expense scope and batch. Existing entries are read-only "
            "in the UI, so escalate any reassignment; after review, recalculate the "
            "open period under Payroll."
        ),
        "action_label": "Review selling expenses",
        "action_href": "/finance/expenses#expense-ledger",
    },
    "unallocated_selling_consumables": {
        "solution": (
            "Review the selling-usage scope and batch. Existing entries are read-only "
            "in the UI, so escalate any reassignment; after review, recalculate the "
            "open period under Payroll."
        ),
        "action_label": "Review consumable usage",
        "action_href": "/finance/consumables#usage-recognition",
    },
    "capital_expenditure_not_linked": {
        "solution": (
            "Compare the capital expenditure with the asset register. Linking an "
            "existing expense to an asset is not yet available in the UI, so do not "
            "duplicate it; escalate the controlled correction to a finance administrator."
        ),
        "action_label": "Review asset register",
        "action_href": "/finance/assets#asset-register",
    },
    "depreciation_allocations_not_reconciling": {
        "solution": (
            "Check the asset production percentage and allocation driver, regenerate "
            "depreciation, and recalculate allocations before period close. Escalate "
            "any correction to an existing asset because asset fields are read-only."
        ),
        "action_label": "Review depreciation",
        "action_href": "/finance/assets#depreciation",
    },
    "legacy_final_snapshots_require_reconciliation": {
        "solution": (
            "Reopen the affected accounting period with a reason, recalculate its "
            "allocations, and close it again to create a controlled final snapshot."
        ),
        "action_label": "Review accounting periods",
        "action_href": "/finance/payroll#period-actions",
    },
    "expired_consumables": {
        "solution": (
            "Verify and isolate the physical stock and do not issue it to production. "
            "The UI does not yet provide a disposal or quantity-adjustment entry, so "
            "escalate the controlled stock correction to a finance administrator."
        ),
        "action_label": "Review expired lots",
        "action_href": "/finance/consumables#consumable-lots",
    },
    "maintenance_overdue": {
        "solution": (
            "Open the register to identify and inspect the affected asset. Maintenance "
            "entry is not yet exposed in the UI, so document the work and next due date "
            "through the authorized asset-administration process."
        ),
        "action_label": "Review affected assets",
        "action_href": "/finance/assets#asset-register",
    },
    "lifecycle_management_cost_basis": {
        "solution": (
            "Use active-batch figures for operational decisions only. Recalculate and "
            "close the accounting period before treating a closed batch result as final."
        ),
        "action_label": "Review accounting periods",
        "action_href": "/finance/payroll#period-actions",
    },
    "central_costs_excluded": {
        "solution": (
            "Use the monthly whole-farm report when assessing net profit because it "
            "includes central administration, finance costs, and tax."
        ),
        "action_label": "Open monthly report",
        "action_href": "/finance/monthly",
    },
    "selling_payroll_excluded": {
        "solution": (
            "Review employee selling percentages and use the monthly report for the "
            "whole-farm result until selling payroll is batch-attributed. Existing "
            "employee percentages are not yet editable in the UI; escalate corrections."
        ),
        "action_label": "Review payroll",
        "action_href": "/finance/payroll#period-actions",
    },
    "ias_41_fair_value_not_recorded": {
        "solution": (
            "Treat this as an internal management-cost report. A qualified accountant "
            "should prepare any IAS 41 fair-value adjustment outside this report until "
            "biological-asset valuation is supported in the system."
        ),
        "action_label": "Review monthly management report",
        "action_href": "/finance/monthly",
    },
    "input_cost_recognition_basis": {
        "solution": (
            "Purchase shared feed and medicine as consumable lots and issue them to "
            "batches as used when inventory deferral and stock control are required."
        ),
        "action_label": "Open consumable inventory",
        "action_href": "/finance/consumables#consumable-lots",
    },
    "cash_receipt_ledger_limitation": {
        "solution": (
            "Use the receivables register to review and follow up outstanding sales. "
            "Record later cash through the farm's controlled accounting process rather "
            "than changing the original sale; a dated receipt ledger is not yet available."
        ),
        "action_label": "Review receivables",
        "action_href": "/finance/receivables",
    },
    "closed_batch_snapshot_controls": {
        "solution": (
            "If a finalized figure is wrong, reopen its accounting period with a "
            "documented reason, make the correction, recalculate, and close it again."
        ),
        "action_label": "Review accounting periods",
        "action_href": "/finance/payroll#period-actions",
    },
    "booked_batches_excluded": {
        "solution": (
            "Confirm delivery and the actual flock entry details before including the "
            "batch in financial performance analysis."
        ),
        "action_label": "Review poultry batches",
        "action_href": "/poultry",
    },
    "pending_batch_finalization": {
        "solution": (
            "Review allocations for the batch's accounting period, resolve open "
            "warnings, then close the period to generate the final batch snapshot."
        ),
        "action_label": "Review accounting periods",
        "action_href": "/finance/payroll#period-actions",
    },
}


def finance_warning(
    *,
    code: str,
    severity: str,
    message: str,
    solution: str | None = None,
    action_label: str | None = None,
    action_href: str | None = None,
) -> dict[str, str]:
    guidance = WARNING_GUIDANCE.get(code, {})
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "solution": solution
        or guidance.get(
            "solution",
            "Review the underlying records and correct or complete the finance entry.",
        ),
        "action_label": action_label
        or guidance.get("action_label", "Open finance dashboard"),
        "action_href": action_href or guidance.get("action_href", "/finance"),
    }
