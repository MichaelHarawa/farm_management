"""Immutable, explicit unit setup in permanent command evidence, NOT a route.

Definitions use the existing append-only FinancialCommandReceipt as their event
source, rather than adopting mutable legacy InventoryUnitConversion rows. No
schema/backfill or inferred supplier pack/clinical dosage policy. A future master
adapter must require fresh online management confirmation and positive scope.
"""
import uuid

from django.conf import settings
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import FinancialCommandReceipt
from ..permissions import FINANCE_MANAGEMENT_ROLES
from .financial_capture import _canonical, _identifier, _submission, _text
from .financial_values import exact_decimal


COMMAND = "inventory.unit_conversion.configure"
MESSAGE = "Original item-specific unit definition is missing, ambiguous or changed; preserve the captured quantity for controlled review."
DEFINITION_KEYS = frozenset({"configuration_id", "item_id", "item_sku", "costing_method",
    "quantity_unit", "base_unit", "to_base_multiplier", "reason"})


def _refuse():
    raise ValidationError({"unit_conversion": MESSAGE})


def require_setup_enabled():
    if not settings.FINANCE_INVENTORY_UNIT_CONVERSIONS:
        raise ValidationError({"unit_conversion": "Controlled unit setup/use is not enabled on this deployment."})


def conversion_reference(value):
    if value is None:
        return None
    if not isinstance(value, (str, uuid.UUID)):
        _refuse()
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        _refuse()


def _payload(*, item_id, quantity_unit, base_unit, to_base_multiplier, reason):
    return dict(item_id=str(item_id), quantity_unit=quantity_unit, base_unit=base_unit,
        to_base_multiplier=to_base_multiplier, reason=reason)


def _fingerprint(actor_id, payload):
    return checksum({"actor": str(actor_id), "command": COMMAND, "payload": _canonical(payload)})


def _version(definition):
    return checksum({"basis": "phase6-item-unit-definition-v1", "definition": definition})


def _anchor(result, submission_id, actor_id, request_hash):
    return checksum({"basis": "phase6-item-unit-receipt-v1", "submission_id": str(submission_id),
        "command": COMMAND, "actor_id": str(actor_id), "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "definition_anchor"}})


def configure_inventory_unit(*, submission_id, user, item_id, quantity_unit, base_unit,
                             to_base_multiplier, reason):
    """Internal management-only immutable setup; no stock/cash/GL effects."""
    require_setup_enabled()
    from .inventory_capture import _item, _required_text
    item_id = _identifier(item_id, "item_id")
    quantity_unit = _required_text(quantity_unit, "quantity_unit", 40)
    base_unit = _required_text(base_unit, "base_unit", 40)
    reason = _required_text(reason, "reason", 255)
    multiplier = exact_decimal(to_base_multiplier, field="to_base_multiplier",
        scale=6, max_digits=18, positive=True)
    payload = _payload(item_id=item_id, quantity_unit=quantity_unit, base_unit=base_unit,
        to_base_multiplier=multiplier, reason=reason)

    def effect(actor):
        item = _item(item_id)
        if base_unit != item.base_unit:
            raise ValidationError({"base_unit": "The observed definition must match the current item base unit; do not reinterpret it."})
        if quantity_unit == base_unit or quantity_unit in {"g", "kg"}:
            raise ValidationError({"quantity_unit": "Base-unit identity and fixed grams/kilograms cannot be overridden by a custom definition."})
        # Item mutex serializes competing setup across actors/operation IDs.
        # Incomplete/ambiguous prior evidence also requires review, not adoption.
        if FinancialCommandReceipt.objects.filter(command=COMMAND, result__item_id=str(item_id),
                result__quantity_unit=quantity_unit).exists():
            raise ValidationError({"unit_conversion": "This item/unit already has retained setup evidence; use its original definition or controlled review."})
        definition = {"configuration_id": conversion_reference(submission_id),
            "item_id": str(item.pk), "item_sku": item.sku, "costing_method": item.costing_method,
            "quantity_unit": quantity_unit, "base_unit": base_unit,
            "to_base_multiplier": format(multiplier, "f"), "reason": reason}
        result = {**definition, "definition_version": _version(definition)}
        result["definition_anchor"] = _anchor(result, result["configuration_id"], actor.pk,
            _fingerprint(actor.pk, payload))
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=payload, roles=FINANCE_MANAGEMENT_ROLES, effect=effect)


def read_inventory_unit(reference, item, unit, *, require_current=False):
    """Retain historical definitions; new captures require the current tip."""
    from .inventory_conversion_supersession import read_definition_chain
    return read_definition_chain(reference, item, unit, require_current=require_current)


def _read_original_inventory_unit(reference, item, unit):
    """Under item mutex. Proof reads remain valid after the setup flag is off.

    New custom effects check the flag separately. No lookup touches receipt
    tables on old base/SI-only paths; no mutable conversion row is read.
    """
    reference = conversion_reference(reference)
    if reference is None:
        _refuse()
    receipt = FinancialCommandReceipt.objects.filter(pk=reference, command=COMMAND).first()
    if receipt is None or receipt.completed_at is None or not isinstance(receipt.result, dict):
        _refuse()
    result = receipt.result
    if set(result) != DEFINITION_KEYS | {"definition_version", "definition_anchor"}:
        _refuse()
    definition = {key: result[key] for key in DEFINITION_KEYS}
    if (definition["configuration_id"] != reference or definition["item_id"] != str(item.pk)
            or definition["item_sku"] != item.sku or definition["costing_method"] != item.costing_method
            or definition["quantity_unit"] != unit or definition["base_unit"] != item.base_unit
            or unit == item.base_unit or unit in {"g", "kg"}
            or result["definition_version"] != _version(definition)):
        _refuse()
    try:
        multiplier = exact_decimal(definition["to_base_multiplier"], field="to_base_multiplier",
            scale=6, max_digits=18, positive=True)
        reason = _text(definition["reason"], "reason", 255)
        if not reason or reason != definition["reason"] or format(multiplier, "f") != definition["to_base_multiplier"]:
            _refuse()
        payload = _payload(item_id=item.pk, quantity_unit=unit, base_unit=item.base_unit,
            to_base_multiplier=multiplier, reason=reason)
        if (receipt.request_hash != _fingerprint(receipt.actor_id, payload)
                or result["definition_anchor"] != _anchor(result, receipt.pk, receipt.actor_id, receipt.request_hash)):
            _refuse()
    except (ValidationError, TypeError, ValueError):
        _refuse()
    candidates = list(FinancialCommandReceipt.objects.filter(command=COMMAND,
        result__item_id=str(item.pk), result__quantity_unit=unit).order_by("pk").values_list("pk", flat=True)[:2])
    if len(candidates) != 1 or str(candidates[0]) != reference:
        _refuse()
    return result, multiplier
