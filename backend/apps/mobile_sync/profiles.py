"""Frozen operational wire profiles, independent of future domain registries.

Adding a service, serializer or projection must not opt existing clients into
another contract. A financial profile needs its own authorization and rollout.
"""
from dataclasses import dataclass
from types import MappingProxyType

from .errors import SyncError


COMMON = frozenset({"server_id", "created_at", "updated_at"})
BATCH = COMMON | frozenset({
    "batch_id", "bird_type", "broiler_strain", "source", "source_other", "booking_date",
    "estimated_chick_arrival_date", "expected_quantity", "actual_quantity_received",
    "entry_date", "expected_maturity_date", "delivery_confirmed_at", "quantity", "closed_at",
    "status", "initial_birds", "sold_bird_count", "total_mortality", "remaining_birds",
    "approved_adjustment_count",
})
V1_FIELDS = MappingProxyType({
    "poultry.batch": BATCH,
    "poultry.mortality": COMMON | frozenset({"batch_uuid", "mortality_date", "quantity_dead",
        "age_in_days", "suspected_cause", "description", "action_taken", "reported_by_name"}),
    "poultry.feed_usage": COMMON | frozenset({"batch_uuid", "initial_age", "feeding_start_date",
        "feeding_end_date", "feed_type", "feed_source", "quantity_given", "unit_of_measurement",
        "current_number_of_birds", "population_calculation_version", "population_calculated_at",
        "notes", "reported_by_name", "quantity_kg"}),
})
V2_FIELDS = MappingProxyType({
    **V1_FIELDS,
    "poultry.batch": BATCH | frozenset({"supplier_name", "booking_reference", "operational_summary"}),
    "poultry.treatment": COMMON | frozenset({"batch_uuid", "vaccination_date", "drug_category",
        "drug_vaccination_type", "other_drug_vaccination", "quantity", "description",
        "timely_status", "reported_by_name"}),
    "poultry.weight_sample": COMMON | frozenset({"batch_uuid", "sampled_at", "age_in_days",
        "sample_size", "average_weight_g", "notes", "reported_by_name"}),
    "poultry.flock_adjustment": COMMON | frozenset({"batch_uuid", "effective_at", "quantity_change", "reason", "status"}),
    "poultry.adjustment_proposal": COMMON | frozenset({"batch_uuid", "effective_at", "quantity_change",
        "reason", "status", "review_reason", "adjustment_server_id"}),
})
SUMMARY_FIELDS = frozenset({"calculation_version", "feed_record_count", "feed_total_kg",
    "feed_per_bird_started_kg", "feed_denominator", "feed_denominator_birds", "growth",
    "mortality", "stock_integration", "fcr"})
GROWTH_FIELDS = frozenset({"state", "sample"})
SAMPLE_FIELDS = frozenset({"sampled_at", "sample_size", "average_weight_g", "age_in_days",
    "target_weight_g", "strain", "deviation_percent"})
MORTALITY_FIELDS = frozenset({"dead_birds", "actual_arrivals", "rate_percent",
    "threshold_percent", "alert", "formula"})

# Preserve original declaration order in capabilities/OpenAPI, and original v1
# entity order in scope hashes. V2 scope names remain sorted by policy.py.
V1_COMMANDS = (("poultry.mortality", "record", 1),)
V2_COMMANDS = V1_COMMANDS + (
    ("poultry.batch", "book", 1),
    ("poultry.batch", "mark_delivered", 1),
    ("poultry.batch", "confirm_delivery", 1),
    ("poultry.feed_usage", "record", 1),
    ("poultry.treatment", "record", 1),
    ("poultry.weight_sample", "record", 1),
    ("poultry.adjustment_proposal", "propose", 1),
    ("poultry.adjustment_proposal", "approve", 1),
    ("poultry.adjustment_proposal", "reject", 1),
    ("poultry.batch", "recalculate_feed", 1),
)


@dataclass(frozen=True)
class OperationalProfile:
    version: int
    entities: tuple
    commands: tuple
    fields: object


PROFILES = MappingProxyType({
    1: OperationalProfile(1, ("poultry.batch", "poultry.mortality", "poultry.feed_usage"), V1_COMMANDS, V1_FIELDS),
    2: OperationalProfile(2, tuple(sorted(V2_FIELDS)), V2_COMMANDS, V2_FIELDS),
})


def operational_profile(version):
    if type(version) is not int or version not in PROFILES:
        raise SyncError("unsupported_protocol", "Operational projection version is unavailable.", 409)
    return PROFILES[version]


def command_key(command):
    return command.get("entity_type"), command.get("action"), command.get("payload_version")


def require_receipt_profile(command, version):
    if type(command.get("payload_version")) is not int or command_key(command) not in operational_profile(version).commands:
        raise SyncError("unsupported_protocol", "Original operation requires its supported projection profile; retain its ID.", 409)


def project_object(value, fields):
    if not isinstance(value, dict):
        raise SyncError("invalid_projection", "Operational projection is unavailable; retain the current replica and pending work.", 503)
    return {key: item for key, item in value.items() if key in fields}


def operational_payload(entity_type, payload, version):
    profile = operational_profile(version)
    if entity_type not in profile.fields:
        raise SyncError("unsupported_protocol", "Entity is unavailable in this operational profile.", 409)
    result = project_object(payload, profile.fields[entity_type])
    if entity_type == "poultry.batch" and "operational_summary" in result:
        summary = project_object(result["operational_summary"], SUMMARY_FIELDS)
        if "growth" in summary:
            growth = project_object(summary["growth"], GROWTH_FIELDS)
            if growth.get("sample") is not None:
                growth["sample"] = project_object(growth["sample"], SAMPLE_FIELDS)
            summary["growth"] = growth
        if "mortality" in summary:
            summary["mortality"] = project_object(summary["mortality"], MORTALITY_FIELDS)
        result["operational_summary"] = summary
    return result


def operational_result(result, version):
    """Project a receipt response without changing its stored hash or evidence."""
    profile = operational_profile(version)
    public = project_object(result, frozenset({"operation_id", "outcome", "code", "message",
        "field_errors", "recovery_action", "canonical_entities", "entity_mappings",
        "transaction_id", "committed_at"}))
    if "canonical_entities" in public:
        public["canonical_entities"] = [
            {"entity_type": row["entity_type"], "entity_uuid": row["entity_uuid"], "revision": row["revision"],
                "payload": operational_payload(row["entity_type"], row["payload"], version)}
            for row in public["canonical_entities"] if row["entity_type"] in profile.entities
        ]
    if "entity_mappings" in public:
        public["entity_mappings"] = [project_object(row, frozenset({"entity_type", "entity_uuid", "server_id", "revision"}))
            for row in public["entity_mappings"] if row["entity_type"] in profile.entities]
    return public
