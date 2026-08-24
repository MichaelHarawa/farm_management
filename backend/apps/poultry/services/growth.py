from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from apps.poultry.models import Batch, BroilerStrain, BatchWeightSample


# Target weights (grams) Day 0-42 - extracted from authoritative guides.
# Ross 308
ROSS308_TARGETS: dict[int, int] = {
    0: 40, 1: 108, 2: 176, 3: 244, 4: 312, 5: 380, 6: 449, 7: 517,
    8: 585, 9: 653, 10: 721, 11: 789, 12: 857, 13: 925, 14: 993,
    15: 1061, 16: 1130, 17: 1198, 18: 1266, 19: 1334, 20: 1402,
    21: 1470, 22: 1538, 23: 1606, 24: 1674, 25: 1742, 26: 1810,
    27: 1879, 28: 1947, 29: 2015, 30: 2083, 31: 2151, 32: 2219,
    33: 2287, 34: 2355, 35: 2423, 36: 2491, 37: 2560, 38: 2628,
    39: 2696, 40: 2764, 41: 2832, 42: 2900,
}

# Cobb 500
COBB500_TARGETS: dict[int, int] = {
    0: 42, 1: 109, 2: 176, 3: 243, 4: 309, 5: 376, 6: 443, 7: 510,
    8: 577, 9: 644, 10: 711, 11: 777, 12: 844, 13: 911, 14: 978,
    15: 1045, 16: 1112, 17: 1179, 18: 1245, 19: 1312, 20: 1379,
    21: 1446, 22: 1513, 23: 1580, 24: 1647, 25: 1713, 26: 1780,
    27: 1847, 28: 1914, 29: 1981, 30: 2048, 31: 2115, 32: 2181,
    33: 2248, 34: 2315, 35: 2382, 36: 2449, 37: 2516, 38: 2583,
    39: 2649, 40: 2716, 41: 2783, 42: 2850,
}

STRAIN_TARGETS: dict[str, dict[int, int]] = {
    BroilerStrain.ROSS_308: ROSS308_TARGETS,
    BroilerStrain.COBB_500: COBB500_TARGETS,
}


def get_broiler_strain_for_batch(batch: Batch) -> str:
    """Return effective strain. For non-broilers return 'n/a'."""
    if batch.bird_type != "broilers":
        return "n/a"
    return batch.broiler_strain or BroilerStrain.ROSS_308


def get_target_weight_g(age_days: int, strain: str) -> int | None:
    """Return expected weight in grams for the given day and strain."""
    if age_days < 0:
        return None
    table = STRAIN_TARGETS.get(strain)
    if not table:
        return None
    # Exact match or interpolate linearly between nearest days
    if age_days in table:
        return table[age_days]
    # find bracketing days
    days = sorted(table.keys())
    if not days:
        return None
    if age_days <= days[0]:
        return table[days[0]]
    if age_days >= days[-1]:
        return table[days[-1]]
    lower = max(d for d in days if d <= age_days)
    upper = min(d for d in days if d >= age_days)
    if lower == upper:
        return table[lower]
    # linear interpolation
    w_lower = table[lower]
    w_upper = table[upper]
    ratio = (age_days - lower) / (upper - lower)
    return int(round(w_lower + (w_upper - w_lower) * ratio))


def deviation_percent(actual_g: int, target_g: int | None) -> float | None:
    if target_g is None or target_g <= 0:
        return None
    return ((actual_g - target_g) / target_g) * 100.0


@dataclass(frozen=True)
class GrowthAlert:
    age_days: int
    actual_g: int
    target_g: int | None
    deviation_pct: float | None
    severity: Literal["ok", "watch", "action", "urgent"]
    message: str
    recommended_actions: list[str]


def classify_deviation(pct: float | None) -> Literal["ok", "watch", "action", "urgent"]:
    if pct is None:
        return "ok"
    if pct >= -3:
        return "ok"
    if pct >= -8:
        return "watch"
    if pct >= -15:
        return "action"
    return "urgent"


def build_growth_alert(
    age_days: int,
    actual_g: int,
    target_g: int | None,
    sample_size: int = 10,
) -> GrowthAlert:
    pct = deviation_percent(actual_g, target_g)
    severity = classify_deviation(pct)
    if target_g is None:
        return GrowthAlert(
            age_days=age_days,
            actual_g=actual_g,
            target_g=None,
            deviation_pct=None,
            severity="ok",
            message="No target defined for this age/strain.",
            recommended_actions=["Ensure correct broiler strain is set on the batch."],
        )

    if severity == "ok":
        msg = f"On target ({actual_g}g vs {target_g}g)."
        actions: list[str] = ["Maintain current feeding & environment program."]
    elif severity == "watch":
        msg = f"Slightly below target ({pct:.1f}%). Monitor closely."
        actions = [
            "Verify feed consumption and quality.",
            "Check house temperature and ventilation.",
            "Weigh another 20 birds within 24h to confirm trend.",
        ]
    elif severity == "action":
        msg = f"Under target by {abs(pct):.1f}%. Immediate management review needed."
        actions = [
            "Audit feed formulation and delivery.",
            "Assess disease pressure or past stress events.",
            "Consider increasing energy density or adding electrolytes.",
            "Re-weigh within 12-24h and log environmental readings.",
        ]
    else:  # urgent
        msg = f"CRITICAL: {abs(pct):.1f}% under target. Risk of major performance loss."
        actions = [
            "Veterinary / nutritionist consult within hours.",
            "Full house walk + mortality and feed intake audit.",
            "Consider therapeutic intervention or ration change.",
            "Weigh sample daily until trend reverses.",
        ]

    if sample_size < 8:
        actions.append("Increase sample size on next weighing (aim >=15 birds).")

    return GrowthAlert(
        age_days=age_days,
        actual_g=actual_g,
        target_g=target_g,
        deviation_pct=pct,
        severity=severity,
        message=msg,
        recommended_actions=actions,
    )


def latest_growth_status(batch: Batch) -> dict | None:
    """Return the most recent weight sample analysis for a batch (if any)."""
    sample = batch.weight_samples.order_by("-sampled_at").first()
    if not sample:
        return None
    strain = get_broiler_strain_for_batch(batch)
    target = get_target_weight_g(sample.age_in_days, strain)
    alert = build_growth_alert(
        sample.age_in_days, sample.average_weight_g, target, sample.sample_size
    )
    return {
        "sample_id": sample.id,
        "age_in_days": sample.age_in_days,
        "sampled_at": sample.sampled_at.isoformat(),
        "average_weight_g": sample.average_weight_g,
        "sample_size": sample.sample_size,
        "target_weight_g": target,
        "deviation_percent": alert.deviation_pct,
        "severity": alert.severity,
        "message": alert.message,
        "recommended_actions": alert.recommended_actions,
        "strain": strain,
    }


def compute_growth_series(batch: Batch) -> list[dict]:
    """Return time-series of weight samples with targets and deviation for charting."""
    samples = list(batch.weight_samples.order_by("age_in_days", "sampled_at"))
    if not samples:
        return []
    strain = get_broiler_strain_for_batch(batch)
    series = []
    for s in samples:
        tgt = get_target_weight_g(s.age_in_days, strain)
        pct = deviation_percent(s.average_weight_g, tgt)
        series.append({
            "age_in_days": s.age_in_days,
            "sampled_at": s.sampled_at.isoformat(),
            "actual_g": s.average_weight_g,
            "target_g": tgt,
            "deviation_pct": round(pct, 2) if pct is not None else None,
            "sample_size": s.sample_size,
            "severity": classify_deviation(pct),
        })
    return series
