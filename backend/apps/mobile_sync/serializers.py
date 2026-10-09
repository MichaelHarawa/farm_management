"""Strict typed v1 input; no ignored caller-supplied fields."""
import re
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from .profiles import V2_COMMANDS
from .schema import PROJECTION


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("Expected a JSON object.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({key: "Unknown field." for key in sorted(unknown)})
        return super().to_internal_value(data)


class StrictInteger(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            raise serializers.ValidationError("Expected an integer JSON value.")
        return super().to_internal_value(data)


class StrictText(serializers.CharField):
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Expected a string JSON value.")
        return super().to_internal_value(data)


class StrictUUID(serializers.UUIDField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", data):
            raise serializers.ValidationError("Expected a lowercase UUID string.")
        return super().to_internal_value(data)


class UTCInstant(serializers.DateTimeField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", data):
            raise serializers.ValidationError("Expected UTC ISO instant with seconds and Z.")
        return super().to_internal_value(data)


class RegisterDeviceSerializer(StrictSerializer):
    installation_id = StrictUUID()
    app_version = StrictText(max_length=40)
    platform = serializers.ChoiceField(choices=["android"])
    protocol_version = StrictInteger(min_value=1, max_value=1)
    device_label = StrictText(max_length=120, allow_blank=True)


class BootstrapSerializer(StrictSerializer):
    protocol_version = StrictInteger(min_value=1, max_value=1)
    packs = serializers.ListField(child=StrictText(max_length=64), min_length=1, max_length=20)
    resume_snapshot_id = StrictUUID(required=False)


class RevokeDeviceSerializer(StrictSerializer):
    reason = StrictText(max_length=255)


class MortalityPayloadSerializer(StrictSerializer):
    batch_uuid = StrictUUID()
    mortality_date = UTCInstant()
    quantity_dead = StrictInteger(min_value=1, max_value=2147483647)
    suspected_cause = StrictText(max_length=200, trim_whitespace=False)
    description = StrictText(max_length=4000, trim_whitespace=False)
    action_taken = StrictText(max_length=4000, trim_whitespace=False)
    reported_by_name = StrictText(max_length=200, trim_whitespace=False)

    def validate(self, attrs):
        for key in ("suspected_cause", "description", "action_taken", "reported_by_name"):
            if not attrs[key].strip():
                raise serializers.ValidationError({key: "Nonblank text required."})
        return attrs


class MortalityOperationSerializer(StrictSerializer):
    operation_id = StrictUUID()
    entity_type = serializers.ChoiceField(choices=["poultry.mortality"])
    entity_uuid = StrictUUID()
    action = serializers.ChoiceField(choices=["record"])
    payload_version = StrictInteger(min_value=1, max_value=1)
    base_version = serializers.JSONField(allow_null=True)
    captured_at = UTCInstant()
    depends_on = serializers.ListField(child=StrictUUID(), max_length=20)
    supersedes_operation_id = StrictUUID(required=False)
    payload = MortalityPayloadSerializer()

    def validate(self, attrs):
        if attrs["base_version"] is not None:
            raise serializers.ValidationError({"base_version": "Append requires null."})
        if len(attrs["depends_on"]) != len(set(attrs["depends_on"])):
            raise serializers.ValidationError({"depends_on": "Duplicate dependencies."})
        return attrs


class PushSerializer(StrictSerializer):
    protocol_version = StrictInteger(min_value=1, max_value=1)
    device_id = StrictUUID()
    operations = MortalityOperationSerializer(many=True, min_length=1, max_length=50)


class FarmDate(serializers.DateField):
    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
            raise serializers.ValidationError("Expected farm calendar date YYYY-MM-DD.")
        return super().to_internal_value(data)


class BookPayload(StrictSerializer):
    from apps.poultry.models import BirdType, BroilerStrain, ChicksSource
    bird_type = serializers.ChoiceField(choices=BirdType.choices)
    broiler_strain = serializers.ChoiceField(choices=BroilerStrain.choices, allow_blank=True, required=False)
    source = serializers.ChoiceField(choices=ChicksSource.choices)
    source_other = StrictText(max_length=200, allow_blank=True, required=False, trim_whitespace=False)
    booking_date = FarmDate()
    estimated_chick_arrival_date = FarmDate()
    supplier_name = StrictText(max_length=200, allow_blank=True, required=False, trim_whitespace=False)
    booking_reference = StrictText(max_length=120, allow_blank=True, required=False, trim_whitespace=False)
    expected_quantity = StrictInteger(min_value=1, max_value=2147483647)
    entry_date = UTCInstant()
    expected_maturity_date = UTCInstant()


class BatchReferencePayload(StrictSerializer):
    batch_uuid = StrictUUID()


class DeliveryPayload(BatchReferencePayload):
    entry_date = UTCInstant()
    expected_maturity_date = UTCInstant(required=False)
    quantity = StrictInteger(min_value=1, max_value=2147483647)


class FeedPayload(BatchReferencePayload):
    from apps.poultry.models import FeedType, FeedSource, UnitMeasurement
    feeding_start_date = UTCInstant()
    feeding_end_date = UTCInstant()
    feed_type = serializers.ChoiceField(choices=FeedType.choices)
    feed_source = serializers.ChoiceField(choices=FeedSource.choices)
    quantity_given = StrictInteger(min_value=1, max_value=2147483647)
    unit_of_measurement = serializers.ChoiceField(choices=UnitMeasurement.choices)
    notes = StrictText(max_length=4000, trim_whitespace=False)
    reported_by_name = StrictText(max_length=200, trim_whitespace=False)


class TreatmentPayload(BatchReferencePayload):
    from apps.poultry.models import DrugCategory, DrugVaccinationType
    vaccination_date = UTCInstant()
    drug_category = serializers.ChoiceField(choices=DrugCategory.choices)
    drug_vaccination_type = serializers.ChoiceField(choices=DrugVaccinationType.choices)
    other_drug_vaccination = StrictText(max_length=200, allow_blank=True, required=False, trim_whitespace=False)
    quantity = StrictInteger(min_value=1, max_value=2147483647)
    description = StrictText(max_length=4000, trim_whitespace=False)
    timely_status = StrictText(max_length=200, trim_whitespace=False)
    reported_by_name = StrictText(max_length=200, trim_whitespace=False)


class WeightPayload(BatchReferencePayload):
    sampled_at = UTCInstant()
    average_weight_g = StrictInteger(min_value=1, max_value=2147483647)
    sample_size = StrictInteger(min_value=1, max_value=2147483647)
    notes = StrictText(max_length=4000, allow_blank=True, required=False, trim_whitespace=False)
    reported_by_name = StrictText(max_length=200, trim_whitespace=False)


class ProposalPayload(BatchReferencePayload):
    effective_at = UTCInstant()
    quantity_change = StrictInteger(min_value=-2147483648, max_value=2147483647)
    reason = StrictText(max_length=255, trim_whitespace=False)

    def validate_quantity_change(self, value):
        if value == 0:
            raise serializers.ValidationError("Adjustment cannot be zero.")
        return value


class ReviewPayload(StrictSerializer):
    reason = StrictText(max_length=255, trim_whitespace=False)


class RecalculatePayload(BatchReferencePayload):
    reason = StrictText(max_length=255, trim_whitespace=False)


PAYLOAD_SERIALIZERS = {
    ("poultry.mortality", "record"): MortalityPayloadSerializer,
    ("poultry.batch", "book"): BookPayload,
    ("poultry.batch", "mark_delivered"): BatchReferencePayload,
    ("poultry.batch", "confirm_delivery"): DeliveryPayload,
    ("poultry.feed_usage", "record"): FeedPayload,
    ("poultry.treatment", "record"): TreatmentPayload,
    ("poultry.weight_sample", "record"): WeightPayload,
    ("poultry.adjustment_proposal", "propose"): ProposalPayload,
    ("poultry.adjustment_proposal", "approve"): ReviewPayload,
    ("poultry.adjustment_proposal", "reject"): ReviewPayload,
    ("poultry.batch", "recalculate_feed"): RecalculatePayload,
}


class PoultryOperationSerializer(MortalityOperationSerializer):
    entity_type = serializers.ChoiceField(choices=sorted({key[0] for key in V2_COMMANDS}))
    action = serializers.ChoiceField(choices=sorted({key[1] for key in V2_COMMANDS}))
    payload = serializers.JSONField()

    def validate(self, attrs):
        from .commands.registry import registry_for_version
        key = (attrs["entity_type"], attrs["action"])
        spec = registry_for_version(2).get((*key, 1))
        serializer_class = PAYLOAD_SERIALIZERS.get(key)
        if serializer_class is None or spec is None:
            raise serializers.ValidationError({"action": "Typed command is unavailable."})
        serializer = serializer_class(data=attrs["payload"])
        serializer.is_valid(raise_exception=True)
        attrs["payload"] = serializer.validated_data
        revision = attrs["base_version"]
        if spec.mutates_existing:
            if revision is None and not attrs["depends_on"] or revision is not None and (
                    not isinstance(revision, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", revision)):
                raise serializers.ValidationError({"base_version": "Expected revision string or an explicit offline-parent dependency required."})
        elif revision is not None:
            raise serializers.ValidationError({"base_version": "Append requires null."})
        if len(attrs["depends_on"]) != len(set(attrs["depends_on"])):
            raise serializers.ValidationError({"depends_on": "Duplicate dependencies."})
        return attrs


class PoultryPushSerializer(PushSerializer):
    operations = PoultryOperationSerializer(many=True, min_length=1, max_length=50)


# Explicit output annotations: operational payload shapes are specified in the
# schema artifact/runbook; financial fields never enter these serializers.
@extend_schema_field(PROJECTION)
class ProjectionField(serializers.JSONField):
    pass


class EntitySerializer(serializers.Serializer):
    entity_type = serializers.CharField()
    entity_uuid = serializers.UUIDField()
    revision = serializers.CharField()
    payload = ProjectionField()


class ResultSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    outcome = serializers.CharField()
    code = serializers.CharField()
    message = serializers.CharField()
    field_errors = serializers.JSONField()
    recovery_action = serializers.CharField()
    canonical_entities = EntitySerializer(many=True, required=False)
    entity_mappings = serializers.ListField(child=serializers.DictField(), required=False)
    transaction_id = serializers.UUIDField(required=False)
    committed_at = serializers.DateTimeField(required=False)


class PushResponseSerializer(serializers.Serializer):
    protocol_version = serializers.IntegerField()
    deployment_id = serializers.UUIDField()
    device_id = serializers.UUIDField()
    server_time = serializers.DateTimeField()
    results = ResultSerializer(many=True)
