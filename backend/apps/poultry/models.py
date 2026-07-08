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

# class UnitMeasurement(models.TextChoices):
#     KGS = "kg", "KG"
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


class Batch(models.Model):
    batch_id = models.CharField(max_length=32, unique=True, editable=False, db_index=True)
    bird_type = models.CharField(max_length=200,
        choices=BirdType.choices,
        default=BirdType.BROILERS,)
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



