from __future__ import annotations
from rest_framework import serializers

from .models import(
    Batch,
    InputCosts,
)

class BatchSerializer(serializers.ModelSerializer):
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)

    class Meta:
        model = Batch
        fields = (
            "id",
            "batch_id"
            "bird_type",
            "entry_date",
            "expected_maturity_date",
            "quantity",
            "created_at",
            "updated_at",
            # "created_by_username",
        )
        read_only_fields = ("id", "batch_id", "created_at", "updated_at",)

class InputCostsSerializer(serializers.ModelSerializer):
    model = InputCosts
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)
    class Meta:
    fields = (
        "id",
        "batch",
        "item",
        "category",
        "quantity",
        "unit_measurement",
        "unit_cost",
        "created_at",
        "updated_at",
        # "created_by_username",
    )
    read_only_fields = ("id", "batch","created_at","updated_at")

