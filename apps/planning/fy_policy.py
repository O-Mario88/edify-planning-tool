"""Fiscal-year planning policy — the one place its questions are answered.

Every planning, scheduling, execution and follow-up surface asks here rather
than comparing dates or reading the table itself (owner, 2026-09-15). The
policy rows live in ``apps.planning.fy_policy_models``; FY arithmetic stays in
``apps.core.fy``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy

from .fy_policy_models import FiscalYearPlanningPolicy

#: The first fiscal year the platform ever planned (apps.core.fy.fy_options).
FIRST_FY = 2025


def default_country() -> str:
    return getattr(settings, "COUNTRY", "Uganda") or "Uganda"


def policy_for(fy, country: str | None = None) -> FiscalYearPlanningPolicy | None:
    """The policy row for one fiscal year, cached for the request."""
    if not fy:
        return None
    country = country or default_country()
    from apps.core.request_cache import memoize

    return memoize(
        ("fy_planning_policy", country, str(fy)),
        lambda: FiscalYearPlanningPolicy.objects.filter(
            country=country, fy=str(fy)
        ).first(),
    )


def _as_datetime(at) -> datetime:
    if at is None:
        return timezone.now()
    if isinstance(at, datetime):
        return at if timezone.is_aware(at) else timezone.make_aware(at)
    return timezone.make_aware(datetime(at.year, at.month, at.day, 12))


def is_planning_open(fy, *, at=None, country: str | None = None) -> bool:
    """Whether a fiscal year may be planned now.

    The operational year and every earlier year stay plannable, exactly as
    before. A later year is plannable once its policy's ``planning_open_at``
    has passed — never without a row.
    """
    at = _as_datetime(at)
    operational = int(get_operational_fy(at))
    try:
        target = int(fy)
    except (TypeError, ValueError):
        return False
    if target <= operational:
        return True
    policy = policy_for(fy, country)
    return bool(policy and policy.planning_open_at and policy.planning_open_at <= at)


def plannable_fys(*, at=None, country: str | None = None) -> list[str]:
    """Fiscal years a planner may choose now, oldest first."""
    at = _as_datetime(at)
    operational = int(get_operational_fy(at))
    years = [str(y) for y in range(FIRST_FY, operational + 1)]
    for policy in FiscalYearPlanningPolicy.objects.filter(
        country=country or default_country(),
        planning_open_at__lte=at,
    ).order_by("fy"):
        if int(policy.fy) > operational and policy.fy not in years:
            years.append(policy.fy)
    return years


def next_open_policy(
    *, at=None, country: str | None = None
) -> FiscalYearPlanningPolicy | None:
    """The policy of the nearest future fiscal year open for planning now."""
    at = _as_datetime(at)
    operational = int(get_operational_fy(at))
    from apps.core.request_cache import memoize

    def compute():
        from django.db.models import Exists, OuterRef

        from apps.budget.models import CostCatalogue, RateCardKind, RateCardStatus

        # Whether the year has its published operational rate card, read in
        # the same query: the To-Do queue asks both questions on every load.
        has_card = Exists(
            CostCatalogue.objects.filter(
                country=OuterRef("country"),
                fy=OuterRef("fy"),
                kind=RateCardKind.OPERATIONAL,
                status=RateCardStatus.PUBLISHED,
                is_active=True,
            )
        )
        for policy in (
            FiscalYearPlanningPolicy.objects.filter(
                country=country or default_country(), planning_open_at__lte=at
            )
            .annotate(has_operational_rate_card=has_card)
            .order_by("fy")
        ):
            if int(policy.fy) > operational:
                return policy
        return None

    return memoize(
        ("fy_next_open_policy", country or default_country(), operational), compute
    )


def next_open_fy(*, at=None, country: str | None = None) -> str | None:
    """The future fiscal year open for planning now, if there is one."""
    policy = next_open_policy(at=at, country=country)
    return policy.fy if policy else None


def _format(day: date) -> str:
    return f"{day:%-d %B %Y}"


def assert_date_plannable(scheduled_for, *, at=None, country: str | None = None):
    """Refuse a date that has passed. Today onwards is plannable.

    Two rules, both the owner's, 2026-09-16.

    The fiscal year a date falls in no longer decides whether it may be
    planned. Planning ran into a wall every 1 October: a year had to be opened
    before anyone could put a school visit, cluster meeting or cluster
    training into it, and a team planning the term ahead was told to "ask the
    Country Director" for a date four weeks away. Staff now schedule as far
    forward as they need, in whichever year the date lands.

    And work is scheduled forward, never backward: "users cannot schedule
    backward like yesterday", and "it can be today onwards but not yesterday
    or any date before today". Today itself is still a working day, so it is
    still a date somebody may plan on.

    This is a change of principle, not a tightening. Scheduling used to be
    deliberately independent of the current date (REG-02), which is why work
    could be entered against a day that had passed. Anything that needs to
    record what already happened does it through completion and evidence,
    which is a different question asked elsewhere — as are the two the fiscal
    year still governs: `assert_may_execute` keeps work from being delivered
    before its year begins on 1 October, and `assert_same_fiscal_year` keeps a
    reschedule from re-stamping an activity's budget line into another year.
    Pricing no longer asks the year at all; the cost catalogue is universal.
    """
    if scheduled_for is None:
        return
    day = scheduled_for.date() if isinstance(scheduled_for, datetime) else scheduled_for
    today = _as_datetime(at).astimezone(timezone.get_current_timezone()).date()
    if day < today:
        raise BadRequest(
            f"{_format(day)} has passed. Schedule work from {_format(today)} onwards."
        )


def assert_may_execute(activity, *, today: date | None = None) -> None:
    """Nothing. The fiscal year no longer gates delivery.

    Owner, 2026-09-17: "can you make sure all restrictions are lifted
    throughout the platform", after the core package's fiscal-year refusal was
    lifted and turned out to be one of several.

    This refused starting, completing or submitting evidence for work before
    its year's execution_start — so a team that had planned the term ahead
    (which 2026-09-16 deliberately allowed: "staff now schedule as far forward
    as they need") could enter the work and then not deliver it. Planning
    forward and being unable to act on what you planned is the same wall in a
    different place.

    Kept as a no-op rather than deleted: it is called from four places in
    apps.activities.services, and a function that does nothing is clearer at
    those call sites than four deletions that leave nobody able to see the
    rule is gone.
    """
    return None


def assert_same_fiscal_year(old_date, new_date) -> None:
    """Nothing. A reschedule may cross 30 September (owner, 2026-09-17).

    This refused moving an activity into another fiscal year, because doing so
    re-stamps its FY and with it the budget line, fund request and target
    credit. The refusal told the planner to cancel and re-plan instead — two
    steps, a lost audit trail and a new activity id, to move one date.

    The re-stamping it guarded against is real, and it is the reschedule's job
    to carry it: `reschedule` in apps.activities.services already rewrites the
    activity's fy and quarter with the new date and moves the money with it.
    What this added was the refusal, not the correctness.

    A no-op rather than a deletion, for the same reason as `assert_may_execute`
    above.
    """
    return None


def follow_up_requires_prior_training(fy, country: str | None = None) -> bool:
    """Whether a school visit follow-up must name a completed training.

    True without a policy row — the rule the platform has always had.
    """
    policy = policy_for(fy, country)
    return True if policy is None else policy.follow_up_visit_requires_prior_training


# ── Governance writes ────────────────────────────────────────────────────────
def may_manage(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return bool(
        getattr(principal, "is_superuser", False)
        or has_permission(principal, Permission.PLANNING_POLICY_MANAGE.value)
    )


def _actor(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


@transaction.atomic
def open_fy_planning(
    fy: str,
    principal,
    *,
    planning_open_at: datetime | None = None,
    follow_up_visit_requires_prior_training: bool | None = None,
    notes: str = "",
    country: str | None = None,
) -> FiscalYearPlanningPolicy:
    """Open a fiscal year for planning (idempotent), audited and announced."""
    from apps.core.fy import get_fy_date_range

    if not may_manage(principal):
        raise Forbidden("Only the Country Director or Admin opens a fiscal year.")
    country = country or default_country()
    start, end = get_fy_date_range(str(fy))
    policy, created = (
        FiscalYearPlanningPolicy.objects.select_for_update().get_or_create(
            country=country,
            fy=str(fy),
            defaults={
                "execution_start": start.date(),
                "execution_end": end.date() - timedelta(days=1),
            },
        )
    )
    previous = {
        "planningOpenAt": policy.planning_open_at.isoformat()
        if policy.planning_open_at
        else None,
        "followUpRequiresTraining": policy.follow_up_visit_requires_prior_training,
    }
    was_open = bool(
        policy.planning_open_at and policy.planning_open_at <= timezone.now()
    )
    policy.planning_open_at = (
        planning_open_at or policy.planning_open_at or timezone.now()
    )
    if follow_up_visit_requires_prior_training is not None:
        policy.follow_up_visit_requires_prior_training = (
            follow_up_visit_requires_prior_training
        )
    policy.opened_by = policy.opened_by or _actor(principal)
    policy.updated_by = _actor(principal)
    if notes:
        policy.notes = notes
    policy.save()
    from apps.audit.services import log as audit_log

    audit_log(
        action="fy.planning_opened" if not was_open else "fy.planning_policy_updated",
        subject_kind="fiscal_year_planning_policy",
        subject_id=policy.id,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=notes or None,
        payload={
            "fy": policy.fy,
            "country": policy.country,
            "previous": None if created else previous,
            "new": {
                "planningOpenAt": policy.planning_open_at.isoformat(),
                "executionStart": policy.execution_start.isoformat(),
                "executionEnd": policy.execution_end.isoformat(),
                "followUpRequiresTraining": policy.follow_up_visit_requires_prior_training,
            },
        },
    )
    if not was_open:
        transaction.on_commit(lambda: announce_fy_planning(policy.id))
    return policy


@transaction.atomic
def set_follow_up_rule(
    fy: str, requires_prior_training: bool, principal, *, reason: str
) -> FiscalYearPlanningPolicy:
    """Turn the follow-up training prerequisite on or off for one year."""
    if not may_manage(principal):
        raise Forbidden("Only the Country Director or Admin changes this rule.")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("Give the reason the follow-up rule changes.")
    policy = (
        FiscalYearPlanningPolicy.objects.select_for_update()
        .filter(country=default_country(), fy=str(fy))
        .first()
    )
    if policy is None:
        raise BadRequest(f"FY{fy} has no planning policy yet. Open the year first.")
    previous = policy.follow_up_visit_requires_prior_training
    policy.follow_up_visit_requires_prior_training = bool(requires_prior_training)
    policy.updated_by = _actor(principal)
    policy.save(
        update_fields=[
            "follow_up_visit_requires_prior_training",
            "updated_by",
            "updated_at",
        ]
    )
    from apps.audit.services import log as audit_log

    audit_log(
        action="planning.follow_up_rule_changed",
        subject_kind="fiscal_year_planning_policy",
        subject_id=policy.id,
        actor_id=_actor(principal),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "fy": policy.fy,
            "previous": {"followUpRequiresTraining": previous},
            "new": {
                "followUpRequiresTraining": policy.follow_up_visit_requires_prior_training
            },
        },
    )
    return policy


def announce_fy_planning(policy_id: str) -> int:
    """Tell the people who plan that a fiscal year is open. Idempotent: the
    notification service keeps one live notice per recipient and policy."""
    import logging

    try:
        policy = FiscalYearPlanningPolicy.objects.filter(id=policy_id).first()
        if policy is None:
            return 0
        from apps.notifications.services import WorkflowNotificationService

        created = WorkflowNotificationService.trigger(
            event_type="fy_planning_opened",
            category="planning",
            priority="normal",
            title=f"FY{policy.fy} is open for planning",
            body=(
                f"Plan FY{policy.fy} activities for dates from "
                f"{_format(policy.execution_start)}."
            ),
            context_type="fiscal_year_planning_policy",
            context_id=policy.id,
            recipients=planners(),
        )
        return len(created)
    except Exception:  # noqa: BLE001 - an announcement never undoes the policy
        logging.getLogger(__name__).warning(
            "FY planning announcement failed for %s", policy_id, exc_info=True
        )
        return 0


def window_state(policy, *, at=None, operational: str | None = None) -> str:
    """How a fiscal year reads today: one phrase for the governed page.

    Derived, never stored. A year the platform is operating is "Operational";
    one it has finished with is "Closed year"; a future year is "Open for
    planning" once its opening moment has passed, and "Not open" until then.
    """
    from apps.core.fy import get_operational_fy

    now = at or timezone.now()
    operational = operational or get_operational_fy()
    try:
        year, current = int(policy.fy), int(operational)
    except (TypeError, ValueError):
        return "Not open"
    if year <= current:
        return "Operational" if year == current else "Closed year"
    if policy.planning_open_at and policy.planning_open_at <= now:
        return "Open for planning"
    return "Not open"


def planners() -> list:
    """Active staff whose roles plan field work."""
    from apps.accounts.models import User
    from apps.core.rbac import EdifyRole

    planning_roles = [
        EdifyRole.CCEO.value,
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        EdifyRole.PROJECT_COORDINATOR.value,
    ]
    from django.db.models import Q

    q = Q()
    for role in planning_roles:
        q |= Q(roles__contains=[role])
    return list(User.objects.filter(q, is_active=True, deleted_at__isnull=True))


__all__ = [
    "announce_fy_planning",
    "assert_date_plannable",
    "assert_may_execute",
    "assert_same_fiscal_year",
    "follow_up_requires_prior_training",
    "is_planning_open",
    "may_manage",
    "next_open_fy",
    "next_open_policy",
    "open_fy_planning",
    "plannable_fys",
    "policy_for",
    "set_follow_up_rule",
    "window_state",
]
