"""Every column Impact Assessment needs, for every IA queue (owner,
2026-10-19: "make sure the IA can export every columns he needs").

IA's working tables — the verification queue, the partner evidence queue,
what has been returned and what has been verified — drew rows on screen and
offered no export. Each now downloads its own rows, filtered as the page is
filtered, laid out once here so the four files read alike: the activity, the
school (by its School ID), who delivered it, its dates, its SSA, its
Salesforce ID, its attendance, where its verification stands and its money.

A read: a few queries for the whole file, whatever its length.
"""

from __future__ import annotations

from django.utils import timezone

HEADERS = (
    "Activity ID",
    "Activity Type",
    "Activity",
    "Delivered By",
    "Partner",
    "Responsible Staff",
    "School ID",
    "School Name",
    "District",
    "Cluster",
    "Planned Date",
    "Delivered On",
    "Sent for Verification",
    "Days Waiting",
    "Purpose of Visit",
    "Focus Intervention",
    "SSA Expected",
    "SSA Not Collected Reason",
    "Teachers Attended",
    "Leaders Attended",
    "Other Participants",
    "Salesforce ID",
    "Evidence",
    "Status",
    "Verification",
    "Verified By",
    "Verified On",
    "Return Reasons",
    "Payment Status",
    "Planned Cost (UGX)",
)

DATE = "d mmm yyyy"
MONEY = "#,##0"


def wants_export(request) -> bool:
    """A queue page asked for its file (``?export=xlsx``; add ``format=csv``
    for a CSV)."""
    return bool((request.GET.get("export") or "").strip())


def _day(value):
    if value is None:
        return None
    if hasattr(value, "hour"):
        return timezone.localdate(value)
    return value


def _label(value) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


def sheet(title: str, activities) -> dict:
    """The sheet for these activities, in the order given."""
    from apps.activities.verification_analytics import (
        _names,
        _partner_names,
        _staff_names,
    )
    from apps.core.enums import SsaIntervention
    from apps.partners.purposes import visit_purpose_label

    rows = list(
        activities.select_related(
            "school", "school__district", "cluster", "ia_verification"
        ).prefetch_related("ia_verification__returned_reasons")
    )
    staff = _staff_names(
        {a.responsible_staff_id or a.monitored_by_staff_id for a in rows}
    )
    partners = _partner_names(
        {a.assigned_partner_id for a in rows if a.assigned_partner_id}
    )
    verifiers = _names(
        {v for a in rows for v in (a.ia_confirmed_by, a.pl_reviewed_by) if v}
    )
    focus = dict(SsaIntervention.choices)
    today = timezone.localdate()

    out = []
    for a in rows:
        sent = _day(a.submitted_to_ia_at)
        waiting = (
            (today - sent).days
            if sent and a.status in ("awaiting_ia_verification", "submitted_to_pl")
            else None
        )
        verified_by = a.ia_confirmed_by or a.pl_reviewed_by
        verified_on = _day(a.ia_confirmed_at) or _day(a.pl_reviewed_at)
        verification = getattr(a, "ia_verification", None)
        reasons = (
            ", ".join(r.reason for r in verification.returned_reasons.all())
            if verification is not None
            else ""
        )
        owner = a.responsible_staff_id or a.monitored_by_staff_id
        out.append(
            [
                a.id,
                a.get_activity_type_display(),
                a.activity_name_snapshot or a.get_activity_type_display(),
                "Partner" if a.delivery_type == "partner" else "Staff",
                partners.get(a.assigned_partner_id, "")
                if a.assigned_partner_id
                else "",
                staff.get(owner, owner or ""),
                a.school.school_id if a.school_id else "",
                a.school.name if a.school_id else "",
                a.school.district.name if a.school_id and a.school.district_id else "",
                a.cluster.name if a.cluster_id else "",
                a.planned_date or _day(a.scheduled_date),
                a.actual_delivery_date,
                sent,
                waiting,
                visit_purpose_label(a.purpose_type, a.activity_purpose_text or ""),
                focus.get(a.focus_intervention, a.focus_intervention or ""),
                "Yes" if a.ssa_collection_expected else "No",
                a.ssa_not_collected_reason or "",
                a.teachers_attended,
                a.leaders_attended,
                a.other_participants,
                a.salesforce_activity_id or "",
                _label(a.evidence_status),
                a.get_status_display(),
                _label(a.ia_verification_status),
                verifiers.get(verified_by, verified_by or ""),
                verified_on,
                reasons,
                _label(a.payment_status),
                a.est_cost_cents or 0,
            ]
        )
    columns = {name: index for index, name in enumerate(HEADERS, start=1)}
    return {
        "title": title,
        "headers": list(HEADERS),
        "rows": out,
        "number_formats": {
            columns["Planned Date"]: DATE,
            columns["Delivered On"]: DATE,
            columns["Sent for Verification"]: DATE,
            columns["Verified On"]: DATE,
            columns["Planned Cost (UGX)"]: MONEY,
        },
    }


def download(request, stem: str, title: str, activities):
    """The queue's rows as ``<stem>.xlsx``, or CSV with ``format=csv``."""
    from apps.core.excel import table_download

    return table_download(request, stem, [sheet(title, activities)])
