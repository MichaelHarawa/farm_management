from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone


MONEY_VALIDATOR = MinValueValidator(Decimal("0.00"))
USD_RATE_VALIDATOR = MinValueValidator(Decimal("0.000001"))


def usd_equivalent(mwk_amount: Decimal | int | None, rate: Decimal | None):
    if mwk_amount is None or not rate:
        return None
    return (Decimal(mwk_amount) / rate).quantize(Decimal("0.01"))


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
    OTHER = "other", "Other"

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


class ChicksSource(models.TextChoices):
    CENTRAL_POULTRY = "central_poultry", "Central Poultry"
    PROTO = "proto", "Proto"
    OTHER = "other", "Other"

class UnitMeasurement(models.TextChoices):
    KGS = "kg", "KG"
    GMS = "g", "Grams"
#     METERS = "meters", "Meters"
#     INCHES = "inches", "Inches"
#     GAUGE = "gauge", "Gauge"


class BroilerStrain(models.TextChoices):
    ROSS_308 = "ross308", "Ross 308"
    COBB_500 = "cobb500", "Cobb 500"


class DrugVaccinationType(models.TextChoices):
    GUMBOLO = "gumbolo", "Gumbolo"
    HITCHNER = "hitchner", "Hitchner"
    LASOTA = "lasota", "Lasota"
    OTHER = "other", "Other"


class DrugCategory(models.TextChoices):
    VACCINATION = "vaccination", "Vaccination"
    DRUG = "drug", "Drug"
    ANTIBIOTIC = "antibiotic", "Antibiotic"
    VITAMIN = "vitamin", "Vitamin"
    DEWORMER = "dewormer", "Dewormer"
    OTHER = "other", "Other"


class BatchStatus(models.TextChoices):
    BOOKED = "booked", "Booked"
    PLANNED = "planned", "Planned"
    DELIVERED = "delivered", "Delivered at farm"
    ACTIVE = "active", "Active"
    MATURE = "mature", "Mature"
    SELLING = "selling", "Selling"
    CLOSED = "closed", "Closed"


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
    broiler_strain = models.CharField(
        max_length=20,
        choices=BroilerStrain.choices,
        default=BroilerStrain.ROSS_308,
        help_text="For broilers only. Used for target weight curves.",
    )
    source = models.CharField(
        max_length=200,
        choices=ChicksSource.choices,
        default=ChicksSource.PROTO,
        )
    source_other = models.CharField(max_length=200, blank=True, default="")
    booking_date = models.DateField(null=True, blank=True)
    estimated_chick_arrival_date = models.DateField(null=True, blank=True)
    supplier_name = models.CharField(max_length=200, blank=True, default="")
    booking_reference = models.CharField(max_length=120, blank=True, default="")
    expected_quantity = models.PositiveIntegerField(null=True, blank=True)
    actual_quantity_received = models.PositiveIntegerField(null=True, blank=True)
    delivery_confirmed_at = models.DateTimeField(null=True, blank=True)
    entry_date = models.DateTimeField()
    expected_maturity_date = models.DateTimeField()
    quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=BatchStatus.choices,
        default=BatchStatus.PLANNED,
        db_index=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.CharField(max_length=255, blank=True, default="")
    profitability_finalized_at = models.DateTimeField(null=True, blank=True)
    target_selling_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    closure_notes = models.TextField(blank=True, default="")
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
        return f"{self.batch_id} of {self.quantity} {self.bird_type}"

    def clean(self):
        super().clean()
        if (
            self.expected_maturity_date
            and self.entry_date
            and self.expected_maturity_date < self.entry_date
        ):
            raise ValidationError(
                {
                    "expected_maturity_date": (
                        "Expected maturity date cannot be before entry date."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if not self.batch_id:
            self.batch_id = self.next_batch_id()
        if self._state.adding and not self.booking_date and self.status == BatchStatus.PLANNED:
            self.status = BatchStatus.ACTIVE
        if self.booking_date and self.expected_quantity is None:
            self.expected_quantity = self.quantity
        if not self.booking_date and self.actual_quantity_received is None:
            self.actual_quantity_received = self.quantity
        if self.booking_date and not self.estimated_chick_arrival_date:
            self.estimated_chick_arrival_date = self.booking_date + timedelta(days=10)
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
    expenditure = models.OneToOneField(
        "finance.Expenditure",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="input_cost_detail",
        help_text="Authoritative financial transaction represented by this operational detail.",
    )
    item = models.CharField(max_length=200)
    category = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_measurement = models.CharField(max_length=200)
    unit = models.PositiveIntegerField(default=1)
    unit_cost = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    usd_exchange_rate = models.DecimalField(
        max_digits=16,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[USD_RATE_VALIDATOR],
        help_text="MWK per USD at entry time.",
    )
    usd_equivalent = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
    )
    purchase_date = models.DateTimeField()
    notes = models.TextField()
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

    @property
    def direct_input_total(self) -> Decimal:
        return (
            Decimal(self.quantity)
            * Decimal(self.unit)
            * self.unit_cost
        ).quantize(Decimal("0.01"))

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."
        if self.unit <= 0:
            errors["unit"] = "Unit must be greater than zero."
        if self.unit_cost < Decimal("0.00"):
            errors["unit_cost"] = "Unit cost cannot be negative."
        if (
            self.purchase_date
            and self.purchase_date.date() > timezone.localdate()
        ):
            errors["purchase_date"] = "Purchase date cannot be in the future."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.usd_equivalent = usd_equivalent(
            self.direct_input_total,
            self.usd_exchange_rate,
        )
        super().save(*args, **kwargs)


class Sales(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="sales_row",)
    sale_id = models.CharField(max_length=32, unique=True, editable=False, db_index=True)
    sale_date = models.DateTimeField()
    due_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Optional collection due date for credit sales.",
    )
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
    )
    quantity_sold = models.PositiveIntegerField()
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    usd_exchange_rate = models.DecimalField(
        max_digits=16,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[USD_RATE_VALIDATOR],
        help_text="MWK per USD at entry time.",
    )
    usd_equivalent = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MONEY_VALIDATOR],
    )
    buyer_name = models.CharField(max_length=200)
    buyer_type = models.CharField(
        max_length=20,
        choices = BuyerType.choices,
    )
    buyer_type_other = models.CharField(max_length=200, blank=True, default="")
    payment_status = models.CharField(
        max_length=20,
        choices = PaymentStatus.choices,
    )
    payment_method = models.CharField(
        max_length=200,
        choices = PaymentMethod.choices,
        )
    amount_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MONEY_VALIDATOR],
    )
    sold_by_name = models.CharField(max_length=200)
    notes = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
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
        self.buyer_type_other = (
            (self.buyer_type_other or "").strip()
            if self.buyer_type == BuyerType.OTHER
            else ""
        )
        self.sync_payment_fields()
        self.usd_equivalent = usd_equivalent(
            self.sale_total,
            self.usd_exchange_rate,
        )
        super().save(*args, **kwargs)

    def sync_payment_fields(self) -> None:
        if self.payment_status == PaymentStatus.PAID:
            self.amount_paid = self.sale_total

        self.balance = self.calculated_balance
        self.payment_status = self.normalized_payment_status

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

    @property
    def sale_total(self) -> Decimal:
        return (
            Decimal(self.quantity_sold)
            * self.unit_price
        ).quantize(Decimal("0.01"))

    @property
    def calculated_balance(self) -> Decimal:
        if self.payment_status == PaymentStatus.CANCELLED:
            return Decimal("0.00")

        return (self.sale_total - self.amount_paid).quantize(Decimal("0.01"))

    @property
    def normalized_payment_status(self) -> str:
        if self.payment_status == PaymentStatus.CANCELLED:
            return PaymentStatus.CANCELLED

        if (
            self.payment_status == PaymentStatus.PAID
            and self.sale_total == Decimal("0.00")
        ):
            return PaymentStatus.PAID

        if self.amount_paid == Decimal("0.00"):
            return PaymentStatus.UNPAID

        if self.amount_paid == self.sale_total:
            return PaymentStatus.PAID

        return PaymentStatus.PARTIAL

    @property
    def reduces_live_birds(self) -> bool:
        return self.product_type in {
            ProductType.LIVE_CHICKEN,
            ProductType.DRESSED_CHICKEN,
        }

    def clean(self):
        super().clean()
        errors = {}
        self.buyer_type_other = (self.buyer_type_other or "").strip()
        if self.buyer_type == BuyerType.OTHER:
            if len(self.buyer_type_other) < 2:
                errors["buyer_type_other"] = (
                    "Other buyer type must contain at least 2 characters."
                )
        else:
            self.buyer_type_other = ""
        if self.quantity_sold <= 0:
            errors["quantity_sold"] = "Quantity sold must be greater than zero."
        if self.unit_price < Decimal("0.00"):
            errors["unit_price"] = "Unit price cannot be negative."
        if self.amount_paid < Decimal("0.00"):
            errors["amount_paid"] = "Amount paid cannot be negative."
        if (
            self.payment_status != PaymentStatus.CANCELLED
            and self.amount_paid > self.sale_total
        ):
            errors["amount_paid"] = "Amount paid cannot exceed the sale total."
        if errors:
            raise ValidationError(errors)

class Mortality(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="mortality_row",)
    mortality_date = models.DateTimeField()
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

    def clean(self):
        super().clean()
        if self.quantity_dead <= 0:
            raise ValidationError(
                {"quantity_dead": "Quantity dead must be greater than zero."}
            )


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
    population_calculation_version = models.CharField(
        max_length=40,
        default="dated-flock-events-v1",
    )
    population_calculated_at = models.DateTimeField(null=True, blank=True)
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

    @property
    def quantity_kg(self) -> Decimal:
        quantity = Decimal(self.quantity_given)
        if self.unit_of_measurement == UnitMeasurement.GMS:
            quantity /= Decimal("1000")
        return quantity.quantize(Decimal("0.001"))

    @property
    def feed_per_live_bird_at_event(self) -> Decimal | None:
        if not self.current_number_of_birds:
            return None
        return (self.quantity_kg / Decimal(self.current_number_of_birds)).quantize(
            Decimal("0.0001")
        )


class FlockAdjustmentStatus(models.TextChoices):
    APPROVED = "approved", "Approved"
    REVERSED = "reversed", "Reversed"


class FlockAdjustment(models.Model):
    batch = models.ForeignKey(
        Batch,
        on_delete=models.PROTECT,
        related_name="flock_adjustments",
    )
    effective_at = models.DateTimeField(db_index=True)
    quantity_change = models.IntegerField(
        help_text="Signed correction to the live-bird cohort.",
    )
    reason = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=FlockAdjustmentStatus.choices,
        default=FlockAdjustmentStatus.APPROVED,
        db_index=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_flock_adjustments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["effective_at", "pk"]

    def clean(self):
        super().clean()
        if self.quantity_change == 0:
            raise ValidationError({"quantity_change": "Adjustment cannot be zero."})

    def __str__(self) -> str:
        return f"{self.batch.batch_id}: {self.quantity_change:+d} on {self.effective_at}"


class DrugsVaccination(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="vaccination_row",)
    vaccination_date = models.DateTimeField()
    drug_vaccination_type = models.CharField(
        max_length=200,
        choices = DrugVaccinationType.choices,
        )
    other_drug_vaccination = models.CharField(max_length=200)
    drug_category = models.CharField(
        max_length=200,
        choices=DrugCategory.choices,
        default=DrugCategory.VACCINATION,
    )
    quantity = models.PositiveIntegerField()
    description = models.TextField()
    timely_status = models.CharField(max_length=200)
    reported_by_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="created_vaccination",
    )

    def __str__(self) -> str:
        return f"{self.batch} {self.quantity} administered on {self.vaccination_date}"


class BatchWeightSample(models.Model):
    """Actual average weight samples taken from the flock at a known age.

    Used to compare against breed-specific target curves (Ross 308 / Cobb 500)
    and trigger urgent intervention alerts when the flock is under-performing.
    """

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="weight_samples",
    )
    age_in_days = models.PositiveIntegerField(
        help_text="Age in days since entry (0 on placement day)."
    )
    sampled_at = models.DateTimeField(
        help_text="When the weighing took place."
    )
    sample_size = models.PositiveIntegerField(
        default=10,
        help_text="Number of birds weighed for this average.",
    )
    average_weight_g = models.PositiveIntegerField(
        help_text="Average live weight in grams."
    )
    notes = models.TextField(blank=True, default="")
    reported_by_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_weight_samples",
    )

    class Meta:
        ordering = ["-sampled_at"]

    def __str__(self) -> str:
        return f"{self.batch} day {self.age_in_days} @ {self.average_weight_g}g (n={self.sample_size})"

    def clean(self):
        super().clean()
        if self.average_weight_g <= 0:
            raise ValidationError(
                {"average_weight_g": "Average weight must be greater than zero."}
            )
        if self.sample_size <= 0:
            raise ValidationError(
                {"sample_size": "Sample size must be greater than zero."}
            )

