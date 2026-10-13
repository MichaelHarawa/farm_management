"""Exact captured units for NEW internal stock commands, not a public contract.

Stock/cost always uses the locked item's base unit. Only identity and the fixed
g/kg conversion are verified here. Legacy item conversion rows are not authority
for guessed bag weights, dosage, strength, density or supplier pack sizes.
"""
from decimal import Decimal, localcontext

from rest_framework.exceptions import ValidationError

from .financial_capture import _text
from .financial_values import exact_decimal


def captured_unit(value):
    if value is None:
        return None
    unit = _text(value, "quantity_unit", 40)
    if not unit:
        raise ValidationError({"quantity_unit": "Record the explicit captured unit."})
    return unit


def unit_payload(unit):
    # Preserve earlier base-unit request hashes and accepted receipts exactly.
    return {"quantity_unit": unit} if unit is not None else {}


def base_quantity(quantity, unit, item, *, field="quantity", positive=True):
    """Call under the item mutex, before quantity limits or any domain effect."""
    if unit is None:
        return quantity, None
    if unit == item.base_unit:
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
    return converted, {"input_quantity": format(quantity, "f"), "input_unit": unit,
        "base_unit": item.base_unit, "to_base_multiplier": format(multiplier, "f"),
        "base_quantity": format(converted, "f"), "quantity_field": field,
        "conversion_version": "identity-g-kg-v1"}


def quantity_result(result, evidence):
    return {**result, "stock_quantity_evidence": evidence} if evidence is not None else result
