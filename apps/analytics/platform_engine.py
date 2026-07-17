"""Shared Python analytics primitives for Edify operational dashboards.

The application keeps database filtering and aggregation in Django's ORM, then
uses this module for statistical interpretation of the resulting role-scoped
records.  That boundary keeps queries efficient while giving planning,
finance, SSA, performance, and impact one definition of trends, variance,
completion, data quality, and confidence.

Every public function returns JSON-serialisable values and suppresses NaN/
infinity so templates and API responses never leak invalid numeric literals.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


ENGINE_NAME = "Edify Python Analytics Engine"
ENGINE_VERSION = "1.0"


def _numeric(values: Iterable[Any] | None) -> tuple[pd.Series, int]:
    raw = list(values) if values is not None else []
    if not raw:
        return pd.Series(dtype="float64"), 0
    series = pd.to_numeric(pd.Series(raw, dtype="object"), errors="coerce")
    series = series.replace([np.inf, -np.inf], np.nan)
    return series.dropna().astype("float64"), int(series.isna().sum())


def _round(value: Any, digits: int = 2) -> float | None:
    if value is None or not np.isfinite(float(value)):
        return None
    return round(float(value), digits)


def _quality(count: int) -> dict[str, Any]:
    if count == 0:
        label, confidence = "No data", 0.0
    elif count < 5:
        label, confidence = "Very limited", 0.25
    elif count < 10:
        label, confidence = "Limited", 0.5
    elif count < 30:
        label, confidence = "Moderate", 0.75
    else:
        label, confidence = "Strong", 0.95
    return {"label": label, "confidence": confidence, "sample_size": count}


def engine_metadata(
    domain: str,
    *,
    record_count: int | None = None,
    confirmed_only: bool | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "name": ENGINE_NAME,
        "version": ENGINE_VERSION,
        "domain": domain,
        "runtime": "Python · pandas · NumPy · SciPy",
        "interpretation": "Decision support; source workflow records remain authoritative.",
    }
    if record_count is not None:
        metadata["record_count"] = int(record_count)
        metadata["quality"] = _quality(int(record_count))
    if confirmed_only is not None:
        metadata["confirmed_only"] = bool(confirmed_only)
    return metadata


def safe_mean(values: Iterable[Any] | None) -> float | None:
    series, _ = _numeric(values)
    return _round(series.mean()) if not series.empty else None


def describe_numeric(
    values: Iterable[Any] | None,
    *,
    previous_values: Iterable[Any] | None = None,
    target: float | None = None,
    digits: int = 2,
) -> dict[str, Any]:
    """Describe one metric with optional period and target comparisons."""
    series, missing = _numeric(values)
    previous, previous_missing = _numeric(previous_values)
    count = int(series.size)
    mean = float(series.mean()) if count else None
    previous_mean = float(previous.mean()) if not previous.empty else None
    delta = (
        mean - previous_mean if mean is not None and previous_mean is not None else None
    )
    delta_pct = (
        delta / abs(previous_mean) * 100
        if delta is not None and previous_mean not in (None, 0)
        else None
    )
    return {
        "count": count,
        "missing": missing,
        "sum": _round(series.sum(), digits) if count else None,
        "mean": _round(mean, digits),
        "median": _round(series.median(), digits) if count else None,
        "minimum": _round(series.min(), digits) if count else None,
        "maximum": _round(series.max(), digits) if count else None,
        "standard_deviation": _round(series.std(ddof=1), digits) if count > 1 else None,
        "q1": _round(series.quantile(0.25), digits) if count else None,
        "q3": _round(series.quantile(0.75), digits) if count else None,
        "previous_count": int(previous.size),
        "previous_missing": previous_missing,
        "previous_mean": _round(previous_mean, digits),
        "delta": _round(delta, digits),
        "delta_pct": _round(delta_pct, 1),
        "target": _round(target, digits),
        "target_gap": _round(mean - target, digits)
        if mean is not None and target is not None
        else None,
        "quality": _quality(count),
    }


def completion_analysis(
    completed: int | float,
    total: int | float,
    *,
    target_rate: float = 100.0,
) -> dict[str, Any]:
    total_value = max(float(total or 0), 0.0)
    completed_value = max(float(completed or 0), 0.0)
    rate = min(completed_value / total_value * 100, 100.0) if total_value else 0.0
    if not total_value:
        status = "no_scope"
    elif rate >= target_rate:
        status = "on_target"
    elif rate >= max(target_rate - 15, 0):
        status = "watch"
    else:
        status = "behind"
    return {
        "completed": int(completed_value),
        "total": int(total_value),
        "remaining": int(max(total_value - completed_value, 0)),
        "rate": round(rate, 1),
        "target_rate": round(float(target_rate), 1),
        "gap": round(rate - float(target_rate), 1),
        "status": status,
    }


def variance_analysis(
    planned: int | float,
    actual: int | float,
    *,
    warning_pct: float = 5.0,
) -> dict[str, Any]:
    planned_value = float(planned or 0)
    actual_value = float(actual or 0)
    variance = actual_value - planned_value
    variance_pct = variance / abs(planned_value) * 100 if planned_value else None
    utilization = actual_value / planned_value * 100 if planned_value else 0.0
    absolute_pct = abs(variance_pct) if variance_pct is not None else None
    if planned_value == 0:
        status = "no_plan" if actual_value == 0 else "unplanned"
    elif absolute_pct is not None and absolute_pct <= 2:
        status = "on_plan"
    elif absolute_pct is not None and absolute_pct <= warning_pct:
        status = "watch"
    else:
        status = "off_plan"
    return {
        "planned": _round(planned_value),
        "actual": _round(actual_value),
        "variance": _round(variance),
        "absolute_variance": _round(abs(variance)),
        "variance_pct": _round(variance_pct, 2),
        "utilization_rate": _round(utilization, 1),
        "status": status,
    }


def trend_analysis(
    values: Sequence[Any] | Iterable[Any],
    *,
    stable_slope: float = 0.01,
) -> dict[str, Any]:
    """Fit a simple linear trend to ordered values, ignoring missing points."""
    raw = list(values) if values is not None else []
    pairs = []
    for index, value in enumerate(raw):
        if isinstance(value, (tuple, list)) and len(value) == 2:
            x_value, y_value = value
        else:
            x_value, y_value = index, value
        try:
            x_float, y_float = float(x_value), float(y_value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(x_float) and np.isfinite(y_float):
            pairs.append((x_float, y_float))
    count = len(pairs)
    if count < 2:
        return {
            "count": count,
            "direction": "insufficient_data",
            "slope": None,
            "r_squared": None,
            "p_value": None,
            "quality": _quality(count),
        }
    x = np.asarray([pair[0] for pair in pairs], dtype=float)
    y = np.asarray([pair[1] for pair in pairs], dtype=float)
    if np.unique(y).size == 1:
        slope, r_squared, p_value = 0.0, 0.0, 1.0
    else:
        result = stats.linregress(x, y)
        slope = float(result.slope)
        r_squared = float(result.rvalue**2)
        p_value = float(result.pvalue)
    direction = "stable"
    if slope > stable_slope:
        direction = "improving"
    elif slope < -stable_slope:
        direction = "declining"
    return {
        "count": count,
        "direction": direction,
        "slope": _round(slope, 4),
        "r_squared": _round(r_squared, 3),
        "p_value": _round(p_value, 4),
        "quality": _quality(count),
    }


def correlation_analysis(
    left: Iterable[Any] | None,
    right: Iterable[Any] | None,
    *,
    method: str = "spearman",
    minimum_sample: int = 5,
) -> dict[str, Any]:
    left_values = list(left) if left is not None else []
    right_values = list(right) if right is not None else []
    paired_count = min(len(left_values), len(right_values))
    frame = pd.DataFrame(
        {
            "left": left_values[:paired_count],
            "right": right_values[:paired_count],
        }
    )
    frame = (
        frame.apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    count = int(len(frame))
    base = {"method": method, "count": count, "quality": _quality(count)}
    if (
        count < minimum_sample
        or frame["left"].nunique() < 2
        or frame["right"].nunique() < 2
    ):
        return {
            **base,
            "coefficient": None,
            "p_value": None,
            "strength": "insufficient_data",
            "direction": "unknown",
        }
    if method == "pearson":
        coefficient, p_value = stats.pearsonr(frame["left"], frame["right"])
    else:
        coefficient, p_value = stats.spearmanr(frame["left"], frame["right"])
        method = "spearman"
    absolute = abs(float(coefficient))
    strength = (
        "very_weak"
        if absolute < 0.2
        else "weak"
        if absolute < 0.4
        else "moderate"
        if absolute < 0.6
        else "strong"
        if absolute < 0.8
        else "very_strong"
    )
    direction = (
        "positive" if coefficient > 0 else "negative" if coefficient < 0 else "none"
    )
    return {
        **base,
        "method": method,
        "coefficient": _round(coefficient, 3),
        "p_value": _round(p_value, 4),
        "strength": strength,
        "direction": direction,
    }


def robust_outlier_analysis(
    values: Iterable[Any] | None,
    *,
    labels: Sequence[str] | None = None,
    threshold: float = 3.5,
) -> dict[str, Any]:
    series, _ = _numeric(values)
    if series.empty:
        return {"count": 0, "outliers": [], "method": "modified_z_score"}
    median = float(series.median())
    deviation = np.abs(series.to_numpy() - median)
    mad = float(np.median(deviation))
    scores = (
        np.zeros(len(series))
        if mad == 0
        else 0.6745 * (series.to_numpy() - median) / mad
    )
    outliers = []
    label_values = list(labels or [])
    for position, (index, value) in enumerate(series.items()):
        score = float(scores[position])
        if abs(score) >= threshold:
            outliers.append(
                {
                    "index": int(index),
                    "label": label_values[index]
                    if index < len(label_values)
                    else str(index),
                    "value": _round(value),
                    "score": _round(score, 2),
                    "direction": "high" if score > 0 else "low",
                }
            )
    return {
        "count": int(series.size),
        "outliers": outliers,
        "method": "modified_z_score",
        "threshold": threshold,
    }


def planning_health(
    *,
    total: int,
    ready: int,
    scheduled: int,
    at_risk: int = 0,
    overdue: int = 0,
) -> dict[str, Any]:
    readiness = completion_analysis(ready, total)
    scheduling = completion_analysis(scheduled, total)
    denominator = max(int(total or 0), 1)
    risk_rate = round((int(at_risk or 0) + int(overdue or 0)) / denominator * 100, 1)
    risk_score = min(
        round(risk_rate * 0.65 + max(0, 100 - readiness["rate"]) * 0.35, 1), 100.0
    )
    return {
        "readiness": readiness,
        "scheduling": scheduling,
        "at_risk": int(at_risk or 0),
        "overdue": int(overdue or 0),
        "risk_rate": risk_rate,
        "risk_score": risk_score,
        "status": "critical"
        if risk_score >= 60
        else "watch"
        if risk_score >= 30
        else "healthy",
        "engine": engine_metadata("planning", record_count=int(total or 0)),
    }


def finance_health(
    *,
    approved: int | float,
    disbursed: int | float,
    accounted: int | float,
    returned: int | float = 0,
    reconciled_count: int = 0,
    disbursed_count: int = 0,
    record_count: int | None = None,
) -> dict[str, Any]:
    utilization = variance_analysis(approved, disbursed)
    reconciliation = completion_analysis(reconciled_count, disbursed_count)
    cash_variance = variance_analysis(disbursed, accounted + returned)
    return {
        "utilization": utilization,
        "reconciliation": reconciliation,
        "cash_variance": cash_variance,
        "engine": engine_metadata(
            "finance",
            record_count=int(
                record_count if record_count is not None else disbursed_count or 0
            ),
        ),
    }


__all__ = [
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "completion_analysis",
    "correlation_analysis",
    "describe_numeric",
    "engine_metadata",
    "finance_health",
    "planning_health",
    "robust_outlier_analysis",
    "safe_mean",
    "trend_analysis",
    "variance_analysis",
]
