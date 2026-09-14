"""Impact findings: what Impact Assessment concluded, and who checked it
(IA review, owner, 2026-09-13).

The role description asks IA to "distinguish what works" and to report it
without bias. Before this, a conclusion lived in a textarea that was written
into a CSV and discarded: nothing kept the numbers it rested on, the evidence
that cut against it, or whether anyone else had read it.

A finding is recorded from Programme Learning (/ia/learning/), usually from a
row of an outcome table, and keeps:

  - the statement, the contrary evidence and the limitations in IA's words;
  - a metric snapshot the SERVER took from the row when the finding was
    recorded (n, comparison n, median changes, corrected verdict, evidence
    grade, period, generated at) — never figures typed or posted by the
    browser, so the numbers cannot be edited to fit the words;
  - the recommendation, the role that should act on it and when to follow up.

Lifecycle, with the owner's review rule (apps.impact.review):

  draft ──submit──▶ in review ──approve──▶ approved ──revise──▶ new draft
    ▲                   │                                (the approved one is
    └────return─────────┘                                 superseded when the
                                                           revision is approved)

  - Only Impact Assessment writes findings, and only the author edits,
    submits or revises one.
  - A second IA officer in the finding's country reviews it; where the
    country has no other officer, the Country Director acknowledges it. The
    author never reviews their own finding.
  - Country-bound: IA and the Country Director read their country's findings,
    Admin reads every country. A finding carries its author's country.
  - Every transition writes an audit row; submission notifies the reviewers
    and the decision notifies the author (WorkflowNotificationService), and a
    decision closes the review notice.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import FindingStatus, ImpactFinding, Programme

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
ADMIN = EdifyRole.ADMIN.value

READER_ROLES = (IA, CD, ADMIN)

DRAFT = FindingStatus.DRAFT.value
IN_REVIEW = FindingStatus.IN_REVIEW.value
RETURNED = FindingStatus.RETURNED.value
APPROVED = FindingStatus.APPROVED.value
SUPERSEDED = FindingStatus.SUPERSEDED.value

STATUS_LABELS = dict(FindingStatus.choices)
STATUS_TONES = {
    DRAFT: "neutral",
    IN_REVIEW: "warning",
    RETURNED: "danger",
    APPROVED: "success",
    SUPERSEDED: "neutral",
}
PROGRAMME_LABELS = dict(Programme.choices)

#: The roles a recommendation may be addressed to.
ACTION_OWNER_ROLES = (
    (CD, "Country Director"),
    (EdifyRole.COUNTRY_PROGRAM_LEAD.value, "Programme Lead"),
    (EdifyRole.REGIONAL_PROGRAM_LEAD.value, "Regional Lead for CCE"),
    (EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value, "Business Transformation"),
    (IA, "Impact Assessment"),
)
ACTION_OWNER_LABELS = dict(ACTION_OWNER_ROLES)

EVENT_REVIEW_REQUESTED = "ia.finding.review_requested"
EVENT_REVIEW_DECIDED = "ia.finding.review_decided"

#: Keys of the metric snapshot a finding keeps from its source row.
SNAPSHOT_KEYS = (
    "row_key",
    "label",
    "exposed_n",
    "comparison_n",
    "coverage_pct",
    "missing_pct",
    "period",
    "design",
    "median_exposed",
    "median_comparison",
    "difference",
    "p",
    "p_adjusted",
    "verdict",
    "grade",
    "grade_label",
    "grade_reasons",
    "outcome",
    "caveat",
)


def _uid(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def reader_country(principal) -> str:
    """The country a reader is bound to: their analytics scope's country, else
    the country on their staff profile. Blank for Admin and a reader with no
    country on file, who read every country (owner rule, 2026-09-03)."""
    from apps.core.scoping import resolve_user_scope
    from apps.impact.review import _profile_country

    if _role(principal) == ADMIN:
        return ""
    scope = resolve_user_scope(principal)
    return (scope.country or _profile_country(principal) or "").strip()


def visible_findings(principal):
    """The findings `principal` may read."""
    if _role(principal) not in READER_ROLES:
        return ImpactFinding.objects.none()
    country = reader_country(principal)
    qs = ImpactFinding.objects.all()
    return qs.filter(country=country) if country else qs


def may_author(principal) -> bool:
    return _role(principal) == IA


def reviewer_basis(principal, finding) -> str | None:
    from apps.impact.review import reviewer_basis as basis

    if finding.status != IN_REVIEW:
        return None
    return basis(principal, author_id=finding.author_id, country=finding.country)


def _audit(action: str, finding, principal, payload: dict | None = None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="ImpactFinding",
        subject_id=str(finding.id),
        actor_id=_uid(principal) or None,
        actor_role=_role(principal) or None,
        reason=(payload or {}).get("note"),
        payload={
            "country": finding.country,
            "programme": finding.programme,
            "status": finding.status,
            **(payload or {}),
        },
    )


# ── Parsing ─────────────────────────────────────────────────────────────────


def _text(data, key, *, label, required=False, max_length=4000) -> str:
    value = str(data.get(key) or "").strip()
    if required and not value:
        raise BadRequest(f"{label} is required.")
    if len(value) > max_length:
        raise BadRequest(f"{label} must be {max_length} characters or fewer.")
    return value


def _clean(data) -> dict:
    from apps.core.enums import SsaIntervention

    programme = str(data.get("programme") or "").strip()
    if programme not in PROGRAMME_LABELS:
        raise BadRequest("Choose the programme the finding is about.")
    intervention = str(data.get("intervention") or "").strip()
    if intervention and intervention not in SsaIntervention.values:
        raise BadRequest("Choose an SSA intervention from the list.")
    owner_role = str(data.get("action_owner_role") or "").strip()
    if owner_role and owner_role not in ACTION_OWNER_LABELS:
        raise BadRequest("Choose who should act on the recommendation.")
    raw_due = str(data.get("follow_up_due") or "").strip()
    follow_up_due = None
    if raw_due:
        try:
            follow_up_due = date.fromisoformat(raw_due)
        except ValueError:
            raise BadRequest("Follow-up date must be a date (YYYY-MM-DD).") from None
    recommendation = _text(data, "recommendation", label="Recommendation")
    if recommendation and not owner_role:
        raise BadRequest("Say who should act on the recommendation.")
    refs = [
        line.strip()[:255]
        for line in str(data.get("evidence_refs") or "").splitlines()
        if line.strip()
    ][:50]
    return {
        "programme": programme,
        "intervention": intervention,
        "statement": _text(
            data, "statement", label="What the evidence shows", required=True
        ),
        "contrary_evidence": _text(
            data, "contrary_evidence", label="Evidence that cuts against it"
        ),
        "limitations": _text(data, "limitations", label="Limitations"),
        "recommendation": recommendation,
        "action_owner_role": owner_role,
        "follow_up_due": follow_up_due,
        "evidence_refs": refs,
    }


def _assert_submittable(finding) -> None:
    if not finding.statement.strip():
        raise BadRequest("Say what the evidence shows before submitting.")
    if not finding.limitations.strip():
        raise BadRequest(
            "State the limitations before submitting: what this evidence cannot show."
        )
    if finding.recommendation and not finding.action_owner_role:
        raise BadRequest("Say who should act on the recommendation.")


def _snapshot(metric_snapshot: dict | None) -> dict:
    snapshot = {
        key: (metric_snapshot or {}).get(key)
        for key in SNAPSHOT_KEYS
        if key in (metric_snapshot or {})
    }
    snapshot["generated_at"] = timezone.now().isoformat()
    return snapshot


# ── Writes ──────────────────────────────────────────────────────────────────


def record_finding(
    principal,
    data,
    *,
    cohort_filters: dict | None = None,
    metric_snapshot: dict | None = None,
    submit: bool = False,
) -> ImpactFinding:
    """Record a draft finding (and submit it for review when `submit`).
    `metric_snapshot` must come from the server's own computation."""
    from apps.impact.review import _profile_country

    if not may_author(principal):
        raise Forbidden("Only Impact Assessment records impact findings.")
    country = _profile_country(principal)
    if not country:
        raise BadRequest(
            "Your staff profile has no country, so nobody can be named to review "
            "the finding. Ask HR to record your country first."
        )
    fields = _clean(data)
    with transaction.atomic():
        finding = ImpactFinding.objects.create(
            country=country,
            author_id=_uid(principal),
            author_role=_role(principal),
            cohort_filters=dict(cohort_filters or {}),
            metric_snapshot=_snapshot(metric_snapshot),
            status=DRAFT,
            **fields,
        )
        _audit("ia.finding.recorded", finding, principal)
    if submit:
        return submit_finding(principal, finding.id)
    return finding


def _own_open_finding(principal, finding_id: str) -> ImpactFinding:
    finding = (
        visible_findings(principal)
        .select_for_update(of=("self",))
        .filter(id=finding_id)
        .first()
    )
    if finding is None:
        raise NotFoundError("That finding is not in your country.")
    if finding.author_id != _uid(principal):
        raise Forbidden("Only the officer who wrote the finding changes it.")
    return finding


def update_finding(principal, finding_id: str, data) -> ImpactFinding:
    """The author corrects a draft or returned finding. The metric snapshot
    stays the one taken when it was recorded."""
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment records impact findings.")
    fields = _clean(data)
    with transaction.atomic():
        finding = _own_open_finding(principal, finding_id)
        if finding.status not in (DRAFT, RETURNED):
            raise BadRequest(
                f"This finding is {STATUS_LABELS[finding.status].lower()}; "
                "revise it to change what it says."
            )
        changed = [k for k, v in fields.items() if getattr(finding, k) != v]
        for key, value in fields.items():
            setattr(finding, key, value)
        finding.save()
        _audit("ia.finding.updated", finding, principal, {"changed": changed})
    return finding


def submit_finding(principal, finding_id: str) -> ImpactFinding:
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment records impact findings.")
    with transaction.atomic():
        finding = _own_open_finding(principal, finding_id)
        if finding.status not in (DRAFT, RETURNED):
            raise BadRequest(
                f"This finding is already {STATUS_LABELS[finding.status].lower()}."
            )
        _assert_submittable(finding)
        finding.status = IN_REVIEW
        finding.submitted_at = timezone.now()
        finding.save(update_fields=["status", "submitted_at", "updated_at"])
        _audit("ia.finding.submitted", finding, principal)
    _notify_reviewers(finding)
    return finding


def review_finding(
    principal, finding_id: str, *, decision: str, note: str = ""
) -> ImpactFinding:
    """Approve or return a finding in review. The reviewer is never the author:
    a second IA officer in the country, or the Country Director where there is
    none (apps.impact.review.assert_can_review)."""
    from apps.impact.review import assert_can_review

    if decision not in ("approve", "return"):
        raise BadRequest("Choose approve or return.")
    note = (note or "").strip()
    if decision == "return" and not note:
        raise BadRequest("Say what the author needs to change.")
    superseded = None
    with transaction.atomic():
        finding = (
            visible_findings(principal)
            .select_for_update(of=("self",))
            .filter(id=finding_id)
            .first()
        )
        if finding is None:
            raise NotFoundError("That finding is not in your country.")
        if finding.status != IN_REVIEW:
            raise BadRequest(
                f"This finding is {STATUS_LABELS[finding.status].lower()}, not in review."
            )
        basis = assert_can_review(
            principal, author_id=finding.author_id, country=finding.country
        )
        finding.status = APPROVED if decision == "approve" else RETURNED
        finding.reviewed_by_id = _uid(principal)
        finding.reviewed_at = timezone.now()
        finding.review_basis = basis
        finding.review_note = note[:4000]
        finding.save(
            update_fields=[
                "status",
                "reviewed_by_id",
                "reviewed_at",
                "review_basis",
                "review_note",
                "updated_at",
            ]
        )
        if decision == "approve":
            prior_id = (finding.metric_snapshot or {}).get("supersedes_finding_id")
            if prior_id:
                superseded = (
                    ImpactFinding.objects.select_for_update()
                    .filter(id=prior_id, country=finding.country, status=APPROVED)
                    .first()
                )
                if superseded is not None:
                    superseded.status = SUPERSEDED
                    superseded.save(update_fields=["status", "updated_at"])
                    _audit(
                        "ia.finding.superseded",
                        superseded,
                        principal,
                        {"superseded_by": finding.id},
                    )
        _audit(
            f"ia.finding.{'approved' if decision == 'approve' else 'returned'}",
            finding,
            principal,
            {"review_basis": basis, "note": note or None},
        )
    _notify_decision(finding)
    return finding


def revise_finding(principal, finding_id: str) -> ImpactFinding:
    """Start a correction of an approved finding: a new draft carrying the same
    words and snapshot, which supersedes the approved one once it is approved
    in turn. The approved finding stands until then."""
    if not may_author(principal):
        raise Forbidden("Only Impact Assessment records impact findings.")
    with transaction.atomic():
        finding = _own_open_finding(principal, finding_id)
        if finding.status != APPROVED:
            raise BadRequest(
                "Only an approved finding is revised; edit a draft instead."
            )
        if ImpactFinding.objects.filter(
            metric_snapshot__supersedes_finding_id=finding.id,
            status__in=(DRAFT, IN_REVIEW, RETURNED),
        ).exists():
            raise BadRequest("A revision of this finding is already open.")
        snapshot = dict(finding.metric_snapshot or {})
        snapshot["supersedes_finding_id"] = finding.id
        revision = ImpactFinding.objects.create(
            country=finding.country,
            programme=finding.programme,
            intervention=finding.intervention,
            cohort_filters=finding.cohort_filters,
            metric_snapshot=snapshot,
            statement=finding.statement,
            contrary_evidence=finding.contrary_evidence,
            limitations=finding.limitations,
            recommendation=finding.recommendation,
            action_owner_role=finding.action_owner_role,
            follow_up_due=finding.follow_up_due,
            evidence_refs=finding.evidence_refs,
            author_id=_uid(principal),
            author_role=_role(principal),
            status=DRAFT,
        )
        _audit(
            "ia.finding.revision_started", revision, principal, {"revises": finding.id}
        )
    return revision


# ── Notifications ───────────────────────────────────────────────────────────


def reviewer_ids(finding) -> list[str]:
    """Who reviews: the country's other IA officers, else its Country Director."""
    from apps.accounts.models import User
    from apps.impact.review import ia_officer_ids

    officers = [
        str(i) for i in ia_officer_ids(finding.country) if str(i) != finding.author_id
    ]
    if officers:
        return officers
    return [
        str(i)
        for i in User.objects.filter(
            roles__contains=[CD],
            is_active=True,
            deleted_at__isnull=True,
            staff_profile__country=finding.country,
        ).values_list("id", flat=True)
    ]


def _notify_reviewers(finding) -> None:
    try:
        from apps.notifications.services import WorkflowNotificationService

        recipients = reviewer_ids(finding)
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_REQUESTED,
            category="ia",
            priority="normal",
            title=f"Impact finding to review · {PROGRAMME_LABELS[finding.programme]}",
            body=finding.statement[:500],
            context_type="ImpactFinding",
            context_id=str(finding.id),
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001 - a notice never undoes the submission
        pass


def _notify_decision(finding) -> None:
    try:
        from apps.notifications.services import (
            WorkflowNotificationService,
            resolve_condition,
        )

        resolve_condition(EVENT_REVIEW_REQUESTED, "ImpactFinding", str(finding.id))
        approved = finding.status == APPROVED
        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEW_DECIDED,
            category="ia",
            priority="normal" if approved else "high",
            title=(
                "Your impact finding was approved"
                if approved
                else "Your impact finding was returned"
            ),
            body=(finding.review_note or finding.statement)[:500],
            context_type="ImpactFinding",
            context_id=str(finding.id),
            recipients=[finding.author_id],
        )
    except Exception:  # noqa: BLE001 - housekeeping only
        pass


# ── Reads ───────────────────────────────────────────────────────────────────


def register(principal, *, status: str = "", programme: str = ""):
    qs = visible_findings(principal)
    if status in STATUS_LABELS:
        qs = qs.filter(status=status)
    if programme in PROGRAMME_LABELS:
        qs = qs.filter(programme=programme)
    return qs.order_by("-updated_at", "-created_at")


def decorate(principal, findings) -> list[dict]:
    """Register rows in bulk: names in one query, rights computed in memory
    (the review basis costs one officer lookup per country, cached here)."""
    from apps.accounts.models import User
    from apps.impact.review import _profile_country, ia_officer_ids

    findings = list(findings)
    ids = {f.author_id for f in findings} | {
        f.reviewed_by_id for f in findings if f.reviewed_by_id
    }
    names = (
        dict(User.objects.filter(id__in=ids).values_list("id", "name")) if ids else {}
    )
    me = _uid(principal)
    role = _role(principal)
    my_country = _profile_country(principal) if role in (IA, CD) else ""
    officers: dict[str, list[str]] = {}

    def can_review(finding) -> bool:
        if finding.status != IN_REVIEW or finding.author_id == me:
            return False
        if my_country != finding.country:
            return False
        if role == IA:
            return True
        if role == CD:
            if finding.country not in officers:
                officers[finding.country] = [
                    str(i) for i in ia_officer_ids(finding.country)
                ]
            return not [i for i in officers[finding.country] if i != finding.author_id]
        return False

    out = []
    for f in findings:
        mine = f.author_id == me and role == IA
        out.append(
            {
                "finding": f,
                "author": names.get(f.author_id, "Unknown"),
                "reviewer": names.get(f.reviewed_by_id, "") if f.reviewed_by_id else "",
                "status_label": STATUS_LABELS.get(f.status, f.status),
                "status_tone": STATUS_TONES.get(f.status, "neutral"),
                "programme_label": PROGRAMME_LABELS.get(f.programme, f.programme),
                "is_mine": mine,
                "can_edit": mine and f.status in (DRAFT, RETURNED),
                "can_revise": mine and f.status == APPROVED,
                "can_review": can_review(f),
            }
        )
    return out


def counts(principal, fy: str) -> dict:
    """Tile counts in one query."""
    from django.db.models import Count, Q

    from apps.core.fy import get_fy_date_range

    start, end = get_fy_date_range(fy)
    return visible_findings(principal).aggregate(
        in_review=Count("id", filter=Q(status=IN_REVIEW)),
        returned=Count("id", filter=Q(status=RETURNED)),
        approved_this_year=Count(
            "id",
            filter=Q(status=APPROVED, reviewed_at__gte=start, reviewed_at__lte=end),
        ),
    )


def approved_findings(principal, *, programme: str = ""):
    """Approved findings the reader may read — what reports cite."""
    qs = visible_findings(principal).filter(status=APPROVED)
    if programme in PROGRAMME_LABELS:
        qs = qs.filter(programme=programme)
    return qs.order_by("-reviewed_at")


def waiting_for(principal) -> dict:
    """What a person has to do on findings, for the To-Do builder: two
    queries at most."""
    role = _role(principal)
    me = _uid(principal)
    out = {"to_review": [], "returned": []}
    if role not in (IA, CD):
        return out
    rows = list(
        visible_findings(principal)
        .filter(status__in=(IN_REVIEW, RETURNED))
        .values("id", "status", "author_id", "country", "submitted_at", "updated_at")
    )
    in_review = [r for r in rows if r["status"] == IN_REVIEW and r["author_id"] != me]
    if in_review:
        from apps.impact.review import _profile_country, ia_officer_ids

        country = _profile_country(principal)
        if role == IA:
            out["to_review"] = [r for r in in_review if r["country"] == country]
        else:
            officers = [str(i) for i in ia_officer_ids(country)] if country else []
            out["to_review"] = [
                r
                for r in in_review
                if r["country"] == country
                and not [i for i in officers if i != r["author_id"]]
            ]
    if role == IA:
        out["returned"] = [
            r for r in rows if r["status"] == RETURNED and r["author_id"] == me
        ]
    return out
