"""Separately gated online-only reads; operational contracts remain frozen."""
from django.conf import settings
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from apps.finance.permissions import FINANCE_READ_ROLES
from apps.finance.services.inventory_payment_summary import MAX_SUMMARY_BYTES, MAX_VERIFIED_FUNDING_ROWS
from . import schema_financial_reads as wire
from .errors import SyncError
from .financial_reads import (MAX_RECEIPT_PROOF_BYTES, financial_read_scope, own_payment_receipt,
    retained_payment_status, retained_payment_summary)
from .policy import permits
from .projections import json_value
from .views import SyncAPIView
from .writers import sync_boundary


FINANCIAL_HEADER = OpenApiParameter("X-Mobile-Finance-Version", int, required=True,
    location=OpenApiParameter.HEADER, enum=[1], description="Explicit separate online financial read profile. No uploads or offline cache grant.")


class FinancialReadAPIView(SyncAPIView):
    def initial(self, request, *args, **kwargs):
        # Default-off before authentication or any database query. Source farm
        # and old clients do not gain a new financial entry point by registration.
        if not settings.MOBILE_SYNC_FINANCIAL_READS:
            raise SyncError("financial_reads_disabled", "Financial receipt reads are disabled on this deployment.", 503)
        super().initial(request, *args, **kwargs)
        if request.headers.get("X-Mobile-Finance-Version") != "1":
            raise SyncError("unsupported_protocol", "Explicit financial read version 1 is required.", 409)
        if request.query_params:
            raise SyncError("malformed_request", "This receipt read accepts no actor, device, deployment, field or paging overrides.")
        self.recheck_finance()

    def recheck_finance(self):
        self.recheck()
        if not permits(self.request.user, FINANCE_READ_ROLES):
            raise SyncError("permission_denied", "Current financial read permission is required.", 403)

    def context(self, stream):
        return {"financial_read_version": 1, "deployment_id": str(stream.deployment_id),
            "device_id": str(self.device.pk), "scope_revision": financial_read_scope(self.request.user, self.device, stream),
            "server_time": json_value(timezone.now()), "access": "online_only_original_actor", "offline_cache_seconds": 0}

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store, max-age=0"
        patch_vary_headers(response, ("Authorization", "X-Mobile-Finance-Version"))
        return response


class FinancialReadCapabilitiesView(FinancialReadAPIView):
    @extend_schema(parameters=[FINANCIAL_HEADER], responses=wire.openapi_responses(wire.CAPABILITIES))
    def get(self, request):
        with sync_boundary() as state:
            self.recheck_finance()
            return Response({**self.context(state["stream"]), "reads": {
                "supplier_payment_status": True, "supplier_payment_summary": True},
                "financial_uploads": False, "packs": [], "limits": {
                    "summary_bytes": MAX_SUMMARY_BYTES, "summary_invoices": 10, "summary_lines": 50,
                    "summary_funding_rows": MAX_VERIFIED_FUNDING_ROWS, "receipt_proof_bytes": MAX_RECEIPT_PROOF_BYTES}})


class SupplierPaymentStatusView(FinancialReadAPIView):
    @extend_schema(parameters=[FINANCIAL_HEADER], responses=wire.openapi_responses(wire.STATUS))
    def get(self, request, operation_id):
        with sync_boundary() as state:
            self.recheck_finance()
            result = retained_payment_status(own_payment_receipt(operation_id, request.user))
            self.recheck_finance()
            return Response({**self.context(state["stream"]), **result})


class SupplierPaymentSummaryView(FinancialReadAPIView):
    @extend_schema(parameters=[FINANCIAL_HEADER], responses=wire.openapi_responses(wire.SUMMARY))
    def get(self, request, operation_id):
        with sync_boundary() as state:
            self.recheck_finance()
            summary = retained_payment_summary(own_payment_receipt(operation_id, request.user))
            self.recheck_finance()
            return Response({**self.context(state["stream"]), "summary": summary})
