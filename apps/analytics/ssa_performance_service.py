"""Role-scoped SSA Performance intelligence workspace.

The dashboard deliberately computes every surface from the same set of latest
confirmed SSA records.  This keeps the KPI strip, district comparisons, risk
queue, heatmap, trend, and decision recommendations internally consistent.
"""

from __future__ import annotations

from collections import defaultdict
from apps.core.enums import SsaIntervention, VerificationStatus, ssa_score_band
from apps.core.fy import fy_options, get_operational_fy, get_quarter_for_date
from apps.core.permissions import RolePermissionService
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from .platform_engine import (
    completion_analysis,
    describe_numeric,
    engine_metadata,
    safe_mean,
    trend_analysis,
)


TARGET_SCORE = 6.0
HIGH_RISK_SCORE = 4.0
QUARTERS = ("Q1", "Q2", "Q3", "Q4")

RECOMMENDED_ACTIONS = {
    SsaIntervention.CHRISTLIKE_BEHAVIOUR.value: "Values coaching and follow-up",
    SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value: "Spiritual formation support",
    SsaIntervention.FINANCIAL_HEALTH.value: "Financial management support",
    SsaIntervention.LEADERSHIP.value: "Leadership coaching and mentoring",
    SsaIntervention.GOVERNMENT_REQUIREMENT.value: "Compliance support and training",
    SsaIntervention.LEARNING_ENVIRONMENT.value: "Learning materials and setup",
    SsaIntervention.TEACHING_ENVIRONMENT.value: "On-site coaching and follow-up",
    SsaIntervention.ENROLMENT.value: "Enrolment planning and monitoring",
}


def _fy_label(fy: str) -> str:
    try:
        end = int(fy)
    except (TypeError, ValueError):
        return f"FY {fy}"
    return f"FY {end - 1}/{str(end)[-2:]}"


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _average(values) -> float | None:
    return safe_mean(values)


def _band(score: float | None) -> dict:
    label, color, tone = ssa_score_band(score)
    return {"label": label, "color": color, "tone": tone}


def _latest(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    """Return the first row per key from a newest-first ordered result set."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for row in rows:
        key = tuple(row[field] for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _previous_period(fy: str, quarter: str) -> tuple[str, str, str]:
    index = QUARTERS.index(quarter)
    if index:
        previous_quarter = QUARTERS[index - 1]
        return fy, previous_quarter, previous_quarter
    previous_fy = str(int(fy) - 1)
    return previous_fy, "Q4", f"Q4 {_fy_label(previous_fy)}"


def _scoped_schools(principal):
    """Resolve the dashboard's aggregate scope before any SSA query runs.

    RVP is the one special case: the shared scope service intentionally blocks
    school rows for the role, but this aggregate page may calculate over the
    assigned region(s).  Individual school identities are still suppressed.
    """
    scope = resolve_user_scope(principal)
    schools = School.objects.filter(deleted_at__isnull=True)
    if scope.country_scope:
        return schools, scope
    if scope.can_view_summary_only:
        if scope.region_ids:
            return schools.filter(region_id__in=scope.region_ids), scope
        return schools.none(), scope
    if scope.school_ids:
        return schools.filter(id__in=scope.school_ids), scope
    return schools.none(), scope


def _record_rows(school_ids: list[str], fy: str, quarter: str | None) -> list[dict]:
    if not school_ids:
        return []
    records = SsaRecord.objects.filter(
        school_id__in=school_ids,
        fy=fy,
        deleted_at__isnull=True,
        verification_status=VerificationStatus.CONFIRMED.value,
    )
    if quarter:
        records = records.filter(quarter=quarter)
    rows = list(
        records.values(
            "id", "school_id", "fy", "quarter", "date_of_ssa", "average_score"
        ).order_by("school_id", "-date_of_ssa", "-created_at")
    )
    return _latest(rows, ("school_id",))


def _scores_by_record(record_ids: list[str]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = defaultdict(dict)
    if not record_ids:
        return scores
    for row in SsaScore.objects.filter(ssa_record_id__in=record_ids).values(
        "ssa_record_id", "intervention", "score"
    ):
        scores[row["ssa_record_id"]][row["intervention"]] = float(row["score"])
    return scores


def _resolved_average(record: dict, score_map: dict[str, float]) -> float | None:
    if record["average_score"] is not None:
        return float(record["average_score"])
    return _average(score_map.values())


def _trend(school_ids: list[str], selected_fy: str) -> dict:
    try:
        end_fy = int(selected_fy)
    except (TypeError, ValueError):
        end_fy = int(get_operational_fy())
    years = [str(year) for year in range(end_fy - 6, end_fy + 1)]
    if not school_ids:
        rows = []
    else:
        raw = list(
            SsaRecord.objects.filter(
                school_id__in=school_ids,
                fy__in=years,
                deleted_at__isnull=True,
                verification_status=VerificationStatus.CONFIRMED.value,
            )
            .values("id", "school_id", "fy", "date_of_ssa", "average_score")
            .order_by("fy", "school_id", "-date_of_ssa", "-created_at")
        )
        rows = _latest(raw, ("fy", "school_id"))

    by_year: dict[str, list[float]] = defaultdict(list)
    missing_average_ids = [row["id"] for row in rows if row["average_score"] is None]
    missing_scores = _scores_by_record(missing_average_ids)
    for row in rows:
        avg = _resolved_average(row, missing_scores.get(row["id"], {}))
        if avg is not None:
            by_year[row["fy"]].append(avg)

    values = [_average(by_year[year]) for year in years]
    plot_left, plot_right, plot_top, plot_bottom = 48, 852, 20, 176
    points = []
    for index, (year, value) in enumerate(zip(years, values)):
        x = plot_left + (plot_right - plot_left) * index / max(len(years) - 1, 1)
        y = None
        if value is not None:
            y = plot_bottom - (max(0.0, min(10.0, value)) / 10.0) * (
                plot_bottom - plot_top
            )
        points.append(
            {
                "fy": year,
                "label": str(int(year) - 1),
                "value": _round(value),
                "x": round(x, 1),
                "y": round(y, 1) if y is not None else None,
            }
        )
    polyline = " ".join(
        f'{point["x"]},{point["y"]}' for point in points if point["y"] is not None
    )
    return {
        "points": points,
        "polyline": polyline,
        "target_y": round(
            plot_bottom - (TARGET_SCORE / 10.0) * (plot_bottom - plot_top), 1
        ),
        "has_data": any(value is not None for value in values),
        "analysis": trend_analysis(values, stable_slope=0.02),
    }


def build_dashboard(principal, query: dict) -> dict:
    """Build the full SSA Performance view model from one role-scoped dataset."""
    schools_qs, scope = _scoped_schools(principal)
    selected_fy = str(query.get("fy") or get_operational_fy())
    if not selected_fy.isdigit():
        selected_fy = get_operational_fy()
    selected_quarter = str(query.get("quarter") or get_quarter_for_date())
    if selected_quarter not in QUARTERS:
        selected_quarter = get_quarter_for_date()

    region_options = list(
        schools_qs.values("region_id", "region__name")
        .distinct()
        .order_by("region__name")
    )
    allowed_regions = {row["region_id"] for row in region_options}
    selected_region = str(query.get("region") or "")
    if selected_region not in allowed_regions:
        selected_region = ""

    district_options_qs = schools_qs
    if selected_region:
        district_options_qs = district_options_qs.filter(region_id=selected_region)
    district_options = list(
        district_options_qs.values("district_id", "district__name")
        .distinct()
        .order_by("district__name")
    )
    allowed_districts = {row["district_id"] for row in district_options}
    selected_district = str(query.get("district") or "")
    if selected_district not in allowed_districts:
        selected_district = ""

    filtered_schools = schools_qs
    if selected_region:
        filtered_schools = filtered_schools.filter(region_id=selected_region)
    if selected_district:
        filtered_schools = filtered_schools.filter(district_id=selected_district)

    schools = list(
        filtered_schools.values(
            "id",
            "school_id",
            "name",
            "school_type",
            "region_id",
            "region__name",
            "district_id",
            "district__name",
        ).order_by("district__name", "name")
    )
    schools_by_id = {row["id"]: row for row in schools}
    school_ids = list(schools_by_id)

    latest_records = _record_rows(school_ids, selected_fy, selected_quarter)
    record_ids = [row["id"] for row in latest_records]
    scores_by_record = _scores_by_record(record_ids)

    assessed = []
    for record in latest_records:
        school = schools_by_id.get(record["school_id"])
        if not school:
            continue
        score_map = scores_by_record.get(record["id"], {})
        average = _resolved_average(record, score_map)
        minimum_intervention = min(score_map, key=score_map.get) if score_map else None
        minimum_score = (
            score_map.get(minimum_intervention) if minimum_intervention else None
        )
        assessed.append(
            {
                **school,
                "record_id": record["id"],
                "average": average,
                "scores": score_map,
                "minimum_intervention": minimum_intervention,
                "minimum_score": minimum_score,
                "is_high_risk": minimum_score is not None
                and minimum_score < HIGH_RISK_SCORE,
            }
        )

    total_schools = len(schools)
    assessed_count = len(assessed)
    completion_rate = assessed_count / total_schools * 100 if total_schools else 0.0
    average_score = _average(row["average"] for row in assessed)
    high_risk = [row for row in assessed if row["is_high_risk"]]

    previous_fy, previous_quarter, previous_label = _previous_period(
        selected_fy, selected_quarter
    )
    previous_records = _record_rows(school_ids, previous_fy, previous_quarter)
    previous_scores = _scores_by_record(
        [row["id"] for row in previous_records if row["average_score"] is None]
    )
    previous_average = _average(
        _resolved_average(row, previous_scores.get(row["id"], {}))
        for row in previous_records
    )
    average_delta = (
        average_score - previous_average
        if average_score is not None and previous_average is not None
        else None
    )
    score_summary = describe_numeric(
        (row["average"] for row in assessed),
        previous_values=(
            _resolved_average(row, previous_scores.get(row["id"], {}))
            for row in previous_records
        ),
        target=TARGET_SCORE,
    )
    completion_summary = completion_analysis(assessed_count, total_schools)

    intervention_rows = []
    intervention_values: dict[str, float | None] = {}
    for value, label in SsaIntervention.choices:
        avg = _average(row["scores"].get(value) for row in assessed)
        intervention_values[value] = avg
        intervention_rows.append(
            {
                "key": value,
                "label": label,
                "average": _round(avg),
                "width": round((avg or 0) * 10, 1),
                "band": _band(avg),
            }
        )

    district_school_counts: dict[str, int] = defaultdict(int)
    for school in schools:
        district_school_counts[school["district_id"]] += 1
    district_assessed: dict[str, list[dict]] = defaultdict(list)
    for row in assessed:
        district_assessed[row["district_id"]].append(row)

    district_rows = []
    matrix_rows = []
    for district_id, district_total in district_school_counts.items():
        district_items = district_assessed.get(district_id, [])
        district_name = next(
            row["district__name"]
            for row in schools
            if row["district_id"] == district_id
        )
        district_average = _average(row["average"] for row in district_items)
        intervention_cells = []
        weakest_key = None
        weakest_average = None
        for value, label in SsaIntervention.choices:
            cell_average = _average(row["scores"].get(value) for row in district_items)
            if cell_average is not None and (
                weakest_average is None or cell_average < weakest_average
            ):
                weakest_key, weakest_average = value, cell_average
            intervention_cells.append(
                {
                    "key": value,
                    "label": label,
                    "value": _round(cell_average, 1),
                    "band": _band(cell_average),
                }
            )
        district_rows.append(
            {
                "id": district_id,
                "name": district_name,
                "schools_assessed": len(district_items),
                "total_schools": district_total,
                "average": _round(district_average),
                "band": _band(district_average),
                "weakest_key": weakest_key,
                "weakest": dict(SsaIntervention.choices).get(weakest_key, "—"),
                "high_risk": sum(1 for row in district_items if row["is_high_risk"]),
                "completion_rate": round(len(district_items) / district_total * 100, 1)
                if district_total
                else 0,
            }
        )
        matrix_rows.append(
            {"id": district_id, "name": district_name, "cells": intervention_cells}
        )

    district_rows.sort(
        key=lambda row: (row["average"] is None, -(row["average"] or 0), row["name"])
    )
    matrix_by_id = {row["id"]: row for row in matrix_rows}
    matrix_rows = [matrix_by_id[row["id"]] for row in district_rows]
    districts_below_target = [
        row
        for row in district_rows
        if row["average"] is not None and row["average"] < TARGET_SCORE
    ]

    urgent_schools = []
    if scope.can_view_school_level_detail:
        for row in sorted(
            high_risk,
            key=lambda item: (
                item["minimum_score"] if item["minimum_score"] is not None else 11,
                item["name"],
            ),
        ):
            intervention = row["minimum_intervention"]
            urgent_schools.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "district": row["district__name"],
                    "intervention": dict(SsaIntervention.choices).get(
                        intervention, "Overall SSA"
                    ),
                    "score": _round(row["minimum_score"], 1),
                    "action": RECOMMENDED_ACTIONS.get(
                        intervention, "Targeted coaching and follow-up"
                    ),
                }
            )

    weak_interventions = [
        row
        for row in intervention_rows
        if row["average"] is not None and row["average"] < TARGET_SCORE
    ]
    potential_core = [
        row
        for row in assessed
        if row["school_type"] == "client"
        and row["average"] is not None
        and row["average"] >= 7.5
    ]
    reporting_districts = sum(1 for row in district_rows if row["schools_assessed"])
    has_intervention_data = any(row["average"] is not None for row in intervention_rows)
    insights = [
        {
            "tone": (
                "info"
                if not reporting_districts
                else "danger"
                if districts_below_target
                else "success"
            ),
            "title": "Districts below target",
            "body": (
                "No districts have confirmed SSA data in this selection."
                if not reporting_districts
                else f"{len(districts_below_target)} district(s) average below the {TARGET_SCORE:.1f} target."
                if districts_below_target
                else f"Every reporting district meets the {TARGET_SCORE:.1f} target."
            ),
            "action": (
                "Complete and confirm assessments"
                if not reporting_districts
                else "Prioritise district coaching"
                if districts_below_target
                else "Maintain support"
            ),
        },
        {
            "tone": (
                "info"
                if not has_intervention_data
                else "warning"
                if weak_interventions
                else "success"
            ),
            "title": "Interventions needing attention",
            "body": (
                "No confirmed intervention data is available for this selection."
                if not has_intervention_data
                else ", ".join(row["label"] for row in weak_interventions[:2])
                + (
                    " need targeted support."
                    if weak_interventions
                    else "All intervention averages meet target."
                )
            ),
            "action": "Review intervention gaps",
        },
        {
            "tone": (
                "info" if not assessed_count else "danger" if high_risk else "success"
            ),
            "title": "High-risk schools",
            "body": (
                "No confirmed school assessments are available for risk classification."
                if not assessed_count
                else f"{len(high_risk)} assessed school(s) score below {HIGH_RISK_SCORE:.1f} in at least one intervention."
            ),
            "action": (
                "Complete and confirm assessments"
                if not assessed_count
                else "Open the urgent-attention queue"
                if high_risk
                else "No urgent action required"
            ),
        },
        {
            "tone": "success" if (average_delta or 0) >= 0 else "danger",
            "title": "Performance momentum",
            "body": (
                f"Average SSA changed by {average_delta:+.2f} points versus {previous_label}."
                if average_delta is not None
                else f"No comparable confirmed SSA set is available for {previous_label}."
            ),
            "action": "Strengthen the highest-impact practices",
        },
        {
            "tone": "info",
            "title": "Potential core-school candidates",
            "body": f"{len(potential_core)} client school(s) average 7.5 or higher in this scope.",
            "action": "Review candidate readiness",
        },
    ]

    export_rows = [
        {
            "school_id": row["school_id"],
            "school": row["name"],
            "region": row["region__name"],
            "district": row["district__name"],
            "average": _round(row["average"]),
            "lowest_intervention": dict(SsaIntervention.choices).get(
                row["minimum_intervention"], ""
            ),
            "lowest_score": _round(row["minimum_score"], 1),
            "high_risk": "Yes" if row["is_high_risk"] else "No",
        }
        for row in assessed
    ]

    all_fy_options = sorted(
        set(fy_options()) | {selected_fy}, key=lambda value: int(value), reverse=True
    )
    selected_region_name = next(
        (
            row["region__name"]
            for row in region_options
            if row["region_id"] == selected_region
        ),
        "All regions",
    )
    selected_district_name = next(
        (
            row["district__name"]
            for row in district_options
            if row["district_id"] == selected_district
        ),
        "All districts",
    )
    scope_note = (
        "Regional summary only — school identities are protected."
        if scope.can_view_summary_only
        else f"Showing only schools available to your {scope.active_role} role."
    )

    trend = _trend(school_ids, selected_fy)
    analytics_engine = engine_metadata(
        "ssa_performance", record_count=assessed_count, confirmed_only=True
    )

    return {
        "filters": {
            "fy": selected_fy,
            "fy_label": _fy_label(selected_fy),
            "quarter": selected_quarter,
            "region": selected_region,
            "region_name": selected_region_name,
            "district": selected_district,
            "district_name": selected_district_name,
            "fy_options": [
                {"value": value, "label": _fy_label(value)} for value in all_fy_options
            ],
            "quarters": QUARTERS,
            "regions": region_options,
            "districts": district_options,
        },
        "scope": {
            "role": scope.active_role,
            "note": scope_note,
            "can_view_school_details": scope.can_view_school_level_detail,
            "can_link_schools": scope.can_view_school_level_detail
            and RolePermissionService.can_view_page(principal, "school_profile"),
            "can_export": scope.can_export,
        },
        "kpis": {
            "total_schools": total_schools,
            "assessed": assessed_count,
            "completion_rate": round(completion_rate, 1),
            "reporting_districts": reporting_districts,
            "total_districts": len(district_rows),
            "average_score": _round(average_score),
            "average_delta": _round(average_delta),
            "high_risk": len(high_risk),
            "high_risk_pct": round(len(high_risk) / assessed_count * 100, 1)
            if assessed_count
            else 0,
            "districts_below_target": len(districts_below_target),
            "target": TARGET_SCORE,
            "comparison_label": previous_label,
        },
        "interventions": intervention_rows,
        "districts": district_rows,
        "matrix": matrix_rows,
        "urgent_schools": urgent_schools,
        "urgent_total": len(high_risk),
        "insights": insights,
        "trend": trend,
        "analytics": {
            "score": score_summary,
            "completion": completion_summary,
            "trend": trend["analysis"],
        },
        "export_rows": export_rows,
        "engine": {
            **analytics_engine,
            "name": "SSA decision engine · Edify Python Analytics Engine",
            "target_score": TARGET_SCORE,
            "high_risk_score": HIGH_RISK_SCORE,
        },
    }


__all__ = ["build_dashboard", "TARGET_SCORE", "HIGH_RISK_SCORE"]
