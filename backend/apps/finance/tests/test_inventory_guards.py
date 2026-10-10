"""All ordinary stock writers refuse managed evidence changes, even gates off."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.contrib import admin
from django.db import transaction
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.finance.models import (ConsumableItem, ConsumableUsage, ConsumableUsageScope,
    FinancialCommandReceipt, InventoryLocation, InventoryLocationStock, InventoryLotBinding,
    InventoryMovementEvidence, InventoryValuePool, JournalEntry, SharedConsumableLot,
    StockMovement, StockMovementType)
from apps.finance.services.consumables import record_consumable_receipt, record_consumable_usage
from apps.finance.services.inventory_capture import record_inventory_purchase, record_inventory_issue
from apps.finance.services.inventory_corrections import record_inventory_transfer, record_inventory_waste
from apps.finance.services.inventory_guards import inventory_posting_boundary
from apps.finance.services.ledger import reverse_journal
from apps.finance.services.financial_capture import record_financial_supplier_payment
from . import test_financial_capture as financial_tests
from . import test_inventory_capture as inventory_tests
from .test_inventory_capture import inventory_fixture, purchase, issue


def legacy_lot(test, **changes):
    return dict(item='Other legacy material', category='Feed', purchase_date=date(2026, 1, 9),
        unit_of_measurement='kg', quantity_purchased=Decimal('3'), quantity_available=Decimal('3'),
        unit_cost=Decimal('10'), total_purchase_cost=Decimal('30'), **changes)


def usage_row(test, lot, **changes):
    return ConsumableUsage(consumable_lot=lot, accounting_period=test.period,
        usage_date=date(2026, 1, 11), quantity_used=Decimal('1'), recognized_cost=Decimal('10'),
        usage_scope=ConsumableUsageScope.BATCH_DIRECT, batch=test.batch,
        task_or_purpose='Synthetic ordinary usage', **changes)


@override_settings(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False,
    MOBILE_SYNC_POULTRY_V2=False, FINANCE_POULTRY_STOCK_LINKAGE=False)
class InventoryWriterGuardTests(TestCase):
    def setUp(self):
        inventory_fixture(self)
        self.lot = record_inventory_purchase(**purchase(self))[0]
        self.binding = InventoryLotBinding.objects.get(lot=self.lot)
        self.pool = InventoryValuePool.objects.get(item=self.item)
        self.stock = InventoryLocationStock.objects.get(binding=self.binding)
        self.receipt = StockMovement.objects.get(lot=self.lot)

    def assert_refused(self, actions):
        before = self.snapshot()
        for action in actions:
            with self.subTest(action=action), self.assertRaises(DjangoValidationError), transaction.atomic():
                action()
            self.assertEqual(self.snapshot(), before)

    def snapshot(self):
        return {model._meta.model_name: list(model.objects.order_by('pk').values()) for model in [
            ConsumableItem, SharedConsumableLot, ConsumableUsage, InventoryValuePool,
            InventoryLotBinding, InventoryLocationStock, InventoryMovementEvidence,
            StockMovement, JournalEntry, FinancialCommandReceipt]}

    def test_pool_all_writer_paths_refused(self):
        self.pool.carrying_value = Decimal('101')
        self.assert_refused([lambda: self.pool.save(), lambda: self.pool.save_base(),
            lambda: self.pool.save_base(raw=True), lambda: self.pool.delete(),
            lambda: InventoryValuePool.objects.update(carrying_value=Decimal('101')),
            lambda: InventoryValuePool.objects.bulk_update([self.pool], ['carrying_value']),
            lambda: InventoryValuePool.objects.bulk_create([]), lambda: InventoryValuePool.objects.all().delete(),
            lambda: InventoryValuePool.objects.all()._raw_delete('default')])

    def test_location_balance_all_writer_paths_refused(self):
        self.stock.quantity = Decimal('11')
        self.assert_refused([lambda: self.stock.save(), lambda: self.stock.save_base(),
            lambda: self.stock.save_base(raw=True), lambda: self.stock.delete(),
            lambda: InventoryLocationStock.objects.update(quantity=Decimal('11')),
            lambda: InventoryLocationStock.objects.bulk_update([self.stock], ['quantity']),
            lambda: InventoryLocationStock.objects.bulk_create([]),
            lambda: InventoryLocationStock.objects.all().delete(),
            lambda: InventoryLocationStock.objects.all()._raw_delete('default'),
            lambda: InventoryLocationStock.objects.create(binding=self.binding, location=self.location)])

    def test_lot_binding_cannot_rebind_payable_item_or_invoice(self):
        self.binding.invoice_key = 'f' * 64
        self.assert_refused([lambda: self.binding.save(), lambda: self.binding.save_base(),
            lambda: self.binding.save_base(raw=True), lambda: self.binding.delete(),
            lambda: InventoryLotBinding.objects.update(invoice_key='f' * 64),
            lambda: InventoryLotBinding.objects.bulk_update([self.binding], ['invoice_key']),
            lambda: InventoryLotBinding.objects.bulk_create([]),
            lambda: InventoryLotBinding.objects.all().delete(),
            lambda: InventoryLotBinding.objects.all()._raw_delete('default')])

    def test_ordinary_new_managed_state_requires_transactional_effect(self):
        other = ConsumableItem.objects.create(sku='OTHER', name='Other', category='Other', base_unit='kg')
        new_pool = InventoryValuePool(item=other, last_movement_date=date(2026, 1, 10))
        new_binding = InventoryLotBinding(lot=self.lot, item=other, expenditure=self.binding.expenditure)
        self.assert_refused([lambda: new_pool.save(), lambda: new_pool.save_base(),
            lambda: new_binding.save(), lambda: new_binding.save_base()])

    def test_managed_lot_economic_and_descriptive_changes_refused(self):
        self.lot.quantity_available = Decimal('11')
        self.assert_refused([lambda: self.lot.save(), lambda: self.lot.save_base(),
            lambda: self.lot.save_base(raw=True), lambda: self.lot.delete(),
            lambda: SharedConsumableLot.objects.filter(pk=self.lot.pk).update(quantity_available=Decimal('11')),
            lambda: SharedConsumableLot.objects.bulk_update([self.lot], ['quantity_available']),
            lambda: SharedConsumableLot.objects.filter(pk=self.lot.pk).update(supplier='Rebound'),
            lambda: SharedConsumableLot.objects.filter(pk=self.lot.pk).update(notes='Rewritten'),
            lambda: SharedConsumableLot.objects.filter(pk=self.lot.pk).delete(),
            lambda: SharedConsumableLot.objects.filter(pk=self.lot.pk)._raw_delete('default')])

    def test_forged_existing_lot_primary_key_cannot_replace_evidence(self):
        forged = SharedConsumableLot(pk=self.lot.pk, **legacy_lot(self))
        self.assert_refused([lambda: forged.save(), lambda: forged.save_base(raw=True)])

    def test_item_economic_identity_all_writer_paths_refused(self):
        for field, value in [('name', 'Rebound'), ('sku', 'REBOUND'), ('base_unit', 'g'), ('costing_method', 'fifo')]:
            original = getattr(self.item, field)
            setattr(self.item, field, value)
            self.assert_refused([lambda: self.item.save(), lambda: self.item.save_base(raw=True),
                lambda: ConsumableItem.objects.filter(pk=self.item.pk).update(**{field: value}),
                lambda: ConsumableItem.objects.bulk_update([self.item], [field])])
            setattr(self.item, field, original)
        self.assert_refused([lambda: self.item.delete(), lambda: ConsumableItem.objects.filter(pk=self.item.pk).delete(),
            lambda: ConsumableItem.objects.filter(pk=self.item.pk)._raw_delete('default')])

    def test_item_descriptive_category_reorder_and_activation_remain_editable(self):
        self.item.category = 'Descriptive stock category'
        self.item.reorder_level = Decimal('2')
        self.item.save(update_fields=['category', 'reorder_level'])
        ConsumableItem.objects.filter(pk=self.item.pk).update(is_active=False)
        self.item.refresh_from_db()
        self.assertEqual((self.item.category, self.item.reorder_level, self.item.is_active),
            ('Descriptive stock category', Decimal('2'), False))
        self.pool.refresh_from_db()
        self.assertEqual((self.pool.quantity, self.pool.carrying_value), (Decimal('10'), Decimal('100')))

    def test_legacy_creation_cannot_overlap_managed_item(self):
        for name in [self.item.name, self.item.name.swapcase()]:
            data = {**legacy_lot(self), 'item': name}
            self.assert_refused([lambda: SharedConsumableLot.objects.create(**data),
                lambda: SharedConsumableLot(**data).save_base(raw=True),
                lambda: SharedConsumableLot.objects.bulk_create([SharedConsumableLot(**data)])])
            with self.assertRaises((ValidationError, DjangoValidationError)):
                record_consumable_receipt(created_by=self.user, **data)

    def test_mixed_bulk_lot_creation_is_atomic(self):
        rows = [SharedConsumableLot(**legacy_lot(self)),
            SharedConsumableLot(**{**legacy_lot(self), 'item': self.item.name})]
        self.assert_refused([lambda: SharedConsumableLot.objects.bulk_create(rows)])

    def test_generic_usage_cannot_bypass_valued_issue(self):
        row = usage_row(self, self.lot)
        self.assert_refused([lambda: row.save(), lambda: row.save(_valued_cost=Decimal('10')),
            lambda: row.save_base(), lambda: row.save_base(raw=True),
            lambda: ConsumableUsage.objects.bulk_create([row])])
        with self.assertRaises((ValidationError, DjangoValidationError)):
            record_consumable_usage(recorded_by=self.user, consumable_lot=self.lot, accounting_period=self.period,
                usage_date=date(2026, 1, 11), quantity_used=Decimal('1'), usage_scope=ConsumableUsageScope.BATCH_DIRECT,
                batch=self.batch, task_or_purpose='Bypass', allocation_driver='direct')

    def test_managed_usage_all_rewrite_paths_refused(self):
        row = record_inventory_issue(**issue(self, self.lot))[0]
        row.recognized_cost = Decimal('1')
        self.assert_refused([lambda: row.save(), lambda: row.save_base(raw=True), lambda: row.delete(),
            lambda: ConsumableUsage.objects.filter(pk=row.pk).update(recognized_cost=Decimal('1')),
            lambda: ConsumableUsage.objects.bulk_update([row], ['recognized_cost']),
            lambda: ConsumableUsage.objects.filter(pk=row.pk).delete(),
            lambda: ConsumableUsage.objects.filter(pk=row.pk)._raw_delete('default')])

    def test_period_lock_unlock_does_not_reprice_managed_usage(self):
        row = record_inventory_issue(**issue(self, self.lot))[0]
        original = row.recognized_cost
        ConsumableUsage.objects.filter(pk=row.pk).update(locked=True)
        row.refresh_from_db()
        self.assertTrue(row.locked)
        row.locked = False
        row.save(update_fields=['locked', 'updated_at'])
        row.refresh_from_db()
        self.assertEqual((row.locked, row.recognized_cost), (False, original))

    def test_mixed_queryset_update_leaves_legacy_and_managed_lots_unchanged(self):
        SharedConsumableLot.objects.create(**legacy_lot(self))
        self.assert_refused([lambda: SharedConsumableLot.objects.all().update(notes='Mixed mutation')])

    def test_existing_legacy_lot_cannot_be_renamed_into_managed_item(self):
        row = SharedConsumableLot.objects.create(**legacy_lot(self))
        row.item = self.item.name
        self.assert_refused([lambda: row.save(), lambda: row.save_base(raw=True),
            lambda: SharedConsumableLot.objects.filter(pk=row.pk).update(item=self.item.name),
            lambda: SharedConsumableLot.objects.bulk_update([row], ['item'])])

    def test_legacy_usage_cannot_be_rebound_to_managed_lot(self):
        lot = SharedConsumableLot.objects.create(**legacy_lot(self))
        row = usage_row(self, lot)
        row.save()
        row.consumable_lot = self.lot
        self.assert_refused([lambda: row.save(), lambda: row.save_base(raw=True),
            lambda: ConsumableUsage.objects.filter(pk=row.pk).update(consumable_lot=self.lot),
            lambda: ConsumableUsage.objects.bulk_update([row], ['consumable_lot'])])

    def test_inventory_bulk_upsert_is_not_an_immutability_bypass(self):
        self.item.base_unit = 'g'
        self.assert_refused([lambda: ConsumableItem.objects.bulk_create([self.item], update_conflicts=True,
            update_fields=['base_unit'], unique_fields=['sku'])])

    def test_movement_direct_base_save_raw_delete_and_reserved_creation_refused(self):
        self.receipt.total_cost = Decimal('1')
        new = StockMovement(movement_type=StockMovementType.RECEIPT, movement_date=date(2026, 1, 10),
            item=self.item, lot=self.lot, to_location=self.location, quantity=Decimal('1'),
            unit_cost=Decimal('10'), total_cost=Decimal('10'), idempotency_key='ordinary-managed-bypass')
        self.assert_refused([lambda: self.receipt.save_base(), lambda: self.receipt.save_base(raw=True),
            lambda: StockMovement.objects.filter(pk=self.receipt.pk)._raw_delete('default'),
            lambda: new.save(), lambda: new.save_base()])
        other = ConsumableItem.objects.create(sku='OTHER', name='Other', category='Other', base_unit='kg')
        new.item, new.lot, new.idempotency_key = other, None, 'inventory-receipt:forged'
        self.assert_refused([lambda: new.save(), lambda: new.save_base()])

    def test_correction_evidence_cannot_be_forged_or_base_saved(self):
        movement = record_inventory_waste(submission_id=uuid.uuid4(), user=self.user, lot_id=self.lot.pk,
            location_id=self.location.pk, movement_date=date(2026, 1, 11), quantity='1', reason='Synthetic waste')[0]
        row = InventoryMovementEvidence.objects.get(movement=movement)
        forged = InventoryMovementEvidence(movement=movement)
        self.assert_refused([lambda: row.save_base(), lambda: row.save_base(raw=True),
            lambda: InventoryMovementEvidence.objects.filter(pk=row.pk)._raw_delete('default'),
            lambda: forged.save_base()])

    def test_context_does_not_permit_evidence_or_source_binding_rewrite(self):
        with inventory_posting_boundary():
            self.binding.invoice_key = 'e' * 64
            self.lot.total_purchase_cost = Decimal('101')
            self.assert_refused([lambda: self.binding.save(), lambda: self.receipt.save_base(),
                lambda: self.lot.save(update_fields=['total_purchase_cost'])])

    def test_managed_purchase_issue_loss_journals_cannot_be_gl_only_reversed(self):
        record_inventory_issue(**issue(self, self.lot))
        record_inventory_waste(submission_id=uuid.uuid4(), user=self.user, lot_id=self.lot.pk,
            location_id=self.location.pk, movement_date=date(2026, 1, 12), quantity='1', reason='Synthetic waste')
        before = self.snapshot()
        for journal in JournalEntry.objects.all():
            with self.subTest(source=journal.source_model), self.assertRaises(ValidationError):
                reverse_journal(journal, posting_date=date(2026, 1, 13), reason='GL-only bypass', user=self.user)
        self.assertEqual(self.snapshot(), before)

    def test_managed_inventory_supplier_payment_cannot_be_gl_only_reversed(self):
        source = inventory_tests.InventoryCaptureTests.funded_source(self)
        record_financial_supplier_payment(submission_id=uuid.uuid4(), user=self.user, currency='MWK',
            expenditure_id=self.binding.expenditure_id, payment_date=date(2026, 1, 12),
            funding_allocations=[{'funding_source': source.pk, 'amount': '40.00'}])
        journal = JournalEntry.objects.get(source_model='finance.FundingAllocation')
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            reverse_journal(journal, posting_date=date(2026, 1, 13), reason='GL-only payment bypass', user=self.user)
        self.assertEqual(self.snapshot(), before)

    def test_managed_admin_history_is_viewable_but_not_editable_or_deletable(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user
        row = record_inventory_issue(**issue(self, self.lot))[0]
        for obj in [self.lot, row]:
            model_admin = admin.site._registry[type(obj)]
            self.assertTrue(model_admin.has_view_permission(request, obj))
            self.assertFalse(model_admin.has_change_permission(request, obj))
            self.assertFalse(model_admin.has_delete_permission(request, obj))
        old = SharedConsumableLot.objects.create(**legacy_lot(self))
        self.assertTrue(admin.site._registry[SharedConsumableLot].has_change_permission(request, old))

    def test_failed_effect_resets_context_and_rolls_back_every_stock_effect(self):
        before = self.snapshot()
        with patch('apps.finance.services.inventory_capture._advance', side_effect=RuntimeError('Synthetic crash')):
            with self.assertRaises(RuntimeError):
                record_inventory_issue(**issue(self, self.lot))
        self.assertEqual(self.snapshot(), before)
        self.assert_refused([lambda: self.pool.save(), lambda: usage_row(self, self.lot).save()])

    def test_valid_transfer_still_retains_quantity_and_value(self):
        destination = InventoryLocation.objects.create(code='DEST', name='Destination')
        payload = dict(submission_id=uuid.uuid4(), user=self.user, lot_id=self.lot.pk,
            from_location_id=self.location.pk, to_location_id=destination.pk, movement_date=date(2026, 1, 11),
            quantity='2', reason='Synthetic transfer')
        row, created = record_inventory_transfer(**payload)
        self.assertTrue(created)
        for _ in range(20):
            replay, created = record_inventory_transfer(**payload)
            self.assertEqual((replay.pk, created), (row.pk, False))
        self.pool.refresh_from_db()
        self.assertEqual((self.pool.quantity, self.pool.carrying_value), (Decimal('10'), Decimal('100')))
        self.assertEqual(sorted(InventoryLocationStock.objects.values_list('quantity', flat=True)), [Decimal('2'), Decimal('8')])

    def test_legacy_lot_item_usage_remain_ordinary_without_new_table_queries(self):
        row = SharedConsumableLot.objects.create(**legacy_lot(self))
        row.notes = 'Legacy note'
        with CaptureQueriesContext(connection) as queries:
            row.save(update_fields=['notes'])
        self.assertFalse(any('finance_inventory' in query['sql'] or 'finance_poultrystock' in query['sql']
            for query in queries.captured_queries))
        row.refresh_from_db()
        self.assertEqual(row.notes, 'Legacy note')
        usage = usage_row(self, row)
        usage.save()
        usage.notes = 'Legacy usage note'
        usage.save(update_fields=['notes'])
        item = ConsumableItem.objects.create(sku='LEGACY', name='Legacy', category='Other', base_unit='kg')
        item.base_unit = 'g'
        item.save()
        self.assertFalse(InventoryLotBinding.objects.filter(lot=row).exists())

    def test_rest_item_and_lot_edits_return_reviewable_400_not_500(self):
        client = APIClient()
        client.force_authenticate(self.user)
        for route, pk, payload in [('finance-consumable-item-detail', self.item.pk, {'base_unit': 'g'}),
                ('finance-consumable-lot-detail', self.lot.pk, {'notes': 'Rewritten'})]:
            url = reverse('finance:' + route, args=[pk])
            response = client.patch(url, payload, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('inventory', response.data)
            self.assertEqual(client.get(url).status_code, 200)


@override_settings(MOBILE_SYNC_ENABLED=False, MOBILE_SYNC_CAPTURE=False,
    MOBILE_SYNC_POULTRY_V2=False, FINANCE_POULTRY_STOCK_LINKAGE=False)
class InventoryGuardConcurrencyTests(TransactionTestCase):
    def setUp(self):
        inventory_fixture(self)

    race = financial_tests.FinancialCaptureConcurrencyTests.race

    def test_first_managed_purchase_and_legacy_receipt_cannot_both_commit(self):
        results = self.race([lambda: record_inventory_purchase(**purchase(self)),
            lambda: record_consumable_receipt(created_by=self.user,
                **{**legacy_lot(self), 'item': self.item.name})])
        self.assertEqual(sum(result[0] == 'accepted' for result in results), 1, results)
        self.assertEqual(SharedConsumableLot.objects.count(), 1)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(JournalEntry.objects.count(), 1)

    def test_first_managed_purchase_and_unit_edit_are_serialized(self):
        results = self.race([lambda: record_inventory_purchase(**purchase(self)),
            lambda: ConsumableItem.objects.filter(pk=self.item.pk).update(base_unit='g')])
        self.assertGreaterEqual(sum(result[0] == 'accepted' for result in results), 1, results)
        self.item.refresh_from_db()
        lot = SharedConsumableLot.objects.get()
        self.assertEqual(lot.unit_of_measurement, self.item.base_unit)
        self.assertEqual((StockMovement.objects.count(), JournalEntry.objects.count()), (1, 1))

    def test_private_inventory_boundary_refuses_nontransactional_use(self):
        with self.assertRaises(DjangoValidationError):
            with inventory_posting_boundary():
                pass

    def test_first_managed_purchase_and_orphan_ordinary_movement_cannot_both_commit(self):
        def ordinary():
            return StockMovement.objects.create(movement_type=StockMovementType.RECEIPT,
                movement_date=date(2026, 1, 9), item=self.item, to_location=self.location,
                quantity=Decimal('1'), unit_cost=Decimal('10'), total_cost=Decimal('10'),
                idempotency_key='synthetic-legacy-orphan')
        results = self.race([lambda: record_inventory_purchase(**purchase(self)), ordinary])
        self.assertEqual(sum(result[0] == 'accepted' for result in results), 1, results)
        self.assertEqual(StockMovement.objects.count(), 1)
