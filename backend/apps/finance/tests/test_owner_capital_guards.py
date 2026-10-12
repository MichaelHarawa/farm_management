"""Owner capital is cash/equity, never sales or mutable analytical evidence."""
from datetime import date
from decimal import Decimal
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection, transaction
from django.db.models import F
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.test import APIClient

from apps.finance.models import (OwnerContributor, OwnerReceiptDesignation, FundingReceipt,
    FundingSource, JournalEntry, JournalLine, CostAllocation, Expenditure, FundingAllocation,
    FinancialCommandReceipt, FinanceActionEvent, AccountingPeriod)
from apps.finance.services.financial_capture import record_financial_owner_contribution
from apps.finance.services.ledger import post_journal, reverse_journal, trial_balance
from apps.finance.services.owner_capital import (record_owner_contribution, add_owner_designations,
    reverse_owner_designation, reverse_funding_receipt, owner_contribution_report)
from apps.finance.services.owner_capital_guards import owner_capital_posting_boundary
from apps.finance.services.profitability import available_funding_source_cash, available_batch_cash
from apps.finance.services.sale_guards import sale_posting_boundary
from . import test_financial_capture as fixtures


SETTINGS = dict(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False,
    FINANCE_FUNDING_RECEIPTS=False, FINANCE_FUNDING_REVERSALS=False)


def payload(test, **changes):
    return dict(dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", owner_id=test.owner.pk,
        amount="500.00", receipt_date=fixtures.instant(), reference="SYNTHETIC-CAPITAL",
        designations=[{"batch": test.batch.pk, "amount": "300.00"}]), **changes)


def setup(test):
    fixtures.fixture(test)
    test.owner = OwnerContributor.objects.create(display_name="Synthetic stable owner")
    test.intent = payload(test)
    test.receipt, _ = record_financial_owner_contribution(**test.intent)
    test.source = test.receipt.funding_source
    test.designation = test.receipt.owner_designations.get()
    test.journal = JournalEntry.objects.get()


@override_settings(**SETTINGS)
class OwnerCapitalWriterTests(TestCase):
    def setUp(self):
        setup(self)

    def snapshot(self):
        return {model._meta.model_name: list(model.objects.order_by("pk").values()) for model in
            [OwnerContributor, OwnerReceiptDesignation, FundingReceipt, FundingSource,
                JournalEntry, JournalLine, FinancialCommandReceipt, FinanceActionEvent,
                Expenditure, CostAllocation, FundingAllocation]}

    def refused(self, actions):
        before = self.snapshot()
        for action in actions:
            with self.subTest(action=action), self.assertRaises(DjangoValidationError), transaction.atomic():
                action()
            self.assertEqual(self.snapshot(), before)

    def test_twenty_retries_have_one_cash_equity_and_designation_effect(self):
        before = self.snapshot()
        for _ in range(20):
            receipt, created = record_financial_owner_contribution(**self.intent)
            self.assertFalse(created)
            self.assertEqual(receipt.pk, self.receipt.pk)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((FundingReceipt.objects.count(), OwnerReceiptDesignation.objects.count(),
            JournalEntry.objects.count(), JournalLine.objects.count()), (1, 1, 1, 2))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        self.assertEqual(available_batch_cash(self.batch), Decimal("0.00"))
        balances = {row["code"]: row["balance"] for row in trial_balance()["accounts"]}
        self.assertEqual(balances, {"1000": Decimal("500.00"), "3000": Decimal("-500.00")})
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("500"), Decimal("500")))
        self.assertEqual((Expenditure.objects.count(), CostAllocation.objects.count(), FundingAllocation.objects.count()), (0, 0, 0))
        summary = owner_contribution_report(date_to=date(2026, 1, 31))["summary"]
        self.assertEqual(summary["cash_introduced_to_date"], Decimal("500.00"))
        self.assertEqual(summary["net_contributed_capital"], Decimal("500.00"))
        self.assertEqual(summary["designated_to_batches_as_of"], Decimal("300.00"))
        self.assertEqual(summary["unassigned_contributions_as_of"], Decimal("200.00"))

    def test_second_atomic_contribution_preserves_original_evidence(self):
        original = FundingReceipt.objects.filter(pk=self.receipt.pk).values().get()
        designation = OwnerReceiptDesignation.objects.filter(pk=self.designation.pk).values().get()
        new, created = record_financial_owner_contribution(**payload(self, amount="100.00",
            receipt_date=fixtures.instant(day=21), reference="SYNTHETIC-SECOND", designations=[]))
        self.assertTrue(created)
        self.assertEqual(new.funding_source_id, self.source.pk)
        self.assertEqual(FundingReceipt.objects.filter(pk=self.receipt.pk).values().get(), original)
        self.assertEqual(OwnerReceiptDesignation.objects.filter(pk=self.designation.pk).values().get(), designation)
        self.assertEqual((FundingSource.objects.count(), FundingReceipt.objects.count(),
            JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (1, 2, 2, 2))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("600.00"))
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("600"), Decimal("600")))

    def test_current_contribution_does_not_reopen_or_redate_older_closed_capital(self):
        self.period.status = "closed"
        self.period.save(update_fields=["status"])
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        receipt, _ = record_financial_owner_contribution(**payload(self, amount="100.00",
            receipt_date=fixtures.instant(month=2), reference="FEBRUARY-ACTUAL", designations=[]))
        self.assertEqual(receipt.receipt_date, fixtures.instant(month=2))
        self.assertEqual(JournalEntry.objects.get(source_identifier=str(receipt.pk)).posting_date, date(2026, 2, 20))
        self.assertEqual({row["code"]: row["balance"] for row in trial_balance(cutoff=date(2026, 1, 31))["accounts"]},
            {"1000": Decimal("500.00"), "3000": Decimal("-500.00")})
        self.assertEqual(available_funding_source_cash(self.source), Decimal("600.00"))
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            record_financial_owner_contribution(**payload(self, amount="1.00", reference="Closed date", designations=[]))
        self.assertEqual(self.snapshot(), before)

    def test_receipt_all_writer_paths_are_refused(self):
        row = self.receipt
        self.refused([lambda: row.save(), lambda: row.save_base(raw=True), lambda: row.delete(),
            lambda: FundingReceipt.objects.filter(pk=row.pk).update(amount="1.00"),
            lambda: FundingReceipt.objects.bulk_update([row], ["amount"]),
            lambda: FundingReceipt.objects.filter(pk=row.pk).delete(),
            lambda: FundingReceipt.objects.filter(pk=row.pk)._raw_delete("default")])

    def test_receipt_identity_dates_actor_notes_status_and_source_cannot_change(self):
        for changes in [{"idempotency_key": None}, {"request_fingerprint": "0" * 64}, {"notes": "Rewrite"},
                {"receipt_date": fixtures.instant(day=21)}, {"status": "reversed"},
                {"reference": "Changed reference"}, {"created_by_id": None}, {"funding_source_id": None}]:
            self.refused([lambda changes=changes: FundingReceipt.objects.filter(pk=self.receipt.pk).update(**changes)])

    def test_new_ordinary_receipts_and_reserved_keys_are_refused(self):
        legacy = FundingSource.objects.create(source_type="general_farm_cash")
        self.refused([lambda: FundingReceipt.objects.create(funding_source=self.source, amount="1.00"),
            lambda: FundingReceipt.objects.bulk_create([FundingReceipt(funding_source=self.source, amount="1.00")]),
            lambda: FundingReceipt.objects.create(funding_source=legacy, amount="1.00", idempotency_key="financial-owner:forged"),
            lambda: FundingReceipt.objects.bulk_create([FundingReceipt(funding_source=legacy, amount="1.00", idempotency_key="financial-owner:forged")])])

    def test_pk_spoof_imports_and_upserts_cannot_replace_receipts(self):
        fake = FundingReceipt(pk=self.receipt.pk, funding_source=self.source, amount="1.00")
        self.refused([lambda: fake.save(force_update=True), lambda: fake.save_base(raw=True),
            lambda: FundingReceipt.objects.bulk_create([fake], ignore_conflicts=True),
            lambda: FundingReceipt.objects.bulk_create([fake], update_conflicts=True,
                update_fields=["amount"], unique_fields=["id"])])

    def test_legacy_receipt_rebinding_or_adoption_is_refused(self):
        legacy_source = FundingSource.objects.create(source_type="general_farm_cash")
        legacy = FundingReceipt.objects.create(funding_source=legacy_source, amount="1.00")
        self.refused([lambda: FundingReceipt.objects.filter(pk=legacy.pk).update(funding_source=self.source),
            lambda: FundingReceipt.objects.filter(pk=legacy.pk).update(funding_source_id=F("funding_source_id")),
            lambda: FundingReceipt.objects.filter(pk=legacy.pk).update(idempotency_key="financial-owner:adopted")])
        legacy.funding_source = self.source
        self.refused([lambda: legacy.save(), lambda: FundingReceipt.objects.bulk_update([legacy], ["funding_source"])])
        legacy.refresh_from_db()
        legacy.idempotency_key = "financial-owner:adopted"
        self.refused([lambda: legacy.save()])

    def test_mixed_receipt_updates_refuse_atomically(self):
        legacy_source = FundingSource.objects.create(source_type="general_farm_cash")
        legacy = FundingReceipt.objects.create(funding_source=legacy_source, amount="1.00")
        self.refused([lambda: FundingReceipt.objects.filter(pk__in=[legacy.pk, self.receipt.pk]).update(notes="Mixed"),
            lambda: FundingReceipt.objects.filter(pk__in=[legacy.pk, self.receipt.pk]).delete()])

    def test_source_economic_binding_is_fixed_after_managed_capital(self):
        for changes in [{"source_type": "grant"}, {"owner_id": None}, {"batch_id": self.batch.pk}]:
            self.refused([lambda changes=changes: FundingSource.objects.filter(pk=self.source.pk).update(**changes)])
        self.source.owner_id = None
        self.refused([lambda: self.source.save(), lambda: self.source.save_base(raw=True),
            lambda: FundingSource.objects.bulk_update([self.source], ["owner"]), lambda: self.source.delete(),
            lambda: FundingSource.objects.filter(pk=self.source.pk)._raw_delete("default")])

    def test_owner_stable_identity_cannot_be_reassigned(self):
        self.owner.public_id = uuid.uuid4()
        self.refused([lambda: self.owner.save(), lambda: self.owner.save_base(raw=True),
            lambda: OwnerContributor.objects.filter(pk=self.owner.pk).update(public_id=uuid.uuid4()),
            lambda: OwnerContributor.objects.bulk_update([self.owner], ["public_id"]),
            lambda: self.owner.delete(), lambda: OwnerContributor.objects.filter(pk=self.owner.pk)._raw_delete("default")])

    def test_owner_and_source_metadata_remain_editable_without_money_effects(self):
        self.owner.display_name = "Updated display name"
        self.owner.notes = "Metadata only"
        self.owner.save()
        self.source.description = "Updated capital label"
        self.source.save(update_fields=["description", "updated_at"])
        OwnerContributor.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            record_financial_owner_contribution(**payload(self, reference="Inactive owner"))
        self.assertEqual(self.snapshot(), before)

    def test_designation_all_writer_paths_are_refused(self):
        row = self.designation
        self.refused([lambda: row.save(), lambda: row.save_base(raw=True), lambda: row.delete(),
            lambda: OwnerReceiptDesignation.objects.filter(pk=row.pk).update(amount="1.00"),
            lambda: OwnerReceiptDesignation.objects.bulk_update([row], ["amount"]),
            lambda: OwnerReceiptDesignation.objects.filter(pk=row.pk).delete(),
            lambda: OwnerReceiptDesignation.objects.filter(pk=row.pk)._raw_delete("default")])

    def test_designation_date_batch_status_and_notes_remain_original(self):
        for changes in [{"designation_date": date(2026, 1, 21)}, {"batch_id": self.other_batch.pk},
                {"status": "reversed"}, {"notes": "Replace original"}, {"receipt_id": None}]:
            self.refused([lambda changes=changes: OwnerReceiptDesignation.objects.filter(pk=self.designation.pk).update(**changes)])

    def test_ordinary_designation_append_and_rebinding_are_refused(self):
        fresh = OwnerReceiptDesignation(receipt=self.receipt, batch=self.other_batch, amount="1.00")
        self.refused([lambda: fresh.save(), lambda: fresh.full_clean(),
            lambda: OwnerReceiptDesignation.objects.bulk_create([fresh])])
        source = FundingSource.objects.create(source_type="owner_capital", owner=self.owner)
        receipt = FundingReceipt.objects.create(funding_source=source, amount="10.00")
        legacy = OwnerReceiptDesignation.objects.create(receipt=receipt, batch=self.other_batch, amount="1.00")
        self.refused([lambda: OwnerReceiptDesignation.objects.filter(pk=legacy.pk).update(receipt=self.receipt),
            lambda: OwnerReceiptDesignation.objects.filter(pk=legacy.pk).update(receipt_id=F("receipt_id"))])
        legacy.receipt = self.receipt
        self.refused([lambda: legacy.save(), lambda: OwnerReceiptDesignation.objects.bulk_update([legacy], ["receipt"])])

    def test_designation_and_owner_pk_spoof_or_upsert_is_refused(self):
        fake = OwnerReceiptDesignation(pk=self.designation.pk, receipt=self.receipt,
            batch=self.batch, amount="1.00")
        fake_owner = OwnerContributor(pk=self.owner.pk, display_name="Spoof", public_id=uuid.uuid4())
        self.refused([lambda: fake.save_base(raw=True), lambda: fake_owner.save(force_update=True),
            lambda: OwnerReceiptDesignation.objects.bulk_create([fake], ignore_conflicts=True),
            lambda: OwnerContributor.objects.bulk_create([fake_owner], ignore_conflicts=True),
            lambda: OwnerReceiptDesignation.objects.bulk_create([fake], update_conflicts=True,
                update_fields=["amount"], unique_fields=["id"])])

    def test_journal_and_lines_all_writer_paths_are_refused(self):
        line = self.journal.lines.first()
        self.refused([lambda: self.journal.save(), lambda: self.journal.save_base(raw=True),
            lambda: self.journal.delete(), lambda: JournalEntry.objects.filter(pk=self.journal.pk).update(idempotency_key="Erase"),
            lambda: JournalEntry.objects.bulk_update([self.journal], ["description"]),
            lambda: JournalEntry.objects.filter(pk=self.journal.pk)._raw_delete("default"),
            lambda: line.save_base(raw=True), lambda: JournalLine.objects.filter(pk=line.pk).update(debit="1.00"),
            lambda: JournalLine.objects.bulk_update([line], ["debit"]),
            lambda: JournalLine.objects.filter(pk=line.pk).delete()])

    def test_reserved_or_alias_journal_creation_and_line_append_refused(self):
        journal = dict(reference="SYNTHETIC-FORGED", posting_date=date(2026, 1, 20),
            accounting_period=self.period, description="Forged capital", source_model="finance.FundingReceipt",
            source_identifier=str(self.receipt.pk))
        line = JournalLine(journal_entry=self.journal, account_id=self.journal.lines.first().account_id, debit="1.00")
        self.refused([lambda: JournalEntry.objects.create(**journal, idempotency_key="financial-owner-receipt:forged"),
            lambda: JournalEntry.objects.create(**journal, idempotency_key="ordinary-alias"),
            lambda: JournalLine.objects.bulk_create([line]), lambda: line.save()])

    def test_journal_pk_spoof_and_bulk_upsert_cannot_replace_history(self):
        fake = JournalEntry(pk=self.journal.pk, reference="SYNTHETIC-PK-SPOOF", posting_date=date(2026, 1, 20),
            accounting_period=self.period, description="Replace capital", source_model="test.Source",
            source_identifier="unrelated", idempotency_key="unrelated-key")
        self.refused([lambda: fake.save_base(raw=True),
            lambda: JournalEntry.objects.bulk_create([fake], ignore_conflicts=True),
            lambda: JournalEntry.objects.bulk_create([fake], update_conflicts=True,
                update_fields=["description"], unique_fields=["id"])])

    def test_legacy_journal_source_adoption_is_refused(self):
        entry = JournalEntry.objects.create(reference="SYNTHETIC-LEGACY", posting_date=date(2026, 1, 20),
            accounting_period=self.period, description="Legacy", source_model="test.Source",
            source_identifier="old", idempotency_key="legacy-capital-journal")
        self.refused([lambda: JournalEntry.objects.filter(pk=entry.pk).update(
            source_model="finance.FundingReceipt", source_identifier=str(self.receipt.pk)),
            lambda: JournalEntry.objects.filter(pk=entry.pk).update(idempotency_key="financial-owner-receipt:adopt")])
        entry.source_model = "finance.FundingReceipt"
        entry.source_identifier = str(self.receipt.pk)
        self.refused([lambda: entry.save(), lambda: JournalEntry.objects.bulk_update([entry], ["source_model", "source_identifier"])])

    def test_standalone_gl_or_source_reversal_cannot_hide_capital(self):
        before = self.snapshot()
        for call in [lambda: reverse_funding_receipt(receipt_id=self.receipt.pk, reason="Source only", user=self.user),
                lambda: reverse_journal(self.journal, posting_date=date(2026, 1, 21), reason="GL only", user=self.user),
                lambda: reverse_owner_designation(designation_id=self.designation.pk, reason="Remove", user=self.user),
                lambda: add_owner_designations(receipt_id=self.receipt.pk, designation_date=date(2026, 1, 21),
                    designations=[{"batch": self.other_batch.pk, "amount": "1.00"}], user=self.user)]:
            with self.assertRaises(ValidationError):
                call()
        self.assertEqual(self.snapshot(), before)

    def test_ordinary_helper_cannot_replay_reserved_financial_identity(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            record_owner_contribution(owner_id=self.owner.pk, amount="500.00", receipt_date=fixtures.instant(),
                reference="SYNTHETIC-CAPITAL", notes="", designations=[],
                idempotency_key=self.receipt.idempotency_key, user=self.user)
        self.assertEqual(self.snapshot(), before)

    def test_private_sale_permission_does_not_authorize_capital_or_mutation(self):
        with sale_posting_boundary():
            self.refused([lambda: JournalEntry.objects.create(reference="SYNTHETIC-OTHER-CONTEXT",
                posting_date=date(2026, 1, 20), accounting_period=self.period, description="Wrong boundary",
                source_model="finance.FundingReceipt", source_identifier=str(self.receipt.pk),
                idempotency_key="financial-owner-receipt:wrong-context")])
        with owner_capital_posting_boundary():
            self.refused([lambda: self.receipt.save(), lambda: self.designation.save(),
                lambda: self.journal.lines.first().save(),
                lambda: FundingReceipt.objects.filter(pk=self.receipt.pk).update(amount="1.00")])

    def test_legacy_source_requires_explicit_review_not_financial_adoption(self):
        owner = OwnerContributor.objects.create(display_name="Legacy synthetic owner")
        source = FundingSource.objects.create(source_type="owner_capital", owner=owner)
        FundingReceipt.objects.create(funding_source=source, amount="20.00", idempotency_key="legacy-owner-cash")
        before = self.snapshot()
        with self.assertRaises(ValidationError) as caught:
            record_financial_owner_contribution(**payload(self, owner_id=owner.pk,
                funding_source_id=source.pk, reference="New evidence"))
        self.assertIn("owner_source_review", caught.exception.detail)
        self.assertEqual(self.snapshot(), before)

    def test_failure_after_actual_journal_rolls_back_and_resets_private_permission(self):
        before = self.snapshot()
        def fail(**kwargs):
            post_journal(**kwargs)
            raise RuntimeError("Synthetic failure after journal")
        intent = payload(self, amount="100.00", reference="Synthetic rollback", designations=[])
        with patch("apps.finance.services.financial_capture.post_journal", side_effect=fail), self.assertRaises(RuntimeError):
            record_financial_owner_contribution(**intent)
        self.assertEqual(self.snapshot(), before)
        self.refused([lambda: FundingReceipt.objects.create(funding_source=self.source, amount="1.00")])
        self.assertTrue(record_financial_owner_contribution(**intent)[1])

    def test_current_role_and_changed_content_still_refuse_replay(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            record_financial_owner_contribution(**{**self.intent, "amount": "501.00"})
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(PermissionDenied):
            record_financial_owner_contribution(**self.intent)
        self.assertEqual(self.snapshot(), before)

    def test_flags_off_guards_never_query_additive_financial_tables(self):
        with CaptureQueriesContext(connection) as queries:
            for action in [lambda: self.receipt.save(), lambda: self.designation.delete(),
                    lambda: self.journal.lines.first().save()]:
                with self.assertRaises(DjangoValidationError):
                    action()
        sql = " ".join(row["sql"].lower() for row in queries.captured_queries)
        for forbidden in ["finance_fundingreceiptreversal", "finance_salecostpaymentreversal",
                "finance_inventorymovementevidence", "finance_inventoryvaluepool", "finance_financialcommandreceipt"]:
            self.assertNotIn(forbidden, sql)

    def test_managed_admin_receipt_read_only_and_source_binding_fields_frozen(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        receipt_admin = admin.site._registry[FundingReceipt]
        self.assertTrue(receipt_admin.has_view_permission(request, self.receipt))
        self.assertFalse(receipt_admin.has_change_permission(request, self.receipt))
        self.assertFalse(receipt_admin.has_delete_permission(request, self.receipt))
        source_admin = admin.site._registry[FundingSource]
        self.assertTrue(source_admin.has_change_permission(request, self.source))
        self.assertFalse(source_admin.has_delete_permission(request, self.source))
        self.assertTrue({"source_type", "batch", "owner"}.issubset(source_admin.get_readonly_fields(request, self.source)))
        form = receipt_admin.get_form(request)(data={"funding_source": self.source.pk,
            "receipt_date_0": "2026-01-21", "receipt_date_1": "12:00:00", "amount": "1.00"})
        self.assertFalse(form.is_valid())
        self.assertIn("Managed owner-capital", str(form.errors))

    def test_ordinary_rest_owner_operations_return_reviewable_400(self):
        client = APIClient()
        client.force_authenticate(self.user)
        before = self.snapshot()
        cases = [("post", f"/api/v1/finance/funding-receipts/{self.receipt.pk}/reverse", {"reason": "Source only"}),
            ("post", f"/api/v1/finance/owner-designations/{self.designation.pk}/reverse", {"reason": "Source only"}),
            ("post", f"/api/v1/finance/owner-designations/for-receipt/{self.receipt.pk}",
                {"designation_date": "2026-01-21", "designations": [{"batch": self.other_batch.pk, "amount": "1.00"}]}),
            ("post", "/api/v1/finance/owner-contributions", {"owner": self.owner.pk, "amount": "1.00",
                "receipt_date": fixtures.instant().isoformat(), "funding_source": self.source.pk,
                "idempotency_key": "ordinary-source-only"}),
            ("patch", f"/api/v1/finance/funding-sources/{self.source.pk}", {"owner": None}),
            ("delete", f"/api/v1/finance/funding-sources/{self.source.pk}", None)]
        for method, path, data in cases:
            response = getattr(client, method)(path, data, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_owner_cash_designation_and_reversal_workflows_remain_separate(self):
        owner = OwnerContributor.objects.create(display_name="Separate legacy owner")
        kwargs = dict(owner_id=owner.pk, amount="10.00", receipt_date=fixtures.instant(), reference="LEGACY",
            notes="", designations=[], idempotency_key="legacy-owner-helper", user=self.user)
        row, created = record_owner_contribution(**kwargs)
        self.assertTrue(created)
        self.assertFalse(record_owner_contribution(**kwargs)[1])
        new = add_owner_designations(receipt_id=row.pk, designation_date=date(2026, 1, 21),
            designations=[{"batch": self.other_batch.pk, "amount": "5.00"}], user=self.user)[0]
        reverse_owner_designation(designation_id=new.pk, reason="Legacy change", user=self.user)
        reverse_funding_receipt(receipt_id=row.pk, reason="Legacy correction", user=self.user)
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(available_funding_source_cash(self.source), Decimal("500.00"))


@override_settings(**SETTINGS)
class OwnerCapitalRaceTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def race(self, ordinary):
        barrier, results = Barrier(2), []
        original = FundingReceipt.objects.filter(pk=self.receipt.pk).values().get()
        intent = payload(self, amount="100.00", reference="Synthetic race", designations=[])
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                call()
                results.append("accepted")
            except (DjangoValidationError, ValidationError):
                results.append("refused")
            except Exception as error:
                results.append(type(error).__name__)
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=(call,)) for call in
            [lambda: record_financial_owner_contribution(**intent), ordinary]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["accepted", "refused"])
        self.assertEqual(FundingReceipt.objects.filter(pk=self.receipt.pk).values().get(), original)
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count(),
            FinancialCommandReceipt.objects.count()), (2, 2, 2))
        self.assertEqual(available_funding_source_cash(self.source), Decimal("600.00"))
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("600"), Decimal("600")))

    def test_capital_contribution_competes_with_ordinary_receipt_edit(self):
        self.race(lambda: FundingReceipt.objects.filter(pk=self.receipt.pk).update(amount="1.00"))

    def test_capital_contribution_competes_with_ordinary_source_rebinding(self):
        self.race(lambda: FundingSource.objects.filter(pk=self.source.pk).update(owner_id=None))

    def test_capital_contribution_competes_with_unjournaled_cash(self):
        self.race(lambda: FundingReceipt.objects.create(funding_source=self.source, amount="1.00"))

    def test_capital_contribution_competes_with_source_only_reversal(self):
        self.race(lambda: reverse_funding_receipt(receipt_id=self.receipt.pk, reason="Ordinary", user=self.user))

    def test_capital_contribution_competes_with_designation_rewrite(self):
        self.race(lambda: OwnerReceiptDesignation.objects.filter(pk=self.designation.pk).update(amount="1.00"))

    def test_capture_enabled_owner_effect_does_not_publish_finance_into_operational_profiles(self):
        from apps.mobile_sync.models import SyncStreamState, SyncChange
        from apps.mobile_sync.writers import sync_boundary
        SyncStreamState.objects.get_or_create(pk=1)
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary():
            record_financial_owner_contribution(**payload(self, amount="100.00", reference="Capture boundary", designations=[]))
        self.assertEqual(SyncChange.objects.count(), 0)
        self.assertEqual((FundingReceipt.objects.count(), JournalEntry.objects.count()), (2, 2))

    def test_private_creation_boundary_requires_atomic_transaction(self):
        with self.assertRaises(DjangoValidationError), owner_capital_posting_boundary():
            self.fail("No private permission should be granted without an atomic command.")
