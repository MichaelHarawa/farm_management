from __future__ import annotations
from rest_framework import serializers

from .models import(
    Batch,
    InputCosts,
    Sales,
)

class BatchSerializer(serializers.ModelSerializer):
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)

    class Meta:
        model = Batch
        fields = (
            "id",
            "batch_id",
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
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)
    class Meta:
        model = InputCosts
        fields = (
            "id",
            "batch",
            "item",
            "category",
            "quantity",
            "unit_measurement",
            "unit",
            "unit_cost",
            "created_at",
            "updated_at",
            # "created_by_username",
        )
        read_only_fields = ("id", "batch","created_at","updated_at")

class SalesSerializer(serializers.ModelSerializer):
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)
    class Meta:
        model = Sales
        fields = (
            "id",
            "batch",
            "sale_id",
            "sale_date",
            "product_type",
            "quantity_sold",
            "unit_price",
            "buyer_name",
            "buyer_type",
            "payment_status",
            "payment_method",
            "amount_paid",
            "balance",
            "sold_by_name",
            "notes",
            "created_at",
            "updated_at",
            "created_by",
            # "created_by_username",
        )
        read_only_fields = ("id", "batch","sale_id","created_at","updated_at","created_by")




