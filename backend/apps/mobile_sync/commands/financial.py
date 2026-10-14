"""Private device-bound financial command bridge; no HTTP route or registry.

One explicit supplier-payment service, not generic CRUD. Posting, financial
receipt, permanent bound command evidence and bounded acceptance commit together.
Publication/authorized UUID references and native finance gates still block uploads.
Only authenticated upstream callers may supply the already validated JWT.
"""
from copy import deepcopy
from datetime import timedelta
from types import MappingProxyType
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, ValidationError as ModelValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaValidationError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.finance.models import FinancialCommandReceipt
from apps.finance.permissions import FINANCE_READ_ROLES, FINANCE_WRITE_ROLES
from apps.finance.services.inventory_referenced_payments import record_referenced_inventory_payment
from apps.finance.services.financial_values import accounting_calendar
from ..authentication import check_binding
from ..errors import SyncError
from ..financial_reads import retained_payment_status
from ..models import SyncOperationReceipt
from ..policy import permits
from ..projections import canonical, checksum, json_value
from ..transport import stream_ready
from ..writers import sync_boundary
from . import financial_schema as wire


MAX_COMMAND_BYTES = 1024 * 1024
MAX_FUNDING_ROWS = 100
PROFILE = "financial-supplier-payment-private-v1"
TERMINAL = {"validation_failed", "permission_denied", "period_locked", "conflict"}
OPERATIONS = Draft7Validator(wire.OPERATION, format_checker=FormatChecker())
RESULTS = Draft7Validator(wire.RESULT, format_checker=FormatChecker())
# Deliberately independent of REGISTRY, operational profiles and capabilities.
REGISTRY = MappingProxyType({wire.COMMAND: record_referenced_inventory_payment})


def _gate(setting):
    if not getattr(settings, setting) or not settings.MOBILE_SYNC_ENABLED or not settings.MOBILE_SYNC_CAPTURE:
        raise SyncError("financial_bridge_disabled", "This private financial bridge is disabled; retain original work.", 503)
    if connection.vendor != "postgresql":
        raise SyncError("financial_bridge_disabled", "Verified PostgreSQL is required.", 503)


def _validate(command):
    try:
        OPERATIONS.validate(command)
        if len(canonical(command).encode("utf-8")) > MAX_COMMAND_BYTES:
            raise SyncError("request_too_large", "Retain the original evidence; the private command exceeds its byte budget.", 413)
        payload = command["payload"]
        lines = [line for invoice in payload["invoices"] for line in invoice["lines"]]
        if len(lines) > 50 or sum(len(line["funding_allocations"]) for line in lines) > MAX_FUNDING_ROWS:
            raise SyncError("request_too_large", "Retain the original evidence; aggregate line/funding budgets are exceeded.", 413)
        if any(int(row["funding_source"]) > 9223372036854775807 for line in lines for row in line["funding_allocations"]):
            raise SchemaValidationError("Invalid private source identifier")
        return deepcopy(command)
    except (SchemaValidationError, TypeError, ValueError):
        raise SyncError("malformed_request", "A strict private supplier-payment command is required; no financial evidence was recorded.") from None


def _bound(actor, session, token):
    claim = settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")
    if str(token.get(claim)) != str(actor.pk):
        raise SyncError("foreign_actor", "Authenticated actor does not match this bound request.", 403)
    try:
        current = get_user_model().objects.get(pk=actor.pk)
    except ObjectDoesNotExist:
        raise SyncError("permission_denied", "Original principal is unavailable; retain protected work.", 403) from None
    try:
        bound = check_binding(token, current.pk)
    except PermissionDenied:
        # Authentication/session denial is NOT an action-level terminal receipt.
        # In particular, revocation during posting rolls everything back without
        # persisting now-restricted command content.
        raise SyncError("device_revoked", "Current mobile binding is unavailable; retain protected original work.", 403) from None
    if bound is None or session is None or bound.pk != session.pk or bound.device_id != session.device_id:
        raise SyncError("device_required", "The original current bound session is required.", 403)
    if not permits(current, FINANCE_READ_ROLES):
        raise SyncError("permission_denied", "Current financial access is required; protected original work is retained.", 403)
    return current, bound


def submission_id(stream, actor, device, operation_id):
    """Separate durable namespaces; never adopt a legacy UUID as this effect."""
    return uuid.uuid5(stream.deployment_id,
        f"mobile-financial-supplier-payment-v1:{actor.pk}:{device.pk}:{operation_id}")


def command_hash(stream, actor, device, command):
    return checksum({"basis": PROFILE, "deployment_id": str(stream.deployment_id),
        "actor_id": str(actor.pk), "device_id": str(device.pk), "operation": command})


def _outcome(command, fingerprint, status, code, *, fields=()):
    result = {"financial_command_version": 1, "operation_id": command["operation_id"], "command": wire.COMMAND,
        "command_hash": fingerprint, "outcome": status, "code": code,
        "message": wire.REVIEW_MESSAGE,
        "field_errors": {key: wire.FIELD_MESSAGE for key in wire.FIELDS if key in fields},
        "recovery_action": "wait_for_dependency" if status == "dependency_blocked" else
            "retry_unchanged" if status == "retry_later" else
            "recover_original_operation" if code == "idempotency_mismatch" else "review_and_supersede"}
    return result


def _anchor(stream, actor, device, operation_id, fingerprint, outcome, public):
    return checksum({"basis": PROFILE + "-result", "deployment_id": str(stream.deployment_id),
        "actor_id": str(actor.pk), "device_id": str(device.pk), "operation_id": str(operation_id),
        "command_hash": fingerprint, "outcome": outcome, "public": public})


def _store(state, actor, session, command, fingerprint, result):
    RESULTS.validate(result)
    stored = {"profile": PROFILE, "public": result, "anchor": _anchor(state["stream"], actor,
        session.device, command["operation_id"], fingerprint, result["outcome"], result)}
    SyncOperationReceipt.objects.create(stream=state["stream"], actor=actor, device=session.device,
        operation_id=command["operation_id"], request_hash=fingerprint, command=command,
        outcome=result["outcome"], result=stored,
        committed_at=parse_datetime(result["committed_at"]) if result["outcome"] == "accepted" else None)


def _retained(receipt, stream, actor, session):
    if receipt.device_id != session.device_id:
        raise SyncError("foreign_device", "Original command belongs to another device; retain it for controlled recovery.", 403)
    if not isinstance(receipt.command, dict):
        raise SyncError("financial_receipt_review_required", "Original command requires controlled review; retain its ID.", 503)
    if receipt.command.get("financial_command_version") != 1 or receipt.command.get("command") != wire.COMMAND:
        raise SyncError("unsupported_protocol", "Original operation requires its own supported profile; retain its ID.", 409)
    try:
        OPERATIONS.validate(receipt.command)
        public = receipt.result["public"]
        RESULTS.validate(public)
        expected = command_hash(stream, actor, session.device, receipt.command)
        if (set(receipt.result) != {"profile", "public", "anchor"} or receipt.result["profile"] != PROFILE
                or receipt.request_hash != expected or public["command_hash"] != expected
                or public["operation_id"] != str(receipt.operation_id) or public["outcome"] != receipt.outcome
                or receipt.result["anchor"] != _anchor(stream, actor, session.device, receipt.operation_id,
                    expected, receipt.outcome, public)):
            raise ValueError
        if receipt.outcome == "accepted":
            if ("transaction_id" not in public or public["field_errors"]
                    or public["recovery_action"] != "retain_receipt_never_resubmit"):
                raise ValueError
            root_id = submission_id(stream, actor, session.device, receipt.operation_id)
            root = FinancialCommandReceipt.objects.get(pk=root_id, actor=actor, command=wire.COMMAND,
                completed_at__isnull=False)
            original = retained_payment_status(root)
            _check_capture(receipt.command, root)
            proof = public["financial_evidence"]
            if (public["code"] != "accepted" or proof != _evidence(original)
                    or json_value(receipt.committed_at) != public["committed_at"]):
                raise ValueError
        elif receipt.outcome not in TERMINAL or receipt.committed_at is not None or any(
                key in public for key in ("financial_evidence", "transaction_id", "committed_at")):
            raise ValueError
        return deepcopy(public)
    except (ObjectDoesNotExist, SchemaValidationError, KeyError, TypeError, ValueError, AttributeError):
        raise SyncError("financial_receipt_review_required",
            "Original command evidence is inconsistent. Retain its ID and physical evidence; never recreate its payment.", 503) from None


def _evidence(status):
    return {"submission_id": status["operation_id"], "receipt_hash": status["receipt_hash"],
        "payment_version": status["payment_version"], "recorded_at": status["recorded_at"],
        "basis": "immutable_completed_financial_receipt_not_current_balance"}


def _check_capture(command, root):
    """Link exact frozen command to the domain receipt without new-date rules.

    Only documented representation changes (private PK text -> retained integer,
    header fields copied to nested captures, existing service text trimming) are
    compared. No money/date/funding arithmetic, inferred splits or resubmission.
    """
    captured = deepcopy(root.result["capture"])
    expected = deepcopy(command["payload"])
    for field in ("payee", "external_reference", "notes"):
        expected[field] = expected[field].strip()
    for invoice in captured["invoices"]:
        if (invoice.pop("currency") != captured["currency"]
                or invoice.pop("payment_date") != captured["payment_date"] or invoice.pop("notes") != ""):
            raise SyncError("financial_receipt_review_required", "Original capture linkage is inconsistent; retain its ID.", 503)
        for line in invoice["lines"]:
            for row in line["funding_allocations"]:
                row["funding_source"] = str(row["funding_source"])
    if captured != expected:
        raise SyncError("financial_receipt_review_required", "Original command and financial capture differ; retain the original evidence, never replace its payment.", 503)


def _rejection(command, fingerprint, error):
    if isinstance(error, PermissionDenied):
        return _outcome(command, fingerprint, "permission_denied", "permission_denied")
    details = getattr(error, "message_dict", None) or getattr(error, "detail", None) or {}
    keys = set(details) if isinstance(details, dict) else set()
    status, code = ("period_locked", "period_locked") if "period_locked" in keys else (
        ("conflict", "possible_duplicate") if "possible_duplicate" in keys else ("validation_failed", "invalid_business_event"))
    # Never return raw service messages, which may contain hidden source/owner
    # identities or captured notes. Named fields have fixed review instructions.
    return _outcome(command, fingerprint, status, code,
        fields=["payment_date"] if status == "period_locked" else keys)


@accounting_calendar
def execute_financial(command, actor, session, token):
    """Private validated candidate only; no public endpoint calls this function."""
    _gate("MOBILE_SYNC_FINANCIAL_COMMANDS")
    command = _validate(command)
    actor, session = _bound(actor, session, token)  # No money lookup before access.
    with sync_boundary(operation_id=command["operation_id"]) as state:
        actor, session = _bound(actor, session, token)  # Also after waiting for stream.
        stream_ready()
        stream = state["stream"]
        fingerprint = command_hash(stream, actor, session.device, command)
        existing = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=command["operation_id"]).first()
        if existing is not None:
            result = _retained(existing, stream, actor, session)
            actor, session = _bound(actor, session, token)
            if existing.request_hash != fingerprint:
                return _outcome(command, fingerprint, "conflict", "idempotency_mismatch")
            if existing.outcome == "accepted":
                result["outcome"] = "replayed"
            return result
        if not permits(actor, FINANCE_WRITE_ROLES):
            result = _outcome(command, fingerprint, "permission_denied", "permission_denied")
        else:
            result = None
        if result is None and command.get("supersedes_operation_id"):
            predecessor = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                operation_id=command["supersedes_operation_id"]).first()
            if predecessor is None or predecessor.outcome not in TERMINAL:
                result = _outcome(command, fingerprint, "conflict", "invalid_supersession")
            else:
                _retained(predecessor, stream, actor, session)
                if SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                        outcome="accepted", command__supersedes_operation_id=command["supersedes_operation_id"]).exists():
                    result = _outcome(command, fingerprint, "conflict", "supersession_already_accepted")
        if result is None:
            dependencies = list(SyncOperationReceipt.objects.filter(stream=stream, actor=actor, device=session.device,
                operation_id__in=command["depends_on"]))
            if len(dependencies) != len(command["depends_on"]) or any(row.outcome != "accepted" for row in dependencies):
                return _outcome(command, fingerprint, "dependency_blocked", "dependency_blocked")
            for parent in dependencies:
                if parent.command.get("command") != wire.COMMAND or parent.command.get("financial_command_version") != 1:
                    result = _outcome(command, fingerprint, "validation_failed", "dependency_profile_mismatch")
                    break
                _retained(parent, stream, actor, session)
        if result is None and parse_datetime(command["captured_at"]) > timezone.now() + timedelta(minutes=5):
            result = _outcome(command, fingerprint, "validation_failed", "future_capture")
        if result is None:
            if not settings.FINANCE_INVENTORY_INVOICES:
                return _outcome(command, fingerprint, "retry_later", "command_unavailable")
            root_id = submission_id(stream, actor, session.device, command["operation_id"])
            # Never adopt independently posted or restored financial evidence.
            # A committed root without its command receipt requires investigation.
            if FinancialCommandReceipt.objects.filter(pk=root_id).exists():
                raise SyncError("financial_receipt_review_required", "Independent original financial evidence needs review; do not adopt or re-post it.", 503)
            try:
                with transaction.atomic():
                    _, created = REGISTRY[wire.COMMAND](submission_id=root_id, user=actor, **command["payload"])
                    if not created:
                        raise SyncError("financial_receipt_review_required", "Original financial evidence cannot be adopted by this command.", 503)
                    root = FinancialCommandReceipt.objects.get(pk=root_id, actor=actor, command=wire.COMMAND,
                        completed_at__isnull=False)
                    status = retained_payment_status(root)
                    _check_capture(command, root)
                    # No role/session mutation during a slow service may survive
                    # with a success receipt. All source effects roll back first.
                    actor, session = _bound(actor, session, token)
                    if not permits(actor, FINANCE_WRITE_ROLES):
                        raise PermissionDenied("Current financial write access was removed.")
                    result = _outcome(command, fingerprint, "accepted", "accepted")
                    result.update(message=wire.ACCEPTED_MESSAGE,
                        recovery_action="retain_receipt_never_resubmit", financial_evidence=_evidence(status),
                        transaction_id=str(state["transaction_id"]), committed_at=json_value(timezone.now()))
                    _store(state, actor, session, command, fingerprint, result)
                    return result
            except (ValidationError, ModelValidationError, PermissionDenied) as error:
                # Nested rollback preserves the exact submitted command only.
                stream.refresh_from_db()
                state["batches"].clear()
                state["changes"].clear()
                state["entity_ids"].clear()
                result = _rejection(command, fingerprint, error)
        _store(state, actor, session, command, fingerprint, result)
        return result


def recover_financial(operation_id, actor, session, token):
    """Private original-device receipt recovery even when new capture is off."""
    _gate("MOBILE_SYNC_FINANCIAL_READS")
    actor, session = _bound(actor, session, token)
    with sync_boundary():
        actor, session = _bound(actor, session, token)
        stream = stream_ready()
        receipt = SyncOperationReceipt.objects.filter(stream=stream, actor=actor, operation_id=operation_id).first()
        if receipt is None:
            raise SyncError("operation_not_found", "No owned receipt; retain original ID/evidence, not a replacement payment.", 404)
        result = _retained(receipt, stream, actor, session)
        _bound(actor, session, token)
        return result
