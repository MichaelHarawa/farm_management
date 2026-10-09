from datetime import timedelta
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .commands.service import execute, order_operations, outcome
from .errors import SyncError
from .models import MobileDevice, MobileDeviceAudit, MobileSession, SyncOperationReceipt
from .policy import READERS, OPERATORS, permits, scope_revision
from .profiles import operational_profile, operational_result, require_receipt_profile
from .projections import CURRENT_PACK, POULTRY_PACK, json_value
from .serializers import (BootstrapSerializer, RegisterDeviceSerializer, RevokeDeviceSerializer,
                          PushSerializer, PoultryPushSerializer, PoultryOperationSerializer)
from .transport import (bootstrap_manifest, bootstrap_page, create_bootstrap, owned_snapshot, pull_changes, stream_ready)
from .writers import sync_boundary
from .authentication import check_binding
from . import schema
from . import schema_poultry as poultry_schema

POULTRY_HEADER=OpenApiParameter('X-Mobile-Poultry-Version',int,location=OpenApiParameter.HEADER,enum=[1,2],description='Default1 is frozen legacy. Opt-in2 requires MOBILE_SYNC_POULTRY_V2.')


def validated(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def page_limit(value, default=500):
    try:
        return min(max(int(value), 1), 500) if value is not None else default
    except (ValueError, TypeError) as error:
        raise SyncError("invalid_limit", "Integer page limit required.") from error


def device_data(device):
    return {"device_id": str(device.pk), "installation_id": str(device.installation_id), "app_version": device.app_version,
            "device_label": device.device_label, "revoked_at": json_value(device.revoked_at)}


class SyncAPIView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mobile_sync"
    requires_device = True

    def initial(self, request, *args, **kwargs):
        if not settings.MOBILE_SYNC_ENABLED or not settings.MOBILE_SYNC_CAPTURE:
            raise SyncError("sync_disabled", "Mobile API is not enabled on this deployment.", 503)
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            content_length = 0
        if content_length > settings.MOBILE_SYNC_PAGE_BYTES or len(request.body) > settings.MOBILE_SYNC_PAGE_BYTES:
            raise SyncError("request_too_large", "JSON request exceeds one MiB.", 413)
        super().initial(request, *args, **kwargs)
        stream_ready()
        if not permits(request.user, READERS):
            raise SyncError("permission_denied", "Operational access required.", 403)
        if self.requires_device and not getattr(request, "mobile_session", None):
            raise SyncError("device_required", "Signed device/session-bound JWT required.", 403)

    def handle_exception(self, error):
        if isinstance(error, DatabaseError):
            error = SyncError("retry_later", "Database request failed; retain the original operation ID.", 503)
        elif isinstance(error, ValidationError):
            error = SyncError("malformed_request", str(error.detail))
        return super().handle_exception(error)

    @property
    def device(self):
        return self.request.mobile_session.device

    def recheck(self):
        """Recheck after acquiring the stream, not just before waiting for it."""
        user = get_user_model().objects.get(pk=self.request.user.pk)
        if not permits(user, READERS):
            raise SyncError("permission_denied", "Current operational access required.", 403)
        self.request.user = user
        session = check_binding(self.request.auth, user.pk)
        if self.requires_device and session is None:
            raise SyncError("device_required", "Bound mobile session required.", 403)
        self.request.mobile_session = session

    def poultry_version(self):
        value = self.request.headers.get("X-Mobile-Poultry-Version", "1")
        if value not in {"1", "2"} or value == "2" and not settings.MOBILE_SYNC_POULTRY_V2:
            raise SyncError("unsupported_protocol", "Requested poultry projection is unavailable.", 409)
        return int(value)


class DeviceView(SyncAPIView):
    requires_device = False
    throttle_scope = "mobile_registration"

    @extend_schema(request=RegisterDeviceSerializer, responses=schema.responses(schema.REGISTER))
    def post(self, request):
        data = validated(RegisterDeviceSerializer, request.data)
        with sync_boundary() as state:
            self.recheck()
            device = MobileDevice.objects.select_for_update().filter(installation_id=data["installation_id"]).first()
            if device and (device.user_id != request.user.pk or device.revoked_at):
                raise SyncError("installation_unavailable", "Installation is foreign or revoked.", 403)
            if device is None:
                device = MobileDevice.objects.create(user=request.user, **data)
            else:
                for field, value in data.items():
                    setattr(device, field, value)
                device.save()
            session = MobileSession.objects.create(device=device, expires_at=timezone.now() + timedelta(days=7))
            refresh = RefreshToken.for_user(request.user)
            refresh["mobile_device_id"] = str(device.pk)
            refresh["mobile_session_id"] = str(session.pk)
            refresh["deployment_id"] = str(state["stream"].deployment_id)
            MobileDeviceAudit.objects.create(device=device, actor=request.user, action="registered")
            return Response({"deployment_id": str(state["stream"].deployment_id), "device_id": str(device.pk),
                             "access": str(refresh.access_token), "refresh": str(refresh),
                             "policy": {"operational_offline_days": 7, "sensitive_offline_hours": 24, "protocol_version": 1}})

    @extend_schema(parameters=[OpenApiParameter("all", str), OpenApiParameter("page", int)], responses=schema.responses(schema.DEVICE_LIST))
    def get(self, request):
        devices = MobileDevice.objects.filter(user=request.user)
        if request.query_params.get("all") == "1":
            if not request.user.has_admin_access:
                raise SyncError("permission_denied", "Administrator access required.", 403)
            devices = MobileDevice.objects.all()
        try:
            page = max(int(request.query_params.get("page", "1")), 1)
        except ValueError as error:
            raise SyncError("invalid_page", "Integer page required.") from error
        return Response({"count": devices.count(), "page": page, "page_size": 20,
                         "results": [device_data(device) for device in devices.order_by("created_at", "pk")[(page-1)*20:page*20]]})


class RevokeDeviceView(SyncAPIView):
    @extend_schema(request=RevokeDeviceSerializer, responses=schema.responses(schema.DEVICE))
    def post(self, request, device_id):
        data = validated(RevokeDeviceSerializer, request.data)
        with sync_boundary():
            self.recheck()
            device = MobileDevice.objects.select_for_update().filter(pk=device_id).first()
            if device is None or (device.user_id != request.user.pk and not request.user.has_admin_access):
                raise SyncError("device_not_found", "Device unavailable.", 404)
            if device.revoked_at is None:
                device.revoked_at = timezone.now()
                device.save(update_fields=["revoked_at"])
                MobileSession.objects.filter(device=device).update(revoked_at=device.revoked_at)
                MobileDeviceAudit.objects.create(device=device, actor=request.user, action="revoked", reason=data["reason"])
            return Response(device_data(device))


class CapabilitiesView(SyncAPIView):
    @extend_schema(parameters=[POULTRY_HEADER],responses=schema.responses({'anyOf':[schema.CAPABILITIES,poultry_schema.capabilities_schema()]}))
    def get(self, request):
        stream = stream_ready()
        capture = permits(request.user, OPERATORS)
        version = self.poultry_version()
        profile = operational_profile(version)
        response = {"protocol_version": 1, "schema_version": version, "policy_version": 1, "projection_version": version,
            "deployment_id": str(stream.deployment_id), "stream_epoch": str(stream.epoch), "device_id": str(self.device.pk),
            "server_time": json_value(timezone.now()), "scope_revision": scope_revision(request.user, version),
            "entities": list(profile.entities),
            "commands": {"poultry.mortality.record": {"available": capture, "payload_version": 1, "capability": "poultry.capture"},
                         "finance": {"available": False, "reason": "later_phase"}},
            "packs": [CURRENT_PACK, "batch:<uuid>"], "offline": {"operational_days": 7, "sensitive_hours": 24},
            "limits": {"push_bytes": settings.MOBILE_SYNC_PAGE_BYTES, "operations": 50, "dependencies": 20,
                       "page_rows": settings.MOBILE_SYNC_PAGE_ROWS, "page_bytes": settings.MOBILE_SYNC_PAGE_BYTES,
                       "group_rows": settings.MOBILE_SYNC_GROUP_ROWS, "group_bytes": settings.MOBILE_SYNC_GROUP_BYTES,
                       "snapshot_rows": settings.MOBILE_SYNC_SNAPSHOT_ROWS, "snapshot_bytes": settings.MOBILE_SYNC_SNAPSHOT_BYTES,
                       "active_snapshots_per_user": settings.MOBILE_SYNC_ACTIVE_SNAPSHOTS_PER_USER,
                       "entity_bytes": settings.MOBILE_SYNC_ENTITY_BYTES, "scan_rows": settings.MOBILE_SYNC_SCAN_ROWS},
            "retention": {"snapshot_hours": 24, "change_days": 90, "deduplication": "indefinite", "minimum_sequence": str(stream.minimum_sequence)}}
        if version == 2:
            from .commands.registry import registry_for_version
            from apps.poultry.models import BirdType, BroilerStrain, ChicksSource, FeedType, FeedSource, UnitMeasurement, DrugCategory, DrugVaccinationType
            response.update(packs=[POULTRY_PACK, "batch-v2:<uuid>"],
                commands={f"{kind}.{action}": {"available": permits(request.user, spec.roles), "payload_version": 1,
                    "capability": spec.capability, "mode": spec.mode} for (kind, action, _), spec in registry_for_version(version).items()})
            response["commands"]["finance"] = {"available": False, "reason": "later_phase"}
            response["lookups"] = {"version": 1, "choices": {key: [{"value": value, "label": label} for value, label in choice.choices]
                for key, choice in {"bird_type": BirdType, "broiler_strain": BroilerStrain, "source": ChicksSource,
                    "feed_type": FeedType, "feed_source": FeedSource, "unit_of_measurement": UnitMeasurement,
                    "drug_category": DrugCategory, "drug_vaccination_type": DrugVaccinationType}.items()},
                "treatment_quantity_unit": "recorded unit (legacy model; record actual unit in description)",
                "stock_linked_capture": False, "mortality_threshold_percent": str(settings.FINANCE_WARNING_THRESHOLDS["high_mortality_rate"])}
        return Response(response)


class BootstrapView(SyncAPIView):
    @extend_schema(request=BootstrapSerializer, responses=schema.responses(schema.BOOTSTRAP))
    def post(self, request):
        data = validated(BootstrapSerializer, request.data)
        with sync_boundary():
            self.recheck()
            if data.get("resume_snapshot_id"):
                snapshot, stream = owned_snapshot(data["resume_snapshot_id"], request.user, self.device)
                if snapshot.packs != sorted(data["packs"]):
                    raise SyncError("snapshot_pack_mismatch", "Resume must use the original pack list.", 409)
            else:
                snapshot = create_bootstrap(request.user, self.device, data["packs"])
                stream = stream_ready()
            return Response(bootstrap_manifest(snapshot, stream, request.user, self.device))


class BootstrapPageView(SyncAPIView):
    @extend_schema(parameters=[OpenApiParameter("cursor", str, required=True)], responses=schema.responses({'anyOf':[schema.PAGE,poultry_schema.PAGE]}))
    def get(self, request, snapshot_id):
        snapshot, stream = owned_snapshot(snapshot_id, request.user, self.device)
        return Response(bootstrap_page(snapshot, stream, request.user, self.device, request.query_params.get("cursor")))


class ChangesView(SyncAPIView):
    @extend_schema(parameters=[OpenApiParameter("cursor", str, required=True), OpenApiParameter("limit", int)], responses=schema.responses({'anyOf':[schema.CHANGES,poultry_schema.CHANGES]}))
    def get(self, request):
        return Response(pull_changes(request.user, self.device, request.query_params.get("cursor"), page_limit(request.query_params.get("limit"))))


class PushView(SyncAPIView):
    @extend_schema(parameters=[POULTRY_HEADER],request={'application/json':poultry_schema.push_schema()},responses=schema.responses(poultry_schema.PUSH_RESPONSE))
    def post(self, request):
        version = self.poultry_version()
        data = validated(PoultryPushSerializer if version == 2 else PushSerializer, request.data)
        if str(self.device.pk) != str(data["device_id"]):
            raise SyncError("foreign_device", "Body device does not match signed JWT.", 403)
        started, results = time.monotonic(), []
        for command in order_operations(data["operations"]):
            if time.monotonic() - started > 20:
                result = outcome(command, "retry_later", "request_budget_exceeded", "Retain this operation and retry it unchanged.")
                result["recovery_action"] = "retry_unchanged"
            else:
                result = execute(command, request.user, request.mobile_session, request.auth, version=version)
            results.append(result)
        return Response({"protocol_version": 1, "deployment_id": str(stream_ready().deployment_id),
                         "device_id": str(self.device.pk), "server_time": json_value(timezone.now()), "results": results})


class OperationView(SyncAPIView):
    @extend_schema(parameters=[POULTRY_HEADER], responses=schema.responses(poultry_schema.RESULT))
    def get(self, request, operation_id):
        version = self.poultry_version()
        receipt = SyncOperationReceipt.objects.filter(stream=stream_ready(), actor=request.user, device=self.device, operation_id=operation_id).first()
        if receipt is None:
            raise SyncError("operation_not_found", "No owned receipt found; retain original operation ID.", 404)
        require_receipt_profile(receipt.command, version)
        return Response(operational_result(receipt.result, version))


class OnlinePoultryView(SyncAPIView):
    """Foreground-only action. Never selected by the automatic upload worker."""
    @extend_schema(parameters=[POULTRY_HEADER],request={'application/json':poultry_schema.operation_schema()},responses=schema.responses(poultry_schema.RESULT))
    def post(self, request):
        if self.poultry_version() != 2:
            raise SyncError("unsupported_protocol", "Poultry projection 2 required.", 409)
        command = validated(PoultryOperationSerializer, request.data)
        return Response(execute(command, request.user, request.mobile_session, request.auth, mode="online", version=2))
