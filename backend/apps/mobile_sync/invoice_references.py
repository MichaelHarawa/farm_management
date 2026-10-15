"""Private online original-actor invoice parents, not a route or financial pack.

Catalog proves retained acceptance, NOT current payable/stock/cash. Detail adds
complete original purchase source/GL proof; still no current amount due. Reads
never prepare mappings, stamp legacy receipts, repair evidence or post effects.
Validated JWT authentication belongs to the upstream caller, as in the private
UUID command adapter. Current persisted binding/scope is checked here twice.
"""
from decimal import Decimal
import uuid

from django.core import signing
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import BigIntegerField, Func, TextField
from django.db.models.functions import Cast
from django.utils import timezone
from jsonschema import Draft7Validator, FormatChecker, ValidationError as SchemaError
from rest_framework.exceptions import ValidationError

from apps.finance.models import CostAllocation, FinancialCommandReceipt, JournalLine, SharedConsumableLot
from apps.finance.services import inventory_invoices as invoices
from apps.finance.services.inventory_invoice_payments import _invoice
from apps.finance.services.financial_capture import _canonical
from . import financial_references as funding, schema_invoice_references as wire
from .commands.financial import _gate
from .errors import SyncError
from .projections import canonical, checksum, json_value
from .transport import stream_ready
from .writers import sync_boundary


BASIS = "mobile-financial-invoice-reference-private-v1"
MAX_CATALOG_ROWS = 100
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_PROOF_BYTES = 8 * 1024 * 1024
MAX_CATALOG_BYTES = 512 * 1024
MAX_DETAIL_BYTES = 64 * 1024
PAGE_ROWS = 25
INVOICE = Draft7Validator(wire.INVOICE, format_checker=FormatChecker())
DETAIL = Draft7Validator(wire.DETAIL, format_checker=FormatChecker())
ID = Draft7Validator(wire.UUID, format_checker=FormatChecker())
VERSION = Draft7Validator(wire.DIGEST)


def _review():
    raise SyncError("invoice_reference_review_required", "Original invoice evidence needs controlled review; retain its original identity and do not replace or repair it automatically.", 503)


def _unavailable():
    raise SyncError("invoice_reference_unavailable", "No authorized original invoice reference. Retain physical evidence for review.", 404)


def _limit():
    raise SyncError("invoice_reference_limit", "Original invoice selection exceeds its bounded proof/display budget; no data was truncated. Request controlled scope review.", 413)


def _scope(stream, actor, session):
    return checksum({"basis": BASIS + "-scope", "funding_access": funding._scope(stream, actor, session),
        "access": "online_only_original_actor_finance_writer", "offline_cache_seconds": 0})


def _unchanged(stream, actor, session, token, scope):
    actor, session = funding._access(actor, session, token)
    if _scope(stream, actor, session) != scope:
        raise SyncError("invoice_reference_scope_changed", "Current invoice access changed; retain pending work and restart selection.", 409)


def _context(stream, session, scope):
    return {"invoice_reference_version": 1, "deployment_id": str(stream.deployment_id),
        "device_id": str(session.device_id), "scope_revision": scope, "server_time": json_value(timezone.now()),
        "access": "online_only_original_actor_finance_writer", "offline_cache_seconds": 0, "financial_uploads": False}


def _owned(actor):
    return FinancialCommandReceipt.objects.filter(actor=actor, command=invoices.COMMAND, completed_at__isnull=False)


def _bounded(query):
    # PostgreSQL measures the uncompressed JSON text BEFORE fetching its values.
    # A corrupted huge parent is not materialized merely to discover the limit.
    sizes = list(query.annotate(wire_bytes=Func(Cast("result", TextField()), function="OCTET_LENGTH",
        output_field=BigIntegerField())).order_by("pk").values("pk", "wire_bytes")[:MAX_CATALOG_ROWS + 1])
    if (len(sizes) > MAX_CATALOG_ROWS or any(row["wire_bytes"] > MAX_RECEIPT_BYTES for row in sizes)
            or sum(row["wire_bytes"] for row in sizes) > MAX_PROOF_BYTES):
        _limit()
    return list(query.filter(pk__in=[row["pk"] for row in sizes]).order_by("pk"))


def _row(receipt):
    """Immutable original acceptance is independent of current source balance."""
    try:
        result = receipt.result
        if (not isinstance(result, dict) or set(result) != {"invoice_group_id", "invoice_key", "capture",
                "children", "invoice_version", "invoice_anchor"} or result["invoice_group_id"] != str(receipt.pk)
                or receipt.request_hash != checksum({"actor": str(receipt.actor_id), "command": invoices.COMMAND,
                    "payload": result["capture"]}) or _canonical(invoices._capture(**result["capture"])) != result["capture"]
                or result["invoice_version"] != invoices._version(result)
                or result["invoice_anchor"] != invoices._anchor(result, receipt.pk, receipt.actor_id, receipt.request_hash)
                or not isinstance(result["children"], list) or len(result["children"]) != len(result["capture"]["lines"])):
            _review()
        # Stored sibling snapshots must have original IDs/capture correspondence.
        # Actual current child/source/GL proof is deliberately detail-only.
        for index, (child, line) in enumerate(zip(result["children"], result["capture"]["lines"], strict=True)):
            if (set(child) != {"operation_id", "actor_id", "request_hash", "completed_at", "result"}
                    or child["operation_id"] != str(invoices._child_id(receipt.pk, index))
                    or child["actor_id"] != str(receipt.actor_id) or child["completed_at"] is None
                    or child["request_hash"] != checksum({"actor": str(receipt.actor_id), "command": "inventory.receipt.record",
                        "payload": invoices._purchase_payload(result["capture"], line, receipt.pk, index)})
                    or child["result"]["invoice_group_id"] != str(receipt.pk) or child["result"]["invoice_line_index"] != index):
                _review()
        capture = result["capture"]
        row = {"invoice_group_id": str(receipt.pk), "invoice_version": result["invoice_version"],
            "supplier": capture["supplier"], "invoice_reference": capture["invoice_reference"], "purchase_date": capture["purchase_date"],
            "currency": capture["currency"], "original_total_purchase_cost": capture["total_purchase_cost"],
            "line_count": len(capture["lines"]), "recorded_at": json_value(receipt.completed_at),
            "evidence": "immutable_original_invoice", "balance_semantics": "original_purchase_not_current_outstanding"}
        INVOICE.validate(row)
        return row
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError, SchemaError):
        _review()


def invoice_reference_catalog(actor, session, token, *, cursor=None):
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    actor, session = funding._access(actor, session, token)
    with sync_boundary():
        actor, session = funding._access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        rows = [_row(receipt) for receipt in _bounded(_owned(actor))]
        if len(canonical(rows).encode("utf-8")) > MAX_CATALOG_BYTES:
            _limit()
        version = checksum({"basis": BASIS + "-catalog", "scope": scope, "rows": rows})
        start = 0
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError
                point = signing.loads(cursor, salt=BASIS + "-cursor", max_age=900)
                if (not isinstance(point, dict) or set(point) != {"version", "scope", "catalog", "last"}
                        or type(point["version"]) is not int or point["version"] != 1
                        or point["scope"] != scope or point["catalog"] != version):
                    raise ValueError
                start = next(index + 1 for index, row in enumerate(rows) if row["invoice_group_id"] == point["last"])
            except (signing.BadSignature, TypeError, ValueError, StopIteration):
                raise SyncError("invoice_catalog_changed", "Restart original invoice selection; retain all pending evidence unchanged.", 409) from None
        page = rows[start:start + PAGE_ROWS]
        next_cursor = signing.dumps({"version": 1, "scope": scope, "catalog": version,
            "last": page[-1]["invoice_group_id"]}, salt=BASIS + "-cursor") if start + len(page) < len(rows) else None
        _unchanged(stream, actor, session, token, scope)
        return {**_context(stream, session, scope), "catalog_version": version,
            "total_authorized_rows": len(rows), "rows": page, "next_cursor": next_cursor}


def invoice_reference_detail(invoice_id, invoice_version, actor, session, token):
    _gate("MOBILE_SYNC_FINANCIAL_REFERENCES")
    try:
        ID.validate(invoice_id)
        VERSION.validate(invoice_version)
    except SchemaError:
        raise SyncError("malformed_request", "Retain the exact original invoice UUID and version.") from None
    actor, session = funding._access(actor, session, token)
    with sync_boundary():
        actor, session = funding._access(actor, session, token)
        stream = stream_ready()
        scope = _scope(stream, actor, session)
        receipts = _bounded(_owned(actor).filter(pk=uuid.UUID(invoice_id)))
        if not receipts:
            _unavailable()
        receipt = receipts[0]
        row = _row(receipt)
        if row["invoice_version"] != invoice_version:
            raise SyncError("invoice_reference_changed", "Review the original invoice version; never silently replace the pending parent.", 409)
        try:
            # An intact inventory purchase has no cost allocations and exactly
            # two original purchase journal lines per child. Bound graph reads
            # BEFORE the existing proof materializes those relations; its full
            # correspondence checks still decide validity, never these counts.
            children = receipt.result["children"]
            if (CostAllocation.objects.filter(expenditure_id__in=[child["result"]["expenditure_id"] for child in children]).exists()
                    or JournalLine.objects.filter(journal_entry_id__in=[child["result"]["journal_id"] for child in children]).count() > 2 * len(children)):
                _review()
            parent = _invoice(receipt.pk, invoice_version)  # Existing complete original source/GL proof.
            lines = parent.result["capture"]["lines"]
            lots = {str(lot.pk): lot for lot in SharedConsumableLot.objects.filter(
                pk__in=[child["result"]["lot_id"] for child in parent.result["children"]])}
            projected = []
            for index, (line, child) in enumerate(zip(lines, parent.result["children"], strict=True)):
                lot = lots[child["result"]["lot_id"]]
                # Lot names/base unit are original purchase snapshots included
                # in the verified payable digest, not mutable item/location labels.
                evidence = child["result"].get("stock_quantity_evidence")
                projected.append({"invoice_line_index": index, "original_item_name": lot.item,
                    "original_location_name": lot.storage_location,
                    "captured_quantity": line["quantity"], "captured_unit": evidence["input_unit"] if evidence else lot.unit_of_measurement,
                    "base_quantity": format(lot.quantity_purchased, ".4f"), "base_unit": lot.unit_of_measurement,
                    "original_line_cost": line["total_purchase_cost"], "expiry_date": line["expiry_date"]})
            detail = {**_context(stream, session, scope), "invoice": row, "lines": projected,
                "proof": "original_invoice_sources_and_purchase_journals",
                "label_semantics": "original_purchase_names_and_values",
                "payment_authority": "none_revalidate_payables_and_cash_on_posting"}
            detail["detail_version"] = checksum({"basis": BASIS + "-detail", "scope": scope, "invoice": row, "lines": projected})
            DETAIL.validate(detail)
            if sum((Decimal(line["original_line_cost"]) for line in projected), Decimal("0.00")) != Decimal(row["original_total_purchase_cost"]):
                _review()
            if len(canonical(detail).encode("utf-8")) > MAX_DETAIL_BYTES:
                _limit()
        except (ObjectDoesNotExist, AttributeError, KeyError, TypeError, ValueError, ValidationError, SchemaError):
            _review()
        _unchanged(stream, actor, session, token, scope)
        return detail
