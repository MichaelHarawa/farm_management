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

class UnitMeasurement(models.TextChoices):
    KGS = "kg", "KG"
    METERS = "meters", "Meters"
    INCHES = "inches", "Inches"
    GAUGE = "gauge", "Gauge"

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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.batch_id} of {self.quantity} {bird_type}"


class InputCosts(models.Model):
    batch = models.ForeignKey(
    Batch,
    on_delete=models.CASCADE,
    related_name="input",)
    item = models.CharField(max_length=200)
    category = models.CharField(max_length=200)
    quantity = models.PositiveIntegerField()
    unit_measurement = models.CharField(
        max_length=200,
    choices=UnitMeasurement.choices,)
    unit_cost = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.batch} costs"


