"""Default-off authenticated evidence grant; no references or financial writes."""
import re

from django.utils.cache import patch_vary_headers
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from . import financial_storage as storage, schema_storage_api as wire
from .errors import SyncError
from .views import SyncAPIView

HEADERS = [
    OpenApiParameter("X-Mobile-Finance-Version", int, required=True, location=OpenApiParameter.HEADER, enum=[1],
        description="Explicit separate financial wire version; not an operational poultry grant."),
    OpenApiParameter("X-Mobile-Finance-Storage-Version", int, required=True, location=OpenApiParameter.HEADER, enum=[1],
        description="Evidence-only storage authorization. No reference cache or posting authority."),
    OpenApiParameter("X-Mobile-Finance-Storage-Request", str, required=True, location=OpenApiParameter.HEADER,
        description="Fresh canonical UUID per grant request. Echoed to reject cached/replayed responses; not authorization."),
]
VARY = ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-Storage-Version", "X-Mobile-Finance-Storage-Request")


class FinancialStorageGrantView(SyncAPIView):
    http_method_names = ["get", "head", "options"]

    def initial(self, request, *args, **kwargs):
        storage._gates()  # Disabled/vendor refusal BEFORE authentication/SQL, for EVERY method.
        super().initial(request, *args, **kwargs)
        if request.headers.get("X-Mobile-Finance-Version") != "1" or request.headers.get("X-Mobile-Finance-Storage-Version") != "1":
            raise SyncError("unsupported_protocol", "Explicit financial and financial-storage versions 1 are required.", 409)
        request_id = request.headers.get("X-Mobile-Finance-Storage-Request", "")
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", request_id):
            raise SyncError("malformed_request", "Use a fresh canonical request UUID; no identity or policy overrides.")
        if request.body or request.query_params:
            raise SyncError("malformed_request", "This grant accepts no request body, query, identity, duration or command overrides.")
        storage.references._access(request.user, request.mobile_session, request.auth)
        self.request_id = request_id

    @extend_schema(operation_id="mobile_financial_evidence_storage_grant", parameters=HEADERS, responses=wire.openapi_responses())
    def get(self, request):
        # FarmJWTAuthentication has cryptographically validated the ACCESS token
        # and current mobile binding; private issuer repeats current checks.
        result = storage.financial_storage_grant(request.user, request.mobile_session, request.auth)
        return Response({"financial_storage_api_version": 1, "request_id": self.request_id, "grant": result})

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store, max-age=0"
        patch_vary_headers(response, VARY)
        return response
