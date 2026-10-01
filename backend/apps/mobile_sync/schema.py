"""Positive v1 wire schemas. No source ModelSerializer or finance payloads."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class FarmJWTScheme(OpenApiAuthenticationExtension):
    target_class = "apps.mobile_sync.authentication.FarmJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


def obj(properties, optional=()):
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional], "additionalProperties": False}


def array(item):
    return {"type": "array", "items": item}


TEXT = {"type": "string"}
UUID = {"type": "string", "format": "uuid"}
INSTANT = {"type": "string", "format": "date-time"}
COUNTER = {"type": "string", "pattern": "^[0-9]+$"}
INTEGER = {"type": "integer"}
BOOL = {"type": "boolean"}
NULLABLE_INSTANT = {**INSTANT, "nullable": True}
NULLABLE_DATE = {"type": "string", "format": "date", "nullable": True}
NULLABLE_INTEGER = {**INTEGER, "nullable": True}

COMMON = {"server_id": COUNTER, "created_at": INSTANT, "updated_at": INSTANT}
BATCH_PAYLOAD = obj({**COMMON, "batch_id": TEXT, "bird_type": TEXT, "broiler_strain": TEXT,
    "source": TEXT, "source_other": TEXT, "booking_date": NULLABLE_DATE,
    "estimated_chick_arrival_date": NULLABLE_DATE, "expected_quantity": NULLABLE_INTEGER,
    "actual_quantity_received": NULLABLE_INTEGER, "entry_date": INSTANT, "expected_maturity_date": INSTANT,
    "delivery_confirmed_at": NULLABLE_INSTANT, "quantity": INTEGER, "closed_at": NULLABLE_INSTANT,
    "status": TEXT, "initial_birds": INTEGER, "sold_bird_count": INTEGER, "total_mortality": INTEGER,
    "remaining_birds": INTEGER, "approved_adjustment_count": INTEGER})
MORTALITY_PAYLOAD = obj({**COMMON, "batch_uuid": UUID, "mortality_date": INSTANT,
    "quantity_dead": INTEGER, "age_in_days": INTEGER, "suspected_cause": TEXT, "description": TEXT,
    "action_taken": TEXT, "reported_by_name": TEXT})
FEED_PAYLOAD = obj({**COMMON, "batch_uuid": UUID, "initial_age": INTEGER, "feeding_start_date": INSTANT,
    "feeding_end_date": INSTANT, "feed_type": TEXT, "feed_source": TEXT, "quantity_given": INTEGER,
    "unit_of_measurement": TEXT, "current_number_of_birds": INTEGER,
    "population_calculation_version": TEXT, "population_calculated_at": NULLABLE_INSTANT,
    "notes": {**TEXT, "nullable": True}, "reported_by_name": TEXT, "quantity_kg": TEXT})
PROJECTION = {"oneOf": [BATCH_PAYLOAD, MORTALITY_PAYLOAD, FEED_PAYLOAD]}
ENTITY = obj({"entity_type": {"type": "string", "enum": ["poultry.batch", "poultry.mortality", "poultry.feed_usage"]},
              "entity_uuid": UUID, "revision": COUNTER, "payload": PROJECTION})
DEVICE = obj({"device_id": UUID, "installation_id": UUID, "app_version": TEXT,
              "device_label": TEXT, "revoked_at": NULLABLE_INSTANT})
DEVICE_LIST = obj({"count": INTEGER, "page": INTEGER, "page_size": INTEGER, "results": array(DEVICE)})
REGISTER = obj({"deployment_id": UUID, "device_id": UUID, "access": TEXT, "refresh": TEXT,
    "policy": obj({"operational_offline_days": INTEGER, "sensitive_offline_hours": INTEGER, "protocol_version": INTEGER})})
CAPABILITIES = obj({"protocol_version": INTEGER, "schema_version": INTEGER, "policy_version": INTEGER,
    "projection_version": INTEGER, "deployment_id": UUID, "stream_epoch": UUID, "device_id": UUID,
    "server_time": INSTANT, "scope_revision": TEXT, "entities": array(TEXT),
    "commands": obj({"poultry.mortality.record": obj({"available": BOOL, "payload_version": INTEGER, "capability": TEXT}),
                     "finance": obj({"available": BOOL, "reason": TEXT})}),
    "packs": array(TEXT), "offline": obj({"operational_days": INTEGER, "sensitive_hours": INTEGER}),
    "limits": obj({key: INTEGER for key in ["push_bytes", "operations", "dependencies", "page_rows", "page_bytes", "group_rows", "group_bytes", "snapshot_rows", "snapshot_bytes", "active_snapshots_per_user", "entity_bytes", "scan_rows"]}),
    "retention": obj({"snapshot_hours": INTEGER, "change_days": INTEGER, "deduplication": TEXT, "minimum_sequence": COUNTER})})
BOOTSTRAP = obj({"snapshot_id": UUID, "deployment_id": UUID, "stream_epoch": UUID,
    "scope_revision": TEXT, "watermark": COUNTER, "expires_at": INSTANT, "packs": array(TEXT),
    "row_count": INTEGER, "manifest": array(obj({"page": INTEGER, "row_count": INTEGER, "sha256": TEXT})),
    "next_page_cursor": TEXT})
PAGE = obj({"snapshot_id": UUID, "page": INTEGER, "entities": array(ENTITY), "sha256": TEXT,
    "page_complete": BOOL, "next_page_cursor": {**TEXT, "nullable": True}, "delta_cursor": TEXT}, optional=("delta_cursor",))
FRAGMENT = obj({"transaction_id": UUID, "fragment_index": INTEGER, "fragment_final": BOOL})
CHANGE = obj({**FRAGMENT["properties"], "sequence": COUNTER, "entity_type": ENTITY["properties"]["entity_type"],
    "entity_uuid": UUID, "revision": COUNTER, "kind": {"type": "string", "enum": ["upsert", "tombstone", "evict_from_pack"]},
    "pack_ids": array(TEXT), "payload": PROJECTION, "origin_operation_id": UUID}, optional=("payload", "origin_operation_id"))
CHANGES = obj({"deployment_id": UUID, "stream_epoch": UUID, "scope_revision": TEXT, "run_watermark": COUNTER,
    "changes": array(CHANGE), "fragments": array(FRAGMENT), "next_cursor": TEXT, "run_complete": BOOL, "server_time": INSTANT})
ERROR = obj({"code": TEXT, "message": TEXT})


def responses(success):
    # DRF authentication and throttling use their established `detail` shape;
    # application errors use stable named codes. Both are explicit on the wire.
    error = {"oneOf": [ERROR, obj({"detail": TEXT}), obj({"detail": TEXT, "code": TEXT,
        "messages": array(obj({"token_class": TEXT, "token_type": TEXT, "message": TEXT}))}, optional=("messages",))]}
    return {200: success, **{status: error for status in [400, 401, 403, 404, 409, 410, 413, 429, 503]}}
