"""Default-off UUID financial HTTP adapter; operational v1/v2 stay frozen.

Each operation commits independently through the existing domain/receipt bridge.
An HTTP failure may follow an accepted payment: retain EVERY original ID and
query status, never recreate physical payment evidence under another ID.
"""
import json

from django.conf import settings
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.utils.decorators import method_decorator
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.parsers import BaseParser
from rest_framework.response import Response

from apps.finance.permissions import FINANCE_WRITE_ROLES
from .commands import financial as bridge, financial_uuid as commands, financial_uuid_schema as wire
from .errors import SyncError
from .projections import canonical, json_value
from .schema_command_api import openapi_schema, openapi_responses, CAPABILITIES, RequiredCommandBodySchema
from .schema import obj
from .policy import permits
from .views import SyncAPIView
from .writers import sync_boundary

MAX_RESPONSE_BYTES = 128 * 1024
HEADERS = [OpenApiParameter("X-Mobile-Finance-Version", int, required=True,
    location=OpenApiParameter.HEADER, enum=[1], description="Separate financial protocol1; not poultry sync."),
    OpenApiParameter("X-Mobile-Finance-Command-Version", int, required=True,
        location=OpenApiParameter.HEADER, enum=[2], description="Exact external UUID command2. No private PK input.")]


class FinancialJSONParser(BaseParser):
    media_type = "application/json"

    def parse(self, stream, media_type=None, parser_context=None):
        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate object member")
                result[key] = value
            return result

        def forbidden_number(value):
            raise ValueError("Only integer JSON numbers and exact decimal strings")

        raw = stream.read(commands.MAX_BYTES + 1)
        if len(raw) > commands.MAX_BYTES:
            raise SyncError("request_too_large", "Retain all original operation IDs; request exceeds one MiB.", 413)
        try:
            return json.loads(raw.decode("utf-8"), object_pairs_hook=object_pairs,
                parse_float=forbidden_number, parse_constant=forbidden_number)
        except (UnicodeError, ValueError, RecursionError):
            raise SyncError("malformed_request", "Strict UTF-8 JSON with unique fields and exact financial values is required.") from None


class FinancialCommandAPIView(SyncAPIView):
    parser_classes = [FinancialJSONParser]
    gate = None
    prerequisites = ()

    def initial(self, request, *args, **kwargs):
        # Includes unsupported methods: default-off/vendor/operational checks
        # precede JWT parsing or SQL. Old flags alone cannot expose this API.
        for flag in (self.gate, *self.prerequisites):
            bridge._gate(flag)
        super().initial(request, *args, **kwargs)
        if (request.headers.get("X-Mobile-Finance-Version") != "1" or
                request.headers.get("X-Mobile-Finance-Command-Version") != "2"):
            raise SyncError("unsupported_protocol", "Explicit financial protocol1 and UUID command2 headers are required.", 409)
        if request.query_params:
            raise SyncError("malformed_request", "No actor, deployment, device, policy or query overrides are accepted.")
        if len(request.body) > commands.MAX_BYTES:
            raise SyncError("request_too_large", "Retain all original operation IDs; request exceeds one MiB.", 413)
        # A live signed binding/read role is required even for status. The
        # service repeats this before/after stream waits and before release.
        bridge._bound(request.user, request.mobile_session, request.auth)

    def response(self, value):
        if len(canonical(value).encode("utf-8")) > MAX_RESPONSE_BYTES:
            # A command may ALREADY be committed. This is NOT a rejection or
            # permission to repost under a replacement operation ID.
            raise SyncError("financial_response_unavailable", "Retain original IDs and recover their immutable statuses.", 503)
        return Response(value)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store, max-age=0"
        patch_vary_headers(response, ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-Command-Version"))
        return response


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class FinancialCommandSubmitView(FinancialCommandAPIView):
    schema = RequiredCommandBodySchema()
    http_method_names = ["post", "options"]
    gate = "MOBILE_SYNC_FINANCIAL_COMMAND_API"
    prerequisites = ("MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API", "MOBILE_SYNC_FINANCIAL_READS",
        "MOBILE_SYNC_FINANCIAL_UUID_COMMANDS", "MOBILE_SYNC_FINANCIAL_COMMANDS",
        "MOBILE_SYNC_FINANCIAL_REFERENCES", "FINANCE_INVENTORY_INVOICES")

    @extend_schema(operation_id="mobile_financial_uuid_commands", parameters=HEADERS,
        request={"application/json": openapi_schema(wire.ENVELOPE)},
        responses={**openapi_responses(wire.RESPONSE), 415: obj({"detail": {"type": "string"}})})
    def post(self, request):
        # No extra wrapping transaction: a later operation/request failure must
        # not falsely imply that earlier accepted commands were undone.
        return self.response(commands.execute_uuid_envelope(request.data, request.user,
            request.mobile_session, request.auth))


class FinancialCommandStatusView(FinancialCommandAPIView):
    http_method_names = ["get", "head", "options"]
    gate = "MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API"
    prerequisites = ("MOBILE_SYNC_FINANCIAL_READS",)

    @extend_schema(operation_id="mobile_financial_uuid_command_status", parameters=HEADERS,
        responses=openapi_responses(wire.RESPONSE))
    def get(self, request, operation_id):
        if request.body:
            raise SyncError("malformed_request", "Original-operation status reads accept no body.")
        with sync_boundary() as state:
            self.recheck()
            result = commands.recover_uuid_command(str(operation_id), request.user, request.mobile_session, request.auth)
            _, session = bridge._bound(request.user, request.mobile_session, request.auth)
            return self.response({"financial_protocol_version": 1, "deployment_id": str(state["stream"].deployment_id),
                "device_id": str(session.device_id), "server_time": json_value(timezone.now()), "results": [result]})


class FinancialCommandCapabilitiesView(FinancialCommandAPIView):
    """Fresh server permission/availability, never an offline or posting grant."""
    http_method_names = ["get", "head", "options"]
    gate = "MOBILE_SYNC_FINANCIAL_COMMAND_STATUS_API"
    prerequisites = ("MOBILE_SYNC_FINANCIAL_READS",)

    @staticmethod
    def can_submit(actor):
        return permits(actor, FINANCE_WRITE_ROLES) and all(getattr(settings, flag)
            for flag in (FinancialCommandSubmitView.gate, *FinancialCommandSubmitView.prerequisites))

    @extend_schema(operation_id="mobile_financial_uuid_command_capabilities", parameters=HEADERS,
        responses=openapi_responses(CAPABILITIES))
    def get(self, request):
        if request.body:
            raise SyncError("malformed_request", "Command discovery accepts no body or policy overrides.")
        with sync_boundary() as state:
            self.recheck()
            actor, session = bridge._bound(request.user, request.mobile_session, request.auth)
            enabled = self.can_submit(actor)
            result = {"financial_protocol_version": 1, "financial_command_version": 2,
                "deployment_id": str(state["stream"].deployment_id), "device_id": str(session.device_id),
                "actor_id": str(actor.pk), "server_time": json_value(timezone.now()),
                "access": "online_only_current_authority", "offline_cache_seconds": 0,
                "packs": [], "requires_separate_native_storage_grant": True,
                "submission_enabled": enabled, "status_recovery_enabled": True,
                "commands": [wire.COMMAND] if enabled else [],
                "limits": {"request_bytes": commands.MAX_BYTES, "response_bytes": MAX_RESPONSE_BYTES,
                    "operations": 20, "dependencies_per_operation": 20, "invoices_per_operation": 10,
                    "lines_per_operation": 50, "funding_rows_per_operation": 100}}
            actor, _ = bridge._bound(actor, session, request.auth)
            if self.can_submit(actor) != enabled:
                raise SyncError("permission_denied", "Financial authority changed; request fresh command discovery.", 403)
            return self.response(result)
