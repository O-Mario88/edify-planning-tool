"""The Country Director's export set.

Four CSVs, one period. Each is the same data the cockpit shows for the
selected FY/quarter/month, so a file a CD takes into a board meeting can never
disagree with the screen it came from:

- ``delivery``: Program Lead oversight roster (targets, execution, risk).
- ``risk``: every priority school with the factors that ranked it.
- ``finance``: the advance pipeline and utilisation against the envelope.
- ``core``: core-package health for every plan in the country.
"""

from __future__ import annotations

from apps.core.fy import get_operational_fy

DATASETS = ("delivery", "risk", "finance", "core")

_LABELS = {
    "delivery": "Delivery",
    "risk": "Risk",
    "finance": "Finance",
    "core": "Core Health",
}


def dataset_label(dataset: str) -> str:
    return _LABELS.get(dataset, _LABELS["delivery"])


def normalise_dataset(raw: str | None) -> str:
    raw = (raw or "").strip().lower()
    return raw if raw in DATASETS else "delivery"


def country_export(user, dataset, fy=None, quarter=None, month=None, filters=None):
    """Return ``(slug, header, rows)`` for one dataset in the selected period."""
    from apps.analytics.cd_analytics_service import (
        CDAnalyticsService,
        _country_activities,
        _prime_target_series,
        country_for,
        resolve_cd_scope,
    )

    fy = fy or get_operational_fy()
    dataset = normalise_dataset(dataset)
    cd = resolve_cd_scope(fy, quarter, month, filters or {}, country=country_for(user))
    acts = _country_activities(cd)

    if dataset == "risk":
        from apps.analytics.cd_dashboard_service import CDDashboardService

        rows = CDDashboardService.priority_schools(cd, acts, limit=None)
        header = ["School", "District / Region", "Risk", "Severity", "Factors"]
        return (
            "priority-schools",
            header,
            [
                [
                    r["school"],
                    r["region"],
                    r["risk"],
                    r["weight"],
                    "; ".join(r["issues"]),
                ]
                for r in rows
            ],
        )

    if dataset == "finance":
        detail = CDAnalyticsService.budget_utilisation_detail(cd)
        health = CDAnalyticsService.budget_finance_health(cd)
        header = ["Line", "Amount (UGX)", "Basis"]
        rows = [
            ["Approved envelope", detail["approved"], detail["basis"]],
            ["Requested (pipeline)", detail["requested"], detail["basis"]],
            ["Disbursed", detail["disbursed"], detail["basis"]],
            ["Utilisation %", detail["pct"], detail["helper"]],
        ]
        rows += [
            [s["label"], s["amount"], "pipeline status"] for s in health["statuses"]
        ]
        rows += [
            [f"Requested in {label}", amount, "quarter"]
            for label, amount in zip(health["quarter_labels"], health["quarter_vals"])
        ]
        return ("finance", header, rows)

    if dataset == "core":
        from apps.core_schools.leadership_service import core_school_health

        report = core_school_health(user, {"fy": fy})
        header = [
            "School",
            "Code",
            "District",
            "Status",
            "Slots Done",
            "Progress %",
            "Visits",
            "Trainings",
            "Assessment Done",
            "Baseline",
            "Follow-up",
            "Movement",
            "Blocked Slots",
            "On Track",
        ]
        rows = [
            [
                r["name"],
                r["code"],
                r["district"],
                r["status"],
                f'{r["slotsDone"]}/{r["slotsTotal"]}',
                r["progressPct"],
                r["visits"],
                r["trainings"],
                "Yes" if r["assessmentDone"] else "No",
                r["baseline"] if r["baseline"] is not None else "",
                r["followUp"] if r["followUp"] is not None else "",
                r["movement"] if r["movement"] is not None else "",
                r["blockedCount"],
                "Yes" if r["onTrack"] else "No",
            ]
            for r in report["plans"]
        ]
        return ("core-health", header, rows)

    _prime_target_series(cd)
    rows = CDAnalyticsService.pl_oversight(cd, acts)["rows"]
    header = [
        "PL",
        "CCEOs Supervised",
        "Target Achievement %",
        "School Visits %",
        "Cluster Meetings %",
        "Cluster Trainings %",
        "SSA Completed %",
        "MSCS %",
        "Schools at Risk",
        "Budget Utilization %",
        "Backlog",
        "Risk Status",
    ]
    return (
        "pl-oversight",
        header,
        [
            [
                r["name"],
                r["cceos"],
                r["target_pct"],
                *[
                    area["pct"] if area["pct"] is not None else "Not set"
                    for area in r["areas"]
                ],
                r["schools_at_risk"],
                r["budget_util"],
                r["backlog"],
                r["risk"],
            ]
            for r in rows
        ],
    )
