from datetime import date
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role, RoleChoices
from apps.finance.models import (AccountingPeriod, AllocationSourceType, ChartOfAccount, ConsumableUsageScope,
    CostAllocation, Expenditure, FinancialCommandReceipt, FundingAllocation,
    InventoryLocation, InventoryLocationStock, InventoryMovementEvidence, InventoryValuePool,
    JournalEntry, JournalLine, PeriodStatus, SharedConsumableLot, StockMovement, StockMovementType)
from apps.finance.services.inventory_capture import record_inventory_purchase, record_inventory_issue
from apps.finance.services.inventory_corrections import (record_inventory_return, record_inventory_transfer,
    record_inventory_waste, record_inventory_expiry, record_inventory_count_loss)
from apps.finance.services.profitability import batch_profitability, batch_survivor_cost_basis
from apps.finance.services.reporting import monthly_profitability_report
from apps.poultry.models import BatchStatus, FlockAdjustment, InputCosts
from .test_financial_capture import instant
from . import test_inventory_capture as inventory_tests


def movement(test, lot, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, lot_id=lot.pk, location_id=test.location.pk,
        movement_date=date(2026, 1, 12), quantity='1.0000', reason='Synthetic physical stock evidence', **extra)


def returned(test, original, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, original_issue_id=original.pk,
        location_id=test.location.pk, movement_date=date(2026, 1, 12), quantity='1.0000',
        reason='Synthetic unused stock returned', **extra)


def transfer(test, lot, **extra):
    return dict(submission_id=uuid.uuid4(), user=test.user, lot_id=lot.pk,
        from_location_id=test.location.pk, to_location_id=test.other_location.pk,
        movement_date=date(2026, 1, 12), quantity='1.0000', reason='Synthetic relocation', **extra)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class InventoryCorrectionTests(TestCase):
    def setUp(self):
        inventory_tests.inventory_fixture(self)
        self.other_location = InventoryLocation.objects.create(code='OTHER-STORE', name='Other synthetic store')

    balance = inventory_tests.InventoryCaptureTests.balance

    def purchase(self, **changes):
        return record_inventory_purchase(**{**inventory_tests.purchase(self), **changes})[0]

    def issue(self, lot, **changes):
        usage = record_inventory_issue(**{**inventory_tests.issue(self, lot), **changes})[0]
        return StockMovement.objects.get(usage=usage)

    def cash_and_payable(self):
        def net(code):
            lines = JournalLine.objects.filter(account__code=code)
            return (lines.aggregate(v=Sum('debit'))['v'] or Decimal('0')) - (lines.aggregate(v=Sum('credit'))['v'] or Decimal('0'))
        self.assertEqual((net('1000'), net('2000')), (Decimal('0'), Decimal('-100')))
        self.assertFalse(FundingAllocation.objects.exists())
        self.assertEqual(Expenditure.objects.count(), 1)
        self.assertFalse(CostAllocation.objects.exists())
        self.assertFalse(InputCosts.objects.exists())

    def test_twenty_returns_replay_original_cost_without_rewriting_issue(self):
        lot = self.purchase()
        original = self.issue(lot)
        payload = returned(self, original)
        result, created = record_inventory_return(**payload)
        self.assertTrue(created)
        before = dict(StockMovement.objects.filter(pk=original.pk).values().get())
        usage_before = dict(original.usage.__class__.objects.filter(pk=original.usage_id).values().get())
        for _ in range(20):
            replay, created = record_inventory_return(**payload)
            self.assertEqual(replay.pk, result.pk)
            self.assertFalse(created)
        self.assertEqual(result.total_cost, Decimal('10.00'))
        self.assertEqual(InventoryMovementEvidence.objects.get(movement=result).original_issue_id, original.pk)
        self.assertEqual(before, StockMovement.objects.filter(pk=original.pk).values().get())
        self.assertEqual(usage_before, original.usage.__class__.objects.filter(pk=original.usage_id).values().get())
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (3, 3, 3))
        self.balance('9', '90')
        self.cash_and_payable()
        self.assertEqual(batch_profitability(self.batch)['direct_batch_cost'], Decimal('10'))
        self.assertEqual(batch_survivor_cost_basis([self.batch])[self.batch.pk]['total_production_cost'], Decimal('10'))
        report = monthly_profitability_report(self.period)
        self.assertEqual(report['production']['direct_consumable_usage'], Decimal('10'))
        self.assertEqual(report['production']['active_batch_work_in_progress'], Decimal('10'))
        self.assertEqual(report['deferred_balances']['closing_consumable_inventory'], Decimal('90'))
        for change in [{'quantity': '2'}, {'movement_date': date(2026, 1, 13)},
                       {'location_id': self.other_location.pk}, {'reason': 'Changed evidence'}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_return(**{**payload, **change})

    def test_return_uses_original_issue_cost_after_new_purchase_price(self):
        lot = self.purchase()
        original = self.issue(lot, quantity='5')
        self.purchase(purchase_date=date(2026, 1, 12), total_purchase_cost='200.00')
        result, _ = record_inventory_return(**returned(self, original))
        self.assertEqual(result.total_cost, Decimal('10'))
        self.balance('16', '260')
        self.assertEqual(batch_profitability(self.batch)['direct_batch_cost'], Decimal('40'))

    def test_partial_return_residual_and_overreturn(self):
        lot = self.purchase(quantity='3', total_purchase_cost='1.00')
        original = self.issue(lot, quantity='3')
        costs = [record_inventory_return(**returned(self, original))[0].total_cost for _ in range(3)]
        self.assertEqual(costs, [Decimal('.33'), Decimal('.34'), Decimal('.33')])
        self.balance('3', '1')
        with self.assertRaises(ValidationError):
            record_inventory_return(**returned(self, original))
        self.assertEqual(batch_profitability(self.batch)['direct_batch_cost'], Decimal('0'))
        self.assertEqual(StockMovement.objects.count(), 5)

    def test_zero_cost_return_has_no_fictional_journal(self):
        lot = self.purchase(quantity='3', total_purchase_cost='0.01')
        original = self.issue(lot, quantity='1')
        record_inventory_return(**returned(self, original))
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.balance('3', '.01')

    def test_return_dated_current_period_leaves_old_period_and_issue_unchanged(self):
        lot = self.purchase()
        original = self.issue(lot)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28))
        record_inventory_return(**{**returned(self, original), 'movement_date': date(2026, 2, 2)})
        # Recalculate, not a fabricated old snapshot: cutoff excludes February.
        from apps.finance.services.reporting import _calculate_monthly_profitability_report
        january = _calculate_monthly_profitability_report(self.period)
        self.assertEqual(january['production']['direct_consumable_usage'], Decimal('20'))
        self.assertEqual(january['deferred_balances']['closing_consumable_inventory'], Decimal('80'))
        february = monthly_profitability_report(feb)
        self.assertEqual(february['production']['direct_consumable_usage'], Decimal('-10'))
        self.assertEqual(february['deferred_balances']['closing_consumable_inventory'], Decimal('90'))

    def test_administration_return_reduces_admin_cost_not_batch(self):
        lot = self.purchase()
        original = self.issue(lot, batch_id=None, usage_scope=ConsumableUsageScope.ADMINISTRATION)
        record_inventory_return(**returned(self, original))
        self.assertEqual(monthly_profitability_report(self.period)['operating_costs']['administration_consumables'], Decimal('10'))
        self.assertEqual(batch_profitability(self.batch)['direct_batch_cost'], Decimal('0'))
        self.assertFalse(JournalLine.objects.filter(batch__isnull=False).exists())
        self.cash_and_payable()

    def test_return_rejects_receipt_preissue_closed_finalized_and_wrong_content(self):
        lot = self.purchase()
        receipt = StockMovement.objects.get(lot=lot)
        with self.assertRaises(ValidationError):
            record_inventory_return(**returned(self, receipt))
        original = self.issue(lot)
        with self.assertRaises(ValidationError):
            record_inventory_return(**{**returned(self, original), 'movement_date': date(2026, 1, 10)})
        self.batch.status = BatchStatus.CLOSED
        self.batch.save()
        with self.assertRaises(ValidationError):
            record_inventory_return(**returned(self, original))
        self.batch.status = BatchStatus.ACTIVE
        self.batch.profitability_finalized_at = instant()
        self.batch.save()
        with self.assertRaises(ValidationError):
            record_inventory_return(**returned(self, original))
        self.balance('8', '80')

    def test_twenty_transfers_move_only_location_no_new_finance(self):
        lot = self.purchase()
        payload = transfer(self, lot)
        result, _ = record_inventory_transfer(**payload)
        for _ in range(20):
            self.assertEqual(record_inventory_transfer(**payload), (result, False))
        self.assertEqual(result.total_cost, Decimal('10'))
        self.assertEqual(InventoryLocationStock.objects.get(location=self.location).quantity, Decimal('9'))
        self.assertEqual(InventoryLocationStock.objects.get(location=self.other_location).quantity, Decimal('1'))
        self.balance('10', '100')
        self.cash_and_payable()
        self.assertEqual(JournalEntry.objects.count(), 1)
        self.assertEqual(FinancialCommandReceipt.objects.count(), 2)
        self.issue(lot, location_id=self.other_location.pk, usage_date=date(2026, 1, 12), quantity='1')
        self.balance('9', '90')

    def test_transfer_rejects_same_location_overdraw_inactive_and_replay_changes(self):
        lot = self.purchase()
        payload = transfer(self, lot)
        for change in [{'to_location_id': self.location.pk}, {'quantity': '11'}, {'quantity': '1.00001'}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_transfer(**{**payload, **change})
        self.other_location.is_active = False
        self.other_location.save()
        with self.assertRaises(ValidationError):
            record_inventory_transfer(**payload)
        self.other_location.is_active = True
        self.other_location.save()
        record_inventory_transfer(**payload)
        with self.assertRaises(ValidationError):
            record_inventory_transfer(**{**payload, 'quantity': '2'})
        self.balance('10', '100')

    def test_twenty_waste_replays_one_loss_and_no_cash_payable_effect(self):
        lot = self.purchase()
        payload = movement(self, lot)
        result, _ = record_inventory_waste(**payload)
        for _ in range(20):
            self.assertEqual(record_inventory_waste(**payload), (result, False))
        self.assertEqual(result.total_cost, Decimal('10'))
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count(), FinancialCommandReceipt.objects.count()), (2, 2, 2))
        self.balance('9', '90')
        self.cash_and_payable()
        report = monthly_profitability_report(self.period)
        self.assertEqual(report['operating_costs']['inventory_losses'], Decimal('10'))
        self.assertEqual(report['operating_costs']['administration_consumables'], Decimal('0'))
        self.assertEqual(report['production']['direct_consumable_usage'], Decimal('0'))
        self.assertEqual(report['deferred_balances']['closing_consumable_inventory'], Decimal('90'))
        self.assertFalse(JournalLine.objects.filter(batch__isnull=False).exists())
        with self.assertRaises(ValidationError):
            record_inventory_waste(**{**payload, 'reason': 'Changed'})

    def test_expiry_requires_recorded_date_then_destroys_only_available_stock(self):
        lot = self.purchase(expiry_date=date(2026, 1, 11))
        with self.assertRaises(ValidationError):
            record_inventory_expiry(**{**movement(self, lot), 'movement_date': date(2026, 1, 11)})
        with self.assertRaises(ValidationError):
            record_inventory_waste(**movement(self, lot))
        with self.assertRaises(ValidationError):
            record_inventory_transfer(**transfer(self, lot))
        payload = {**movement(self, lot), 'quantity': '10'}
        result, _ = record_inventory_expiry(**payload)
        for _ in range(20):
            self.assertEqual(record_inventory_expiry(**payload), (result, False))
        self.balance('0', '0')
        self.cash_and_payable()
        self.assertEqual(monthly_profitability_report(self.period)['operating_costs']['inventory_losses'], Decimal('100'))

    def test_return_of_expired_physical_stock_cannot_reissue_but_can_expire(self):
        lot = self.purchase(expiry_date=date(2026, 1, 11))
        original = self.issue(lot)
        record_inventory_return(**returned(self, original))
        with self.assertRaises(ValidationError):
            self.issue(lot, usage_date=date(2026, 1, 12), quantity='1')
        record_inventory_expiry(**{**movement(self, lot), 'quantity': '9'})
        self.balance('0', '0')

    def test_count_loss_records_expected_actual_and_binds_revision(self):
        lot = self.purchase()
        revision = InventoryValuePool.objects.get(item=self.item).revision
        payload = dict(submission_id=uuid.uuid4(), user=self.user, lot_id=lot.pk, location_id=self.location.pk,
            movement_date=date(2026, 1, 12), counted_quantity='8.0000', expected_revision=revision, reason='Synthetic counted discrepancy')
        result, _ = record_inventory_count_loss(**payload)
        evidence = InventoryMovementEvidence.objects.get(movement=result)
        self.assertEqual((evidence.expected_quantity, evidence.counted_quantity, result.quantity, result.total_cost),
            (Decimal('10'), Decimal('8'), Decimal('2'), Decimal('20')))
        for _ in range(20):
            self.assertEqual(record_inventory_count_loss(**payload), (result, False))
        with self.assertRaises(ValidationError):
            record_inventory_count_loss(**{**payload, 'submission_id': uuid.uuid4()})
        with self.assertRaises(ValidationError):
            record_inventory_count_loss(**{**payload, 'counted_quantity': '7'})
        self.balance('8', '80')
        self.cash_and_payable()

    def test_positive_or_unchanged_count_cannot_invent_value(self):
        lot = self.purchase()
        for quantity in ['10', '11', '-1', 'NaN', '1.00001', 1.0, True]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                record_inventory_count_loss(submission_id=uuid.uuid4(), user=self.user, lot_id=lot.pk,
                    location_id=self.location.pk, movement_date=date(2026, 1, 12), counted_quantity=quantity,
                    expected_revision=2, reason='Synthetic count')
        self.balance('10', '100')
        self.assertFalse(InventoryMovementEvidence.objects.exists())

    def test_all_corrections_refuse_closed_period_without_losing_original_evidence(self):
        lot = self.purchase()
        original = self.issue(lot)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        for function, payload in [(record_inventory_return, returned(self, original)),
                                  (record_inventory_transfer, transfer(self, lot)),
                                  (record_inventory_waste, movement(self, lot))]:
            with self.subTest(function=function.__name__), self.assertRaises(ValidationError):
                function(**payload)
        self.balance('8', '80')
        self.assertFalse(InventoryMovementEvidence.objects.exists())

    def test_future_and_chronology_rejections_do_not_redate(self):
        lot = self.purchase()
        record_inventory_waste(**movement(self, lot))
        for day in [date(2026, 1, 11), date(2099, 1, 1)]:
            with self.subTest(day=day), self.assertRaises(ValidationError):
                record_inventory_transfer(**{**transfer(self, lot), 'movement_date': day})
        self.balance('9', '90')

    def test_failed_journal_and_post_balance_error_roll_back_every_effect(self):
        lot = self.purchase()
        original = self.issue(lot)
        ChartOfAccount.objects.filter(code='1200').update(is_active=False)
        with self.assertRaises(ValidationError):
            record_inventory_return(**returned(self, original))
        ChartOfAccount.objects.filter(code='1200').update(is_active=True)
        with patch('apps.finance.services.inventory_corrections._advance', side_effect=ValidationError({'synthetic': 'rollback'})):
            with self.assertRaises(ValidationError):
                record_inventory_transfer(**transfer(self, lot))
            with self.assertRaises(ValidationError):
                record_inventory_waste(**movement(self, lot))
        self.balance('8', '80')
        self.assertEqual((JournalEntry.objects.count(), StockMovement.objects.count(), FinancialCommandReceipt.objects.count()), (2, 2, 2))
        self.assertFalse(InventoryMovementEvidence.objects.exists())
        self.assertFalse(InventoryLocationStock.objects.filter(location=self.other_location).exists())

    def test_management_role_required_for_expiry_and_count_replay(self):
        actor = get_user_model().objects.create_user(username='synthetic-supervisor', email='synthetic@example.invalid')
        actor.roles.add(Role.objects.get_or_create(slug=RoleChoices.FARM_SUPERVISOR, defaults={'name': 'Supervisor'})[0])
        lot = self.purchase(expiry_date=date(2026, 1, 11))
        with self.assertRaises(PermissionDenied):
            record_inventory_expiry(**{**movement(self, lot), 'user': actor})
        with self.assertRaises(PermissionDenied):
            record_inventory_count_loss(submission_id=uuid.uuid4(), user=actor, lot_id=lot.pk,
                location_id=self.location.pk, movement_date=date(2026, 1, 12), counted_quantity='9',
                expected_revision=2, reason='Synthetic discrepancy')
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            record_inventory_transfer(**transfer(self, lot))
        self.balance('10', '100')

    def test_correction_evidence_is_immutable_and_tampered_pool_refuses_next_write(self):
        lot = self.purchase()
        result, _ = record_inventory_waste(**movement(self, lot))
        evidence = InventoryMovementEvidence.objects.get(movement=result)
        for action in [lambda: evidence.save(), lambda: evidence.delete(),
                       lambda: InventoryMovementEvidence.objects.filter(pk=evidence.pk).update(counted_quantity=Decimal('1')),
                       lambda: InventoryMovementEvidence.objects.filter(pk=evidence.pk).delete(),
                       lambda: InventoryMovementEvidence.objects.bulk_create([]),
                       lambda: InventoryMovementEvidence.objects.bulk_update([evidence], ['counted_quantity'])]:
            with self.assertRaises(DjangoValidationError):
                action()
        InventoryValuePool.objects.filter(item=self.item).update(carrying_value=Decimal('99'))
        with self.assertRaises(ValidationError) as error:
            record_inventory_transfer(**transfer(self, lot))
        self.assertIn('inventory_reconciliation', error.exception.detail)

    def test_wip_uses_net_direct_stock_and_approved_flock_at_cutoff(self):
        lot = self.purchase()
        original = self.issue(lot, quantity='10')
        record_inventory_return(**{**returned(self, original), 'quantity': '1'})
        from apps.finance.services.financial_capture import record_financial_sale
        from .test_financial_capture import sale_payload
        record_financial_sale(**{**sale_payload(self), 'quantity_sold': 2})
        FlockAdjustment.objects.create(batch=self.batch, effective_at=instant(day=25), quantity_change=-3,
            reason='Synthetic approved correction', approved_by=self.user)
        # Net cost90; 10 initial -2 sold -3 removals =5 remaining /7 saleable.
        report = monthly_profitability_report(self.period)
        self.assertEqual(report['production']['active_batch_work_in_progress'], Decimal('64.29'))
        self.assertEqual(report['deferred_balances']['closing_consumable_inventory'], Decimal('10'))

    def test_losses_consume_final_cent_and_lifetime_overhead_has_one_effect(self):
        lot = self.purchase(quantity='3', total_purchase_cost='0.01')
        record_inventory_waste(**movement(self, lot))
        self.assertEqual(JournalEntry.objects.count(), 1)
        record_inventory_waste(**{**movement(self, lot), 'quantity': '2'})
        self.balance('0', '0')
        self.assertEqual(JournalEntry.objects.count(), 2)
        self.assertEqual(monthly_profitability_report(self.period)['operating_costs']['inventory_losses'], Decimal('.01'))
        self.assertEqual(batch_profitability(self.batch)['direct_batch_cost'], Decimal('0'))

    def test_wip_does_not_capitalize_inventory_purchase_allocation_again(self):
        lot = self.purchase()
        self.issue(lot)
        # Privileged/import-like unsupported allocation must not double-charge
        # purchase plus issue. It is not permission to create this through UI.
        from apps.finance.models import InventoryLotBinding
        CostAllocation.objects.create(accounting_period=self.period, batch=self.batch,
            source_type=AllocationSourceType.EXPENDITURE,
            expenditure=InventoryLotBinding.objects.get(lot=lot).expenditure, allocated_amount=Decimal('100'))
        self.assertEqual(monthly_profitability_report(self.period)['production']['active_batch_work_in_progress'], Decimal('20'))

    def test_expiry_without_expiry_evidence_is_refused_and_loss_replay_checks_date_location_amount(self):
        lot = self.purchase()
        payload = movement(self, lot)
        with self.assertRaises(ValidationError):
            record_inventory_expiry(**payload)
        record_inventory_waste(**payload)
        for change in [{'movement_date': date(2026, 1, 13)}, {'location_id': self.other_location.pk}, {'quantity': '2'}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_inventory_waste(**{**payload, **change})
        self.balance('9', '90')

    def test_invalid_evidence_cannot_link_return_to_receipt_or_fabricate_count(self):
        lot = self.purchase()
        receipt = StockMovement.objects.get(lot=lot)
        original = self.issue(lot)
        result, _ = record_inventory_return(**returned(self, original))
        with self.assertRaises(DjangoValidationError):
            InventoryMovementEvidence(movement=result, original_issue=receipt).full_clean()
        result, _ = record_inventory_waste(**movement(self, lot))
        with self.assertRaises(DjangoValidationError):
            InventoryMovementEvidence(movement=result, counted_quantity=Decimal('7'), expected_quantity=Decimal('8')).full_clean()

    def test_consistently_tampered_pool_lot_location_cannot_invent_stock(self):
        lot = self.purchase()
        SharedConsumableLot.objects.filter(pk=lot.pk).update(quantity_available=Decimal('20'))
        InventoryLocationStock.objects.update(quantity=Decimal('20'))
        InventoryValuePool.objects.update(quantity=Decimal('20'))
        with self.assertRaises(ValidationError) as error:
            record_inventory_waste(**movement(self, lot))
        self.assertIn('inventory_reconciliation', error.exception.detail)
        self.assertFalse(InventoryMovementEvidence.objects.exists())

    def test_location_balance_cannot_move_without_a_transfer(self):
        lot = self.purchase()
        from apps.finance.models import InventoryLotBinding
        binding = InventoryLotBinding.objects.get(lot=lot)
        InventoryLocationStock.objects.filter(binding=binding, location=self.location).update(quantity=Decimal('5'))
        InventoryLocationStock.objects.create(binding=binding, location=self.other_location, quantity=Decimal('5'))
        with self.assertRaises(ValidationError) as error:
            self.issue(lot, location_id=self.other_location.pk, quantity='1')
        self.assertIn('inventory_reconciliation', error.exception.detail)
        self.assertEqual(StockMovement.objects.count(), 1)


@override_settings(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_POULTRY_V2=False)
class InventoryCorrectionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        inventory_tests.inventory_fixture(self)
        self.other_location = InventoryLocation.objects.create(code='OTHER-STORE', name='Other synthetic store')

    race = inventory_tests.InventoryConcurrencyTests.race

    def test_two_returns_compete_for_last_original_issue_quantity(self):
        lot, _ = record_inventory_purchase(**inventory_tests.purchase(self))
        usage, _ = record_inventory_issue(**{**inventory_tests.issue(self, lot), 'quantity': '1'})
        original = StockMovement.objects.get(usage=usage)
        results = self.race([lambda: record_inventory_return(**returned(self, original))] * 2)
        self.assertEqual(sum(isinstance(result, ValidationError) for result in results), 1)
        self.assertEqual(InventoryMovementEvidence.objects.count(), 1)
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal('10'))

    def test_same_return_intent_concurrently_commits_once(self):
        lot, _ = record_inventory_purchase(**inventory_tests.purchase(self))
        usage, _ = record_inventory_issue(**inventory_tests.issue(self, lot))
        payload = returned(self, StockMovement.objects.get(usage=usage))
        results = self.race([lambda: record_inventory_return(**payload)] * 2)
        self.assertEqual(sorted(result[1] for result in results), [False, True])
        self.assertEqual(InventoryMovementEvidence.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 3)

    def test_transfer_and_loss_compete_for_last_source_stock(self):
        lot, _ = record_inventory_purchase(**{**inventory_tests.purchase(self), 'quantity': '1'})
        results = self.race([lambda: record_inventory_transfer(**transfer(self, lot)),
                             lambda: record_inventory_waste(**movement(self, lot))])
        self.assertEqual(sum(isinstance(result, ValidationError) for result in results), 1)
        self.assertEqual(InventoryMovementEvidence.objects.count(), 1)
        self.assertGreaterEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal('0'))
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_two_counts_same_revision_one_commits_one_conflicts(self):
        lot, _ = record_inventory_purchase(**inventory_tests.purchase(self))
        revision = InventoryValuePool.objects.get(item=self.item).revision
        def count():
            return record_inventory_count_loss(submission_id=uuid.uuid4(), user=self.user, lot_id=lot.pk,
                location_id=self.location.pk, movement_date=date(2026, 1, 12), counted_quantity='9',
                expected_revision=revision, reason='Synthetic counted discrepancy')
        results = self.race([count] * 2)
        self.assertEqual(sum(isinstance(result, ValidationError) for result in results), 1)
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).quantity, Decimal('9'))
        self.assertEqual(StockMovement.objects.count(), 2)
