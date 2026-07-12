from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone
from django.conf import settings


class BirdType(models.TextChoices):
    BROILERS = "broilers", "Broilers"
    LAYERS = "layers", "Layers"
    LOCAL = "local", "Local"
    KLOILERS = "kloilers", "Kloilers"
    MIKOLONGWE = "mikolongwe", "Mikolongwe"

class ProductType(models.TextChoices):
    LIVE_CHICKEN = "live_chicken", "Live Chicken" 
    DRESSED_CHICKEN = "dressed_chicken", "Dressed Chicken"
    EGGS = "eggs", "Eggs" 
    MANURE = "manure", "Manure"

class PaymentStatus(models.TextChoices):
    PAID = "paid", "Paid"
    PARTIAL = "partial", "Partial"
    LOAN = "loan", "Loan"
    UNPAID = "unpaid", "Unpaid"
    CANCELLED = "cancelled", "Cancelled"

class PaymentMethod(models.TextChoices):
    CASH = "cash", "Cash"
    MOBILE_MONEY = "mobile_money", "Mobile Money"
    BANK_TRANSFER = "bank_transfer", "Bank Transfer" 
    CREDIT = "credit", "Credit"

class BuyerType(models.TextChoices):
    MARKET_VENDOR = "market_vendor", "Market Vendor"
    RETAIL = "retail", "Retail"
    RETAIL_SUPPLY = "retail_supply", "Retail Supply" 
    BULK_ORDER = "bulk_order", "Bulk Order"

class FeedType(models.TextChoices):
    PRE_STARTER = "pre_starter", "Pre-Starter"
    STARTER = "starter", "STARTER"
    GROWER = "grower", "Grower"
    FINISHER = "finisher", "Finisher"
    PULLET_STARTER = "pullet_starter", "Pullet Starter"
    PULLET_GROWER = "pullet_grower", "Pullet Grower"
    LAYERS_MARSH = "layers_marsh", "Layers Marsh"
    LAYERS_FINISHER = "layers_finisher", "Layers Finisher"

class FeedSource(models.TextChoices):
    CP_FEED = "cp_feed", "CP Feed"
    PROTO_FEED = "proto_feed", "Proto Feed"
    CONCENTRATES_FEED = "concentrates_feed", "Concentrates Feed"
    SELF_MADE = "self_made", "Self Made"

class UnitMeasurement(models.TextChoices):
    KGS = "kg", "KG"
    GMS = "g", "Grams"
#     METERS = "meters", "Meters"
#     INCHES = "inches", "Inches"
#     GAUGE = "gauge", "Gauge"

class BatchIDSequence(models.Model):
    sequence_date = models.DateField(unique=True)
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sequence_date"]

    def __str__(self) -> str:
        return f"{self.sequence_date:%Y%m%d}: {self.last_number}"


class SaleIDSequence(models.Model):
    sequence_date = models.DateField(unique=True)
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sequence_date"]

    def __str__(self) -> str:
        return f"{self.sequence_date:%Y%m%d}: {self.last_number}"

class Batch(models.Model):
    batch_id = models.CharField(max_length=32, unique=True, editable=False, db_index=True)
    bird_type = models.CharField(max_length=200,
        choices=BirdType.choices,
        default=BirdType.BROILERS,)
    source = models.CharField(max_length=200, default="Central Poultry")
    entry_date = models.DateTimeField()
    expected_maturity_date = models.DateTimeField()
    quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_batch",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.batch_id} of {self.quantity} {bird_type}"

    def save(self, *args, **kwargs):
        if not self.batch_id:
            self.batch_id = self.next_batch_id()
        super().save(*args, **kwargs)

    @staticmethod
    def next_batch_id() -> str:
        today = timezone.localdate()

        with transaction.atomic():
            sequence, _ = (
                BatchIDSequence.objects.select_for_update()
                .get_or_create(sequence_date=today)
            )

            sequence.last_number += 1
            sequence.save(update_fields=["last_number", "updated_at"])

            return f"BATCH-{today:%Y%m%d}-{sequence.last_number:04d}"


class InputCosts(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="input_costs",)
    item = models.CharField(max_length=200)
    category = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_measurement = models.CharField(max_length=200)
    unit = models.PositiveIntegerField(default = 0)
    unit_cost = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_inputs",
    )

    def __str__(self) -> str:
        return f"{self.batch} costs"


class Sales(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="sales_row",)
    sale_id = models.CharField(max_length=32, unique=True, editable=False, db_index=True)
    sale_date = models.DateTimeField()
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
    )
    quantity_sold = models.PositiveIntegerField()
    unit_price = models.PositiveIntegerField()
    buyer_name = models.CharField(max_length=200)
    buyer_type = models.CharField(
        max_length=20,
        choices = BuyerType.choices,
    )
    payment_status = models.CharField(
        max_length=20,
        choices = PaymentStatus.choices,
    )
    payment_method = models.CharField(
        max_length=200,
        choices = PaymentMethod.choices,
        )
    amount_paid = models.PositiveIntegerField()
    balance = models.PositiveIntegerField()
    sold_by_name = models.CharField(max_length=200)
    notes = models.TextField()
    created_at = created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_sales",
    )

    def save(self, *args, **kwargs):
        if not self.sale_id:
            self.sale_id = self.next_sale_id()
        super().save(*args, **kwargs)

    @staticmethod
    def next_sale_id() -> str:
        today = timezone.localdate()

        with transaction.atomic():
            sequence, _ = (
                SaleIDSequence.objects.select_for_update()
                .get_or_create(sequence_date=today)
            )

            sequence.last_number += 1
            sequence.save(update_fields=["last_number", "updated_at"])

            return f"SALE-{today:%Y%m%d}-{sequence.last_number:04d}"

    def __str__(self) -> str:
        return f"{self.batch} of sale {self.sale_id} sold at {self.sale_date}"

class Mortality(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="mortality_row",)
    mortality_date = models.DateTimeField(auto_now_add=True)
    quantity_dead = models.PositiveIntegerField()
    age_in_days = models.PositiveIntegerField()
    suspected_cause = models.CharField(max_length=200)
    description = models.TextField()
    action_taken = models.TextField()
    reported_by_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_mortality",
    )

    def __str__(self) -> str:
        return f"{self.batch} {self.quantity_dead} died on {self.created_at}"


class FeedUsage(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="feed_usage_row",)
    initial_age = models.PositiveIntegerField()
    feeding_start_date = models.DateTimeField()
    feeding_end_date = models.DateTimeField()
    feed_type = models.CharField(
        max_length=200,
        choices = FeedType.choices,
    )
    feed_source = models.CharField(
        max_length=200,
        choices = FeedSource.choices,
    )
    quantity_given = models.PositiveIntegerField()
    unit_of_measurement = models.CharField(
        max_length=200,
        choices = UnitMeasurement.choices,
        )    
    current_number_of_birds = models.PositiveIntegerField()
    notes = models.TextField()
    reported_by_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_feed_usage",
    )

    def __str__(self) -> str:
        return f"{self.batch} consumed {self.quantity_given} {self.unit_of_measurement}"


