"""Verification quality as a pattern, not a record (2026-09-03).

The ledger answered "was this activity verified". This answers the
questions an Impact Assessment officer asks about the whole flow: what are
we returning for, who keeps sending weak evidence, how fast do verifiers
turn work round, and — from the sample checks — how often does a
verification survive a second look.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from apps.activities.ia_models import (
    ReturnedReason,
    VerificationDecision,
    VerificationHistory,
    VerificationSample,
)
from apps.activities.models import Activity
from apps.core.metrics import percentage_or_zero as _pct
from apps.core.scoping import activity_country_q, resolve_user_scope

DEFAULT_WINDOW_DAYS = 90


def _names(user_ids):
    from apps.accounts.models import User

    return {
        u.id: u.name
        for u in User.objects.filter(id__in=[i for i in user_ids if i]).only(
            "id", "name"
        )
    }


def _staff_names(staff_ids):
    from apps.accounts.models import StaffProfile

    ids = [i for i in staff_ids if i]
    out = {}
    for sp in StaffProfile.objects.filter(id__in=ids).select_related("user"):
        out[sp.id] = sp.user.name if sp.user else sp.id
    # Legacy rows hold a User id in responsible_staff_id.
    out.update(_names([i for i in ids if i not in out]))
    return out


def _partner_names(partner_ids):
    from apps.partners.models import Partner

    return {
        p.id: p.name
        for p in Partner.objects.filter(id__in=[i for i in partner_ids if i]).only(
            "id", "name"
        )
    }


def _hours(start, end):
    if not start or not end:
        return None
    return round((end - start).total_seconds() / 3600, 1)


def verification_analytics(principal, window_days: int | None = None) -> dict:
    scope = resolve_user_scope(principal)
    window_days = int(window_days or DEFAULT_WINDOW_DAYS)
    since = timezone.now() - timedelta(days=window_days)
    reach = Activity.objects.filter(deleted_at__isnull=True).filter(
        activity_country_q(scope)
    )

    decisions = list(
        VerificationDecision.objects.filter(
            decided_at__gte=since, verification__activity__in=reach.values("id")
        )
        .select_related("verification__activity__school", "verification")
        .order_by("-decided_at")
    )
    reasons_by_verification = defaultdict(list)
    for rr in ReturnedReason.objects.filter(
        verification_id__in={d.verification_id for d in decisions}
    ):
        reasons_by_verification[rr.verification_id].append(rr.reason)

    submitters = defaultdict(lambda: {"submitted": 0, "returned": 0})
    partners = defaultdict(lambda: {"submitted": 0, "returned": 0})
    reason_counts = defaultdict(int)
    months = defaultdict(lambda: {"decisions": 0, "returned": 0})
    rows = []
    verifier_ids, staff_ids, partner_ids = set(), set(), set()
    for d in decisions:
        a = d.verification.activity
        returned = d.decision == "RETURN"
        key = a.responsible_staff_id or "—"
        staff_ids.add(key)
        submitters[key]["submitted"] += 1
        if a.assigned_partner_id:
            partner_ids.add(a.assigned_partner_id)
            partners[a.assigned_partner_id]["submitted"] += 1
        month = timezone.localtime(d.decided_at).strftime("%Y-%m")
        months[month]["decisions"] += 1
        if returned:
            submitters[key]["returned"] += 1
            if a.assigned_partner_id:
                partners[a.assigned_partner_id]["returned"] += 1
            months[month]["returned"] += 1
            for reason in reasons_by_verification.get(d.verification_id, []) or [
                "Unspecified"
            ]:
                reason_counts[reason] += 1
        verifier_ids.add(d.decided_by)
        rows.append(
            {
                "decided_at": d.decided_at,
                "activity_id": a.id,
                "school": a.school.name if a.school_id else "Cluster-wide",
                "activity_type": a.get_activity_type_display(),
                "submitter_id": key,
                "partner_id": a.assigned_partner_id,
                "decision": "Returned" if returned else "Verified",
                "reasons": "; ".join(
                    reasons_by_verification.get(d.verification_id, [])
                ),
                "verifier_id": d.decided_by,
                "turnaround_hours": _hours(a.submitted_to_ia_at, d.decided_at),
            }
        )

    staff_names = _staff_names(staff_ids)
    partner_names = _partner_names(partner_ids)

    history = list(
        VerificationHistory.objects.filter(
            verified_at__gte=since, activity__in=reach.values("id")
        ).select_related("activity")
    )
    turnaround = defaultdict(list)
    for h in history:
        hrs = _hours(h.activity.submitted_to_ia_at, h.verified_at)
        if hrs is not None:
            turnaround[h.verified_by].append(hrs)
        verifier_ids.add(h.verified_by)

    samples = list(
        VerificationSample.objects.filter(
            sampled_at__gte=since, activity__in=reach.values("id")
        ).exclude(status="pending")
    )
    accuracy = defaultdict(lambda: {"checked": 0, "confirmed": 0})
    for smp in samples:
        accuracy[smp.original_verifier]["checked"] += 1
        if smp.status == "confirmed":
            accuracy[smp.original_verifier]["confirmed"] += 1
        verifier_ids.add(smp.original_verifier)

    verifier_names = _names(verifier_ids)
    for r in rows:
        r["submitter"] = staff_names.get(r["submitter_id"], r["submitter_id"])
        r["partner"] = partner_names.get(r["partner_id"], "") if r["partner_id"] else ""
        r["verifier"] = verifier_names.get(r["verifier_id"], r["verifier_id"])

    def _rate_rows(counter, names):
        out = []
        for key, c in counter.items():
            out.append(
                {
                    "name": names.get(key, key),
                    "submitted": c["submitted"],
                    "returned": c["returned"],
                    "return_rate": _pct(c["returned"], c["submitted"]),
                }
            )
        out.sort(key=lambda r: (-r["return_rate"], -r["submitted"], r["name"]))
        return out

    verifiers = []
    for vid in verifier_ids:
        hours = turnaround.get(vid, [])
        acc = accuracy.get(vid)
        verifiers.append(
            {
                "name": verifier_names.get(vid, vid),
                "verified": len(hours),
                "avg_hours": round(sum(hours) / len(hours), 1) if hours else None,
                "within_24h": _pct(sum(1 for h in hours if h <= 24), len(hours)),
                "sampled": acc["checked"] if acc else 0,
                "sample_accuracy": _pct(acc["confirmed"], acc["checked"])
                if acc
                else None,
            }
        )
    verifiers.sort(key=lambda r: (-r["verified"], r["name"]))

    total = len(decisions)
    returned_total = sum(1 for d in decisions if d.decision == "RETURN")
    trend = [
        {
            "month": m,
            "decisions": v["decisions"],
            "returned": v["returned"],
            "return_rate": _pct(v["returned"], v["decisions"]),
        }
        for m, v in sorted(months.items())
    ]
    reasons = [
        {"reason": r, "count": c, "share": _pct(c, returned_total)}
        for r, c in sorted(reason_counts.items(), key=lambda kv: -kv[1])
    ]
    return {
        "window_days": window_days,
        "since": since,
        "decisions": total,
        "returned": returned_total,
        "return_rate": _pct(returned_total, total),
        "reasons": reasons,
        "submitters": _rate_rows(submitters, staff_names),
        "partners": _rate_rows(partners, partner_names),
        "trend": trend,
        "verifiers": verifiers,
        "rows": rows,
    }


EXPORT_HEADER = [
    "Decided at",
    "Activity",
    "School",
    "Type",
    "Submitted by",
    "Partner",
    "Decision",
    "Return reasons",
    "Verifier",
    "Turnaround (hours)",
]


def export_rows(data: dict):
    for r in data["rows"]:
        yield [
            timezone.localtime(r["decided_at"]).strftime("%Y-%m-%d %H:%M"),
            r["activity_id"],
            r["school"],
            r["activity_type"],
            r["submitter"],
            r["partner"],
            r["decision"],
            r["reasons"],
            r["verifier"],
            r["turnaround_hours"] if r["turnaround_hours"] is not None else "",
        ]
