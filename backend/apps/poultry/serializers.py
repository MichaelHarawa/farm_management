from __future__ import annotations
from rest_framework import serializers

from .models import(
    Batch,
    ChicksSource,
    InputCosts,
    Sales,
    Mortality,
    FeedUsage,
)

class BatchSerializer(serializers.ModelSerializer):
    # created_by_username = serializers.CharField(source = "created_by.username", read_only = True)

    class Meta:
        model = Batch
        fields = (
            "id",
            "batch_id",
            "bird_type",
            "source",
            "source_other",
            "entry_date",
            "expected_maturity_date",
            "quantity",
            "created_at",
            "updated_at",
            # "created_by_username",
        )
        read_only_fields = ("id", "batch_id", "created_at", "updated_at",)

    def validate(self, attrs):
        source = attrs.get("source", getattr(self.instance, "source", None))
        source_other_value = attrs.get(
            "source_other",
            getattr(self.instance, "source_other", ""),
        )
        source_other = (source_other_value or "").strip()

        if source == ChicksSource.OTHER and not source_other:
            raise serializers.ValidationError(
                {"source_other": "Enter the source name."}
            )

        attrs["source_other"] = (
            source_other if source == ChicksSource.OTHER else ""
        )

        return attrs

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
            "purchase_date",
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

class MortalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Mortality
        fields= (
                "id",
                "batch",
                "mortality_date",
                "quantity_dead",
                "age_in_days",
                "suspected_cause",
                "description",
                "action_taken",
                "reported_by_name",
                "created_at",
                "updated_at"
        )
        read_only_fields = ("id", "batch","created_at","updated_at","created_by")

class FeedUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedUsage
        fields = (
                "id",
                "batch",
                "initial_age",
                "feeding_start_date",
                "feeding_end_date",
                "feed_type",
                "feed_source",
                "quantity_given",
                "unit_of_measurement",
                "current_number_of_birds",
                "notes",
                "reported_by_name",
                "created_at",
                "updated_at"

        )
        read_only_fields = ("id", "batch","created_at","updated_at","created_by")


