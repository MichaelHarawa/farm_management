from __future__ import annotations
from decimal import Decimal

from rest_framework import serializers

from .models import(
    Batch,
    ChicksSource,
    PaymentStatus,
    InputCosts,
    Sales,
    Mortality,
    FeedUsage,
    DrugsVaccination,
)

class BatchSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

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
            "status",
            "closed_at",
            "closure_reason",
            "profitability_finalized_at",
            "target_selling_price",
            "closure_notes",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )
        read_only_fields = (
            "id",
            "batch_id",
            "status",
            "closed_at",
            "closure_reason",
            "profitability_finalized_at",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )

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

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username

class InputCostsSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    direct_input_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )

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
            "direct_input_total",
            "purchase_date",
            "notes",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )
        read_only_fields = (
            "id",
            "batch",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
            "direct_input_total",
        )

    def validate(self, attrs):
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 0))
        unit = attrs.get("unit", getattr(self.instance, "unit", 0))
        unit_cost = attrs.get(
            "unit_cost",
            getattr(self.instance, "unit_cost", Decimal("0.00")),
        )

        errors = {}
        if quantity <= 0:
            errors["quantity"] = "Quantity must be greater than zero."
        if unit <= 0:
            errors["unit"] = "Unit must be greater than zero."
        if unit_cost < Decimal("0.00"):
            errors["unit_cost"] = "Unit cost cannot be negative."
        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username

class SalesSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    sale_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )

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
            "sale_total",
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
            "created_by_name",
        )
        read_only_fields = (
            "id",
            "batch",
            "sale_id",
            "sale_total",
            "balance",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )

    def validate(self, attrs):
        quantity_sold = attrs.get(
            "quantity_sold",
            getattr(self.instance, "quantity_sold", 0),
        )
        unit_price = attrs.get(
            "unit_price",
            getattr(self.instance, "unit_price", Decimal("0.00")),
        )
        amount_paid = attrs.get(
            "amount_paid",
            getattr(self.instance, "amount_paid", Decimal("0.00")),
        )
        payment_status = attrs.get(
            "payment_status",
            getattr(self.instance, "payment_status", None),
        )
        sale_total = (Decimal(quantity_sold) * unit_price).quantize(
            Decimal("0.01")
        )

        errors = {}
        if quantity_sold <= 0:
            errors["quantity_sold"] = "Quantity sold must be greater than zero."
        if unit_price < Decimal("0.00"):
            errors["unit_price"] = "Unit price cannot be negative."
        if amount_paid < Decimal("0.00"):
            errors["amount_paid"] = "Amount paid cannot be negative."
        if (
            payment_status != PaymentStatus.CANCELLED
            and amount_paid > sale_total
        ):
            errors["amount_paid"] = "Amount paid cannot exceed sale total."
        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username

class MortalitySerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

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
                "updated_at",
                "created_by",
                "created_by_name",
        )
        read_only_fields = (
            "id",
            "batch",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username

class FeedUsageSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

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
                "updated_at",
                "created_by",
                "created_by_name",

        )
        read_only_fields = (
            "id",
            "batch",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username

class DrugsVaccinationSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DrugsVaccination
        fields = (
                "id",
                "batch",
                "vaccination_date",
                "drug_vaccination_type",
                "other_drug_vaccination",
                "drug_category",
                "quantity",
                "description",
                "timely_status",
                "reported_by_name",
                "created_at",
                "updated_at",
                "created_by",
                "created_by_name",

        )
        read_only_fields = (
            "id",
            "batch",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        )

    def get_created_by_name(self, obj):
        if obj.created_by_id is None:
            return ""

        return obj.created_by.get_full_name() or obj.created_by.username


