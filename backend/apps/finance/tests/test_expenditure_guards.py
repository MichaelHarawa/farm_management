"""Managed spending source/GL writers, including PostgreSQL bypass races."""
from datetime import date
from decimal import Decimal
from threading import Barrier, Thread
import uuid

from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, close_old_connections, transaction
from django.db.models import F
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finance.models import (Expenditure, CostAllocation, FundingAllocation, FundingSource,
    FinancialCommandReceipt, JournalEntry, JournalLine, FinanceActionEvent)
from apps.finance.services.expenditure_drafts import update_financial_expenditure_draft, post_financial_expenditure_draft
from apps.finance.services.expenditure_guards import expenditure_effect_boundary
from apps.finance.services.expenditures import post_expenditure, record_expenditure_payment, reverse_expenditure
from apps.finance.services.financial_capture import record_financial_supplier_payment
from apps.finance.services.ledger import reverse_journal, trial_balance
from apps.finance.services.profitability import available_funding_source_cash, available_batch_cash
from . import test_expenditure_drafts as drafts
from . import test_financial_capture as fixtures


SETTINGS = dict(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False)


def setup(test, *, post=True):
    fixtures.fixture(test)
    test.source = drafts.funded_source(test)
    test.expense = drafts.draft(test, post=post, payment_date=date(2026, 1, 22) if post else None,
        funding_allocations=[{"funding_source": test.source.pk, "amount": "40.00"}] if post else [])
    if post:
        test.cost = CostAllocation.objects.get(expenditure=test.expense)
        test.payment = FundingAllocation.objects.get(expenditure=test.expense)
        test.journal = JournalEntry.objects.get(source_model="finance.Expenditure")


def payment(test):
    return dict(submission_id=uuid.uuid4(), user=test.user, currency="MWK", expenditure_id=test.expense.pk,
        payment_date=date(2026, 1, 23), funding_allocations=[{"funding_source": test.source.pk, "amount": "10.00"}])


@override_settings(**SETTINGS)
class ExpenditureWriterTests(TestCase):
    def setUp(self):
        setup(self)

    def snapshot(self):
        return {model._meta.model_name: list(model.objects.order_by("pk").values()) for model in
            [Expenditure, CostAllocation, FundingAllocation, FundingSource, JournalEntry, JournalLine,
                FinancialCommandReceipt, FinanceActionEvent]}

    def refused(self, actions):
        before = self.snapshot()
        for action in actions:
            with self.subTest(action=action), self.assertRaises(DjangoValidationError), transaction.atomic():
                action()
            self.assertEqual(self.snapshot(), before)

    def test_posted_source_all_writer_paths(self):
        self.expense.amount = Decimal("101")
        self.refused([lambda: self.expense.save(), lambda: self.expense.save_base(),
            lambda: self.expense.save_base(raw=True), lambda: self.expense.save(update_fields=["amount"]),
            lambda: Expenditure.objects.filter(pk=self.expense.pk).update(amount="101"),
            lambda: Expenditure.objects.bulk_update([self.expense], ["amount"]), lambda: self.expense.delete(),
            lambda: Expenditure.objects.filter(pk=self.expense.pk).delete(),
            lambda: Expenditure.objects.filter(pk=self.expense.pk)._raw_delete("default")])

    def test_posted_identity_date_description_and_status_are_fixed(self):
        for field, value in [("idempotency_key", None), ("status", "void"), ("payment_status", "paid"),
                ("expenditure_date", date(2026, 1, 23)), ("payee", "Changed"), ("notes", "Changed"),
                ("external_reference", "Changed"), ("cost_allocation_plan", []), ("created_by", None),
                ("accounting_nature", "indirect_operating_expense")]:
            self.refused([lambda: Expenditure.objects.filter(pk=self.expense.pk).update(**{field: value})])

    def test_funding_evidence_all_writer_paths(self):
        self.payment.amount = Decimal("41")
        self.refused([lambda: self.payment.save(), lambda: self.payment.save_base(raw=True),
            lambda: FundingAllocation.objects.filter(pk=self.payment.pk).update(amount=F("amount") + 1),
            lambda: FundingAllocation.objects.bulk_update([self.payment], ["amount"]), lambda: self.payment.delete(),
            lambda: FundingAllocation.objects.filter(pk=self.payment.pk).delete(),
            lambda: FundingAllocation.objects.filter(pk=self.payment.pk)._raw_delete("default")])

    def test_funding_source_date_classification_and_group_cannot_change(self):
        for field, value in [("funding_source_id", None), ("allocation_date", date(2026, 1, 23)),
                ("classification", "owner_drawing"), ("notes", "Changed"), ("payment_group_key", ""),
                ("expenditure_id", None)]:
            self.refused([lambda: FundingAllocation.objects.filter(pk=self.payment.pk).update(**{field: value})])

    def test_cost_evidence_all_writer_paths(self):
        self.cost.allocated_amount = Decimal("101")
        self.refused([lambda: self.cost.save(), lambda: self.cost.save_base(raw=True),
            lambda: CostAllocation.objects.filter(pk=self.cost.pk).update(allocated_amount="101"),
            lambda: CostAllocation.objects.bulk_update([self.cost], ["allocated_amount"]), lambda: self.cost.delete(),
            lambda: CostAllocation.objects.filter(pk=self.cost.pk).delete(),
            lambda: CostAllocation.objects.filter(pk=self.cost.pk)._raw_delete("default")])

    def test_period_lock_metadata_remains_supported(self):
        CostAllocation.objects.filter(pk=self.cost.pk).update(locked=True)
        self.cost.refresh_from_db()
        self.cost.locked = False
        self.cost.save(update_fields=["locked", "updated_at"])
        self.assertEqual(CostAllocation.objects.get(pk=self.cost.pk).allocated_amount, Decimal("100"))

    def test_ordinary_payment_and_post_cannot_bypass_even_replay(self):
        self.refused([lambda: record_expenditure_payment(expenditure_id=self.expense.pk, user=self.user,
            funding_rows=[{"funding_source": self.source.pk, "amount": "40.00"}],
            payment_date=self.payment.allocation_date, payment_group_key=self.payment.payment_group_key),
            lambda: post_expenditure(expenditure_id=self.expense.pk, user=self.user, allow_unpaid=True)])

    def test_source_only_void_is_refused_without_cash_or_gl_change(self):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            reverse_expenditure(expenditure_id=self.expense.pk, reason="Source only", user=self.user)
        self.assertEqual(before, self.snapshot())

    def test_new_ordinary_funding_or_cost_is_refused(self):
        values = {field.attname: getattr(self.payment, field.attname) for field in self.payment._meta.concrete_fields
            if not field.primary_key}
        values["payment_group_key"] = "unjournaled"
        new_payment = FundingAllocation(**values)
        cost_values = {field.attname: getattr(self.cost, field.attname) for field in self.cost._meta.concrete_fields
            if not field.primary_key}
        self.refused([lambda: new_payment.save(), lambda: FundingAllocation.objects.bulk_create([new_payment]),
            lambda: CostAllocation.objects.create(**cost_values), lambda: CostAllocation(**cost_values).full_clean()])

    def test_pk_spoof_and_bulk_upserts_are_refused(self):
        spoof = Expenditure(pk=self.expense.pk, expenditure_date=self.expense.expenditure_date, amount="1", description="Spoof")
        self.refused([lambda: spoof.save_base(raw=True),
            lambda: Expenditure.objects.bulk_create([spoof], ignore_conflicts=True),
            lambda: Expenditure.objects.bulk_create([spoof], update_conflicts=True, update_fields=["amount"], unique_fields=["id"]),
            lambda: FundingAllocation.objects.bulk_create([self.payment], update_conflicts=True, update_fields=["amount"], unique_fields=["id"])])

    def test_legacy_parent_rebinding_reserved_keys_and_expressions_are_refused(self):
        legacy = Expenditure.objects.create(expenditure_date=date(2026, 1, 21), amount="1", description="Legacy")
        row = FundingAllocation.objects.create(expenditure=legacy, funding_source=self.source, amount="1", allocation_date=date(2026, 1, 22))
        self.refused([lambda: FundingAllocation.objects.filter(pk=row.pk).update(expenditure=self.expense),
            lambda: FundingAllocation.objects.filter(pk=row.pk).update(expenditure_id=F("expenditure_id")),
            lambda: FundingAllocation.objects.filter(pk=row.pk).update(payment_group_key="financial-payment:fake"),
            lambda: Expenditure.objects.filter(pk=legacy.pk).update(idempotency_key="financial-expense:fake")])
        row.expenditure = self.expense
        self.refused([lambda: row.save()])

    def test_mixed_bulk_refuses_atomically_before_legacy_change(self):
        legacy = Expenditure.objects.create(expenditure_date=date(2026, 1, 21), amount="1", description="Legacy")
        legacy.notes, self.expense.notes = "Changed", "Changed"
        self.refused([lambda: Expenditure.objects.bulk_update([legacy, self.expense], ["notes"], batch_size=1),
            lambda: Expenditure.objects.all().update(notes="Changed")])

    def test_managed_payable_and_payment_journals_are_immutable(self):
        for entry in JournalEntry.objects.filter(source_model__in=["finance.Expenditure", "finance.FundingAllocation"]):
            line = entry.lines.first()
            entry.idempotency_key = "Erased"
            line.debit = Decimal("1")
            self.refused([lambda: entry.save(), lambda: entry.save_base(raw=True),
                lambda: JournalEntry.objects.filter(pk=entry.pk).update(idempotency_key="Erased"),
                lambda: entry.delete(), lambda: line.save(),
                lambda: JournalLine.objects.filter(pk=line.pk).update(debit="1"),
                lambda: JournalLine.objects.bulk_update([line], ["debit"]),
                lambda: JournalLine.objects.filter(journal_entry=entry).delete()])

    def test_appended_lines_and_standalone_reversal_are_refused(self):
        self.refused([lambda: JournalLine.objects.create(journal_entry=self.journal,
            account=self.journal.lines.first().account, debit="1", credit="0")])
        before = self.snapshot()
        for entry in JournalEntry.objects.filter(source_model__in=["finance.Expenditure", "finance.FundingAllocation"]):
            with self.assertRaises(ValidationError):
                reverse_journal(entry, posting_date=date(2026, 1, 23), reason="GL only", user=self.user)
        self.assertEqual(self.snapshot(), before)

    def test_payment_source_economic_binding_fixed_metadata_editable(self):
        self.refused([lambda: FundingSource.objects.filter(pk=self.source.pk).update(source_type="loan")])
        FundingSource.objects.filter(pk=self.source.pk).update(description="Clearer label")
        self.assertEqual(available_funding_source_cash(self.source), Decimal("160"))

    def test_valid_new_payment_twenty_retries_preserves_original_sources_and_gl(self):
        original = self.snapshot()
        command = payment(self)
        self.assertTrue(record_financial_supplier_payment(**command)[1])
        accepted = self.snapshot()
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**command)[1])
        self.assertEqual(accepted, self.snapshot())
        self.assertEqual(original["costallocation"], accepted["costallocation"])
        self.assertEqual(original["fundingallocation"][0], accepted["fundingallocation"][0])
        self.assertEqual((FundingAllocation.objects.count(), CostAllocation.objects.count(),
            JournalEntry.objects.count(), available_funding_source_cash(self.source)), (2, 1, 5, Decimal("150")))
        self.assertEqual(available_batch_cash(self.other_batch), Decimal("0"))
        totals = {code: sum((line.debit - line.credit for line in JournalLine.objects.filter(account__code=code)), Decimal("0"))
            for code in ["1000", "2000", "5000"]}
        self.assertEqual(totals, {"1000": Decimal("150"), "2000": Decimal("-50"), "5000": Decimal("100")})
        self.assertEqual((trial_balance()["debits"], trial_balance()["credits"]), (Decimal("550"), Decimal("550")))

    def test_reserved_journal_create_and_legacy_source_adoption_are_refused(self):
        legacy = JournalEntry.objects.create(accounting_period=self.period, posting_date=date(2026, 1, 21), description="Legacy", idempotency_key="legacy-journal")
        self.refused([lambda: JournalEntry.objects.create(posting_date=date(2026, 1, 21),
            description="Fake", idempotency_key="financial-expenditure:fake"),
            lambda: JournalEntry.objects.filter(pk=legacy.pk).update(idempotency_key="inventory-purchase:fake"),
            lambda: JournalEntry.objects.filter(pk=legacy.pk).update(source_model="finance.FundingAllocation", source_identifier=str(self.payment.pk)),
            lambda: JournalEntry.objects.create(posting_date=date(2026, 1, 23), description="Fake reversal",
                idempotency_key="opposite", reversal_of=self.journal)])

    def test_bulk_journal_and_line_delete_or_upsert_refused(self):
        entry = self.journal
        line = entry.lines.first()
        entry.description = "Changed"
        self.refused([lambda: JournalEntry.objects.bulk_update([entry], ["description"]),
            lambda: JournalEntry.objects.filter(pk=entry.pk).delete(),
            lambda: JournalEntry.objects.filter(pk=entry.pk)._raw_delete("default"),
            lambda: JournalLine.objects.filter(pk=line.pk)._raw_delete("default"),
            lambda: JournalEntry.objects.bulk_create([entry], update_conflicts=True, update_fields=["description"], unique_fields=["id"]),
            lambda: JournalLine.objects.bulk_create([JournalLine(journal_entry=entry, account=line.account, debit="1", credit="0")])])

    def test_failed_payment_resets_private_boundary_and_rolls_back_all_effects(self):
        from unittest.mock import patch
        before = self.snapshot()
        with patch("apps.finance.services.expenditures.sync_payment_status", side_effect=RuntimeError("Synthetic failure")):
            with self.assertRaises(RuntimeError):
                record_financial_supplier_payment(**payment(self))
        self.assertEqual(before, self.snapshot())
        self.refused([lambda: Expenditure.objects.filter(pk=self.expense.pk).update(payment_status="paid"),
            lambda: FundingAllocation.objects.create(expenditure=self.expense, funding_source=self.source,
                amount="1", allocation_date=date(2026, 1, 23))])

    def test_private_modes_cannot_rewrite_posted_economics_or_payment_evidence(self):
        for mode in ["create", "edit", "post", "payment"]:
            with expenditure_effect_boundary(mode):
                self.refused([lambda: Expenditure.objects.filter(pk=self.expense.pk).update(amount="101"),
                    lambda: FundingAllocation.objects.filter(pk=self.payment.pk).update(amount="41")])
        self.refused([lambda: Expenditure.objects.filter(pk=self.expense.pk).update(payment_status="paid")])

    def test_flags_off_detection_never_reads_new_phase6_tables(self):
        with CaptureQueriesContext(connection) as guard_queries:
            with self.assertRaises(DjangoValidationError), transaction.atomic():
                Expenditure.objects.filter(pk=self.expense.pk).update(notes="Changed")
        sql = " ".join(query["sql"] for query in guard_queries).lower()
        self.assertNotIn("finance_financialcommandreceipt", sql)
        self.assertNotIn("finance_inventorylotbinding", sql)
        self.assertTrue(guard_queries)

    def test_admin_managed_rows_viewable_read_only(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for obj in [self.expense, self.payment, self.cost]:
            registered = admin.site._registry[type(obj)]
            self.assertTrue(registered.has_view_permission(request, obj))
            self.assertFalse(registered.has_change_permission(request, obj))
            self.assertFalse(registered.has_delete_permission(request, obj))

    def test_rest_void_and_record_payment_return_reviewable_400(self):
        client = APIClient()
        client.force_authenticate(self.user)
        before = self.snapshot()
        for action, payload in [("void", {"reason": "Source only"}), ("record-payment", {
                "idempotency_key": "ordinary", "payment_date": "2026-01-23",
                "funding_allocations": [{"funding_source": self.source.pk, "amount": "10.00"}]})]:
            response = client.post(reverse(f"finance:finance-expenditure-{action}", args=[self.expense.pk]), payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(self.snapshot(), before)


@override_settings(**SETTINGS)
class ManagedDraftWriterTests(TestCase):
    def setUp(self):
        setup(self, post=False)

    def test_ordinary_draft_save_delete_post_or_funding_cannot_evade_lineage(self):
        original = Expenditure.objects.get(pk=self.expense.pk).__dict__.copy()
        for action in [lambda: Expenditure.objects.filter(pk=self.expense.pk).update(notes="Changed"),
                lambda: self.expense.save(), lambda: self.expense.delete(),
                lambda: post_expenditure(expenditure_id=self.expense.pk, user=self.user, allow_unpaid=True)]:
            with self.assertRaises(DjangoValidationError), transaction.atomic():
                action()
        self.assertEqual(Expenditure.objects.get(pk=self.expense.pk).notes, original["notes"])
        self.assertEqual(FundingAllocation.objects.count(), 0)

    def test_versioned_edit_then_post_remains_available(self):
        reference = self.expense.expenditure_reference
        changed, _ = update_financial_expenditure_draft(**drafts.editing(self, self.expense, {"notes": "Corrected"}))
        posted, _ = post_financial_expenditure_draft(**drafts.posting(self, changed))
        self.assertEqual((posted.pk, posted.expenditure_reference, posted.notes, posted.status),
            (self.expense.pk, reference, "Corrected", "posted"))

    def test_managed_draft_rest_edit_delete_and_legacy_post_refused(self):
        client = APIClient()
        client.force_authenticate(self.user)
        detail = reverse("finance:finance-expenditure-detail", args=[self.expense.pk])
        original = drafts.expenditure_draft_version(self.expense)
        response = client.patch(detail, {"notes": "Changed"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(client.delete(detail).status_code, 400)
        response = client.post(reverse("finance:finance-expenditure-post", args=[self.expense.pk]),
            {"payment_status": "unpaid"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.expense.refresh_from_db()
        self.assertEqual(original, drafts.expenditure_draft_version(self.expense))

    def test_new_admin_funding_form_reports_managed_parent(self):
        from django.forms import modelform_factory
        form = modelform_factory(FundingAllocation, fields=["expenditure", "funding_source", "amount", "allocation_date"])(
            data={"expenditure": self.expense.pk, "funding_source": self.source.pk, "amount": "1", "allocation_date": "2026-01-22"})
        self.assertFalse(form.is_valid())
        self.assertIn("Managed expenditure", str(form.non_field_errors()))

    def test_legacy_draft_edit_post_and_payment_compatibility(self):
        legacy = Expenditure.objects.create(expenditure_date=date(2026, 1, 21), amount="20", description="Legacy")
        legacy.notes = "Editable"
        legacy.save()
        post_expenditure(expenditure_id=legacy.pk, user=self.user, funding_rows=[], allow_unpaid=True)
        record_expenditure_payment(expenditure_id=legacy.pk, user=self.user, payment_group_key="legacy",
            payment_date=date(2026, 1, 22), funding_rows=[{"funding_source": self.source.pk, "amount": "10"}])
        legacy.refresh_from_db()
        self.assertEqual((legacy.notes, legacy.payment_status), ("Editable", "partial"))


@override_settings(**SETTINGS)
class ExpenditureWriterRaceTests(TransactionTestCase):
    def setUp(self):
        setup(self)

    def test_private_boundary_requires_an_atomic_effect(self):
        with self.assertRaises(DjangoValidationError), expenditure_effect_boundary("payment"):
            self.fail("No private permission should be granted outside an atomic command.")

    def race(self, ordinary):
        barrier, results = Barrier(2), []
        def run(call):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                call()
                results.append("accepted")
            except (ValidationError, DjangoValidationError):
                results.append("rejected")
            except Exception as error:
                results.append(type(error).__name__)
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=(call,)) for call in
            [lambda: record_financial_supplier_payment(**payment(self)), ordinary]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=25)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["accepted", "rejected"])
        self.assertEqual((FundingAllocation.objects.count(), CostAllocation.objects.count(),
            available_funding_source_cash(self.source)), (2, 1, Decimal("150")))
        self.assertEqual(JournalEntry.objects.count(), 5)
        self.assertEqual(trial_balance()["debits"], trial_balance()["credits"])

    def test_capture_enabled_effect_preserves_operational_positive_projection(self):
        from apps.mobile_sync.models import SyncChange, SyncStreamState
        from apps.mobile_sync.writers import sync_boundary
        SyncStreamState.objects.get_or_create(pk=1)
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary():
            record_financial_supplier_payment(**payment(self))
        # Supplier settlement changes no published operational entity. Finance
        # publication needs its separate profile; no empty/vacuous loop proof.
        self.assertEqual(SyncChange.objects.count(), 0)
        self.assertEqual((FundingAllocation.objects.count(), JournalEntry.objects.count()), (2, 5))

    def test_valid_payment_competes_with_ordinary_summary_edit(self):
        self.race(lambda: Expenditure.objects.filter(pk=self.expense.pk).update(payment_status="paid"))

    def test_valid_payment_competes_with_unjournaled_funding(self):
        self.race(lambda: FundingAllocation.objects.create(expenditure=self.expense, funding_source=self.source,
            amount="10", allocation_date=date(2026, 1, 23), payment_group_key="unjournaled"))

    def test_valid_payment_competes_with_source_only_void(self):
        self.race(lambda: reverse_expenditure(expenditure_id=self.expense.pk, reason="Source only", user=self.user))
