"""Online receipt recovery, not financial command dispatch or replication.

Only the original actor may read a completed supplier-payment receipt, from
any of that actor's currently authorized bound devices on this deployment.
These IDs/hashes belong to FinancialCommandReceipt, NOT SyncOperationReceipt
or SyncEntity. Never adopt a legacy payment, create effects or repair evidence.
"""
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.exceptions import ValidationError

from apps.finance.models import FinancialCommandReceipt
from apps.finance.services import inventory_payment_summary as summaries
from apps.finance.services.inventory_referenced_payments import COMMAND
from .errors import SyncError
from .projections import canonical, checksum, json_value


MAX_RECEIPT_PROOF_BYTES = 8 * 1024 * 1024
REVIEW_MESSAGE = "Original payment evidence needs controlled review. Retain its original ID; do not submit a replacement payment."


def own_payment_receipt(operation_id, actor):
    receipt = FinancialCommandReceipt.objects.filter(pk=operation_id, actor=actor,
        command=COMMAND, completed_at__isnull=False).first()
    if receipt is None:
        # Identical missing/foreign/type responses. Not-found is NOT assurance
        # that an unknown payment can safely be sent under a different ID.
        raise SyncError("payment_receipt_not_found",
            "No owned completed receipt is available. Retain the original ID and evidence; do not create a replacement payment.", 404)
    return receipt


def retained_payment_status(receipt):
    """Prove permanent original acceptance without loading the source graph.

    Detailed source/GL proof belongs to the separate summary read. A graph or
    display failure never turns this intact immutable acceptance into rejection
    or permission to repost. This does NOT certify current balances or reversals.
    """
    try:
        result = receipt.result
        summaries._need(len(canonical(result).encode("utf-8")) <= MAX_RECEIPT_PROOF_BYTES)
        summaries._need(isinstance(result, dict) and set(result) == {
            "capture", "reference_key", "payments", "payment_version", "payment_anchor"})
        capture = result["capture"]
        summaries._need(isinstance(capture, dict) and set(capture) == {"currency", "payee",
            "payment_method", "external_reference", "payment_date", "total_payment_amount", "invoices", "notes"})
        summaries._stable_capture(capture)
        summaries._sealed(receipt, "phase6-inventory-referenced-payment")
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise SyncError("payment_receipt_review_required", REVIEW_MESSAGE, 503)
    return {"operation_id": str(receipt.pk), "identity_kind": "financial_command_receipt",
        "command": COMMAND, "outcome": "accepted", "evidence": "immutable_completed_receipt",
        "receipt_hash": receipt.request_hash, "payment_version": result["payment_version"],
        "recorded_at": json_value(receipt.completed_at),
        "balance_semantics": "historical_acceptance_not_current_balance",
        "recovery_action": "retain_original_id_do_not_resubmit"}


def retained_payment_summary(receipt):
    # Authorization is performed by the adapter before lookup and again after
    # proof under the stream boundary. The posting flag is intentionally NOT a
    # prerequisite for reading intact retained evidence after capture is disabled.
    retained_payment_status(receipt)
    try:
        result = summaries._summary(receipt)
        # The private candidate uses +00:00. Native wire instants are UTC Z;
        # project a fresh summary only, never rewrite original receipt evidence.
        result["recorded_at"] = json_value(receipt.completed_at)
        return result
    except summaries._SummaryLimit:
        raise SyncError("payment_summary_limit",
            "The original payment is accepted but exceeds the summary budget. Recover its status separately; retain its ID and request controlled detail review, never resubmit it.", 409)
    except (ObjectDoesNotExist, AttributeError, KeyError, IndexError, TypeError, ValueError, ValidationError):
        raise SyncError("payment_summary_review_required", REVIEW_MESSAGE, 503)


def financial_read_scope(user, device, stream):
    return checksum({"basis": "mobile-financial-reads-v1", "policy": 1,
        "deployment_id": str(stream.deployment_id), "device_id": str(device.pk),
        "actor_id": str(user.pk), "active": user.is_active, "superuser": user.is_superuser,
        "roles": sorted(user.roles.values_list("slug", flat=True)),
        "access": "online_only_original_actor", "offline_cache_seconds": 0,
        "reads": ["supplier_payment_status", "supplier_payment_summary"]})
