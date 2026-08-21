"""HR exceptions — what needs a person, derived from workflow state.

HR held twenty-six To-Do builders' worth of platform and three of them ever
addressed HR, all inbound approvals. Everything else HR is accountable for —
an expiring work permit, a probation nobody reviewed, an employee with no
manager, an approved leave with nobody covering it — was reachable only by
opening the right register and reading it. Nothing looked for them.

This module looks for them. It follows the platform's To-Do law: nothing is
stored, every queue is a query over current state, and an item disappears the
moment the condition clears. There is no "mark done" and no way for a queue to
disagree with the records it came from.

Four groups, in the order HR triages them:

    waiting_on_hr      HR is the actor. Nothing moves until they act.
    manager_overdue    Someone else is the actor and has run late.
    people_risk        No single owner yet — a condition that needs a decision.
    deadlines          Nothing is wrong yet; it will be.

Scope is the viewer's country, the same rule the People register uses. HR is a
country function; a Uganda officer must not be triaging Kenya.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Count, Q, Sum

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
)
from apps.hr.models import (
    EmployeeComplianceRecord,
    OnboardingPlan,
    PerformancePriority,
    PerformanceReview,
)

# How long a decision may sit with its owner before it counts as late. These
# are deliberately generous: the queue must mean "nobody is dealing with this",
# never "this arrived yesterday".
LEAVE_DECISION_DAYS = 3
REVIEW_OVERDUE_DAYS = 0
DEADLINE_HORIZON_DAYS = 30

WAITING_ON_HR = "waiting_on_hr"
MANAGER_OVERDUE = "manager_overdue"
PEOPLE_RISK = "people_risk"
DEADLINES = "deadlines"

GROUP_LABELS = {
    WAITING_ON_HR: "Waiting on HR",
    MANAGER_OVERDUE: "Manager actions overdue",
    PEOPLE_RISK: "People-risk exceptions",
    DEADLINES: "Upcoming deadlines",
}


@dataclass
class HRException:
    """One thing a person must do, and enough to do it without searching."""

    group: str
    kind: str
    title: str
    detail: str
    url: str
    severity: str = "medium"  # critical | high | medium
    person: str = ""
    due_label: str = ""
    sort_key: tuple = field(default=(1, ""))

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "url": self.url,
            "severity": self.severity,
            "person": self.person,
            "due_label": self.due_label,
        }


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def scoped_profiles(principal):
    """The People records this viewer is accountable for.

    Mirrors `_profile_scope` in the HR views: Admin org-wide, a Program Lead
    their own team, everyone else their country. A viewer with no People
    record of their own has no scope — that is a data-quality problem the
    exception queue itself reports, not something to paper over here.
    """
    profiles = StaffProfile.objects.select_related("user").filter(
        user__deleted_at__isnull=True
    )
    role = getattr(principal, "active_role", "")
    if role == "Admin":
        return profiles
    viewer = getattr(principal, "staff_profile", None)
    if role in {"Program Lead", "ProgramLead"} and viewer:
        return profiles.filter(
            Q(id=viewer.id) | Q(supervisor_links__supervisor=viewer)
        ).distinct()
    if viewer and viewer.country:
        return profiles.filter(country=viewer.country)
    return profiles.none()


def _name(profile) -> str:
    user = getattr(profile, "user", None)
    return getattr(user, "name", None) or getattr(user, "email", "") or "Staff member"


def _days_ago_label(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    return f"{days} days"


def _due_label(target: date, today: date) -> str:
    delta = (target - today).days
    if delta < 0:
        return f"{abs(delta)} days overdue"
    if delta == 0:
        return "due today"
    if delta == 1:
        return "due tomorrow"
    return f"in {delta} days"


# ── Waiting on HR ────────────────────────────────────────────────────────────


def _escalated_leave(profile_ids, today) -> list[HRException]:
    out = []
    rows = (
        Leave.objects.filter(status="hr_review", staff_id__in=profile_ids)
        .select_related("staff__user")
        .order_by("created_at")[:50]
    )
    for leave in rows:
        waited = (today - leave.created_at.date()).days
        out.append(
            HRException(
                group=WAITING_ON_HR,
                kind="leave_escalated",
                title="Leave escalated to HR",
                detail=(
                    f"{leave.type.replace('_', ' ').title()}, "
                    f"{leave.start_date} to {leave.end_date}. "
                    f"Waiting {_days_ago_label(waited)}."
                ),
                url=f"/leave/approvals?id={leave.id}",
                severity="high" if waited >= LEAVE_DECISION_DAYS else "medium",
                person=_name(leave.staff),
                due_label=f"waiting {_days_ago_label(waited)}",
                sort_key=(0, -waited),
            )
        )
    return out


def _pd_awaiting_hr(profile_ids, today) -> list[HRException]:
    from apps.professional_development.models import ProfessionalDevelopmentRequest

    out = []
    rows = ProfessionalDevelopmentRequest.objects.filter(
        staff_id__in=profile_ids,
        status__in=("submitted_to_hr", "pending_exception", "awaiting_hr_signoff"),
    ).order_by("submitted_at")[:50]
    labels = {
        "submitted_to_hr": "Professional Development request needs HR review",
        "pending_exception": "Professional Development exception needs HR",
        "awaiting_hr_signoff": "Professional Development completion needs HR sign-off",
    }
    for req in rows:
        out.append(
            HRException(
                group=WAITING_ON_HR,
                kind=f"pd_{req.status}",
                title=labels[req.status],
                detail=f"{req.course_name or 'Course'} — {req.staff_name or ''}".strip(
                    " —"
                ),
                url=f"/my-professional-development/request?id={req.id}",
                severity="high" if req.status == "pending_exception" else "medium",
                person=req.staff_name or "",
                sort_key=(0, 0),
            )
        )
    return out


def _policies_awaiting_publication(principal) -> list[HRException]:
    """A policy that has cleared review and is sitting unpublished."""
    from apps.documents.models import DocumentAsset

    role = getattr(principal, "active_role", "")
    if role not in ("HumanResources", "Human Resources", "Admin"):
        return []
    out = []
    rows = DocumentAsset.objects.filter(
        status__in=("approved", "under_review", "returned"), archived_at__isnull=True
    ).order_by("updated_at")[:25]
    for doc in rows:
        waiting_label = {
            "approved": "Approved and waiting to be published",
            "under_review": "Waiting for a reviewer's decision",
            "returned": "Returned for revision",
        }[doc.status]
        out.append(
            HRException(
                group=WAITING_ON_HR,
                kind=f"policy_{doc.status}",
                title=waiting_label,
                detail=doc.title,
                url=f"/documents/{doc.slug}/manage",
                severity="medium",
                sort_key=(0, 0),
            )
        )
    return out


def _probation_decisions_due(profile_ids, today) -> list[HRException]:
    out = []
    rows = (
        OnboardingPlan.objects.filter(
            staff_id__in=profile_ids,
            probation_review_date__isnull=False,
            probation_review_date__lte=today,
        )
        .exclude(status="closed")
        .select_related("staff__user")
        .order_by("probation_review_date")[:50]
    )
    for plan in rows:
        out.append(
            HRException(
                group=WAITING_ON_HR,
                kind="probation_decision_due",
                title="Probation decision due",
                detail=(
                    f"Probation review date was "
                    f"{plan.probation_review_date.isoformat()}. Confirm, extend "
                    f"or end."
                ),
                url="/onboarding",
                severity="high",
                person=_name(plan.staff),
                due_label=_due_label(plan.probation_review_date, today),
                sort_key=(0, 0),
            )
        )
    return out


# ── Manager actions overdue ──────────────────────────────────────────────────


def _leave_decisions_overdue(profile_ids, today) -> list[HRException]:
    cutoff = today - timedelta(days=LEAVE_DECISION_DAYS)
    out = []
    rows = (
        Leave.objects.filter(
            status="pending", staff_id__in=profile_ids, created_at__date__lte=cutoff
        )
        .select_related("staff__user")
        .order_by("created_at")[:50]
    )
    for leave in rows:
        waited = (today - leave.created_at.date()).days
        out.append(
            HRException(
                group=MANAGER_OVERDUE,
                kind="leave_decision_overdue",
                title="Leave request has no decision",
                detail=(
                    f"Submitted {_days_ago_label(waited)} ago and still pending "
                    f"with the manager."
                ),
                url=f"/leave/approvals?id={leave.id}",
                severity="high" if waited >= LEAVE_DECISION_DAYS * 2 else "medium",
                person=_name(leave.staff),
                due_label=f"waiting {_days_ago_label(waited)}",
                sort_key=(1, -waited),
            )
        )
    return out


def _reviews_overdue(profile_ids, today) -> list[HRException]:
    out = []
    rows = (
        PerformanceReview.objects.filter(
            staff_id__in=profile_ids,
            due_date__isnull=False,
            due_date__lt=today - timedelta(days=REVIEW_OVERDUE_DAYS),
        )
        .exclude(stage__in=("closed", "signed_and_archived"))
        .exclude(status__in=("Completed", "Closed"))
        .select_related("staff__user")
        .order_by("due_date")[:50]
    )
    for review in rows:
        late = (today - review.due_date).days
        out.append(
            HRException(
                group=MANAGER_OVERDUE,
                kind="review_overdue",
                title="Performance review overdue",
                detail=f"{review.period or review.fy or ''} review is {late} days late.".strip(),
                url=f"/performance-conversation?staff={review.staff_id}",
                severity="high" if late > 14 else "medium",
                person=_name(review.staff),
                due_label=_due_label(review.due_date, today),
                sort_key=(1, -late),
            )
        )
    return out


# ── People risk ──────────────────────────────────────────────────────────────


def _staff_without_supervisor(profiles, today) -> list[HRException]:
    """No manager — or a link that cannot actually carry the review.

    A bare "has a supervisor row" test passed people whose only link was an
    oversight row, or whose manager had been suspended. The rule applied here
    is the one apps.hr.review_authority enforces at the write path, so this
    queue cannot disagree with what the engine will allow.

    Resolved in two queries for the whole roster rather than one per person —
    an exception queue that costs a query per employee stops being usable at
    exactly the headcount where HR starts needing it.
    """
    from apps.hr.review_authority import LIVE_STATES, REVIEWER_ROLE_FOR

    active = list(
        profiles.filter(onboarding_state="active").select_related("user")[:500]
    )
    if not active:
        return []

    links = StaffSupervisorAssignment.objects.filter(
        supervisee_id__in=[p.id for p in active],
        supervisor__user__is_active=True,
        supervisor__user__deleted_at__isnull=True,
        supervisor__onboarding_state__in=LIVE_STATES,
    ).values_list("supervisee_id", "supervisor__user__active_role")

    any_link: set[str] = set()
    by_supervisee: dict[str, list[str]] = {}
    for supervisee_id, supervisor_role in links:
        any_link.add(supervisee_id)
        by_supervisee.setdefault(supervisee_id, []).append(supervisor_role)

    out = []
    for profile in active:
        role = getattr(getattr(profile, "user", None), "active_role", "")
        expected = REVIEWER_ROLE_FOR.get(role)
        if not expected:
            continue  # partner and support roles sit outside the review chain
        matches = [r for r in by_supervisee.get(profile.id, []) if r in expected]
        if len(matches) == 1:
            continue
        if len(matches) > 1:
            out.append(
                HRException(
                    group=PEOPLE_RISK,
                    kind="two_managers",
                    title="Employee has two managers",
                    detail=(
                        "Two people hold the reporting line, so it is "
                        "undefined who conducts their review."
                    ),
                    url="/org-structure",
                    severity="high",
                    person=_name(profile),
                    sort_key=(2, 0),
                )
            )
            continue
        has_row = profile.id in any_link
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="no_supervisor",
                title=(
                    "Employee's manager cannot review them"
                    if has_row
                    else "Active employee has no manager"
                ),
                detail=(
                    "Their reporting link is an oversight row, not the "
                    "reporting line, so nobody can conduct their review."
                    if has_row
                    else "Nobody can approve their leave, review their "
                    "performance or receive their escalations."
                ),
                url="/org-structure",
                severity="high",
                person=_name(profile),
                sort_key=(2, 0),
            )
        )
    return out[:50]


def _users_without_people_record(principal) -> list[HRException]:
    """An account that can sign in but has no People record behind it."""
    from apps.accounts.models import User

    role = getattr(principal, "active_role", "")
    if role not in ("HumanResources", "Human Resources", "Admin"):
        return []
    rows = User.objects.filter(
        is_active=True, deleted_at__isnull=True, staff_profile__isnull=True
    ).order_by("name")[:50]
    return [
        HRException(
            group=PEOPLE_RISK,
            kind="no_people_record",
            title="Account has no People record",
            detail=(
                "They can sign in, but hold no country, department, manager or "
                "performance agreement — and appear in no HR report."
            ),
            url="/admin-panel/users",
            severity="high",
            person=user.name or user.email,
            sort_key=(2, 0),
        )
        for user in rows
    ]


def _leave_without_coverage(profile_ids, today) -> list[HRException]:
    horizon = (today + timedelta(days=14)).isoformat()
    today_iso = today.isoformat()
    covered = set(
        TemporaryCoverageAssignment.objects.filter(status="active").values_list(
            "leave_request_id", flat=True
        )
    )
    out = []
    rows = (
        Leave.objects.filter(
            status="approved",
            staff_id__in=profile_ids,
            end_date__gte=today_iso,
            start_date__lte=horizon,
            covering_staff__isnull=True,
        )
        .select_related("staff__user")
        .order_by("start_date")[:50]
    )
    for leave in rows:
        if leave.id in covered:
            continue
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="leave_without_coverage",
                title="Approved leave with nobody covering",
                detail=(
                    f"{leave.start_date} to {leave.end_date}. Their approvals "
                    f"and To-Dos stay with them while they are away."
                ),
                url="/leave/coverage",
                severity="high",
                person=_name(leave.staff),
                due_label=f"starts {leave.start_date}",
                sort_key=(2, 0),
            )
        )
    return out


def _agreements_missing_or_malformed(profiles, today) -> list[HRException]:
    """No agreement at all, or weights that do not total 100."""
    from apps.core.fy import get_operational_fy

    fy = get_operational_fy()
    active = profiles.filter(onboarding_state="active")
    active_ids = list(active.values_list("id", flat=True))
    if not active_ids:
        return []
    reviews = PerformanceReview.objects.filter(
        staff_id__in=active_ids, fy=fy, review_type="annual_priorities"
    )
    with_agreement = set(reviews.values_list("staff_id", flat=True))
    out = []
    for profile in active.exclude(id__in=with_agreement)[:50]:
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="no_agreement",
                title="Active employee has no performance agreement",
                detail=(
                    f"No FY{fy} agreement, so none of their delivery counts "
                    f"towards anything."
                ),
                url="/hr/performance-cycle",
                severity="high",
                person=_name(profile),
                sort_key=(2, 0),
            )
        )

    # Weight totals were validated on one write path only, so an agreement
    # created any other way could carry weights summing to anything at all and
    # silently skew every weighted score built on it.
    totals = (
        PerformancePriority.objects.filter(review__in=reviews)
        .values("review_id", "review__staff_id")
        .annotate(total=Sum("weight"), rows=Count("id"))
    )
    for row in totals:
        if not row["rows"] or row["total"] == 100:
            continue
        profile = next(
            (p for p in active if p.id == row["review__staff_id"]),
            None,
        )
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="weights_not_100",
                title="Priority weights do not total 100",
                detail=(
                    f"They total {row['total']}, so every weighted score on "
                    f"this agreement is wrong."
                ),
                url=f"/performance-conversation?staff={row['review__staff_id']}",
                severity="high",
                person=_name(profile) if profile else "",
                sort_key=(2, 0),
            )
        )
    return out


def _departed_staff_holding_work(profiles, today) -> list[HRException]:
    """Suspended or exited people who still hold live responsibilities."""
    from apps.hr.offboarding_service import outstanding_work

    out = []
    # This is the one builder that costs a few queries per person, so it is
    # capped tighter than the rest and says so rather than truncating quietly.
    departed = profiles.filter(onboarding_state__in=("suspended", "exited"))
    total_departed = departed.count()
    gone = departed[:10]
    if total_departed > 10:
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="departed_review_truncated",
                title=f"{total_departed} departed employees to review",
                detail=("Showing the first 10. Open Offboarding for the full list."),
                url="/offboarding",
                severity="high",
                sort_key=(2, 0),
            )
        )
    for profile in gone:
        try:
            work = outstanding_work(profile)
        except Exception:  # noqa: BLE001 — a reporting queue never breaks a page
            continue
        held = [f"{count} {label}" for label, count in sorted(work.items()) if count]
        if not held:
            continue
        out.append(
            HRException(
                group=PEOPLE_RISK,
                kind="departed_holding_work",
                title=f"{profile.onboarding_state.title()} employee still holds work",
                detail="Still assigned: " + ", ".join(held) + ".",
                url="/offboarding",
                severity="critical",
                person=_name(profile),
                sort_key=(2, 0),
            )
        )
    return out


# ── Deadlines ────────────────────────────────────────────────────────────────


def _expiring_compliance(profile_ids, today) -> list[HRException]:
    horizon = today + timedelta(days=DEADLINE_HORIZON_DAYS)
    out = []
    rows = (
        EmployeeComplianceRecord.objects.filter(
            staff_id__in=profile_ids,
            expiry_date__isnull=False,
            expiry_date__lte=horizon,
        )
        .select_related("staff__user", "requirement")
        .order_by("expiry_date")[:50]
    )
    for record in rows:
        expired = record.expiry_date < today
        out.append(
            HRException(
                group=DEADLINES,
                kind="compliance_expiry",
                title=(
                    "Compliance document expired"
                    if expired
                    else "Compliance document expiring"
                ),
                detail=f"{record.requirement.name} — {record.expiry_date.isoformat()}.",
                url="/compliance-register",
                severity="high" if expired else "medium",
                person=_name(record.staff),
                due_label=_due_label(record.expiry_date, today),
                sort_key=(3, (record.expiry_date - today).days),
            )
        )
    return out


def _probation_ending(profile_ids, today) -> list[HRException]:
    horizon = today + timedelta(days=DEADLINE_HORIZON_DAYS)
    out = []
    rows = (
        OnboardingPlan.objects.filter(
            staff_id__in=profile_ids,
            probation_review_date__gt=today,
            probation_review_date__lte=horizon,
        )
        .exclude(status="closed")
        .select_related("staff__user")
        .order_by("probation_review_date")[:50]
    )
    for plan in rows:
        out.append(
            HRException(
                group=DEADLINES,
                kind="probation_ending",
                title="Probation period ending",
                detail=(
                    f"Review due {plan.probation_review_date.isoformat()} — a "
                    f"decision is needed before it lapses."
                ),
                url="/onboarding",
                severity="medium",
                person=_name(plan.staff),
                due_label=_due_label(plan.probation_review_date, today),
                sort_key=(3, (plan.probation_review_date - today).days),
            )
        )
    return out


def _policy_review_due(principal, today) -> list[HRException]:
    """A published policy reaching its own review date.

    `review_date` was collected on upload and read by nothing, so a policy
    could pass the date it declared for itself in silence.
    """
    from apps.documents.models import DocumentVersion

    role = getattr(principal, "active_role", "")
    if role not in ("HumanResources", "Human Resources", "Admin"):
        return []
    horizon = today + timedelta(days=DEADLINE_HORIZON_DAYS)
    out = []
    rows = (
        DocumentVersion.objects.filter(
            review_date__isnull=False,
            review_date__lte=horizon,
            document__status__in=("published", "effective"),
            superseded_at__isnull=True,
        )
        .select_related("document")
        .order_by("review_date")[:25]
    )
    for version in rows:
        out.append(
            HRException(
                group=DEADLINES,
                kind="policy_review_due",
                title=(
                    "Policy review date passed"
                    if version.review_date < today
                    else "Policy review date approaching"
                ),
                detail=(
                    f"{version.document.title} (v{version.version_number}) — "
                    f"{version.review_date.isoformat()}."
                ),
                url=f"/documents/{version.document.slug}/manage",
                severity="high" if version.review_date < today else "medium",
                due_label=_due_label(version.review_date, today),
                sort_key=(3, (version.review_date - today).days),
            )
        )
    return out


# ── Assembly ─────────────────────────────────────────────────────────────────

_BUILDERS_PROFILE_IDS = (
    _escalated_leave,
    _pd_awaiting_hr,
    _probation_decisions_due,
    _leave_decisions_overdue,
    _reviews_overdue,
    _leave_without_coverage,
    _expiring_compliance,
    _probation_ending,
)
_BUILDERS_PROFILES = (
    _staff_without_supervisor,
    _agreements_missing_or_malformed,
    _departed_staff_holding_work,
)
_BUILDERS_PRINCIPAL_ONLY = (
    _policies_awaiting_publication,
    _users_without_people_record,
)


def build_hr_exceptions(principal, today: date | None = None) -> list[HRException]:
    """Every open HR exception for this viewer, worst first."""
    today = today or date.today()
    profiles = scoped_profiles(principal)
    profile_ids = list(profiles.values_list("id", flat=True))

    items: list[HRException] = []
    if profile_ids:
        for build in _BUILDERS_PROFILE_IDS:
            items.extend(build(profile_ids, today))
        for build in _BUILDERS_PROFILES:
            items.extend(build(profiles, today))
    for build in _BUILDERS_PRINCIPAL_ONLY:
        items.extend(build(principal))
    items.extend(_policy_review_due(principal, today))

    items.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 3), i.sort_key))
    return items


def grouped_hr_exceptions(principal, today: date | None = None) -> dict:
    """The same items arranged for HR Today, with the four headline counts."""
    items = build_hr_exceptions(principal, today)
    groups = {key: [] for key in GROUP_LABELS}
    for item in items:
        groups[item.group].append(item.as_dict())
    return {
        "groups": [
            {"key": key, "label": GROUP_LABELS[key], "items": groups[key]}
            for key in (WAITING_ON_HR, MANAGER_OVERDUE, PEOPLE_RISK, DEADLINES)
        ],
        "counts": {key: len(value) for key, value in groups.items()},
        "critical_count": sum(1 for i in items if i.severity == "critical"),
        "total": len(items),
    }
