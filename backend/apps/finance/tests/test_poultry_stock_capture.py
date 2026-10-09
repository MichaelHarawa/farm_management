from copy import deepcopy
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from threading import Barrier, Thread
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import close_old_connections, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import Role
from apps.finance.models import (AccountingPeriod, ChartOfAccount, ConsumableItem, ConsumableUsage,
    CostAllocation, Expenditure, FinancialCommandReceipt, InventoryLocationStock, InventoryValuePool,
    JournalEntry, PeriodStatus, PoultryStockConsumption, PoultryStockItemPolicy, StockMovement, StockMovementType)
from apps.finance.services.inventory_capture import record_inventory_purchase
from apps.finance.services.inventory_corrections import record_inventory_return
from apps.finance.services.poultry_stock_capture import (configure_poultry_stock_item,
    record_stock_backed_feed, record_stock_backed_treatment)
from apps.finance.services.reporting import monthly_profitability_report
from apps.finance.services.ledger import trial_balance
from apps.poultry.models import FeedUsage, DrugsVaccination, InputCosts, Mortality
from apps.poultry.services.feed_metrics import record_feed_usage, recalculate_feed_event_populations
from .test_financial_capture import instant
from .test_inventory_capture import inventory_fixture, purchase


SETTINGS = dict(MOBILE_SYNC_CAPTURE=False, MOBILE_SYNC_ENABLED=False,
    MOBILE_SYNC_POULTRY_V2=False, FINANCE_POULTRY_STOCK_LINKAGE=True)


def setup_stock(test):
    inventory_fixture(test)
    test.policy, _ = configure_poultry_stock_item(submission_id=uuid.uuid4(), user=test.user,
        item_id=test.item.pk, kind='feed', reason='Explicit synthetic feed classification')
    test.lot, _ = record_inventory_purchase(**purchase(test))


def feed(test, **changes):
    return dict(submission_id=uuid.uuid4(), user=test.user, batch_id=test.batch.pk,
        lot_id=test.lot.pk, location_id=test.location.pk, feeding_start_date=instant(day=11),
        feeding_end_date=instant(day=11), feed_type='starter', feed_source='cp_feed',
        quantity_given=1500, unit_of_measurement='g', notes='Synthetic observed feed',
        reported_by_name='Synthetic worker', **changes)


@override_settings(**SETTINGS)
class PoultryStockCaptureTests(TestCase):
    def setUp(self):
        setup_stock(self)

    def counts(self):
        return tuple(model.objects.count() for model in [FeedUsage, DrugsVaccination, ConsumableUsage,
            PoultryStockConsumption, StockMovement, JournalEntry, FinancialCommandReceipt, Expenditure,
            CostAllocation, InputCosts])

    def test_twenty_feed_retries_one_observation_issue_cost_receipt_and_exact_hash(self):
        payload = feed(self)
        before = self.counts()
        link, created = record_stock_backed_feed(**payload)
        self.assertTrue(created)
        receipt = FinancialCommandReceipt.objects.get(pk=payload['submission_id'])
        original = deepcopy((receipt.request_hash, receipt.result))
        for _ in range(20):
            replay, created = record_stock_backed_feed(**payload)
            self.assertFalse(created)
            self.assertEqual(replay.pk, link.pk)
        self.assertEqual(tuple(now - old for now, old in zip(self.counts(), before)), (1, 0, 1, 1, 1, 1, 1, 0, 0, 0))
        self.assertEqual((link.feed.quantity_given, link.feed.unit_of_measurement, link.usage.quantity_used,
            link.usage.recognized_cost), (1500, 'g', Decimal('1.5000'), Decimal('15.00')))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal('8.5000'), Decimal('85.00')))
        lines = list(JournalEntry.objects.get(source_model='finance.ConsumableUsage').lines.order_by('account__code').values_list('account__code', 'debit', 'credit', 'batch_id'))
        self.assertEqual(lines, [('1200', Decimal('0.00'), Decimal('15.00'), self.batch.pk), ('5000', Decimal('15.00'), Decimal('0.00'), self.batch.pk)])
        for change in [{'quantity_given': 1600}, {'unit_of_measurement': 'kg'}, {'notes': 'Changed evidence'},
                       {'batch_id': self.other_batch.pk}, {'feeding_end_date': instant(day=12)}]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                record_stock_backed_feed(**{**payload, **change})
        receipt.refresh_from_db()
        self.assertEqual((receipt.request_hash, receipt.result), original)

    def treatment(self):
        item = ConsumableItem.objects.create(sku='SYNTHETIC-MED', name='Synthetic treatment', category='Any free-text category', base_unit='ml')
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user, item_id=item.pk,
            kind='treatment', reason='Explicit synthetic treatment classification')
        lot, _ = record_inventory_purchase(**{**purchase(self), 'item_id': item.pk, 'quantity': '100', 'total_purchase_cost': '200.00'})
        return dict(submission_id=uuid.uuid4(), user=self.user, batch_id=self.batch.pk, lot_id=lot.pk,
            location_id=self.location.pk, vaccination_date=instant(day=11), drug_category='drug',
            drug_vaccination_type='other', other_drug_vaccination='Observed synthetic medicine', quantity=5,
            quantity_unit='ml', description='Actual observed administration', timely_status='Observed', reported_by_name='Synthetic worker')

    def test_twenty_treatment_retries_one_issue_with_explicit_unit_and_no_mirror_cost(self):
        payload = self.treatment()
        before = self.counts()
        link, _ = record_stock_backed_treatment(**payload)
        for _ in range(20):
            self.assertFalse(record_stock_backed_treatment(**payload)[1])
        self.assertEqual(tuple(now - old for now, old in zip(self.counts(), before)), (0, 1, 1, 1, 1, 1, 1, 0, 0, 0))
        self.assertEqual((link.quantity_unit, link.usage.quantity_used, link.usage.recognized_cost), ('ml', Decimal('5.0000'), Decimal('10.00')))
        self.assertIn('5 ml', link.treatment.description)
        with self.assertRaises(ValidationError):
            record_stock_backed_treatment(**{**payload, 'quantity_unit': 'vial'})

    def test_feed_kg_converts_exactly_to_a_gram_based_item(self):
        item = ConsumableItem.objects.create(sku='SYNTHETIC-GRAMS', name='Synthetic grams', category='Not guessed', base_unit='g')
        configure_poultry_stock_item(submission_id=uuid.uuid4(), user=self.user, item_id=item.pk, kind='feed', reason='Explicit feed')
        lot, _ = record_inventory_purchase(**{**purchase(self), 'item_id': item.pk, 'quantity': '10000'})
        link, _ = record_stock_backed_feed(**{**feed(self), 'lot_id': lot.pk, 'quantity_given': 1, 'unit_of_measurement': 'kg'})
        self.assertEqual((link.usage.quantity_used, link.usage.recognized_cost), (Decimal('1000.0000'), Decimal('10.00')))

    def test_uses_current_weighted_average_not_selected_lot_price(self):
        record_inventory_purchase(**{**purchase(self), 'total_purchase_cost': '200.00'})
        link, _ = record_stock_backed_feed(**{**feed(self), 'quantity_given': 5000})
        self.assertEqual(link.usage.recognized_cost, Decimal('75.00'))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal('15.0000'), Decimal('225.00')))

    def test_stock_shortage_rolls_back_observation_usage_journal_link_and_receipt(self):
        before = self.counts()
        with self.assertRaises(ValidationError) as error:
            record_stock_backed_feed(**{**feed(self), 'quantity_given': 11000})
        self.assertIn('insufficient_stock', error.exception.detail)
        self.assertEqual(self.counts(), before)
        self.assertEqual(InventoryValuePool.objects.get(item=self.item).carrying_value, Decimal('100.00'))

    def test_missing_account_rolls_back_whole_composite(self):
        before = self.counts()
        ChartOfAccount.objects.filter(code='5000').update(is_active=False)
        with self.assertRaises(ValidationError):
            record_stock_backed_feed(**feed(self))
        self.assertEqual(self.counts(), before)
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantity_available, Decimal('10.0000'))

    def test_failure_after_valued_issue_rolls_back_all_source_stock_and_receipt_effects(self):
        before = self.counts()
        with patch('apps.finance.models.PoultryStockConsumption.save', side_effect=RuntimeError('Synthetic link failure')):
            with self.assertRaises(RuntimeError):
                record_stock_backed_feed(**feed(self))
        self.assertEqual(self.counts(), before)
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal('10.0000'), Decimal('100.00')))

    def test_expired_lot_refuses_original_date_without_an_orphan_observation(self):
        lot, _ = record_inventory_purchase(**purchase(self, expiry_date=date(2026, 1, 10)))
        before = self.counts()
        with self.assertRaises(ValidationError):
            record_stock_backed_feed(**{**feed(self), 'lot_id': lot.pk})
        self.assertEqual(self.counts(), before)

    def test_naive_or_future_observation_instants_are_not_silently_converted(self):
        payload = feed(self)
        for at in [datetime(2026, 1, 11), datetime(2099, 1, 11, tzinfo=datetime_timezone.utc)]:
            with self.assertRaises(ValidationError):
                record_stock_backed_feed(**{**payload, 'feeding_start_date': at})
        self.assertFalse(FeedUsage.objects.exists())

    def test_invalid_observation_rolls_back_without_any_stock_effect(self):
        before = self.counts()
        with self.assertRaises((ValidationError, DjangoValidationError)):
            record_stock_backed_feed(**{**feed(self), 'feeding_end_date': instant(day=10)})
        self.assertEqual(self.counts(), before)

    def test_classification_is_explicit_no_free_text_category_or_legacy_auto_link(self):
        item = ConsumableItem.objects.create(sku='UNCLASSIFIED', name='Feed', category='Feed', base_unit='kg')
        lot, _ = record_inventory_purchase(**{**purchase(self), 'item_id': item.pk})
        before = self.counts()
        with self.assertRaises(ValidationError) as error:
            record_stock_backed_feed(**{**feed(self), 'lot_id': lot.pk})
        self.assertIn('item', error.exception.detail)
        self.assertEqual(self.counts(), before)
        payload = feed(self)
        ordinary = {key: value for key, value in payload.items() if key not in {'submission_id', 'user', 'lot_id', 'location_id'}}
        record_feed_usage(created_by=self.user, **ordinary)
        self.assertEqual(PoultryStockConsumption.objects.count(), 0)
        self.assertEqual(ConsumableUsage.objects.count(), 0)

    def test_wrong_purpose_and_unverified_bag_or_treatment_conversion_are_refused(self):
        with self.assertRaises(ValidationError):
            record_stock_backed_feed(**{**feed(self), 'unit_of_measurement': 'bag'})
        payload = self.treatment()
        with self.assertRaises(ValidationError):
            record_stock_backed_feed(**{**feed(self), 'lot_id': payload['lot_id']})
        with self.assertRaises(ValidationError):
            record_stock_backed_treatment(**{**payload, 'quantity_unit': 'litre'})
        self.assertFalse(PoultryStockConsumption.objects.exists())

    def test_whole_observation_quantity_does_not_accept_float_boolean_or_fraction(self):
        for quantity in [True, 1.5, '1500', 0, -1]:
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                record_stock_backed_feed(**{**feed(self), 'quantity_given': quantity})
        self.assertFalse(FeedUsage.objects.exists())

    def test_cross_midnight_keeps_financial_day_and_checks_farm_day_period(self):
        feb = AccountingPeriod.objects.create(period_start=date(2026, 2, 1), period_end=date(2026, 2, 28), status=PeriodStatus.CLOSED)
        at = datetime(2026, 1, 31, 22, 30, tzinfo=datetime_timezone.utc)
        payload = {**feed(self), 'feeding_start_date': at, 'feeding_end_date': at}
        before = self.counts()
        with self.assertRaises((ValidationError, DjangoValidationError)):
            record_stock_backed_feed(**payload)
        self.assertEqual(self.counts(), before)
        feb.status = PeriodStatus.OPEN
        feb.save()
        link, _ = record_stock_backed_feed(**payload)
        self.assertEqual(link.usage.usage_date, date(2026, 1, 31))
        self.assertEqual(link.feed.feeding_start_date, at)

    def test_closed_period_rejects_new_intent_but_existing_accepted_replays(self):
        payload = feed(self)
        link, _ = record_stock_backed_feed(**payload)
        self.period.status = PeriodStatus.CLOSED
        self.period.save()
        self.assertEqual(record_stock_backed_feed(**payload)[0].pk, link.pk)
        self.assertFalse(record_stock_backed_feed(**payload)[1])
        with self.assertRaises(ValidationError):
            record_stock_backed_feed(**{**payload, 'submission_id': uuid.uuid4()})

    def role_user(self, slug):
        role, _ = Role.objects.get_or_create(slug=slug, defaults={'name': slug})
        user = get_user_model().objects.create_user(username='stock-' + slug, email=slug + '@example.invalid')
        user.roles.add(role)
        return user

    def test_current_roles_required_for_configure_capture_and_replay(self):
        for slug in ['general_worker', 'stake_holder', 'farm_supervisor']:
            user = self.role_user(slug)
            item = ConsumableItem.objects.create(sku='ROLE-' + slug, name=slug, category='Feed', base_unit='kg')
            with self.assertRaises(PermissionDenied):
                configure_poultry_stock_item(submission_id=uuid.uuid4(), user=user, item_id=item.pk, kind='feed', reason='Explicit')
            if slug != 'farm_supervisor':
                with self.assertRaises(PermissionDenied):
                    record_stock_backed_feed(**{**feed(self), 'user': user})
            else:
                payload = {**feed(self), 'user': user}
                record_stock_backed_feed(**payload)
                user.is_active = False
                user.save()
                with self.assertRaises(PermissionDenied):
                    record_stock_backed_feed(**payload)

    def test_linked_observation_cannot_be_rewritten_bulk_changed_or_deleted(self):
        link, _ = record_stock_backed_feed(**feed(self))
        record = link.feed
        record.quantity_given = 2000
        for write in [lambda: record.save(), lambda: record.save_base(raw=True),
                lambda: FeedUsage.objects.filter(pk=record.pk).update(quantity_given=2000),
                lambda: FeedUsage.objects.bulk_update([record], ['quantity_given']),
                lambda: FeedUsage.objects.filter(pk=record.pk).delete(),
                lambda: record.delete()]:
            with self.assertRaises((DjangoValidationError, ProtectedError)):
                write()
        record.refresh_from_db()
        self.assertEqual(record.quantity_given, 1500)
        recalculate_feed_event_populations(self.batch)
        self.assertEqual(FeedUsage.objects.get(pk=record.pk).current_number_of_birds, 10)

    def test_linked_usage_cannot_be_repriced_and_policy_unit_cannot_change(self):
        link, _ = record_stock_backed_feed(**feed(self))
        usage = link.usage
        usage.recognized_cost = Decimal('1.00')
        for write in [lambda: usage.save(), lambda: usage.save_base(raw=True),
                lambda: ConsumableUsage.objects.filter(pk=usage.pk).update(recognized_cost=Decimal('1.00')),
                lambda: ConsumableUsage.objects.bulk_update([usage], ['recognized_cost'])]:
            with self.assertRaises(DjangoValidationError):
                write()
        self.item.base_unit = 'g'
        for write in [lambda: self.item.save(), lambda: self.item.save_base(raw=True),
                lambda: ConsumableItem.objects.filter(pk=self.item.pk).update(base_unit='g'),
                lambda: ConsumableItem.objects.bulk_update([self.item], ['base_unit'])]:
            with self.assertRaises(DjangoValidationError):
                write()
        usage.refresh_from_db()
        self.assertEqual(usage.recognized_cost, Decimal('15.00'))

    def test_treatment_evidence_cannot_be_changed_after_stock_consumption(self):
        link, _ = record_stock_backed_treatment(**self.treatment())
        treatment = link.treatment
        treatment.quantity = 7
        for write in [lambda: treatment.save(), lambda: treatment.save_base(raw=True),
                lambda: DrugsVaccination.objects.filter(pk=treatment.pk).update(quantity=7),
                lambda: DrugsVaccination.objects.bulk_update([treatment], ['quantity']),
                lambda: treatment.delete()]:
            with self.assertRaises((DjangoValidationError, ProtectedError)):
                write()
        treatment.refresh_from_db()
        self.assertEqual(treatment.quantity, 5)

    def test_consumed_stock_cannot_be_returned_as_unused_without_correcting_observation(self):
        link, _ = record_stock_backed_feed(**feed(self))
        before = self.counts()
        with self.assertRaises(ValidationError) as error:
            record_inventory_return(submission_id=uuid.uuid4(), user=self.user,
                original_issue_id=StockMovement.objects.get(usage=link.usage).pk, location_id=self.location.pk,
                movement_date=date(2026, 1, 12), quantity='1', reason='Synthetic attempted return')
        self.assertIn('original_issue', error.exception.detail)
        self.assertEqual(self.counts(), before)

    def test_monthly_report_counts_stock_cost_once_without_purchase_or_input_mirror(self):
        record_stock_backed_feed(**feed(self))
        report = monthly_profitability_report(self.period)
        self.assertEqual(report['production']['direct_consumable_usage'], Decimal('15.00'))
        self.assertEqual(report['production']['direct_batch_costs'], Decimal('0.00'))
        self.assertEqual(report['deferred_balances']['closing_consumable_inventory'], Decimal('85.00'))
        balance = trial_balance()
        self.assertEqual(balance['debits'], balance['credits'])
        self.assertEqual((InputCosts.objects.count(), CostAllocation.objects.count(), Expenditure.objects.count()), (0, 0, 1))

    @override_settings(MOBILE_SYNC_CAPTURE=True, MOBILE_SYNC_POULTRY_V2=True)
    def test_operational_changes_commit_with_composite_and_replay_never_republishes(self):
        from apps.mobile_sync.models import SyncChange, SyncEntity, SyncStreamState
        from apps.mobile_sync.projections import wire_entity
        from apps.mobile_sync.writers import sync_boundary
        # Compare deltas, not guessed initial sequence values or replacement
        # identities. Explicit boundary precedes domain locks inside TestCase.
        before = SyncStreamState.objects.get(pk=1).sequence
        payload = feed(self)
        with sync_boundary():
            link, _ = record_stock_backed_feed(**payload)
        changes = list(SyncChange.objects.filter(sequence__gt=before))
        self.assertEqual({row.entity_type for row in changes}, {'poultry.batch', 'poultry.feed_usage'})
        self.assertEqual(len({row.transaction_id for row in changes}), 1)
        for _ in range(20):
            with sync_boundary():
                self.assertFalse(record_stock_backed_feed(**payload)[1])
        self.assertEqual(SyncStreamState.objects.get(pk=1).sequence, changes[-1].sequence)
        for mapping in SyncEntity.objects.filter(batch_pk=str(self.batch.pk)):
            for version in [1, 2]:
                public = wire_entity(mapping, version)
                self.assertNotIn('recognized_cost', str(public))
                self.assertNotIn('poultry_consumption', str(public))
        with sync_boundary():
            recalculate_feed_event_populations(self.batch)
        link.usage.refresh_from_db()
        self.assertEqual(link.usage.recognized_cost, Decimal('15.00'))

    @override_settings(MOBILE_SYNC_CAPTURE=True, MOBILE_SYNC_POULTRY_V2=True)
    def test_failed_composite_rolls_back_operational_changes_and_financial_effects_together(self):
        from apps.mobile_sync.models import SyncChange, SyncStreamState
        from apps.mobile_sync.writers import sync_boundary
        before = self.counts(), SyncChange.objects.count(), SyncStreamState.objects.get(pk=1).sequence
        with patch('apps.finance.models.PoultryStockConsumption.save', side_effect=RuntimeError('Synthetic post-issue crash')):
            with self.assertRaises(RuntimeError):
                with sync_boundary():
                    record_stock_backed_feed(**feed(self))
        self.assertEqual((self.counts(), SyncChange.objects.count(), SyncStreamState.objects.get(pk=1).sequence), before)

    def test_link_and_policy_evidence_are_append_only_and_database_requires_one_observation(self):
        link, _ = record_stock_backed_feed(**feed(self))
        for obj in [link, self.policy]:
            with self.assertRaises(DjangoValidationError):
                obj.save()
            with self.assertRaises(DjangoValidationError):
                type(obj).objects.filter(pk=obj.pk).update(quantity_unit='Changed')
            with self.assertRaises(DjangoValidationError):
                obj.delete()
            with self.assertRaises(DjangoValidationError):
                obj.save_base(raw=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            # Raw SQL deliberately tests the check constraint, not an API bypass.
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute('UPDATE finance_poultrystockconsumption SET feed_id=NULL WHERE id=%s', [link.pk])

    def test_flag_off_requires_no_new_table_queries_or_historical_relink(self):
        with override_settings(FINANCE_POULTRY_STOCK_LINKAGE=False):
            with self.assertNumQueries(0), self.assertRaises(ValidationError):
                record_stock_backed_feed(**feed(self))
            with patch('apps.finance.models.PoultryStockConsumption.objects.filter', side_effect=AssertionError('New table queried')):
                ordinary = FeedUsage.objects.create(batch=self.batch, initial_age=10,
                    feeding_start_date=instant(day=11), feeding_end_date=instant(day=11), feed_type='starter',
                    feed_source='cp_feed', quantity_given=1, unit_of_measurement='kg', current_number_of_birds=10,
                    notes='Legacy observation', reported_by_name='Synthetic worker', created_by=self.user)
                ordinary.notes = 'Legacy notes still editable'
                ordinary.save()


@override_settings(**SETTINGS)
class PoultryStockConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_stock(self)

    def race(self, payloads):
        barrier = Barrier(2)
        results = []
        def run(payload):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                link, created = record_stock_backed_feed(**payload)
                results.append(('accepted', link.pk, created))
            except ValidationError:
                results.append(('rejected', None, False))
            finally:
                close_old_connections()
        threads = [Thread(target=run, args=(payload,)) for payload in payloads]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2, results)
        return results

    def test_same_composite_id_races_create_one_observation_issue_and_receipt(self):
        payload = feed(self)
        results = self.race([payload, payload])
        self.assertEqual({row[1] for row in results}, {PoultryStockConsumption.objects.get().pk})
        self.assertEqual(sum(row[2] for row in results), 1)
        self.assertEqual((FeedUsage.objects.count(), ConsumableUsage.objects.count(), FinancialCommandReceipt.objects.count()), (1, 1, 3))

    def test_two_batches_competing_last_stock_leave_no_orphan_observation_or_cost(self):
        results = self.race([{**feed(self), 'quantity_given': 10000},
            {**feed(self), 'quantity_given': 10000, 'batch_id': self.other_batch.pk}])
        self.assertEqual(sorted(row[0] for row in results), ['accepted', 'rejected'])
        self.assertEqual((FeedUsage.objects.count(), ConsumableUsage.objects.count(), PoultryStockConsumption.objects.count()), (1, 1, 1))
        pool = InventoryValuePool.objects.get(item=self.item)
        self.assertEqual((pool.quantity, pool.carrying_value), (Decimal('0.0000'), Decimal('0.00')))
        self.assertEqual(JournalEntry.objects.count(), 2)
