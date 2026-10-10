"""This year's SSA scores beside last year's, for any set of schools.

Owner, 2026-10-09: "For SSA analysis and performance we shall be comparing
previous FY SSA scores with the current SSA Scores to measure improvement.
therefore apply the format above to all SSA charts on school profile,
cluster, district, sub-region, staff, projects".

One definition for every page that draws it. A school's score for a year is
its latest *confirmed* record of that year (the record's own ``fy``, as
`apps.ssa.current_year` reads a year); an intervention's score for a set of
schools is the mean of those records' scores for it, and the overall score
the mean of the records' averages. A year with no confirmed record is not
measured, which is never a zero.

The year compared is the one a page names (a page with a year filter passes
its own). With none named it is the running financial year, and the year
before it is the baseline (owner, 2026-10-09: FY2026 against FY2027, never
FY2025). Until the running year has a confirmed assessment it is "not
measured" beside last year's scores.
"""

from __future__ import annotations

from collections import defaultdict

__all__ = [
    "fy_label",
    "intervention_comparison",
    "latest_measured_fy",
    "previous_fy",
    "school_intervention_scores",
    "school_year_scores",
]


def fy_label(fy) -> str:
    """ "FY 2025/26" for the year that ends in 2026."""
    try:
        end = int(str(fy))
    except (TypeError, ValueError):
        return f"FY {fy}"
    return f"FY {end - 1}/{str(end)[-2:]}"


def previous_fy(fy) -> str | None:
    try:
        return str(int(str(fy)) - 1)
    except (TypeError, ValueError):
        return None


def _mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def latest_measured_fy(schools=None) -> str:
    """The year an SSA comparison reads when a page names none: the running
    financial year, compared with the one before it.

    Owner, 2026-10-09: "SSA scores being used for comparison is fy2026 and
    2025 ... i mean fy2026 vs fy2027 not 2025". It used to be the latest year
    in which any of ``schools`` had a confirmed record, so that a chart was
    not empty between 1 October and the year's first confirmed assessment;
    in October 2026 that put FY2025 beside FY2026 on the staff profile, the
    cluster scorecard and the Admin snapshot while the profiles beside them
    compared FY2026 with FY2027. The current year is the current year: until
    it has a confirmed SSA it reads "not measured" beside last year's scores.
    ``schools`` is kept for the callers that pass it."""
    from apps.core.fy import get_operational_fy

    return str(get_operational_fy())


def school_year_scores(schools, fy) -> dict[str, dict]:
    """``{school id: {"current", "previous"}}``: each school's average score
    in ``fy`` and in the year before, from its latest confirmed record of
    each (a record's own average, else the mean of the scores it carries).
    A school with a record in neither year is not in it. Two queries."""
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord, SsaScore

    fy = str(fy)
    before = previous_fy(fy)
    latest: dict[tuple[str, str], dict] = {}
    for row in (
        SsaRecord.objects.filter(
            school_id__in=schools,
            fy__in=[year for year in (fy, before) if year],
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
        .values("id", "school_id", "fy", "average_score")
        .order_by("school_id", "fy", "-date_of_ssa", "-created_at", "-id")
    ):
        latest.setdefault((row["school_id"], row["fy"]), row)
    missing = [r["id"] for r in latest.values() if r["average_score"] is None]
    carried: dict[str, list[float]] = defaultdict(list)
    if missing:
        for record_id, score in SsaScore.objects.filter(
            ssa_record_id__in=missing, score__isnull=False
        ).values_list("ssa_record_id", "score"):
            carried[record_id].append(float(score))
    scores: dict[str, dict] = {}
    for (school_id, year), row in latest.items():
        value = (
            round(float(row["average_score"]), 2)
            if row["average_score"] is not None
            else _mean(carried.get(row["id"], ()))
        )
        entry = scores.setdefault(school_id, {"current": None, "previous": None})
        entry["current" if year == fy else "previous"] = value
    return scores


def school_intervention_scores(schools, fy, intervention: str) -> dict[str, dict]:
    """``{school id: {"current", "previous"}}`` for one intervention: each
    school's score for it on its latest confirmed record of ``fy`` and of
    the year before. A school with a score in neither is not in it. Two
    queries."""
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord, SsaScore

    fy = str(fy)
    before = previous_fy(fy)
    latest: dict[tuple[str, str], str] = {}
    for record_id, school_id, year in (
        SsaRecord.objects.filter(
            school_id__in=schools,
            fy__in=[year for year in (fy, before) if year],
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
        .order_by("school_id", "fy", "-date_of_ssa", "-created_at", "-id")
        .values_list("id", "school_id", "fy")
    ):
        latest.setdefault((school_id, year), record_id)
    place = {record_id: key for key, record_id in latest.items()}
    scores: dict[str, dict] = {}
    if not place:
        return scores
    for record_id, score in SsaScore.objects.filter(
        ssa_record_id__in=list(place), intervention=intervention, score__isnull=False
    ).values_list("ssa_record_id", "score"):
        school_id, year = place[record_id]
        entry = scores.setdefault(school_id, {"current": None, "previous": None})
        entry["current" if year == fy else "previous"] = round(float(score), 2)
    return scores


def intervention_comparison(schools, fy=None) -> dict:
    """The eight interventions for ``schools`` (ids, or a queryset of
    schools), each with this year's score and last year's:

        {"fy", "previous_fy", "label", "previous_label",
         "rows": [{"key", "label", "current", "previous"}, ...],
         "current", "previous",           # the overall averages
         "schools", "previous_schools",   # schools with a confirmed record
         "has_current", "has_previous", "has_any"}

    Three queries whatever the number of schools, two when the year is
    named."""
    from apps.core.enums import SsaIntervention
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord, SsaScore

    fy = str(fy or latest_measured_fy(schools))
    before = previous_fy(fy)
    years = [year for year in (fy, before) if year]

    # The first row per (school, year) is that year's latest record; the id
    # settles two records of one day the same way on every run.
    latest: dict[tuple[str, str], dict] = {}
    for row in (
        SsaRecord.objects.filter(
            school_id__in=schools,
            fy__in=years,
            deleted_at__isnull=True,
            verification_status__in=CURRENT_SSA_STATUSES,
        )
        .values("id", "school_id", "fy", "average_score")
        .order_by("school_id", "fy", "-date_of_ssa", "-created_at", "-id")
    ):
        latest.setdefault((row["school_id"], row["fy"]), row)

    year_of = {row["id"]: row["fy"] for row in latest.values()}
    by_year: dict[str, dict[str, list[float]]] = {
        year: defaultdict(list) for year in years
    }
    per_record: dict[str, list[float]] = defaultdict(list)
    if year_of:
        for record_id, intervention, score in SsaScore.objects.filter(
            ssa_record_id__in=list(year_of)
        ).values_list("ssa_record_id", "intervention", "score"):
            if score is None:
                continue
            by_year[year_of[record_id]][intervention].append(float(score))
            per_record[record_id].append(float(score))

    def overall(year) -> float | None:
        # A record's own average, else the mean of the scores it carries.
        return _mean(
            row["average_score"]
            if row["average_score"] is not None
            else _mean(per_record.get(row["id"], ()))
            for row in latest.values()
            if row["fy"] == year
        )

    rows = [
        {
            "key": value,
            "label": label,
            "current": _mean(by_year[fy].get(value, ())),
            "previous": _mean(by_year[before].get(value, ())) if before else None,
        }
        for value, label in SsaIntervention.choices
    ]
    has_current = any(row["current"] is not None for row in rows)
    has_previous = any(row["previous"] is not None for row in rows)
    return {
        "fy": fy,
        "previous_fy": before,
        "label": fy_label(fy),
        "previous_label": fy_label(before) if before else "",
        "rows": rows,
        "current": overall(fy),
        "previous": overall(before) if before else None,
        "schools": sum(1 for _school, year in latest if year == fy),
        "previous_schools": sum(1 for _school, year in latest if year == before),
        "has_current": has_current,
        "has_previous": has_previous,
        "has_any": has_current or has_previous,
    }
