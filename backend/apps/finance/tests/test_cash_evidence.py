"""Managed incoming-cash proof in new owned PostgreSQL databases only."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import ValidationError

from apps.finance.models import (ChartOfAccount, FinancialCommandReceipt, FundingReceipt,
    FundingReceiptReversal, JournalEntry, JournalLine, OwnerContributor,
    OwnerReceiptDesignation, SalePayment, FundingSource, FundingSourceType)
from apps.finance.services.cash_evidence import MESSAGE, require_cash_receipt
from apps.finance.services.financial_capture import (record_financial_owner_contribution,
    record_financial_receipt, record_financial_sale, record_financial_supplier_payment)
from apps.finance.services.funding_capture import funding_source_version, record_financial_funding_receipt
from apps.finance.services.funding_reversals import funding_receipt_version, reverse_financial_funding_receipt
from apps.finance.services.profitability import available_funding_source_cash
from apps.finance.services.selling_cost_settlement import record_sale_cost_payment
from apps.poultry.models import Batch, Sales
from . import test_dated_cash_funding as cash
from . import test_expenditure_drafts as drafts
from . import test_financial_capture as fixtures
from .inventory_corruption import corrupt_inventory, corrupt_inventory_insert


def snapshot():
    return {**cash.snapshot(), **{model._meta.model_name: list(model.objects.order_by("pk").values())
        for model in [SalePayment, FundingReceipt, OwnerReceiptDesignation, FundingReceiptReversal, Batch, Sales]}}


def erase(model, **where):
    if not str(connection.settings_dict["NAME"]).startswith("test_mobile_phase02_"):
        raise AssertionError("Privileged deletion is allowed only in a new owned test database.")
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM " + quote(model._meta.db_table) + " WHERE " +
            " AND ".join(quote(model._meta.get_field(field).column) + "=%s" for field in where), list(where.values()))


def setup(test):
    fixtures.fixture(test)
    test.sale_request = {**fixtures.sale_payload(test), "initial_receipt": {
        "amount": "100.00", "payment_date": fixtures.instant(), "payment_method": "cash"}}
    record_financial_sale(**test.sale_request)
    test.source = FundingSource.objects.get(source_type=FundingSourceType.BATCH_COLLECTION, batch=test.batch)
    test.alias = FundingSource.objects.create(source_type=FundingSourceType.BATCH_COLLECTION,
        batch=test.batch, description="Synthetic same-batch cash alias")
    test.expense = drafts.draft(test, expenditure_date=date(2026, 1, 10), post=True)
    test.receipt = SalePayment.objects.get()
    test.original = FinancialCommandReceipt.objects.get(result__payment_id=str(test.receipt.pk))
    test.journal = JournalEntry.objects.get(idempotency_key=f"sale-receipt:{test.receipt.pk}")


def loan(test, amount="100.00", reference="SYNTHETIC-PROOF-LOAN"):
    source = FundingSource.objects.create(source_type=FundingSourceType.LOAN)
    receipt = record_financial_funding_receipt(submission_id=uuid.uuid4(), user=test.user, currency="MWK",
        funding_source_id=source.pk, source_version=funding_source_version(source), amount=amount,
        receipt_date=fixtures.instant(), counterparty="Synthetic lender", payment_method="bank_transfer",
        reference=reference)[0]
    return source, receipt


@override_settings(**cash.SETTINGS)
class IncomingCashProofTests(TestCase):
    def setUp(self):
        setup(self)

    def refused(self, **extra):
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            record_financial_supplier_payment(**cash.payment(self, "25.00", **extra))
        self.assertIn("funding_allocations", error.exception.detail)
        self.assertEqual(str(error.exception.detail["funding_allocations"]), MESSAGE)
        self.assertEqual(snapshot(), before)

    def damage_result(self, **changes):
        result = {**deepcopy(self.original.result), **changes}
        corrupt_inventory(FinancialCommandReceipt, self.original.pk, result=json.dumps(result))

    def test_new_initial_receipt_is_sealed_and_twenty_payment_retries_post_once(self):
        require_cash_receipt(self.receipt)
        self.assertEqual(len(self.original.result["cash_version"]), 64)
        self.assertEqual(len(self.original.result["cash_anchor"]), 64)
        request = cash.payment(self, "25.00")
        first, created = record_financial_supplier_payment(**request)
        self.assertTrue(created)
        after = snapshot()
        for _ in range(20):
            rows, created = record_financial_supplier_payment(**request)
            self.assertFalse(created)
            self.assertEqual(rows.pk, first.pk)
        self.assertEqual(snapshot(), after)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("75.00"))
        self.assertEqual(len(after["expenditure"]), 1)
        self.assertEqual(len(after["costallocation"]), 1)
        self.assertEqual(len(after["fundingallocation"]), 1)
        self.assertEqual(len(after["journalentry"]), 4)
        self.assertEqual(len(after["journalline"]), 8)
        self.assertEqual(cash.trial_balance()["debits"], Decimal("425.00"))
        self.assertEqual(cash.trial_balance()["credits"], Decimal("425.00"))
        self.original.refresh_from_db()
        self.assertEqual(self.original.result["payment_id"], str(self.receipt.pk))

    def test_later_collection_keeps_original_proof_and_adds_its_own(self):
        original = deepcopy(self.original.result)
        receipt = record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=self.receipt.sale_id, amount="50.00", payment_date=fixtures.instant(day=21), payment_method="cash")[0]
        self.receipt.refresh_from_db()
        require_cash_receipt(self.receipt)
        require_cash_receipt(receipt)
        record_financial_supplier_payment(**cash.payment(self, "25.00", payment_date=date(2026, 1, 22)))
        self.original.refresh_from_db()
        self.assertEqual(self.original.result, original)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("125.00"))

    def test_receipt_amount_damage_requires_review(self):
        corrupt_inventory(SalePayment, self.receipt.pk, amount=Decimal("101.00"))
        self.refused()

    def test_receipt_reference_damage_requires_review(self):
        corrupt_inventory(SalePayment, self.receipt.pk, external_reference="Changed evidence")
        self.refused()

    def test_receipt_capture_damage_requires_review(self):
        corrupt_inventory(SalePayment, self.receipt.pk, created_at=self.receipt.created_at - timedelta(days=1))
        self.refused()

    def test_receipt_date_damage_requires_review(self):
        corrupt_inventory(SalePayment, self.receipt.pk, payment_date=fixtures.instant(day=19))
        self.refused()

    def test_erased_receipt_key_is_still_detected_by_cash_journal(self):
        corrupt_inventory(SalePayment, self.receipt.pk, idempotency_key=None)
        self.refused()

    def test_rebound_receipt_is_detected_by_original_journal_pool(self):
        other = record_financial_sale(**{**fixtures.sale_payload(self), "batch_id": self.other_batch.pk})[0]
        corrupt_inventory(SalePayment, self.receipt.pk, sale_id=other.pk)
        self.refused()

    def test_reversed_receipt_without_source_correction_is_not_trusted(self):
        corrupt_inventory(SalePayment, self.receipt.pk, status="reversed")
        self.refused()

    def test_wrong_but_balanced_cash_credit_account_requires_review(self):
        credit = self.journal.lines.get(credit__gt=0)
        corrupt_inventory(JournalLine, credit.pk, account_id=ChartOfAccount.objects.get(code="4000").pk)
        self.refused()

    def test_wrong_but_balanced_cash_amount_requires_review(self):
        for line in self.journal.lines.all():
            corrupt_inventory(JournalLine, line.pk, **{"debit" if line.debit else "credit": Decimal("99.00")})
        self.refused()

    def test_cash_line_batch_damage_requires_review(self):
        line = self.journal.lines.get(debit__gt=0)
        corrupt_inventory(JournalLine, line.pk, batch_id=self.other_batch.pk)
        self.refused()

    def test_cash_line_memo_damage_requires_review(self):
        corrupt_inventory(JournalLine, self.journal.lines.first().pk, memo="Changed original caption")
        self.refused()

    def test_extra_balanced_cash_lines_require_review(self):
        for debit, credit in [(Decimal("1.00"), Decimal("0.00")), (Decimal("0.00"), Decimal("1.00"))]:
            corrupt_inventory_insert(JournalLine(journal_entry=self.journal,
                account=ChartOfAccount.objects.get(code="1000"), debit=debit, credit=credit, batch=self.batch))
        self.refused()

    def test_cash_journal_actor_damage_requires_review(self):
        user = get_user_model().objects.create_user(username="synthetic-other-cash-actor", email="other-cash@example.invalid")
        corrupt_inventory(JournalEntry, self.journal.pk, posted_by_id=user.pk)
        self.refused()

    def test_cash_journal_caption_damage_requires_review(self):
        corrupt_inventory(JournalEntry, self.journal.pk, description="Changed cash caption")
        self.refused()

    def test_cash_journal_date_damage_requires_review(self):
        corrupt_inventory(JournalEntry, self.journal.pk, posting_date=date(2026, 1, 19))
        self.refused()

    def test_erased_cash_journal_key_does_not_avoid_proof(self):
        corrupt_inventory(JournalEntry, self.journal.pk, idempotency_key="historical-erased-marker")
        self.refused()

    def test_missing_cash_journal_requires_review_without_recreation(self):
        erase(JournalLine, journal_entry_id=self.journal.pk)
        erase(JournalEntry, id=self.journal.pk)
        self.refused()

    def test_missing_cash_row_is_detected_by_retained_journal(self):
        erase(SalePayment, id=self.receipt.pk)
        self.refused()

    def test_original_sale_journal_damage_requires_review(self):
        journal = JournalEntry.objects.get(idempotency_key=f"financial-sale:{self.receipt.sale_id}")
        corrupt_inventory(JournalEntry, journal.pk, description="Wrong original source evidence")
        self.refused()

    def test_missing_permanent_receipt_requires_review(self):
        erase(FinancialCommandReceipt, submission_id=self.original.pk)
        self.refused()

    def test_request_hash_damage_requires_review(self):
        corrupt_inventory(FinancialCommandReceipt, self.original.pk, request_hash="f" * 64)
        self.refused()

    def test_result_damage_requires_review(self):
        self.damage_result(journal_ids=[])
        self.refused()

    def test_missing_version_is_not_backfilled_on_payment_or_replay(self):
        result = deepcopy(self.original.result)
        result.pop("cash_version")
        result.pop("cash_anchor")
        corrupt_inventory(FinancialCommandReceipt, self.original.pk, result=json.dumps(result))
        self.refused()
        # An identical original sale replay is still its stored result; it must
        # not execute the effect or stamp older evidence during recovery.
        before = snapshot()
        self.assertFalse(record_financial_sale(**self.sale_request)[1])
        self.original.refresh_from_db()
        self.assertEqual(self.original.result, result)
        self.assertEqual(snapshot(), before)

    def test_ambiguous_permanent_receipt_requires_review(self):
        FinancialCommandReceipt.objects.create(submission_id=uuid.uuid4(), command=self.original.command,
            actor=self.user, request_hash=self.original.request_hash, result=deepcopy(self.original.result),
            completed_at=self.original.completed_at)
        self.refused()

    def test_source_metadata_and_period_lock_metadata_do_not_change_original_proof(self):
        self.source.description = "Renamed label"
        self.source.save(update_fields=["description", "updated_at"])
        self.period.notes = "Reconciliation note"
        self.period.save(update_fields=["notes", "updated_at"])
        record_financial_supplier_payment(**cash.payment(self, "25.00"))

    def test_later_receipt_parent_request_damage_requires_review(self):
        receipt = record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=self.receipt.sale_id, amount="50.00", payment_date=fixtures.instant(day=21), payment_method="cash")[0]
        require_cash_receipt(receipt)
        corrupt_inventory(FinancialCommandReceipt, self.original.pk, request_hash="0" * 64)
        self.refused(payment_date=date(2026, 1, 22))

    def test_malformed_parent_of_later_cash_is_reviewable_not_server_error(self):
        sale = record_financial_sale(**{**fixtures.sale_payload(self), "batch_id": self.other_batch.pk})[0]
        receipt = record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            sale_id=sale.pk, amount="100.00", payment_date=fixtures.instant(day=21), payment_method="cash")[0]
        parent = FinancialCommandReceipt.objects.get(command="poultry.sale.record", result__sale_id=str(sale.pk))
        corrupt_inventory(FinancialCommandReceipt, parent.pk, result=json.dumps({**parent.result, "journal_ids": 1}))
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            require_cash_receipt(receipt)
        self.assertIn("funding_allocations", error.exception.detail)
        self.assertEqual(snapshot(), before)

    def test_legacy_cash_is_not_adopted_or_stamped_by_this_increment(self):
        self.source = FundingSource.objects.create(source_type=FundingSourceType.GENERAL_FARM_CASH)
        receipt = FundingReceipt.objects.create(funding_source=self.source, amount=Decimal("100.00"),
            receipt_date=fixtures.instant(), reference="SYNTHETIC-LEGACY-CASH", created_by=self.user)
        original = dict(FundingReceipt.objects.filter(pk=receipt.pk).values().get())
        record_financial_supplier_payment(**cash.payment(self, "25.00"))
        self.assertEqual(dict(FundingReceipt.objects.filter(pk=receipt.pk).values().get()), original)
        self.assertFalse(FinancialCommandReceipt.objects.filter(result__receipt_id=str(receipt.pk)).exists())

    @override_settings(FINANCE_FUNDING_RECEIPTS=True)
    def test_erased_loan_marker_is_still_detected_by_original_cash_journal(self):
        self.source, receipt = loan(self)
        corrupt_inventory(FundingReceipt, receipt.pk, idempotency_key=None)
        self.refused()

    @override_settings(FINANCE_FUNDING_RECEIPTS=True)
    def test_changed_loan_result_or_fingerprint_cannot_fund_payment(self):
        self.source, receipt = loan(self)
        corrupt_inventory(FundingReceipt, receipt.pk, request_fingerprint="0" * 64)
        self.refused()

    @override_settings(FINANCE_SALE_COST_SETTLEMENT=True)
    def test_damaged_incoming_cash_also_blocks_sale_cost_settlement(self):
        request = cash.selling_cost(self)
        corrupt_inventory(SalePayment, self.receipt.pk, notes="Changed collection evidence")
        before = snapshot()
        with self.assertRaises(ValidationError) as error:
            record_sale_cost_payment(**request)
        self.assertIn("funding_allocations", error.exception.detail)
        self.assertEqual(snapshot(), before)

    def test_proof_review_is_bounded_not_partial_cash_success(self):
        with patch("apps.finance.services.cash_evidence.MAX_CASH_EVIDENCE", 0):
            self.refused()

    def test_cash_seal_failure_rolls_back_composite_sale(self):
        before = snapshot()
        sales = self.batch.sales_row.count()
        with patch("apps.finance.services.cash_evidence._version", side_effect=ValidationError("Synthetic seal failure")):
            with self.assertRaises(ValidationError):
                record_financial_sale(**{**fixtures.sale_payload(self), "initial_receipt": {
                    "amount": "100.00", "payment_date": fixtures.instant(), "payment_method": "cash"}})
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.batch.sales_row.count(), sales)

    def test_owner_identity_and_designations_are_proved_but_display_name_is_not_cash(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic original contributor")
        receipt = record_financial_owner_contribution(submission_id=uuid.uuid4(), user=self.user,
            currency="MWK", owner_id=owner.pk, amount="100.00", receipt_date=fixtures.instant(),
            reference="SYNTHETIC-OWNER-PROOF", designations=[{"batch": self.other_batch.pk, "amount": "20.00"}])[0]
        self.source = receipt.funding_source
        owner.display_name = "Renamed synthetic contributor"
        owner.save(update_fields=["display_name", "updated_at"])
        require_cash_receipt(receipt)
        record_financial_supplier_payment(**cash.payment(self, "25.00"))
        corrupt_inventory(OwnerContributor, owner.pk, public_id=uuid.uuid4())
        self.refused()

    def test_owner_designation_damage_requires_review(self):
        owner = OwnerContributor.objects.create(display_name="Synthetic designation owner")
        receipt = record_financial_owner_contribution(submission_id=uuid.uuid4(), user=self.user,
            currency="MWK", owner_id=owner.pk, amount="100.00", receipt_date=fixtures.instant(),
            designations=[{"batch": self.other_batch.pk, "amount": "20.00"}])[0]
        self.source = receipt.funding_source
        corrupt_inventory(OwnerReceiptDesignation, receipt.owner_designations.get().pk, amount=Decimal("21.00"))
        self.refused()

    @override_settings(FINANCE_FUNDING_RECEIPTS=True)
    def test_loan_original_full_journal_is_proved(self):
        self.source, receipt = loan(self)
        require_cash_receipt(receipt)
        journal = JournalEntry.objects.get(idempotency_key=f"financial-funding-receipt:{receipt.pk}")
        corrupt_inventory(JournalLine, journal.lines.get(credit__gt=0).pk,
            account_id=ChartOfAccount.objects.get(code="3000").pk)
        self.refused()

    @override_settings(FINANCE_FUNDING_RECEIPTS=True, FINANCE_FUNDING_REVERSALS=True)
    def test_valid_linked_loan_correction_allows_only_other_confirmed_cash(self):
        self.source, receipt = loan(self, "500.00")
        record_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            funding_source_id=self.source.pk, source_version=funding_source_version(self.source), amount="100.00",
            receipt_date=fixtures.instant(day=21), counterparty="Synthetic lender", payment_method="cash",
            reference="SYNTHETIC-SECOND-LOAN")
        reversal = reverse_financial_funding_receipt(submission_id=uuid.uuid4(), user=self.user, currency="MWK",
            receipt_id=receipt.pk, source_version=funding_receipt_version(receipt), reversal_date=date(2026, 1, 22),
            reason="Synthetic complete funding correction")[0]
        require_cash_receipt(receipt)
        record_financial_supplier_payment(**cash.payment(self, "25.00", payment_date=date(2026, 1, 23)))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("75.00"))
        corrupt_inventory(JournalLine, reversal.reversal_journal.lines.get(debit__gt=0).pk, memo="Wrong correction")
        self.refused(payment_date=date(2026, 1, 23))


@override_settings(**cash.SETTINGS)
class IncomingCashProofRaces(TransactionTestCase):
    def setUp(self):
        setup(self)

    def race(self, callbacks):
        barrier = Barrier(len(callbacks))
        results = []
        def run(callback):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                callback()
                results.append("accepted")
            except ValidationError:
                results.append("rejected")
            except Exception as error:
                results.append(type(error).__name__)
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=(callback,)) for callback in callbacks]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
            self.assertFalse(thread.is_alive())
        return results

    def test_two_payables_share_intact_original_cash_proof_and_last_cash(self):
        other = drafts.draft(self, expenditure_date=date(2026, 1, 10), post=True)
        first = cash.payment(self, "75.00")
        second = cash.payment(self, "75.00", expenditure_id=other.pk,
            funding_allocations=[{"funding_source": self.alias.pk, "amount": "75.00"}])
        results = self.race([lambda: record_financial_supplier_payment(**first),
            lambda: record_financial_supplier_payment(**second)])
        self.assertCountEqual(results, ["accepted", "rejected"])
        self.assertEqual(available_funding_source_cash(self.source), Decimal("25.00"))
        require_cash_receipt(self.receipt)

    def test_same_payment_id_with_verified_cash_has_one_effect(self):
        request = cash.payment(self, "25.00")
        self.assertEqual(self.race([lambda: record_financial_supplier_payment(**request),
            lambda: record_financial_supplier_payment(**request)]), ["accepted", "accepted"])
        self.assertEqual(available_funding_source_cash(self.source), Decimal("75.00"))
        self.assertEqual(FinancialCommandReceipt.objects.filter(pk=request["submission_id"]).count(), 1)
