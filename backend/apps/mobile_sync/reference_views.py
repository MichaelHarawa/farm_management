"""Default-off authenticated ONLINE reference reads. No financial dispatch."""
from django.conf import settings
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from . import financial_references as funding, invoice_references as invoices
from . import schema_financial_references as funding_wire, schema_invoice_references as invoice_wire
from . import schema_reference_api as wire
from .commands.financial import _gate
from .errors import SyncError
from .financial_views import FINANCIAL_HEADER
from .projections import json_value
from .transport import stream_ready
from .views import SyncAPIView
from .writers import sync_boundary

REFERENCE_HEADER = OpenApiParameter("X-Mobile-Finance-References-Version", int, required=True,
    location=OpenApiParameter.HEADER, enum=[1], description="Explicit online reference API; no financial upload, replication or offline grant.")
HEADERS = [FINANCIAL_HEADER, REFERENCE_HEADER]
CURSOR = OpenApiParameter("cursor", str, description="Exact opaque cursor returned by this same authorized catalog.")
VERSION = OpenApiParameter("invoice_version", str, required=True, description="Exact original accepted invoice version; never substitute a current version.")


class FinancialReferenceAPIView(SyncAPIView):
    http_method_names = ["get", "head", "options"]
    allowed_query = frozenset()
    required_query = frozenset()

    def initial(self, request, *args, **kwargs):
        # Every method, including OPTIONS/unsupported writes, fails closed before
        # authentication/SQL when the new read surface is not explicitly enabled.
        if not settings.MOBILE_SYNC_FINANCIAL_READS or not settings.MOBILE_SYNC_FINANCIAL_REFERENCES:
            raise SyncError("financial_reference_reads_disabled", "Financial reference reads are disabled on this deployment.", 503)
        _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
        super().initial(request, *args, **kwargs)
        if request.headers.get("X-Mobile-Finance-Version") != "1" or request.headers.get("X-Mobile-Finance-References-Version") != "1":
            raise SyncError("unsupported_protocol", "Explicit financial and reference read versions 1 are required.", 409)
        if (request.body or set(request.query_params) - self.allowed_query
                or self.required_query - set(request.query_params)
                or any(len(request.query_params.getlist(key)) != 1 or not request.query_params[key]
                    for key in request.query_params)):
            raise SyncError("malformed_request", "Use only the exact supported reference query; no body, duplicate values or identity/field overrides.")
        self.recheck_access()

    def recheck_access(self):
        actor, session = funding._access(self.request.user, self.request.mobile_session, self.request.auth)
        self.request.user = actor
        self.request.mobile_session = session
        return actor, session

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store, max-age=0"
        patch_vary_headers(response, ("Authorization", "X-Mobile-Finance-Version", "X-Mobile-Finance-References-Version"))
        return response


class ReferenceCapabilitiesView(FinancialReferenceAPIView):
    @extend_schema(operation_id="mobile_financial_reference_capabilities", parameters=HEADERS, responses=wire.openapi_responses(wire.CAPABILITIES))
    def get(self, request):
        with sync_boundary():
            actor, session = self.recheck_access()
            stream = stream_ready()
            scope = funding._scope(stream, actor, session)
            result = {"financial_reference_api_version": 1, "deployment_id": str(stream.deployment_id),
                "device_id": str(session.device_id), "actor_id": str(actor.pk), "server_time": json_value(timezone.now()),
                "access": "online_only_current_finance_writer", "offline_cache_seconds": 0, "financial_uploads": False,
                "packs": [], "profiles": {"funding": 1, "original_invoices": 1},
                "scopes": {"funding": scope, "original_invoices": invoices._scope(stream, actor, session)},
                "limits": {"funding_rows": funding.MAX_CATALOG_ROWS, "funding_page_rows": funding.PAGE_ROWS,
                    "funding_catalog_bytes": funding.MAX_CATALOG_BYTES, "invoice_rows": invoices.MAX_CATALOG_ROWS,
                    "invoice_page_rows": invoices.PAGE_ROWS, "invoice_catalog_bytes": invoices.MAX_CATALOG_BYTES,
                    "invoice_detail_bytes": invoices.MAX_DETAIL_BYTES, "invoice_lines": 50, "cursor_seconds": 900}}
            funding._unchanged_access(stream, actor, session, request.auth, scope)
            return Response(result)


class FundingReferenceCatalogView(FinancialReferenceAPIView):
    allowed_query = frozenset({"cursor"})

    @extend_schema(operation_id="mobile_financial_funding_catalog", parameters=[*HEADERS, CURSOR], responses=wire.openapi_responses(funding_wire.CATALOG))
    def get(self, request):
        return Response(funding.funding_reference_catalog(request.user, request.mobile_session, request.auth,
            cursor=request.query_params.get("cursor")))


class InvoiceReferenceCatalogView(FinancialReferenceAPIView):
    allowed_query = frozenset({"cursor"})

    @extend_schema(operation_id="mobile_financial_invoice_catalog", parameters=[*HEADERS, CURSOR], responses=wire.openapi_responses(invoice_wire.CATALOG))
    def get(self, request):
        return Response(invoices.invoice_reference_catalog(request.user, request.mobile_session, request.auth,
            cursor=request.query_params.get("cursor")))


class InvoiceReferenceDetailView(FinancialReferenceAPIView):
    allowed_query = required_query = frozenset({"invoice_version"})

    @extend_schema(operation_id="mobile_financial_invoice_detail", parameters=[*HEADERS, VERSION], responses=wire.openapi_responses(invoice_wire.DETAIL))
    def get(self, request, invoice_id):
        return Response(invoices.invoice_reference_detail(str(invoice_id), request.query_params["invoice_version"],
            request.user, request.mobile_session, request.auth))
