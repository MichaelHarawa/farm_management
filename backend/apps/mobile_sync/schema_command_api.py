"""OpenAPI 3.0 documentation only; runtime UUID JSON schemas stay unchanged."""
from .commands.financial_uuid_schema import UUID, INSTANT, COMMAND
from drf_spectacular.openapi import AutoSchema
from .schema import obj, responses

CAPABILITIES = obj({"financial_protocol_version": {"type": "integer", "const": 1},
    "financial_command_version": {"type": "integer", "const": 2},
    "deployment_id": UUID, "device_id": UUID, "actor_id": UUID, "server_time": INSTANT,
    "access": {"const": "online_only_current_authority"}, "offline_cache_seconds": {"const": 0},
    "packs": {"type": "array", "maxItems": 0}, "requires_separate_native_storage_grant": {"const": True},
    "submission_enabled": {"type": "boolean"}, "status_recovery_enabled": {"const": True},
    "commands": {"type": "array", "maxItems": 1, "uniqueItems": True, "items": {"const": COMMAND}},
    "limits": obj({"request_bytes": {"const": 1048576}, "response_bytes": {"const": 131072},
        "operations": {"const": 20}, "dependencies_per_operation": {"const": 20},
        "invoices_per_operation": {"const": 10}, "lines_per_operation": {"const": 50},
        "funding_rows_per_operation": {"const": 100}})})


def openapi_schema(value):
    if isinstance(value, dict):
        if "anyOf" in value and len(value["anyOf"]) == 2 and {"type": "null"} in value["anyOf"]:
            return {**openapi_schema(next(item for item in value["anyOf"] if item != {"type": "null"})),
                "nullable": True}
        return {("enum" if key == "const" else key): ([item] if key == "const" else openapi_schema(item))
            for key, item in value.items() if not (key == "required" and item == [])}
    if isinstance(value, list):
        return [openapi_schema(item) for item in value]
    return value


def openapi_responses(success):
    return {**responses(openapi_schema(success)), 405: obj({"detail": {"type": "string"}})}


class RequiredCommandBodySchema(AutoSchema):
    def _get_request_body(self, direction="request"):
        body = super()._get_request_body(direction)
        if body is not None and self.method == "POST":
            body["required"] = True
        return body
