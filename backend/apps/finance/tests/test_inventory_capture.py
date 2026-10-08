from datetime import date
from decimal import Decimal
from threading import Barrier, Thread
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.finance.models import (AccountingNature, AccountingPeriod, ChartOfAccount, ConsumableItem,
    ConsumableUsage, ConsumableUsageScope, CostAllocation, Expenditure, ExpenditureCategory,
    FinancialCommandReceipt, FundingAllocation, OwnerContributor,
    InventoryCostingMethod, InventoryLocation, InventoryLocationStock, InventoryLotBinding,
    InventoryValuePool, JournalEntry, JournalLine, PeriodStatus, SharedConsumableLot,
    StockMovement, StockMovementType)
from apps.finance.services.financial_capture import record_financial_supplier_payment, record_financial_owner_contribution
from apps.finance.services.inventory_capture import record_inventory_purchase, record_inventory_issue
from apps.finance.services.ledger import trial_balance
from apps.finance.services.expenditures import (post_expenditure, record_expenditure_payment,
    reverse_expenditure, create_batch_cost_transaction)
from apps.finance.serializers import ExpenditureSerializer
from apps.finance.services.reporting import monthly_profitability_report
from apps.poultry.models import BatchStatus, InputCosts
from .test_financial_capture import fixture, instant
from apps.finance.services.consumables import record_consumable_usage, record_consumable_receipt


def inventory_fixture(test):
    fixture(test)
    for batch in (test.batch, test.other_batch):
        batch.status = BatchStatus.ACTIVE
        batch.save(update_fields=['status'])
    test.stock_category = ExpenditureCategory.objects.create(name='Synthetic consumable stock', code='stock-test',
        default_accounting_nature=AccountingNature.INVENTORY_PURCHASE, requires_item_details=True)
    test.item = ConsumableItem.objects.create(sku='TEST-FEED', name='Synthetic feed', category='Feed', base_unit='kg')
    test.location = InventoryLocation.objects.create(code='TEST-STORE', name='Synthetic store')


def purchase(test, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, currency='MWK', item_id=test.item.pk,
        location_id=test.location.pk, category_id=test.stock_category.pk, purchase_date=date(2026, 1, 10),
        quantity='10.0000', total_purchase_cost='100.00', supplier='Synthetic supplier', **extra)


def issue(test, lot, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, lot_id=lot.pk, location_id=test.location.pk,
        usage_date=date(2026, 1, 11), quantity='2.0000', task_or_purpose='Synthetic feeding',
        batch_id=test.batch.pk, **extra)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class InventoryCaptureTests(TestCase):
    def setUp(self):
        inventory_fixture(self)

    def balance(self, quantity, value):
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal(quantity), Decimal(value)))
        self.assertEqual(sum(SharedConsumableLot.objects.values_list('quantity_available', flat=True)), pool.quantity)
        self.assertEqual(sum(InventoryLocationStock.objects.values_list('quantity', flat=True)), pool.quantity)
        totals = trial_balance()
        self.assertEqual(totals['debits'], totals['credits'])

    def test_twenty_purchase_replays_one_lot_payable_movement_journal(self):
        payload = purchase(self, invoice_reference='INV-1')
        lot, created = record_inventory_purchase(**payload)
        self.assertTrue(created)
        for _ in range(20):
            replay, created = record_inventory_purchase(**payload)
            self.assertEqual(replay.pk, lot.pk)
            self.assertFalse(created)
        self.assertEqual((SharedConsumableLot.objects.count(), Expenditure.objects.count(),
            StockMovement.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (1, 1, 1, 1, 1))
        self.assertEqual((CostAllocation.objects.count(), ConsumableUsage.objects.count(), InputCosts.objects.count()), (0, 0, 0))
        self.assertEqual(list(JournalLine.objects.order_by('account__code').values_list('account__code', 'debit', 'credit')),
            [('1200', Decimal('100.00'), Decimal('0.00')), ('2000', Decimal('0.00'), Decimal('100.00'))])
        self.balance('10', '100')
        for change in [{'quantity': '11'}, {'total_purchase_cost': '101'}, {'purchase_date': date(2026, 1, 12)},
                       {'supplier': 'Changed'}, {'invoice_reference': 'Changed'}, {'expiry_date': date(2026, 2, 1)}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_purchase(**{**payload, **change})
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_twenty_issue_replays_one_cost_and_stock_decrement(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        payload = issue(self, lot)
        usage, _ = record_inventory_issue(**payload)
        for _ in range(20):
            replay, created = record_inventory_issue(**payload)
            self.assertEqual(replay.pk, usage.pk)
            self.assertFalse(created)
        self.assertEqual(usage.recognized_cost, Decimal('20.00'))
        self.assertEqual((ConsumableUsage.objects.count(), StockMovement.objects.count(), JournalEntry.objects.count()), (1, 2, 2))
        self.assertEqual((CostAllocation.objects.count(), InputCosts.objects.count()), (0, 0))
        self.balance('8', '80')
        for change in [{'quantity': '3'}, {'batch_id': self.other_batch.pk}, {'usage_date': date(2026, 1, 12)},
                       {'task_or_purpose': 'Changed'}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_issue(**{**payload, **change})
        report = monthly_profitability_report(self.period)
        self.assertEqual(report['production']['direct_consumable_usage'], Decimal('20.00'))
        self.assertEqual(report['production']['direct_batch_costs'], Decimal('0.00'))
        self.assertEqual(report['deferred_balances']['closing_consumable_inventory'], Decimal('80.00'))

    def test_weighted_average_across_lots_not_first_lot_purchase_price(self):
        first, _ = record_inventory_purchase(**purchase(self))
        record_inventory_purchase(**{**purchase(self), 'total_purchase_cost': '200.00'})
        usage, _ = record_inventory_issue(**{**issue(self, first), 'quantity': '5'})
        self.assertEqual(usage.recognized_cost, Decimal('75.00'))
        self.assertEqual(StockMovement.objects.get(usage=usage).total_cost, Decimal('75.00'))
        self.balance('15', '225')

    def test_rounding_residual_consumed_exactly_on_final_issue(self):
        lot, _ = record_inventory_purchase(**{**purchase(self), 'quantity': '3', 'total_purchase_cost': '1.00'})
        costs = [record_inventory_issue(**{**issue(self, lot), 'quantity': '1'})[0].recognized_cost for _ in range(3)]
        self.assertEqual(costs, [Decimal('0.33'), Decimal('0.34'), Decimal('0.33')])
        self.assertEqual(sum(costs), Decimal('1.00'))
        self.assertEqual(sum(StockMovement.objects.filter(movement_type=StockMovementType.ISSUE).values_list('total_cost', flat=True)), Decimal('1.00'))
        self.balance('0', '0')

    def test_subcent_issue_does_not_fabricate_zero_journal_or_lose_final_cent(self):
        lot, _ = record_inventory_purchase(**{**purchase(self), 'quantity': '3', 'total_purchase_cost': '0.01'})
        first, _ = record_inventory_issue(**{**issue(self, lot), 'quantity': '1'})
        self.assertEqual(first.recognized_cost, Decimal('0.00'))
        self.assertEqual(JournalEntry.objects.count(), 1)
        last, _ = record_inventory_issue(**{**issue(self, lot), 'quantity': '2'})
        self.assertEqual(last.recognized_cost, Decimal('0.01'))
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.balance('0', '0')

    def funded_source(self):
        owner = OwnerContributor.objects.create(display_name='Synthetic stock funder')
        receipt, _ = record_financial_owner_contribution(submission_id=uuid.uuid4(), user=self.user, currency='MWK',
            owner_id=owner.pk, amount='200.00', receipt_date=instant(day=2))
        return receipt.funding_source

    def test_partial_initial_and_later_payment_cash_payable_not_second_expense(self):
        source = self.funded_source()
        lot, _ = record_inventory_purchase(**purchase(self, funding_allocations=[{'funding_source': source.pk, 'amount': '40.00'}],
            payment_date=date(2026, 1, 12)))
        binding = InventoryLotBinding.objects.get(lot=lot)
        self.assertEqual((lot.payment_status, lot.payment_date), ('partial', None))
        self.assertEqual(binding.expenditure.payment_status, 'partial')
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency='MWK', expenditure_id=binding.expenditure_id,
            payment_date=date(2026, 2, 2), funding_allocations=[{'funding_source': source.pk, 'amount': '60.00'}])
        expense, _ = record_financial_supplier_payment(**payload)
        for _ in range(20):
            self.assertFalse(record_financial_supplier_payment(**payload)[1])
        lot.refresh_from_db()
        self.assertEqual((expense.payment_status, lot.payment_status, lot.payment_date), ('paid', 'paid', date(2026, 2, 2)))
        self.assertEqual((FundingAllocation.objects.count(), JournalEntry.objects.count(), Expenditure.objects.count()), (2, 4, 1))
        self.balance('10', '100')
        report = monthly_profitability_report(feb)
        self.assertEqual(report['cash_flow']['operating']['outflows'], Decimal('60.00'))
        self.assertEqual(report['operating_costs']['general_operating_expenses'], Decimal('0.00'))

    def test_failed_funding_rolls_back_lot_pool_payable_journal_and_receipt(self):
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**purchase(self, funding_allocations=[{'funding_source': 9223372036854775807, 'amount': '100.00'}],
                payment_date=date(2026, 1, 12)))
        for model in [SharedConsumableLot, InventoryLotBinding, InventoryValuePool, InventoryLocationStock,
                      Expenditure, StockMovement, JournalEntry, FinancialCommandReceipt]:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_later_inventory_settlement_refuses_deposit_and_future_evidence(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        binding = InventoryLotBinding.objects.get(lot=lot)
        source = self.funded_source()
        payload = dict(submission_id=uuid.uuid4(), user=self.user, currency='MWK', expenditure_id=binding.expenditure_id,
            funding_allocations=[{'funding_source': source.pk, 'amount': '100.00'}])
        # A valid covering period prevents an absent-period error from hiding a
        # missing actual-date guard.
        AccountingPeriod.objects.create(period_start=date(2099, 1, 1), period_end=date(2099, 1, 31))
        for day in [date(2026, 1, 9), date(2099, 1, 1)]:
            with self.subTest(day=day), self.assertRaises(ValidationError) as error:
                record_financial_supplier_payment(**payload, payment_date=day)
            self.assertIn('payment_date', error.exception.detail)
        self.assertFalse(FundingAllocation.objects.exists())
        self.balance('10', '100')

    def test_missing_journal_account_rolls_back_purchase_and_issue(self):
        ChartOfAccount.objects.filter(code='1200').update(is_active=False)
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**purchase(self))
        self.assertFalse(SharedConsumableLot.objects.exists())
        self.assertFalse(InventoryValuePool.objects.exists())
        ChartOfAccount.objects.filter(code='1200').update(is_active=True)
        lot, _ = record_inventory_purchase(**purchase(self))
        ChartOfAccount.objects.filter(code='5000').update(is_active=False)
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        self.assertFalse(ConsumableUsage.objects.exists())
        self.assertEqual(StockMovement.objects.count(), 1)
        self.balance('10', '100')

    def test_expired_stock_closed_period_and_original_chronology_refused(self):
        lot, _ = record_inventory_purchase(**purchase(self, expiry_date=date(2026, 1, 12)))
        for day in [date(2026, 1, 9), date(2026, 1, 13)]:
            with self.subTest(day=day), self.assertRaises(ValidationError):
                record_inventory_issue(**{**issue(self, lot), 'usage_date': day})
        record_inventory_issue(**{**issue(self, lot), 'usage_date': date(2026, 1, 12)})
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**purchase(self))
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        with self.assertRaises(ValidationError):
            record_inventory_issue(**{**issue(self, lot), 'usage_date': date(2026, 1, 12)})
        self.balance('8', '80')

    def test_wrong_location_insufficient_stock_and_corrupt_balance_require_review(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        wrong = InventoryLocation.objects.create(code='WRONG', name='Different store')
        for change in [{'quantity': '10.0001'}, {'location_id': wrong.pk}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_issue(**{**issue(self, lot), **change})
        SharedConsumableLot.objects.filter(pk=lot.pk).update(quantity_available=Decimal('9.0000'))
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        self.assertFalse(ConsumableUsage.objects.exists())

    def test_tampered_carrying_value_or_recognized_cost_is_not_silently_repriced(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        InventoryValuePool.objects.filter(item=self.item).update(carrying_value=Decimal('101.00'))
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        InventoryValuePool.objects.filter(item=self.item).update(carrying_value=Decimal('100.00'))
        usage, _ = record_inventory_issue(**issue(self, lot))
        ConsumableUsage.objects.filter(pk=usage.pk).update(recognized_cost=Decimal('21.00'))
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        self.assertEqual(ConsumableUsage.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_legacy_overlap_before_and_after_pool_never_imported(self):
        data = dict(item=self.item.name, category='Feed', purchase_date=date(2026, 1, 1), quantity_purchased=Decimal('5'),
            unit_of_measurement='kg', total_purchase_cost=Decimal('50'), unit_cost=Decimal('10'), quantity_available=Decimal('5'))
        legacy = SharedConsumableLot.objects.create(**data)
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**purchase(self))
        legacy.delete()
        lot, _ = record_inventory_purchase(**purchase(self))
        legacy = SharedConsumableLot.objects.create(**data)
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, legacy))
        self.assertEqual(InventoryLotBinding.objects.count(), 1)
        self.assertFalse(ConsumableUsage.objects.exists())

    def test_fifo_and_current_permission_fail_even_on_retry(self):
        self.item.costing_method = InventoryCostingMethod.FIFO
        self.item.save()
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**purchase(self))
        self.item.costing_method = InventoryCostingMethod.WEIGHTED_AVERAGE
        self.item.save()
        payload = purchase(self)
        record_inventory_purchase(**payload)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            record_inventory_purchase(**payload)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_ordinary_receipt_and_usage_cannot_mix_with_managed_stock(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        with self.assertRaises(ValidationError):
            record_consumable_usage(recorded_by=self.user, consumable_lot=lot, accounting_period=self.period,
                usage_date=date(2026, 1, 11), quantity_used=Decimal('1'), usage_scope=ConsumableUsageScope.BATCH_DIRECT,
                batch=self.batch, task_or_purpose='Must not bypass the pool')
        with self.assertRaises(ValidationError):
            record_consumable_receipt(created_by=self.user, item=self.item.name, category='Feed',
                purchase_date=date(2026, 1, 11), quantity_purchased=Decimal('1'), total_purchase_cost=Decimal('10'),
                unit_of_measurement='kg')
        self.assertFalse(ConsumableUsage.objects.exists())
        self.assertEqual(SharedConsumableLot.objects.count(), 1)
        self.balance('10', '100')

    def test_supported_invoice_pair_unique_but_different_suppliers_allowed(self):
        record_inventory_purchase(**purchase(self, invoice_reference='INV-1'))
        with self.assertRaises(ValidationError):
            record_inventory_purchase(**{**purchase(self, invoice_reference=' inv-1 '), 'supplier': ' SYNTHETIC SUPPLIER '})
        record_inventory_purchase(**{**purchase(self, invoice_reference='INV-1'), 'supplier': 'Another supplier'})
        record_inventory_purchase(**purchase(self))
        record_inventory_purchase(**purchase(self))
        self.assertEqual(SharedConsumableLot.objects.count(), 4)

    def test_only_received_open_nonfinalized_batches_allow_direct_issue(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        for status in [BatchStatus.BOOKED, BatchStatus.DELIVERED, BatchStatus.PLANNED, BatchStatus.CLOSED]:
            self.batch.status = status
            self.batch.save(update_fields=['status'])
            with self.subTest(status=status), self.assertRaises(ValidationError):
                record_inventory_issue(**issue(self, lot))
        self.batch.status = BatchStatus.ACTIVE
        self.batch.entry_date = instant(day=15)
        self.batch.save(update_fields=['status', 'entry_date'])
        with self.assertRaises(ValidationError) as error:
            record_inventory_issue(**issue(self, lot))
        self.assertIn('usage_date', error.exception.detail)
        self.batch.entry_date = instant(day=1)
        self.batch.profitability_finalized_at = self.batch.entry_date
        self.batch.save(update_fields=['entry_date', 'profitability_finalized_at'])
        with self.assertRaises(ValidationError):
            record_inventory_issue(**issue(self, lot))
        self.balance('10', '100')

    def test_administration_cost_has_no_funding_batch_beneficiary(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        usage, _ = record_inventory_issue(**{**issue(self, lot), 'batch_id': None,
            'usage_scope': ConsumableUsageScope.ADMINISTRATION})
        self.assertIsNone(usage.batch_id)
        self.assertEqual(JournalLine.objects.get(account__code='6100').debit, Decimal('20.00'))
        self.assertFalse(JournalLine.objects.filter(batch__isnull=False).exists())
        self.assertEqual(monthly_profitability_report(self.period)['operating_costs']['administration_consumables'], Decimal('20.00'))

    def test_movement_model_and_bulk_mutations_cannot_rewrite_evidence(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        movement = StockMovement.objects.get(lot=lot)
        with self.assertRaises(DjangoValidationError):
            movement.save()
        with self.assertRaises(DjangoValidationError):
            movement.delete()
        for action in [lambda: StockMovement.objects.filter(pk=movement.pk).update(total_cost=Decimal('1')),
                       lambda: StockMovement.objects.filter(pk=movement.pk).delete(),
                       lambda: StockMovement.objects.bulk_update([movement], ['total_cost']),
                       lambda: StockMovement.objects.bulk_create([])]:
            with self.assertRaises(DjangoValidationError):
                action()
        movement._state.adding = True
        with self.assertRaises(DjangoValidationError):
            movement.save(force_update=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            movement.save()

    def test_purchase_input_never_accepts_float_rounding_or_fictional_payment(self):
        for change in [{'quantity': '1.00001'}, {'quantity': 1.5}, {'total_purchase_cost': '1.001'},
                       {'total_purchase_cost': True}, {'currency': 'USD'}, {'supplier': ''},
                       {'payment_date': date(2026, 1, 12)}, {'expiry_date': date(2026, 1, 9)}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_purchase(**{**purchase(self), **change})
        self.assertFalse(InventoryValuePool.objects.exists())

    def test_generic_expenditure_cannot_create_or_edit_inventory_purchase(self):
        data = dict(expenditure_date='2026-01-10', amount='100.00', description='Must use inventory command',
            category=self.stock_category.pk, accounting_nature=AccountingNature.INVENTORY_PURCHASE)
        serializer = ExpenditureSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('accounting_nature', serializer.errors)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post(reverse('finance:finance-expenditure-list'), data, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Expenditure.objects.exists())
        lot, _ = record_inventory_purchase(**purchase(self))
        expense = InventoryLotBinding.objects.get(lot=lot).expenditure
        serializer = ExpenditureSerializer(expense, data={'notes': 'Must not edit'}, partial=True)
        self.assertFalse(serializer.is_valid())
        with self.assertRaises(DjangoValidationError):
            expense.full_clean()
        expense.accounting_nature = AccountingNature.DIRECT_COST
        with self.assertRaises(DjangoValidationError):
            expense.full_clean()

    def test_generic_post_payment_and_void_cannot_bypass_stock_boundary(self):
        lot, _ = record_inventory_purchase(**purchase(self))
        expense = InventoryLotBinding.objects.get(lot=lot).expenditure
        source = self.funded_source()
        with self.assertRaises(ValidationError):
            post_expenditure(expenditure_id=expense.pk, user=self.user, allow_unpaid=True)
        with self.assertRaises(ValidationError):
            record_expenditure_payment(expenditure_id=expense.pk, user=self.user, payment_date=date(2026, 1, 12),
                payment_group_key='generic-bypass', funding_rows=[{'funding_source': source.pk, 'amount': '100.00'}])
        with self.assertRaises(ValidationError):
            reverse_expenditure(expenditure_id=expense.pk, reason='Not a standalone void', user=self.user)
        expense.refresh_from_db()
        self.assertEqual((expense.status, expense.payment_status), ('posted', 'unpaid'))
        self.assertFalse(FundingAllocation.objects.exists())
        self.balance('10', '100')

    def test_batch_cost_purchase_does_not_bypass_inventory_category(self):
        with self.assertRaises(ValidationError):
            create_batch_cost_transaction(batch=self.batch, user=self.user, data={
                'idempotency_key': 'stock-must-not-be-input-cost', 'payment_status': 'credit',
                'category_id': self.stock_category.pk})
        self.assertFalse(Expenditure.objects.exists())
        self.assertFalse(InputCosts.objects.exists())
        self.assertFalse(CostAllocation.objects.exists())


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class InventoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        inventory_fixture(self)

    def race(self, functions):
        self.assertEqual(connection.vendor, 'postgresql')
        barrier = Barrier(len(functions))
        results, errors = [], []
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results.append(function())
            except ValidationError as error:
                results.append(error)
            except Exception as error:
                errors.append(error)
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=(function,)) for function in functions]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        return results

    def test_same_intent_concurrent_purchase_posts_once(self):
        payload = purchase(self)
        results = self.race([lambda: record_inventory_purchase(**payload)] * 2)
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual((SharedConsumableLot.objects.count(), Expenditure.objects.count(), JournalEntry.objects.count()), (1, 1, 1))

    def test_two_batches_compete_for_last_stock_one_cost_and_issue(self):
        lot, _ = record_inventory_purchase(**{**purchase(self), 'quantity': '1'})
        left = {**issue(self, lot), 'quantity': '1'}
        right = {**issue(self, lot), 'quantity': '1', 'batch_id': self.other_batch.pk}
        results = self.race([lambda: record_inventory_issue(**left), lambda: record_inventory_issue(**right)])
        self.assertEqual(sum(isinstance(result, ValidationError) for result in results), 1)
        self.assertEqual((ConsumableUsage.objects.count(), StockMovement.objects.count(), JournalEntry.objects.count()), (1, 2, 2))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal('0'), Decimal('0')))
        self.assertEqual(ConsumableUsage.objects.get().recognized_cost, Decimal('100.00'))

    def test_duplicate_supplier_invoice_different_items_accepts_one_purchase(self):
        other = ConsumableItem.objects.create(sku='OTHER', name='Another synthetic item', category='Feed', base_unit='kg')
        AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        left = purchase(self, invoice_reference='SAME')
        right = {**purchase(self, invoice_reference='same'), 'item_id': other.pk, 'purchase_date': date(2026, 2, 10)}
        results = self.race([lambda: record_inventory_purchase(**left), lambda: record_inventory_purchase(**right)])
        self.assertEqual(sum(isinstance(result, ValidationError) for result in results), 1)
        self.assertEqual((Expenditure.objects.count(), InventoryLotBinding.objects.count(), JournalEntry.objects.count()), (1, 1, 1))
