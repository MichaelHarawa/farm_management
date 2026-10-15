"""Private external-UUID adapter over the unchanged private posting bridge.

External capture + frozen resolution + inner/domain receipts commit together.
Replay proves the ORIGINAL linkage; it does not resolve today's sources again.
No route, capabilities, financial pack, native upload or API authentication here.
Upstream callers must supply already cryptographically validated JWTs.
"""
from copy import deepcopy
from datetime import timedelta
import time
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError

from apps.finance.models import FinancialCommandReceipt
from apps.finance.permissions import FINANCE_WRITE_ROLES
from apps.finance.services.financial_values import accounting_calendar
from apps.finance.services.inventory_invoices import COMMAND as INVOICE_COMMAND
from .. import financial_references as references
from ..errors import SyncError
from ..models import SyncEntity, SyncOperationReceipt
from ..policy import permits
from ..projections import canonical, checksum, json_value
from ..transport import stream_ready
from ..writers import sync_boundary, current_writer
from . import financial as bridge, financial_uuid_schema as wire
from .service import order_operations

PROFILE = "financial-supplier-payment-uuid-private-v1"
MAX_BYTES = 1024 * 1024
REQUEST_SECONDS = 20
OPERATIONS = Draft7Validator(wire.OPERATION, format_checker=FormatChecker())
ENVELOPES = Draft7Validator(wire.ENVELOPE, format_checker=FormatChecker())
RESULTS = Draft7Validator(wire.RESULT, format_checker=FormatChecker())
RESOLUTIONS = Draft7Validator(wire.RESOLUTION, format_checker=FormatChecker())


def _validate(value, validator):
    try:
        validator.validate(value)
        if len(canonical(value).encode("utf-8")) > MAX_BYTES:
            raise SyncError("request_too_large", "Retain original financial work; this candidate exceeds its byte budget.", 413)
        commands = value["operations"] if validator is ENVELOPES else [value]
        for command in commands:
            lines = [line for invoice in command["payload"]["invoices"] for line in invoice["lines"]]
            if len(lines) > 50 or sum(len(line["funding_allocations"]) for line in lines) > 100:
                raise SyncError("request_too_large", "Retain original financial work; aggregate line/funding budget exceeded.", 413)
        order_operations(commands)  # Whole request duplicate IDs/cycles, before any effect.
        return deepcopy(value)
    except (SchemaError, TypeError, ValueError):
        raise SyncError("malformed_request", "A strict financial UUID candidate is required. Retain unknown-outcome IDs and evidence.") from None


def inner_id(stream, actor, device, operation_id):
    return uuid.uuid5(stream.deployment_id, f"{PROFILE}:{actor.pk}:{device.pk}:{operation_id}")


def command_hash(stream, actor, device, command):
    return checksum({"basis": PROFILE, "deployment_id": str(stream.deployment_id),
        "actor_id": str(actor.pk), "device_id": str(device.pk), "operation": command})


def _result(command, fingerprint, status, code, *, fields=()):
    return {**bridge._outcome(command, fingerprint, status, code, fields=fields), "financial_command_version": 2}


def _seal(stream, actor, device, command, fingerprint, outcome, public, resolution):
    return checksum({"basis": PROFILE + "-result", "deployment_id": str(stream.deployment_id),
        "actor_id": str(actor.pk), "device_id": str(device.pk), "operation": command,
        "command_hash": fingerprint, "outcome": outcome, "public": public, "resolution": resolution})


def _store(state, actor, session, command, fingerprint, public, resolution=None):
    RESULTS.validate(public)
    if resolution is not None:
        RESOLUTIONS.validate(resolution)
    SyncOperationReceipt.objects.create(stream=state["stream"], actor=actor, device=session.device,
        operation_id=command["operation_id"], request_hash=fingerprint, command=command,
        outcome=public["outcome"], committed_at=parse_datetime(public["committed_at"]) if public["outcome"] == "accepted" else None,
        result={"profile": PROFILE, "public": public, "resolution": resolution,
            "anchor": _seal(state["stream"], actor, session.device, command, fingerprint, public["outcome"], public, resolution)})


def _review():
    raise SyncError("financial_receipt_review_required", "Original UUID/payment linkage needs controlled review. Retain its ID and evidence; do not repair or repost.", 503)


def _translate(command, resolution, stream, actor, session):
    """Pure replay-safe translation from retained evidence, not current sources."""
    RESOLUTIONS.validate(resolution)
    expected_id = str(inner_id(stream, actor, session.device, command["operation_id"]))
    if resolution["inner_operation_id"] != expected_id:
        _review()
    bindings = {}
    for row in resolution["funding"]:
        if row["reference_id"] in bindings or int(row["source_pk"]) > 9223372036854775807:
            _review()
        expected_version = checksum({"basis": references.BASIS + "-selection", "deployment_id": str(stream.deployment_id),
            "reference_id": row["reference_id"], "identity": row["identity"], "active": True})
        if str(references._id(stream, row["source_pk"])) != row["reference_id"] or expected_version != row["reference_version"]:
            _review()
        bindings[row["reference_id"]] = row
    payload, used = deepcopy(command["payload"]), set()
    for invoice in payload["invoices"]:
        for line in invoice["lines"]:
            seen = set()
            for row in line["funding_allocations"]:
                reference = row["funding_source"]
                if reference in seen or reference not in bindings or row.pop("funding_version") != bindings[reference]["reference_version"]:
                    _review()
                used.add(reference)
                seen.add(reference)
                row["funding_source"] = bindings[reference]["source_pk"]
    if used != set(bindings):
        _review()
    return {"financial_command_version": 1, "operation_id": expected_id, "command": wire.COMMAND,
        "captured_at": command["captured_at"], "depends_on": [], "payload": payload}


def _project(inner, command, fingerprint):
    return {**deepcopy(inner), "financial_command_version": 2,
        "operation_id": command["operation_id"], "command_hash": fingerprint}


def _retained(receipt, stream, actor, session):
    if receipt.device_id != session.device_id:
        raise SyncError("foreign_device", "Original financial operation belongs to another device.", 403)
    if not isinstance(receipt.command, dict) or receipt.command.get("financial_command_version") != 2 or receipt.command.get("command") != wire.COMMAND:
        raise SyncError("unsupported_protocol", "Original operation requires its original financial/operational profile; retain its ID.", 409)
    try:
        OPERATIONS.validate(receipt.command)
        stored = receipt.result
        if set(stored) != {"profile", "public", "resolution", "anchor"} or stored["profile"] != PROFILE:
            _review()
        public, resolution = stored["public"], stored["resolution"]
        RESULTS.validate(public)
        fingerprint = command_hash(stream, actor, session.device, receipt.command)
        if (receipt.request_hash != fingerprint or public["command_hash"] != fingerprint
                or public["operation_id"] != str(receipt.operation_id) or public["outcome"] != receipt.outcome
                or stored["anchor"] != _seal(stream, actor, session.device, receipt.command, fingerprint, receipt.outcome, public, resolution)):
            _review()
        if resolution is not None:
            expected = _translate(receipt.command, resolution, stream, actor, session)
            inner = SyncOperationReceipt.objects.get(stream=stream, actor=actor, operation_id=resolution["inner_operation_id"])
            if inner.command != expected:
                _review()
            original = bridge._retained(inner, stream, actor, session)
            if _project(original, receipt.command, fingerprint) != public:
                _review()
        else:
            early = {"permission_denied": ("permission_denied", ()),
                "invalid_supersession": ("conflict", ()), "supersession_already_accepted": ("conflict", ()),
                "future_capture": ("validation_failed", ()),
                "dependency_profile_mismatch": ("validation_failed", ()),
                "funding_reference_unavailable": ("conflict", ("funding_allocations",)),
                "funding_reference_changed": ("conflict", ("funding_allocations",)),
                "invoice_reference_unavailable": ("conflict", ("invoices",))}
            if public["code"] not in early:
                _review()
            status, fields = early[public["code"]]
            if public != _result(receipt.command, fingerprint, status, public["code"], fields=fields):
                _review()
        if receipt.outcome == "accepted":
            if json_value(receipt.committed_at) != public["committed_at"]:
                _review()
        elif receipt.outcome not in bridge.TERMINAL or receipt.committed_at is not None:
            _review()
        return deepcopy(public)
    except (ObjectDoesNotExist, SchemaError, KeyError, TypeError, ValueError, AttributeError):
        _review()


def _resolve(command, stream, actor, session, token):
    """Current access/proof only for a NEW effect, under the outer stream."""
    state = current_writer()
    if state is None or state["stream"].deployment_id != stream.deployment_id:
        raise SyncError("financial_boundary_required", "Resolution requires its original outer stream transaction.", 503)
    funding = {}
    for invoice in command["payload"]["invoices"]:
        # Deliberately narrow initial policy: the ORIGINAL invoice actor only.
        # Cross-writer/legacy adoption stays unsupported, including for admin.
        if not FinancialCommandReceipt.objects.filter(pk=invoice["invoice_group_id"], actor=actor,
                command=INVOICE_COMMAND, completed_at__isnull=False).exists():
            raise SyncError("invoice_reference_unavailable", "No authorized original invoice reference. Retain physical evidence for review.", 404)
        for line in invoice["lines"]:
            resolved = references.resolve_funding_references(line["funding_allocations"], actor, session, token)
            for observed, private in zip(line["funding_allocations"], resolved, strict=True):
                reference = observed["funding_source"]
                mapping = SyncEntity.objects.get(stream=stream, entity_type=references.ENTITY_TYPE, entity_uuid=reference)
                if private["funding_source"] != mapping.source_pk:
                    _review()
                binding = {"reference_id": reference, "reference_version": observed["funding_version"],
                    "source_pk": private["funding_source"], "identity": mapping.payload["identity"]}
                if reference in funding and funding[reference] != binding:
                    _review()
                funding[reference] = binding
    return {"inner_operation_id": str(inner_id(stream, actor, session.device, command["operation_id"])),
        "funding": sorted(funding.values(), key=lambda value: value["reference_id"])}


@accounting_calendar
def execute_uuid_command(command, actor, session, token):
    bridge._gate("MOBILE_SYNC_FINANCIAL_UUID_COMMANDS")
    command = _validate(command, OPERATIONS)
    actor, session = bridge._bound(actor, session, token)
    with sync_boundary(operation_id=command["operation_id"]) as state:
        actor, session = bridge._bound(actor, session, token)
        stream = stream_ready()
        fingerprint = command_hash(stream, actor, session.device, command)
        existing = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=command["operation_id"]).first()
        if existing is not None:
            result = _retained(existing, stream, actor, session)
            bridge._bound(actor, session, token)
            if existing.request_hash != fingerprint:
                return _result(command, fingerprint, "conflict", "idempotency_mismatch")
            return {**result, "outcome": "replayed"} if existing.outcome == "accepted" else result
        if not permits(actor, FINANCE_WRITE_ROLES):
            result = _result(command, fingerprint, "permission_denied", "permission_denied")
            _store(state, actor, session, command, fingerprint, result)
            return result
        if command.get("supersedes_operation_id"):
            predecessor = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                operation_id=command["supersedes_operation_id"]).first()
            if predecessor is None or predecessor.outcome not in bridge.TERMINAL:
                result = _result(command, fingerprint, "conflict", "invalid_supersession")
            else:
                _retained(predecessor, stream, actor, session)
                result = _result(command, fingerprint, "conflict", "supersession_already_accepted") if SyncOperationReceipt.objects.filter(
                    stream=stream, actor=actor, device=session.device, outcome="accepted",
                    command__supersedes_operation_id=command["supersedes_operation_id"]).exists() else None
            if result is not None:
                _store(state, actor, session, command, fingerprint, result)
                return result
        parents = list(SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
            operation_id__in=command["depends_on"]))
        if len(parents) != len(command["depends_on"]) or any(parent.outcome != "accepted" for parent in parents):
            return _result(command, fingerprint, "dependency_blocked", "dependency_blocked")
        for parent in parents:
            if parent.command.get("financial_command_version") != 2 or parent.command.get("command") != wire.COMMAND:
                result = _result(command, fingerprint, "validation_failed", "dependency_profile_mismatch")
                _store(state, actor, session, command, fingerprint, result)
                return result
            _retained(parent, stream, actor, session)
        if parse_datetime(command["captured_at"]) > timezone.now() + timedelta(minutes=5):
            result = _result(command, fingerprint, "validation_failed", "future_capture")
            _store(state, actor, session, command, fingerprint, result)
            return result
        if not all(getattr(settings, flag) for flag in ("MOBILE_SYNC_FINANCIAL_COMMANDS",
                "MOBILE_SYNC_FINANCIAL_REFERENCES", "FINANCE_INVENTORY_INVOICES")):
            return _result(command, fingerprint, "retry_later", "command_unavailable")
        private_id = inner_id(stream, actor, session.device, command["operation_id"])
        if (SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=private_id).exists()
                or FinancialCommandReceipt.objects.filter(pk=bridge.submission_id(stream, actor, session.device, private_id)).exists()):
            _review()  # Never adopt an independently posted inner intent/root.
        scope = references._scope(stream, actor, session)
        try:
            resolution = _resolve(command, stream, actor, session, token)
        except SyncError as error:
            code = str(error.detail["code"])
            if code not in {"funding_reference_unavailable", "funding_reference_changed", "invoice_reference_unavailable"}:
                raise
            result = _result(command, fingerprint, "conflict", code, fields=("funding_allocations",) if code.startswith("funding_") else ("invoices",))
            references._unchanged_access(stream, actor, session, token, scope)
            _store(state, actor, session, command, fingerprint, result)
            return result
        private = _translate(command, resolution, stream, actor, session)
        inner = bridge.execute_financial(private, actor, session, token)
        references._unchanged_access(stream, actor, session, token, scope)
        result = _project(inner, command, fingerprint)
        if inner["outcome"] in {"retry_later", "dependency_blocked"}:
            return result
        if inner["outcome"] == "replayed":
            _review()  # This new outer UUID must create its inner effect atomically.
        _store(state, actor, session, command, fingerprint, result, resolution)
        return result


def recover_uuid_command(operation_id, actor, session, token):
    bridge._gate("MOBILE_SYNC_FINANCIAL_READS")
    if not isinstance(operation_id, str) or not Draft7Validator(wire.UUID, format_checker=FormatChecker()).is_valid(operation_id):
        raise SyncError("malformed_request", "Canonical original operation UUID required.")
    actor, session = bridge._bound(actor, session, token)
    with sync_boundary():
        actor, session = bridge._bound(actor, session, token)
        stream = stream_ready()
        receipt = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=operation_id).first()
        if receipt is None:
            raise SyncError("operation_not_found", "No owned original receipt; retain unknown-outcome evidence, never invent a replacement ID.", 404)
        result = _retained(receipt, stream, actor, session)
        bridge._bound(actor, session, token)
        return result


def execute_uuid_envelope(envelope, actor, session, token):
    """Private candidate, per-operation atomicity (NOT whole-envelope atomicity)."""
    bridge._gate("MOBILE_SYNC_FINANCIAL_UUID_COMMANDS")
    envelope = _validate(envelope, ENVELOPES)
    actor, session = bridge._bound(actor, session, token)
    stream = stream_ready()
    if envelope["deployment_id"] != str(stream.deployment_id) or envelope["device_id"] != str(session.device_id):
        raise SyncError("foreign_environment", "Financial envelope must match the current bound deployment/device.", 403)
    deadline, results = time.monotonic() + REQUEST_SECONDS, []
    for command in order_operations(envelope["operations"]):
        actor, session = bridge._bound(actor, session, token)
        if time.monotonic() >= deadline:
            results.append(_result(command, command_hash(stream, actor, session.device, command), "retry_later", "request_budget_exceeded"))
        else:
            results.append(execute_uuid_command(command, actor, session, token))
    bridge._bound(actor, session, token)
    response = {"financial_protocol_version": 1, "deployment_id": str(stream.deployment_id),
        "device_id": str(session.device_id), "server_time": json_value(timezone.now()), "results": results}
    Draft7Validator(wire.RESPONSE, format_checker=FormatChecker()).validate(response)
    return response
