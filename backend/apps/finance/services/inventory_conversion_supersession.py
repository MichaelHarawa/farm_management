"""Private prospective unit correction; NOT an online adapter or wire command.

Append one immutable replacement linked to the exact current definition. Never
edit a definition, revalue stock or reinterpret an earlier captured quantity.
Both proof and prospective use validate the bounded, unbranched retained chain
under the item mutex. Fresh device/scope/online confirmation remains a future
adapter requirement, not an authority granted by these internal functions.
"""
import re

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.mobile_sync.projections import checksum
from ..models import FinancialCommandReceipt
from ..permissions import FINANCE_MANAGEMENT_ROLES
from .financial_capture import _canonical, _identifier, _submission, _text
from .financial_values import exact_decimal
from .inventory_conversion_setup import (COMMAND as SETUP_COMMAND, DEFINITION_KEYS,
    _read_original_inventory_unit, _refuse, _version, conversion_reference, require_setup_enabled)


COMMAND = "inventory.unit_conversion.supersede"
MAX_REPLACEMENTS = 50
PREVIOUS_KEYS = frozenset({"operation_id", "actor_id", "command", "request_hash",
    "completed_at", "result_hash", "definition_version"})


def _snapshot(receipt):
    return dict(operation_id=str(receipt.pk), actor_id=str(receipt.actor_id), command=receipt.command,
        request_hash=receipt.request_hash, completed_at=_canonical(receipt.completed_at),
        result_hash=checksum(receipt.result), definition_version=receipt.result["definition_version"])


def _payload(*, item_id, previous_definition_id, previous_definition_version, to_base_multiplier, reason):
    return dict(item_id=str(item_id), previous_definition_id=previous_definition_id,
        previous_definition_version=previous_definition_version,
        to_base_multiplier=to_base_multiplier, reason=reason)


def _fingerprint(actor_id, payload):
    return checksum({"actor": str(actor_id), "command": COMMAND, "payload": _canonical(payload)})


def _anchor(result, receipt_id, actor_id, request_hash):
    return checksum({"basis": "phase6-item-unit-supersession-v1", "operation_id": str(receipt_id),
        "actor_id": str(actor_id), "command": COMMAND, "request_hash": request_hash,
        "result": {key: value for key, value in result.items() if key != "definition_anchor"}})


def _replacement(receipt, previous, item, unit):
    result = receipt.result
    if (receipt.command != COMMAND or receipt.completed_at is None or not isinstance(result, dict)
            or set(result) != DEFINITION_KEYS | {"definition_version", "definition_anchor", "previous_definition"}
            or result["previous_definition"] != _snapshot(previous)):
        _refuse()
    definition = {key: result[key] for key in DEFINITION_KEYS}
    if (definition["configuration_id"] != str(receipt.pk) or definition["item_id"] != str(item.pk)
            or definition["item_sku"] != item.sku or definition["costing_method"] != item.costing_method
            or definition["quantity_unit"] != unit or definition["base_unit"] != item.base_unit
            or unit == item.base_unit or unit in {"g", "kg"}
            or result["definition_version"] != _version(definition)):
        _refuse()
    try:
        multiplier = exact_decimal(definition["to_base_multiplier"], field="to_base_multiplier",
            scale=6, max_digits=18, positive=True)
        reason = _text(definition["reason"], "reason", 255)
        if (not reason or reason != definition["reason"]
                or format(multiplier, "f") != definition["to_base_multiplier"]
                or definition["to_base_multiplier"] == previous.result["to_base_multiplier"]):
            _refuse()
        payload = _payload(item_id=item.pk, previous_definition_id=str(previous.pk),
            previous_definition_version=previous.result["definition_version"],
            to_base_multiplier=multiplier, reason=reason)
        if (receipt.request_hash != _fingerprint(receipt.actor_id, payload)
                or result["definition_anchor"] != _anchor(result, receipt.pk, receipt.actor_id, receipt.request_hash)):
            _refuse()
    except (ValidationError, TypeError, ValueError):
        _refuse()
    return result, multiplier


def _chain(item, unit):
    roots = list(FinancialCommandReceipt.objects.filter(command=SETUP_COMMAND,
        result__item_id=str(item.pk), result__quantity_unit=unit).order_by("pk")[:2])
    if len(roots) != 1:
        _refuse()
    original = roots[0]
    definition, multiplier = _read_original_inventory_unit(str(original.pk), item, unit)
    # Also find retained links to this root even if their top-level markers were
    # damaged. Ordinary receipt mutations are forbidden; privileged corruption
    # fixtures exercise fail-closed evidence reads, not SQL-level immutability.
    replacements = list(FinancialCommandReceipt.objects.filter(
        Q(command=COMMAND, result__item_id=str(item.pk), result__quantity_unit=unit)
        | Q(result__previous_definition__isnull=False, result__item_id=str(item.pk), result__quantity_unit=unit)
        | Q(result__previous_definition__operation_id=str(original.pk)))
        .order_by("pk")[:MAX_REPLACEMENTS + 1])
    if len(replacements) > MAX_REPLACEMENTS:
        _refuse()
    successors = {}
    for receipt in replacements:
        result = receipt.result
        previous = result.get("previous_definition") if isinstance(result, dict) else None
        if not isinstance(previous, dict) or set(previous) != PREVIOUS_KEYS:
            _refuse()
        prior_id = conversion_reference(previous["operation_id"])
        if prior_id is None or prior_id != previous["operation_id"] or prior_id in successors:
            _refuse()
        successors[prior_id] = receipt
    chain = [(original, definition, multiplier)]
    seen = {str(original.pk)}
    while str(chain[-1][0].pk) in successors:
        previous = chain[-1][0]
        receipt = successors[str(previous.pk)]
        if str(receipt.pk) in seen:
            _refuse()
        definition, multiplier = _replacement(receipt, previous, item, unit)
        chain.append((receipt, definition, multiplier))
        seen.add(str(receipt.pk))
    if len(chain) != len(replacements) + 1:
        _refuse()  # Orphan/cycle/another root is review, never last-write-wins.
    return chain


def read_definition_chain(reference, item, unit, *, require_current=False):
    reference = conversion_reference(reference)
    if reference is None:
        _refuse()
    chain = _chain(item, unit)
    if require_current and reference != str(chain[-1][0].pk):
        raise ValidationError({"unit_conversion": "This definition was superseded. Preserve the observed quantity and request review; never substitute the new factor automatically."})
    for receipt, definition, multiplier in chain:
        if str(receipt.pk) == reference:
            return definition, multiplier
    _refuse()


def supersede_inventory_unit(*, submission_id, user, item_id, previous_definition_id,
                            previous_definition_version, to_base_multiplier, reason):
    """One prospective factor replacement; no inventory/cash/payable/GL effect."""
    require_setup_enabled()
    from .inventory_capture import _item, _required_text
    item_id = _identifier(item_id, "item_id")
    previous_id = conversion_reference(previous_definition_id)
    if previous_id is None:
        _refuse()
    if not isinstance(previous_definition_version, str) or not re.fullmatch(r"[0-9a-f]{64}", previous_definition_version):
        raise ValidationError({"previous_definition_version": "Retain the exact current accepted definition version."})
    multiplier = exact_decimal(to_base_multiplier, field="to_base_multiplier", scale=6, max_digits=18, positive=True)
    reason = _required_text(reason, "reason", 255)
    payload = _payload(item_id=item_id, previous_definition_id=previous_id,
        previous_definition_version=previous_definition_version, to_base_multiplier=multiplier, reason=reason)

    def effect(actor):
        item = _item(item_id)
        previous = FinancialCommandReceipt.objects.filter(pk=previous_id,
            command__in=(SETUP_COMMAND, COMMAND)).first()
        if previous is None or not isinstance(previous.result, dict):
            _refuse()
        unit = previous.result.get("quantity_unit")
        chain = _chain(item, unit)
        current, definition, original_multiplier = chain[-1]
        if str(current.pk) != previous_id or definition["definition_version"] != previous_definition_version:
            raise ValidationError({"unit_conversion": "The referenced definition is no longer current or its version changed. Preserve the correction for review."})
        if multiplier == original_multiplier:
            raise ValidationError({"to_base_multiplier": "A replacement must record an actual factor change, not a second copy of the same definition."})
        if len(chain) > MAX_REPLACEMENTS:
            raise ValidationError({"unit_conversion": "The retained definition chain requires controlled archival review before another replacement."})
        replacement = {key: definition[key] for key in DEFINITION_KEYS}
        replacement.update(configuration_id=conversion_reference(submission_id),
            to_base_multiplier=format(multiplier, "f"), reason=reason)
        result = {**replacement, "definition_version": _version(replacement), "previous_definition": _snapshot(current)}
        result["definition_anchor"] = _anchor(result, submission_id, actor.pk, _fingerprint(actor.pk, payload))
        return result

    return _submission(submission_id=submission_id, command=COMMAND, user=user,
        payload=payload, roles=FINANCE_MANAGEMENT_ROLES, effect=effect)
