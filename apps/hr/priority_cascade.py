"""PriorityCascadeService — one strategy, many role-appropriate measures.

The rule this module exists to make structural: *the same strategic priority
must not assign the same metric to every role.* Before it, priorities were
generated from ``RolePriorityTemplate``, keyed by role, so each role carried an
independent list with no shared parent. That arrangement cannot express the
rule, because there is no single priority the roles are translations OF — and
it cannot be violated either, which is why the gap was invisible.

The cascade runs top-down and each step narrows:

    RVP publishes a regional priority
      → CD translates it into a country priority (parent link preserved)
        → a per-role rule says HOW each role carries it
          → the draft agreement renders that rule as one commitment
            → the approved commitment feeds My Targets / Team Targets

What each layer may and may not do is the design:

  The RVP and CD author STRATEGY — purpose, expected result, minimum standard,
  a weighting RANGE. They never write an individual's milestones. That is the
  brief's central instruction and the reason weight is a range rather than a
  number: the figure is a manager conversation inside bounds leadership set.

  The per-role rule decides ACCOUNTABILITY — execute, supervise, verify,
  finance, or explicitly not applicable. A role that should not carry a
  priority is recorded as NOT_APPLICABLE rather than omitted, because an
  absent row is indistinguishable from an oversight, and an accountant
  silently inheriting a school-visit target is exactly the failure being
  designed out.

  The employee and manager own the MILESTONES and phasing. They may not change
  a mandatory priority's metric, and may not remove it at all.

Nothing here writes progress. Progress is derived live from the verified
ledger by ``performance_engine.live_progress`` — a cascade that copied numbers
forward would drift from the data the moment either side changed.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

# Who may author at each level. Kept here rather than inline so the answer to
# "who sets strategy" is one list, not a condition repeated at every call site.
REGIONAL_AUTHOR_ROLES = ("RegionalVicePresident", "Admin")
COUNTRY_AUTHOR_ROLES = ("CountryDirector", "Admin")

# Spec §3 — who holds the priority-setting conversation with whom. The cascade
# decides WHAT is discussed; this decides WITH WHOM, and the two are separate
# on purpose: changing a reporting line must not silently re-author strategy.
PRIORITY_SETTING_MANAGER = {
    "CCEO": "Program Lead",
    "Program Lead": "CountryDirector",
    "ImpactAssessment": "CountryDirector",
    "ProjectCoordinator": "CountryDirector",
    "Accountant": "CountryDirector",
    "HumanResources": "RegionalVicePresident",
    "CountryDirector": "RegionalVicePresident",
    "RegionalVicePresident": "Admin",
}


def manager_role_for(role: str) -> str | None:
    """The role that holds this role's priority-setting conversation."""
    return PRIORITY_SETTING_MANAGER.get(role)


def _actor_id(principal) -> str | None:
    """The acting user's id, whether we were handed a principal or a User.

    Both reach this module — the services pass a principal with ``user_id``,
    the views pass ``request.user``. Reading only one of the two silently
    leaves ``published_by`` null, so the audit trail loses the person who made
    the priority binding while everything else still works.
    """
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


def _assert_can_author(principal, level: str) -> None:
    from apps.hr.models import StrategicPriorityLevel

    active = getattr(principal, "active_role", None)
    allowed = (
        REGIONAL_AUTHOR_ROLES
        if level == StrategicPriorityLevel.REGIONAL
        else COUNTRY_AUTHOR_ROLES
    )
    if active not in allowed:
        raise Forbidden(
            f"{active or 'This role'} cannot author {level} strategic priorities."
        )


def publish(priority, principal):
    """Publish a strategic priority so it can cascade.

    Publication is the moment the priority becomes a contract, so the checks
    that matter run here rather than at draft time — a half-written strategy
    should be savable, just not bindable.
    """
    from apps.hr.models import (
        PriorityAccountability,
        StrategicPriorityStatus,
    )

    _assert_can_author(principal, priority.level)

    rules = list(priority.role_rules.all())
    if not rules:
        raise BadRequest(
            "A strategic priority cannot be published without role rules — "
            "with none, it reaches nobody and silently measures nothing."
        )

    # Every role that carries the priority must name the canonical metric its
    # progress comes from. Publishing without one produces a commitment that
    # can never be evidenced, which is worse than no commitment: it looks
    # measured at the conversation and is not.
    unmeasurable = [
        rule.role
        for rule in rules
        if rule.accountability != PriorityAccountability.NOT_APPLICABLE
        and not (rule.metric_key or "").strip()
    ]
    if unmeasurable:
        raise BadRequest(
            "These roles carry the priority but name no canonical metric, so "
            f"their progress could never be derived: {', '.join(sorted(unmeasurable))}"
        )

    # Naming a metric is not the same as naming one that exists. An unknown
    # key is not an error anywhere downstream — `live_progress` falls through
    # every branch and returns actual=0 — so the commitment reads as 0%
    # forever and looks like an employee failing rather than a typo.
    from apps.hr.performance_engine import METRIC_KEYS

    unknown = sorted(
        {
            rule.metric_key
            for rule in rules
            if rule.accountability != PriorityAccountability.NOT_APPLICABLE
            and (rule.metric_key or "").strip()
            and rule.metric_key not in METRIC_KEYS
        }
    )
    if unknown:
        raise BadRequest(
            "These measures are not canonical metrics the platform computes, "
            f"so they would report 0% forever: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(METRIC_KEYS))}."
        )

    if priority.weight_max < priority.weight_min:
        raise BadRequest("The weighting range runs backwards.")

    priority.status = StrategicPriorityStatus.PUBLISHED
    priority.published_at = timezone.now()
    priority.published_by_id = _actor_id(principal)
    priority.save(
        update_fields=["status", "published_at", "published_by", "updated_at"]
    )

    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="hr.strategic_priority_published",
            subject_kind="StrategicPriority",
            subject_id=priority.id,
            actor_id=_actor_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "fy": priority.fy,
                "level": priority.level,
                "roles": sorted(r.role for r in rules),
            },
        )
    except Exception:  # noqa: BLE001 — publication must not fail on audit
        pass
    return priority


def rules_for_role(role: str, fy: str, country_id: str | None = None) -> list:
    """Every published rule that applies to this role, most specific first.

    Country priorities take precedence over the regional priorities they
    translate: a CD who has rendered regional direction into country terms has
    said something more specific, and applying both would give the employee
    two commitments for one strategic intent.
    """
    from apps.hr.models import (
        PriorityAccountability,
        StrategicPriorityLevel,
        StrategicPriorityRoleRule,
        StrategicPriorityStatus,
    )

    published = StrategicPriorityRoleRule.objects.filter(
        role=role,
        priority__fy=fy,
        priority__status=StrategicPriorityStatus.PUBLISHED,
    ).select_related("priority")

    if country_id:
        published = published.filter(
            models_q_country(country_id)  # regional rows carry no country
        )

    country_rules, regional_rules = [], []
    for rule in published:
        if rule.priority.level == StrategicPriorityLevel.COUNTRY:
            country_rules.append(rule)
        else:
            regional_rules.append(rule)

    # A regional rule is dropped when a country priority already translates it.
    translated_parents = {
        r.priority.parent_id for r in country_rules if r.priority.parent_id
    }
    effective = country_rules + [
        r for r in regional_rules if r.priority_id not in translated_parents
    ]

    # NOT_APPLICABLE is a deliberate exemption, not a commitment. It is kept in
    # the model so the decision is reviewable, and dropped here so it never
    # becomes a row on somebody's agreement.
    return [
        rule
        for rule in effective
        if rule.accountability != PriorityAccountability.NOT_APPLICABLE
    ]


def models_q_country(country_id: str):
    """Rows for this country, plus regional rows (which carry no country)."""
    from django.db.models import Q

    return Q(priority__country_id=country_id) | Q(priority__country_id__isnull=True)


@transaction.atomic
def apply_to_review(review, role: str, denominators: dict | None = None) -> int:
    """Render every applicable strategic rule onto a draft agreement.

    Idempotent per (review, rule): re-running after a newly published priority
    tops the agreement up rather than duplicating what is already there, so HR
    can publish late and re-cascade without rebuilding drafts by hand.

    Returns how many commitments were added.
    """
    from apps.hr.models import PerformancePriority

    denominators = denominators or {}
    country_id = getattr(review, "country_id", None)
    rules = rules_for_role(role, review.fy, country_id)
    if not rules:
        return 0

    existing_rule_ids = set(
        review.priorities.exclude(source_rule__isnull=True).values_list(
            "source_rule_id", flat=True
        )
    )
    next_sequence = max((p.sequence for p in review.priorities.all()), default=0) + 1

    added = 0
    for rule in rules:
        if rule.id in existing_rule_ids:
            continue
        denom = denominators.get(rule.metric_key)
        PerformancePriority.objects.create(
            review=review,
            sequence=next_sequence,
            priority_layer="org",
            strategic_alignment=rule.priority.title,
            outcome_statement=rule.outcome_statement,
            metric_key=rule.metric_key,
            weight=_clamp_weight(rule),
            target_number=denom,
            denominator_note=f"{denom} assigned schools" if denom else None,
            target=(
                rule.target_guidance
                or rule.priority.target_guidance
                or (f"100% of {denom}" if denom else "As agreed")
            ),
            source_rule=rule,
            is_mandatory=rule.priority.is_mandatory,
        )
        next_sequence += 1
        added += 1
    return added


def _clamp_weight(rule) -> int:
    """Keep a rule's default weight inside the priority's published range.

    A template weight that drifted outside the range leadership approved would
    otherwise be applied silently to every agreement built from it.
    """
    return max(
        rule.priority.weight_min, min(rule.default_weight, rule.priority.weight_max)
    )


def assert_removable(priority) -> None:
    """Refuse to drop a mandatory inherited commitment (§2A).

    Called by any path that would delete a priority from an agreement. The
    check reads the row's OWN mandatory flag rather than walking to the rule,
    so a retired strategic priority cannot quietly unlock commitments already
    signed against it.
    """
    if priority.is_mandatory:
        raise BadRequest(
            "This priority was inherited from a mandatory strategic priority "
            "and cannot be removed. Its milestones and phasing are open to "
            "discussion; whether it applies is not. Raise a PriorityAmendment "
            "if the target itself needs to change."
        )


def assert_metric_unchanged(priority, new_metric_key) -> None:
    """A mandatory commitment's metric belongs to the strategy, not the pair.

    Employees and managers own milestones, phasing and support needed. Letting
    them re-point the metric would keep the priority on the agreement while
    measuring something else — the appearance of the control without it.
    """
    if not priority.is_mandatory:
        return
    if (new_metric_key or None) != (priority.metric_key or None):
        raise BadRequest(
            "The measure for a mandatory strategic priority is set by the "
            "priority itself and cannot be changed on an individual agreement."
        )


def coverage_report(fy: str, country_id: str | None = None) -> dict:
    """Which published priorities reached which roles — HR's §3 validation.

    Answers the question HR cannot otherwise ask: was the strategy actually
    cascaded, or did it stop at publication? A priority with rules that reached
    zero agreements is published-but-inert, and looks identical to a working
    one on every screen except this.
    """
    from apps.hr.models import (
        PerformancePriority,
        StrategicPriority,
        StrategicPriorityStatus,
    )

    published = StrategicPriority.objects.filter(
        fy=fy, status=StrategicPriorityStatus.PUBLISHED
    ).prefetch_related("role_rules")
    if country_id:
        published = published.filter(models_q_country_direct(country_id))

    published = list(published)

    # One grouped query for every priority rather than one per priority. This
    # runs on a page load, and a per-priority count would grow with the very
    # thing the page exists to encourage — leadership publishing more strategy.
    from django.db.models import Count

    reach_counts = dict(
        PerformancePriority.objects.filter(source_rule__priority__in=published)
        .values_list("source_rule__priority_id")
        .annotate(staff=Count("review__staff_id", distinct=True))
    )

    rows = []
    for priority in published:
        reached = reach_counts.get(priority.id, 0)
        rows.append(
            {
                "priority_id": priority.id,
                "title": priority.title,
                "level": priority.level,
                "roles": sorted(r.role for r in priority.role_rules.all()),
                "staff_reached": reached,
                "inert": reached == 0,
            }
        )
    return {
        "fy": fy,
        "priorities": rows,
        "inert_count": sum(1 for r in rows if r["inert"]),
    }


def models_q_country_direct(country_id: str):
    from django.db.models import Q

    return Q(country_id=country_id) | Q(country_id__isnull=True)


__all__ = [
    "PRIORITY_SETTING_MANAGER",
    "manager_role_for",
    "publish",
    "rules_for_role",
    "apply_to_review",
    "assert_removable",
    "assert_metric_unchanged",
    "coverage_report",
]
