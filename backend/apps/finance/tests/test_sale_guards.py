"""Posted sales/cash cannot be mutated through ordinary writers, gates off."""
from datetime import date
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import F
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finance.models import FinancialCommandReceipt, JournalEntry, JournalLine, SalePayment, FundingSource
from apps.finance.services.collections import record_sale_payment, reverse_sale_payment
from apps.finance.services.financial_capture import record_financial_sale, record_financial_receipt
from apps.finance.services.ledger import reverse_journal, trial_balance
from apps.finance.services.profitability import available_batch_cash
from apps.finance.services.sale_guards import sale_posting_boundary
from apps.poultry.models import Sales, SaleSellingCost, Batch
from apps.poultry.services.batch_lifecycle import create_sale_with_lifecycle
from . import test_financial_capture as fixtures
from .inventory_corruption import corrupt_inventory


def original_sale(test):
    data = fixtures.sale_payload(test)
    data.update(selling_costs=[{'category': 'transport', 'amount': '15.00'},
        {'category': 'packaging', 'amount': '5.00'}],
        initial_receipt={'amount': '50.00', 'payment_date': fixtures.instant(), 'payment_method': 'cash'})
    test.original_request = data
    test.sale = record_financial_sale(**data)[0]
    test.payment = test.sale.payments.get()
    test.cost = test.sale.selling_costs.order_by('pk').first()


def legacy_sale(test):
    data = fixtures.sale_payload(test)
    for key in ['submission_id', 'currency', 'user']:
        data.pop(key)
    data['unit_price'] = Decimal(data['unit_price'])
    return create_sale_with_lifecycle(created_by=test.user, amount_paid=Decimal('0'),
        payment_status='unpaid', payment_method='cash', **data)


def ordinary_payment(test, sale=None, **extra):
    return dict(sale_id=(sale or test.sale).pk, amount=Decimal('10'), payment_date=fixtures.instant(day=21),
        payment_method='cash', created_by=test.user, **extra)


@override_settings(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False,
    FINANCE_SALE_COST_SETTLEMENT=False, FINANCE_SALE_COST_REVERSALS=False)
class SaleWriterGuardTests(TestCase):
    def setUp(self):
        fixtures.fixture(self)
        original_sale(self)

    def snapshot(self):
        return {model._meta.model_name: list(model.objects.order_by('pk').values()) for model in
            [Sales, SaleSellingCost, SalePayment, FundingSource, JournalEntry, JournalLine, FinancialCommandReceipt]}

    def refused(self, actions):
        before = self.snapshot()
        for action in actions:
            with self.subTest(action=action), self.assertRaises(DjangoValidationError), transaction.atomic():
                action()
            self.assertEqual(before, self.snapshot())

    def test_sale_all_writer_paths_refuse_economic_changes(self):
        self.sale.unit_price = Decimal('101')
        self.refused([lambda: self.sale.save(), lambda: self.sale.save_base(),
            lambda: self.sale.save_base(raw=True), lambda: self.sale.save(update_fields=['unit_price']),
            lambda: Sales.objects.filter(pk=self.sale.pk).update(unit_price='101'),
            lambda: Sales.objects.bulk_update([self.sale], ['unit_price']),
            lambda: self.sale.delete(), lambda: Sales.objects.filter(pk=self.sale.pk).delete(),
            lambda: Sales.objects.filter(pk=self.sale.pk)._raw_delete('default')])

    def test_sale_source_evidence_and_summary_cannot_be_edited(self):
        for field, value in [('sale_date', fixtures.instant(day=21)), ('buyer_name', 'Changed'),
                ('batch_id', self.other_batch.pk), ('quantity_sold', 1), ('notes', 'Changed'),
                ('amount_paid', '200.00'), ('balance', '0'), ('payment_status', 'cancelled')]:
            self.refused([lambda: Sales.objects.filter(pk=self.sale.pk).update(**{field: value})])

    def test_unchanged_full_save_and_raw_import_refused(self):
        self.refused([lambda: self.sale.save(), lambda: self.sale.save_base(raw=True),
            lambda: self.cost.save(), lambda: self.payment.save()])

    def test_primary_key_spoofing_cannot_replace_original_sale(self):
        forged = Sales.objects.get(pk=self.sale.pk)
        forged._state.adding = True
        forged.buyer_name = 'Forged'
        self.refused([lambda: forged.save(), lambda: forged.save_base(raw=True),
            lambda: Sales.objects.bulk_create([forged], ignore_conflicts=True),
            lambda: Sales.objects.bulk_create([forged], update_conflicts=True,
                update_fields=['buyer_name'], unique_fields=['id'])])

    def test_selling_cost_all_writer_paths_refused(self):
        self.cost.amount = Decimal('1')
        self.refused([lambda: self.cost.save(), lambda: self.cost.save_base(raw=True),
            lambda: SaleSellingCost.objects.filter(pk=self.cost.pk).update(amount='1'),
            lambda: SaleSellingCost.objects.bulk_update([self.cost], ['amount']),
            lambda: self.cost.delete(), lambda: SaleSellingCost.objects.filter(pk=self.cost.pk).delete(),
            lambda: SaleSellingCost.objects.filter(pk=self.cost.pk)._raw_delete('default')])

    def test_selling_cost_parent_and_evidence_cannot_be_rewritten(self):
        for field, value in [('sale_id', 999999), ('category', 'other'), ('notes', 'Changed')]:
            self.refused([lambda: SaleSellingCost.objects.filter(pk=self.cost.pk).update(**{field: value})])

    def test_payment_all_writer_paths_refused(self):
        self.payment.amount = Decimal('1')
        self.refused([lambda: self.payment.save(), lambda: self.payment.save_base(raw=True),
            lambda: SalePayment.objects.filter(pk=self.payment.pk).update(amount='1'),
            lambda: SalePayment.objects.bulk_update([self.payment], ['amount']),
            lambda: self.payment.delete(), lambda: SalePayment.objects.filter(pk=self.payment.pk).delete(),
            lambda: SalePayment.objects.filter(pk=self.payment.pk)._raw_delete('default')])

    def test_payment_date_status_reference_and_identity_cannot_change(self):
        for field, value in [('payment_date', fixtures.instant(day=22)), ('status', 'reversed'),
                ('external_reference', 'Changed'), ('idempotency_key', None), ('sale_id', 999999)]:
            self.refused([lambda: SalePayment.objects.filter(pk=self.payment.pk).update(**{field: value})])

    def test_ordinary_collection_cannot_create_unjournaled_cash(self):
        self.refused([lambda: record_sale_payment(**ordinary_payment(self)),
            lambda: SalePayment.objects.create(**ordinary_payment(self)),
            lambda: SalePayment.objects.bulk_create([SalePayment(payment_reference='UNJOURNALED',
                **ordinary_payment(self))])])

    def test_ordinary_selling_cost_cannot_append_unjournaled_payable(self):
        row = SaleSellingCost(sale=self.sale, amount='1', category='other')
        self.refused([lambda: row.save(), lambda: row.save_base(raw=True),
            lambda: SaleSellingCost.objects.bulk_create([row])])

    def test_ordinary_payment_reversal_cannot_change_only_source_cash(self):
        self.refused([lambda: reverse_sale_payment(payment_id=self.payment.pk,
            reason='Synthetic source-only attempt', reversed_by=self.user)])
        self.assertEqual(available_batch_cash(self.batch), Decimal('50.00'))

    def test_gl_only_reversal_refused_for_sale_receipt_and_cost_even_gates_off(self):
        before = self.snapshot()
        for journal in JournalEntry.objects.all():
            with self.subTest(source=journal.source_model), self.assertRaises(ValidationError):
                reverse_journal(journal, posting_date=date(2026, 1, 22), reason='GL-only', user=self.user)
        self.assertEqual(before, self.snapshot())

    def test_authorized_dated_collection_updates_only_summary_and_one_journal(self):
        original = Sales.objects.filter(pk=self.sale.pk).values().get()
        request = dict(submission_id=uuid.uuid4(), user=self.user, currency='MWK', sale_id=self.sale.pk,
            amount='10.00', payment_date=fixtures.instant(day=21), payment_method='cash')
        payment, created = record_financial_receipt(**request)
        self.assertTrue(created)
        for _ in range(20):
            replay, created = record_financial_receipt(**request)
            self.assertEqual(payment.pk, replay.pk)
            self.assertFalse(created)
        current = Sales.objects.filter(pk=self.sale.pk).values().get()
        self.assertEqual({key: val for key, val in current.items() if key not in
            {'amount_paid', 'balance', 'payment_status', 'updated_at'}},
            {key: val for key, val in original.items() if key not in
            {'amount_paid', 'balance', 'payment_status', 'updated_at'}})
        self.assertEqual((current['amount_paid'], current['balance']), (Decimal('60'), Decimal('140')))
        self.assertEqual((SalePayment.objects.count(), JournalEntry.objects.count()), (2, 5))
        self.assertEqual(trial_balance()['debits'], trial_balance()['credits'])

    def test_authorized_effect_failure_rolls_back_sources_journal_and_permanent_receipt(self):
        before = self.snapshot()
        with patch('apps.finance.services.financial_capture._post_receipt', side_effect=RuntimeError('Synthetic failure')):
            with self.assertRaises(RuntimeError):
                record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency='MWK',
                    sale_id=self.sale.pk, amount='10', payment_date=fixtures.instant(day=21), payment_method='cash')
        self.assertEqual(before, self.snapshot())
        # The private permission cannot leak out of the failed transaction.
        self.refused([lambda: record_sale_payment(**ordinary_payment(self))])

    def test_private_effect_does_not_authorize_rewriting_original_cost_or_sale(self):
        with transaction.atomic(), sale_posting_boundary():
            self.refused([lambda: Sales.objects.filter(pk=self.sale.pk).update(buyer_name='Changed'),
                lambda: SaleSellingCost.objects.filter(pk=self.cost.pk).update(amount='1'),
                lambda: SalePayment.objects.filter(pk=self.payment.pk).update(amount='1')])

    def test_managed_detection_uses_no_phase6_tables_when_gates_off(self):
        with CaptureQueriesContext(connection) as captured:
            self.refused([lambda: Sales.objects.filter(pk=self.sale.pk).update(unit_price='1')])
        guard_queries = [q['sql'] for q in captured if 'UPDATE' in q['sql'] or 'sale_guard_pk' in q['sql']]
        self.assertTrue(guard_queries)
        self.assertFalse(any('finance_financialcommandreceipt' in sql or 'finance_salecostpayment' in sql
            for sql in guard_queries))

    def test_rest_collection_and_reversal_refused_as_400_not_server_error(self):
        client = APIClient()
        client.force_authenticate(self.user)
        before = self.snapshot()
        response = client.post(reverse('finance:sale-payments', args=[self.sale.pk]),
            {'amount': '10.00', 'payment_date': fixtures.instant(day=21).isoformat(), 'payment_method': 'cash',
             'idempotency_key': 'synthetic-ordinary-receipt'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('sale', response.data)
        response = client.post(reverse('finance:sale-payment-reverse', args=[self.payment.pk]),
            {'reason': 'Synthetic attempt'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('payment', response.data)
        self.assertEqual(before, self.snapshot())

    def test_admin_keeps_managed_sale_and_cost_viewable_but_read_only(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user
        for obj in [self.sale, self.cost, self.payment]:
            panel = admin.site._registry[type(obj)]
            self.assertTrue(panel.has_view_permission(request, obj))
            self.assertFalse(panel.has_change_permission(request, obj))
            self.assertFalse(panel.has_delete_permission(request, obj))

    def test_admin_new_cost_form_reports_posted_parent_before_saving(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user
        form_type = admin.site._registry[SaleSellingCost].get_form(request)
        form = form_type(data={'sale': str(self.sale.pk), 'amount': '1', 'category': 'other',
            'created_by': str(self.user.pk), 'notes': 'Synthetic attempted cost'})
        self.assertFalse(form.is_valid())
        self.assertIn('sale', form.errors)
        self.assertIn('controlled financial cost workflow', str(form.errors['sale']))
        self.assertEqual(SaleSellingCost.objects.count(), 2)

    def test_collected_cash_source_cannot_be_rebound_through_ordinary_writers(self):
        source = FundingSource.objects.get(source_type='batch_collection', batch=self.batch)
        source.batch = self.other_batch
        self.refused([lambda: source.save(), lambda: source.save_base(raw=True),
            lambda: source.delete(), lambda: FundingSource.objects.filter(pk=source.pk).delete(),
            lambda: FundingSource.objects.filter(pk=source.pk)._raw_delete('default'),
            lambda: FundingSource.objects.filter(pk=source.pk).update(batch=self.other_batch),
            lambda: FundingSource.objects.filter(pk=source.pk).update(source_type='loan'),
            lambda: FundingSource.objects.bulk_update([source], ['batch']),
            lambda: FundingSource.objects.bulk_create([source], update_conflicts=True,
                update_fields=['batch'], unique_fields=['id'])])

    def test_collected_cash_source_metadata_and_activation_remain_editable(self):
        source = FundingSource.objects.get(source_type='batch_collection', batch=self.batch)
        source.description = 'Updated source label'
        source.save(update_fields=['description'])
        FundingSource.objects.filter(pk=source.pk).update(is_active=False)
        source.refresh_from_db()
        self.assertEqual((source.description, source.is_active), ('Updated source label', False))
        self.assertEqual(available_batch_cash(self.batch), Decimal('50'))

    def test_operational_publication_keeps_finance_fields_out_of_worker_projection(self):
        from apps.mobile_sync.models import SyncEntity
        from apps.mobile_sync.writers import sync_boundary
        with override_settings(MOBILE_SYNC_CAPTURE=True), sync_boundary():
            self.capture_receipt()
        batch = SyncEntity.objects.get(entity_type='poultry.batch', source_pk=str(self.batch.pk))
        from apps.mobile_sync.projections import public_payload
        public = public_payload('poultry.batch', batch.payload)
        self.assertEqual(public['sold_bird_count'], 2)
        self.assertNotIn('amount_paid', public)
        self.assertNotIn('selling_costs', public)
        self.assertNotIn('sale_version', public)

    def test_legacy_records_keep_old_edit_and_collection_workflows(self):
        sale = legacy_sale(self)
        sale.buyer_name = 'Legacy editable'
        sale.save()
        cost = SaleSellingCost.objects.create(sale=sale, amount='3', category='other')
        cost.notes = 'Legacy editable'
        cost.save()
        payment = record_sale_payment(**ordinary_payment(self, sale))[0]
        reverse_sale_payment(payment_id=payment.pk, reason='Legacy reversal', reversed_by=self.user)
        payment.refresh_from_db()
        self.assertEqual(payment.status, 'reversed')
        self.assertEqual(JournalEntry.objects.count(), 4)

    def test_financial_collection_refuses_legacy_parent_without_adopting_earlier_cash(self):
        sale = legacy_sale(self)
        original = record_sale_payment(**ordinary_payment(self, sale))[0]
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency='MWK', sale_id=sale.pk,
                amount='10', payment_date=fixtures.instant(day=21), payment_method='cash')
        self.assertEqual(before, self.snapshot())
        self.assertFalse(JournalEntry.objects.filter(source_model='finance.SalePayment', source_identifier=str(original.pk)).exists())

    def test_reserved_keys_cannot_be_forged_on_legacy_receipts(self):
        sale = legacy_sale(self)
        self.refused([lambda: record_sale_payment(**ordinary_payment(self, sale, idempotency_key='financial-receipt:forged'))])
        payment = record_sale_payment(**ordinary_payment(self, sale))[0]
        self.refused([lambda: SalePayment.objects.filter(pk=payment.pk).update(idempotency_key='sale-initial:forged')])

    def test_legacy_child_cannot_be_rebound_into_managed_sale(self):
        sale = legacy_sale(self)
        payment = record_sale_payment(**ordinary_payment(self, sale))[0]
        cost = SaleSellingCost.objects.create(sale=sale, amount='1', category='other')
        payment.sale = self.sale
        cost.sale = self.sale
        self.refused([lambda: payment.save(), lambda: cost.save(),
            lambda: SalePayment.objects.filter(pk=payment.pk).update(sale=self.sale),
            lambda: SaleSellingCost.objects.filter(pk=cost.pk).update(sale_id=self.sale.pk),
            lambda: SaleSellingCost.objects.filter(pk=cost.pk).update(sale_id=F('sale_id'))])

    def test_mixed_bulk_update_refuses_every_row_atomically(self):
        sale = legacy_sale(self)
        self.sale.buyer_name = sale.buyer_name = 'Attempt'
        self.refused([lambda: Sales.objects.bulk_update([sale, self.sale], ['buyer_name'], batch_size=1)])

    def test_batch_cascade_cannot_remove_managed_sale_or_cost(self):
        before = self.snapshot()
        for action in [lambda: self.batch.delete(), lambda: Batch.objects.filter(pk=self.batch.pk).delete()]:
            with self.assertRaises((DjangoValidationError, ProtectedError)), transaction.atomic():
                action()
            self.assertEqual(before, self.snapshot())

    def capture_receipt(self):
        return record_financial_receipt(submission_id=uuid.uuid4(), user=self.user, currency='MWK',
            sale_id=self.sale.pk, amount='10', payment_date=fixtures.instant(day=21), payment_method='cash')

    def test_source_tampering_is_independently_detected_before_new_cash(self):
        corrupt_inventory(Sales, self.sale.pk, buyer_name='Privileged damage')
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.capture_receipt()
        self.assertEqual(before, self.snapshot())

    def test_journal_line_damage_is_independently_detected_before_new_cash(self):
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        line = journal.lines.get(account__code='1100')
        corrupt_inventory(JournalLine, line.pk, debit='199.00')
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.capture_receipt()
        self.assertEqual(before, self.snapshot())

    def test_cancelled_or_reversed_original_requires_review(self):
        for model, pk, field, value in [(Sales, self.sale.pk, 'payment_status', 'cancelled'),
                (JournalEntry, JournalEntry.objects.get(source_model='poultry.Sales').pk, 'status', 'reversed')]:
            with self.subTest(field=field), transaction.atomic():
                old = model.objects.filter(pk=pk).values(field).get()[field]
                corrupt_inventory(model, pk, **{field: value})
                before = self.snapshot()
                with self.assertRaises(ValidationError):
                    self.capture_receipt()
                self.assertEqual(before, self.snapshot())
                corrupt_inventory(model, pk, **{field: old})

    def test_older_unversioned_anchor_can_replay_but_cannot_authorize_new_receipt(self):
        import json
        anchor = FinancialCommandReceipt.objects.get(pk=self.original_request['submission_id'])
        old_result = {key: value for key, value in anchor.result.items() if key != 'sale_version'}
        corrupt_inventory(FinancialCommandReceipt, anchor.pk, result=json.dumps(old_result))
        before = self.snapshot()
        self.assertEqual(record_financial_sale(**self.original_request), (self.sale, False))
        with self.assertRaises(ValidationError):
            self.capture_receipt()
        self.assertEqual(before, self.snapshot())

    def test_mismatched_permanent_journal_anchor_cannot_authorize_collection(self):
        import json
        anchor = FinancialCommandReceipt.objects.get(pk=self.original_request['submission_id'])
        corrupt_inventory(FinancialCommandReceipt, anchor.pk, result=json.dumps({**anchor.result, 'journal_ids': []}))
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.capture_receipt()
        self.assertEqual(before, self.snapshot())

    def test_valid_dated_collection_does_not_change_sale_cost_version(self):
        from apps.finance.services.selling_cost_settlement import selling_cost_version
        before = selling_cost_version(self.cost)
        self.capture_receipt()
        self.cost = SaleSellingCost.objects.select_related('sale').get(pk=self.cost.pk)
        self.assertEqual(before, selling_cost_version(self.cost))

    def test_journal_marker_source_date_status_and_key_all_writers_refused(self):
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        journal.status = 'reversed'
        self.refused([lambda: journal.save(), lambda: journal.save_base(raw=True),
            lambda: JournalEntry.objects.filter(pk=journal.pk).update(status='reversed'),
            lambda: JournalEntry.objects.filter(pk=journal.pk).update(idempotency_key='Erased marker'),
            lambda: JournalEntry.objects.filter(pk=journal.pk).update(source_model='Changed'),
            lambda: JournalEntry.objects.filter(pk=journal.pk).update(posting_date=date(2026, 1, 22)),
            lambda: JournalEntry.objects.bulk_update([journal], ['status']),
            lambda: journal.delete(), lambda: JournalEntry.objects.filter(pk=journal.pk).delete(),
            lambda: JournalEntry.objects.filter(pk=journal.pk)._raw_delete('default')])

    def test_journal_lines_all_writer_paths_refused(self):
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        line = journal.lines.get(account__code='1100')
        line.debit = Decimal('199')
        self.refused([lambda: line.save(), lambda: line.save_base(raw=True),
            lambda: JournalLine.objects.filter(pk=line.pk).update(debit='199'),
            lambda: JournalLine.objects.bulk_update([line], ['debit']), lambda: line.delete(),
            lambda: JournalLine.objects.filter(pk=line.pk).delete(),
            lambda: JournalLine.objects.filter(pk=line.pk)._raw_delete('default')])

    def test_completed_journal_cannot_receive_new_lines_even_inside_private_effect(self):
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        line = JournalLine(journal_entry=journal, account=journal.lines.first().account, debit='1', credit='0')
        self.refused([lambda: line.save_base(raw=True), lambda: JournalLine.objects.bulk_create([line])])
        with transaction.atomic(), sale_posting_boundary():
            self.refused([lambda: line.save_base(), lambda: JournalLine.objects.bulk_create([line])])

    def test_reserved_journal_cannot_be_created_outside_source_command(self):
        original = JournalEntry.objects.get(source_model='poultry.Sales')
        forged = JournalEntry(reference='FORGED-SALE', posting_date=original.posting_date,
            accounting_period=self.period, source_model='poultry.Sales', source_identifier=str(self.sale.pk),
            idempotency_key='financial-sale:forged', description='Synthetic forgery')
        self.refused([lambda: forged.save(), lambda: forged.save_base(raw=True),
            lambda: JournalEntry.objects.bulk_create([forged])])

    def test_private_boundary_cannot_mutate_posted_journal_or_line(self):
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        line = journal.lines.first()
        with transaction.atomic(), sale_posting_boundary():
            self.refused([lambda: journal.save(update_fields=['status']),
                lambda: JournalEntry.objects.filter(pk=journal.pk).update(status='draft'),
                lambda: JournalLine.objects.filter(pk=line.pk).update(memo='Rewritten')])

    def test_legacy_line_cannot_be_rebound_into_posted_sale_journal(self):
        from apps.finance.services.ledger import post_journal
        old = post_journal(posting_date=date(2026, 1, 21), description='Legacy', source_model='test.Legacy',
            source_identifier='1', idempotency_key='synthetic-old-journal', user=self.user,
            lines=[{'account': '1000', 'debit': '1'}, {'account': '3000', 'credit': '1'}])
        line = old.lines.first()
        journal = JournalEntry.objects.get(source_model='poultry.Sales')
        line.journal_entry = journal
        self.refused([lambda: line.save_base(raw=True),
            lambda: JournalLine.objects.filter(pk=line.pk).update(journal_entry=journal),
            lambda: JournalEntry.objects.filter(pk=old.pk).update(idempotency_key='financial-sale:adopted'),
            lambda: JournalEntry.objects.filter(pk=old.pk).update(reversal_of=journal)])


@override_settings(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_POULTRY_V2=False)
class SaleWriterRaceTests(TransactionTestCase):
    race = fixtures.FinancialCaptureConcurrencyTests.race

    def setUp(self):
        fixtures.fixture(self)
        original_sale(self)
        self.assertEqual(connection.vendor, 'postgresql')

    def test_private_boundary_without_transaction_is_refused(self):
        with self.assertRaises(DjangoValidationError), sale_posting_boundary():
            self.fail('Unreachable')

    def test_collection_competes_with_ordinary_summary_edit(self):
        outcomes = self.race([lambda: record_financial_receipt(submission_id=uuid.uuid4(), user=self.user,
            currency='MWK', sale_id=self.sale.pk, amount='10', payment_date=fixtures.instant(day=21), payment_method='cash'),
            lambda: Sales.objects.filter(pk=self.sale.pk).update(amount_paid='200')])
        self.assertCountEqual([row[0] for row in outcomes], ['accepted', 'rejected'])
        self.sale.refresh_from_db()
        self.assertEqual((self.sale.amount_paid, self.sale.balance), (Decimal('60'), Decimal('140')))
        self.assertEqual((SalePayment.objects.count(), JournalEntry.objects.count()), (2, 5))

    def test_collection_competes_with_unjournaled_payment(self):
        outcomes = self.race([lambda: record_financial_receipt(submission_id=uuid.uuid4(), user=self.user,
            currency='MWK', sale_id=self.sale.pk, amount='10', payment_date=fixtures.instant(day=21), payment_method='cash'),
            lambda: record_sale_payment(**ordinary_payment(self))])
        self.assertCountEqual([row[0] for row in outcomes], ['accepted', 'rejected'])
        self.assertEqual((SalePayment.objects.count(), JournalEntry.objects.count()), (2, 5))

    def test_collection_competes_with_source_only_reversal(self):
        outcomes = self.race([lambda: record_financial_receipt(submission_id=uuid.uuid4(), user=self.user,
            currency='MWK', sale_id=self.sale.pk, amount='10', payment_date=fixtures.instant(day=21), payment_method='cash'),
            lambda: reverse_sale_payment(payment_id=self.payment.pk, reason='Source only', reversed_by=self.user)])
        self.assertCountEqual([row[0] for row in outcomes], ['accepted', 'rejected'])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'posted')
        self.assertEqual(available_batch_cash(self.batch), Decimal('60'))
