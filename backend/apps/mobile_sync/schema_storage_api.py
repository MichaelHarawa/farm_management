"""Separate positive grant HTTP envelope; private storage grant v1 stays exact."""
from .schema import obj
from .schema_financial_storage import GRANT, UUID
from .schema_reference_api import openapi_responses as read_responses

REQUEST_UUID = {**UUID, "pattern": r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])"}
RESPONSE = obj({"financial_storage_api_version": {"type": "integer", "const": 1},
    "request_id": REQUEST_UUID, "grant": GRANT})


def openapi_responses():
    return read_responses(RESPONSE)
