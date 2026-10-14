"""Exact captured units for NEW internal stock commands, not a public contract.

Stock/cost always uses the locked item's base unit. Custom units require an
explicit, immutable management definition, never a mutable legacy conversion
row or an inferred bag weight, dosage, strength or density.
"""
from decimal import Decimal, localcontext

from rest_framework.exceptions import ValidationError

from .financial_capture import _text
from .financial_values import exact_decimal
from .inventory_conversion_setup import (conversion_reference, read_inventory_unit,
    require_setup_enabled)


def captured_unit(value):
    if value is None:
        return None
    unit = _text(value, "quantity_unit", 40)
    if not unit:
        raise ValidationError({"quantity_unit": "Record the explicit captured unit."})
    return unit


def unit_payload(unit, reference=None):
    # Preserve earlier base-unit request hashes and accepted receipts exactly.
    payload = {"quantity_unit": unit} if unit is not None else {}
    if reference is not None:
        if unit is None:
            raise ValidationError({"quantity_unit": "A definition requires the original captured unit."})
        payload["unit_conversion_id"] = conversion_reference(reference)
    return payload


def base_quantity(quantity, unit, item, *, field="quantity", positive=True, unit_conversion_id=None):
    """Call under the item mutex, before quantity limits or any domain effect."""
    reference = conversion_reference(unit_conversion_id)
    if unit is None and reference is None:
        return quantity, None
    definition = None
    if reference is not None:
        require_setup_enabled()
        definition, multiplier = read_inventory_unit(reference, item, unit, require_current=True)
    elif unit == item.base_unit:
        multiplier = Decimal("1")
    elif (unit, item.base_unit) == ("g", "kg"):
        multiplier = Decimal("0.001")
    elif (unit, item.base_unit) == ("kg", "g"):
        multiplier = Decimal("1000")
    else:
        raise ValidationError({"quantity_unit": "Use the explicit item base unit or verified grams/kilograms; pack, dose and other conversions require controlled setup."})
    with localcontext() as context:
        context.prec = 40
        converted = exact_decimal(quantity * multiplier, field=field, scale=4,
            max_digits=14, positive=positive)
    evidence = {"input_quantity": format(quantity, "f"), "input_unit": unit,
        "base_unit": item.base_unit, "to_base_multiplier": format(multiplier, "f"),
        "base_quantity": format(converted, "f"), "quantity_field": field,
        "conversion_version": "identity-g-kg-v1"}
    if definition is not None:
        evidence.update(conversion_version="configured-unit-v1", unit_conversion_id=reference,
            unit_conversion_version=definition["definition_version"])
    return converted, evidence


def require_quantity_definition(evidence, item, expected_base, *, field="quantity"):
    """Check earlier custom source proof before NEW effects, even with flag off."""
    if not isinstance(evidence, dict) or evidence.get("conversion_version") != "configured-unit-v1":
        return
    definition, multiplier = read_inventory_unit(evidence.get("unit_conversion_id"), item,
        evidence.get("input_unit"))
    with localcontext() as context:
        context.prec = 40
        original = exact_decimal(evidence.get("input_quantity"), field=field, scale=4,
            max_digits=14, positive=field != "counted_quantity")
        converted = exact_decimal(original * multiplier, field=field, scale=4,
            max_digits=14, positive=field != "counted_quantity")
    expected = {"input_quantity": format(original, "f"), "input_unit": definition["quantity_unit"],
        "base_unit": item.base_unit, "to_base_multiplier": format(multiplier, "f"),
        "base_quantity": format(converted, "f"), "quantity_field": field,
        "conversion_version": "configured-unit-v1", "unit_conversion_id": definition["configuration_id"],
        "unit_conversion_version": definition["definition_version"]}
    if evidence != expected or converted != expected_base:
        raise ValidationError({"unit_conversion": "Original captured/base unit evidence does not match its retained definition."})


def quantity_result(result, evidence):
    return {**result, "stock_quantity_evidence": evidence} if evidence is not None else result
