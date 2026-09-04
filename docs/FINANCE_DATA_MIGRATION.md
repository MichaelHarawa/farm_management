# Finance data migration and reconciliation

## Safe deployment order

1. Back up the database and retain the backup unchanged.
2. Run `python backend/manage.py migrate`.
3. Run `python backend/manage.py finance_preflight`; deployment must stop if migrations remain.
4. Run `python backend/manage.py finance_audit --json` and retain the output.
5. Run `python backend/manage.py apply_finance_reconciliation` without `--apply`.
6. Review every proposed correction. Only then run the same command with `--apply`.
7. Run `python backend/manage.py snapshot_closed_period_reports` and review legacy periods. Use `--apply` only after their figures are approved.
8. Run `python backend/manage.py backfill_general_ledger --json`. Approve mapping and opening balances before running with `--apply`.
9. Re-run the audit and archive before/after output.

All correction/backfill commands are dry-run by default and idempotent. They add traceable records; they do not silently delete or rewrite posted financial records.

## Latest supplied dump verification

The latest reference dump, `dump-farm_management-202609031558.sql`, was restored into isolated verification databases (final pass: `farm_management_codex_latest_final`) using a PostgreSQL 18 client. Its SHA-256 is `1BA1096E0662613D945EF13F752DF820BCB9BEAAA9BB470DF61A797561DA5BD9`; the source file was not modified. The single ignored restore statement was `SET transaction_timeout = 0`, which PostgreSQL 16 does not recognize; table data restored successfully.

Before migration the isolated copy contained 3 batches, 79 expenditures, 69 input-cost records, 31 sale-payment rows, 4 payroll entries and 1 asset. Finance migrations 0020 through 0024 and accounts migration 0003 applied successfully. The same counts remained afterward and no source records were deleted.

The post-migration audit found:

- input cost 26, MWK 15,000, not linked to an expenditure;
- input cost 53, MWK 18,000, linked to a void expenditure;
- 52 posted expenditures with MWK 4,422,200 not fully assigned to dated funding;
- 32 allocation/usage/depreciation rows in a closed period whose legacy `locked` flag is false;
- 136 core source events reported by the audit and 165 journal candidates in the dry-run backfill preview.

All 4 payroll entries total MWK 540,000 and are marked paid in this latest dump. The exceptions above are queued, not guessed. A finance owner must decide whether the MWK 18,000 event remains void or receives a replacement expenditure, identify the MWK 15,000 source document, confirm historical funding, and approve legacy locks. The application preserves all 31 dated sale receipts.

## Backfill boundaries

The GL preview generates unique source-based idempotency keys and reports trial-balance totals before and after. Payroll-linked expenditures are excluded from ordinary expenditure journals to avoid double-counting payroll generation. Management overhead allocations remain reporting dimensions and are not converted into duplicate expenses.

Do not run `backfill_general_ledger --apply` on production until source exceptions, cash/bank opening balances, payable splits, stock/asset histories and accounting policies are approved. Rollback uses forward corrective migrations and reversal journals; do not remove applied migrations or delete posted journals.
