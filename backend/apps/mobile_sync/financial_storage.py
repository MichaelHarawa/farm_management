"""Private authorization for retaining own local payment evidence, NOT posting.

No HTTP route/capability/native hook. Upstream must cryptographically validate
the access JWT before calling. Existing online-only reference contracts grant
zero cache seconds and are deliberately unchanged. No source lookup or writes.
"""
from datetime import timedelta

from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker

from . import financial_references as references, schema_financial_storage as wire
from .commands.financial import _gate
from .errors import SyncError
from .projections import checksum, json_value
from .transport import stream_ready
from .writers import sync_boundary

PROFILE = "financial-evidence-private-v1"
TTL = 86400
COMMANDS = ["inventory.supplier_payment.record"]
VALID = Draft7Validator(wire.GRANT, format_checker=FormatChecker())


def _gates():
    _gate("MOBILE_SYNC_FINANCIAL_STORAGE")
    _gate("MOBILE_SYNC_FINANCIAL_UUID_COMMANDS")


def _scope(stream, actor, session):
    return checksum({"basis": PROFILE, "policy": 1,
        "access": references._scope(stream, actor, session),
        "session": str(session.pk), "epoch": str(stream.epoch),
        "commands": COMMANDS, "maximum_offline_seconds": TTL,
        "session_expires_at": json_value(session.expires_at),
        "reference_cache_seconds": 0, "financial_uploads": False})


def financial_storage_grant(actor, session, token):
    """Current finance writer only, before/after stream wait and at release.

    An offline device cannot learn immediate revocation. The eventual native
    consumer must persist online denials before reopening and enforce this
    independently bounded sensitive window, never the operational seven days.
    """
    _gates()  # All flags/vendor are checked before SQL.
    actor, session = references._access(actor, session, token)
    with sync_boundary():
        actor, session = references._access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        actor, session = references._access(actor, session, token)
        _gates()
        if _scope(stream_ready(), actor, session) != scope:
            raise SyncError("financial_storage_scope_changed", "Authorization changed; retain original protected evidence and sign in again.", 409)
        now = timezone.now()
        expiry = min(now + timedelta(seconds=TTL), session.expires_at)
        if expiry <= now:
            raise SyncError("device_revoked", "Current mobile session expired; retain protected evidence.", 403)
        result = {"financial_storage_version": 1, "profile": PROFILE,
            "deployment_id": str(stream.deployment_id), "actor_id": str(actor.pk),
            "device_id": str(session.device_id), "session_id": str(session.pk), "stream_epoch": str(stream.epoch),
            "scope_revision": scope, "server_time": json_value(now), "expires_at": json_value(expiry),
            "maximum_offline_seconds": TTL, "access": "local_evidence_only_not_posting_authority",
            "commands": list(COMMANDS), "reference_cache_seconds": 0, "financial_uploads": False}
        VALID.validate(result)
        return result
