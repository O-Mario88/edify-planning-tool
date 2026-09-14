"""Most Significant Change story review (IA review, owner, 2026-09-13).

A story is submitted by the person who witnessed the change (My Targets, or a
field debrief's draft) and counts toward that person's MSCS target, and as
discipleship evidence, only once it is APPROVED. Until this module nothing in
production ever changed a story's status, so no story could ever count.

Impact Assessment reviews stories from its own country (/ia/stories/):

  approve  the story is credible evidence of change; the reviewer tags the
           outcome area it evidences (and, where one fits, the SSA domain), so
           an approved story feeds the outcome it describes;
  return   the author needs to add or correct something (a new submission);
  reject   the story is not evidence of change (a duplicate, an activity
           report, a story without a school change).

The reviewer is never the author (apps.impact.review.reviewer_basis: a second
IA officer in the author's country, or the Country Director where the author is
that country's only officer). Every decision is audited, tells the author, and
refreshes the author's target ledger so My Targets reflects it at once.

A story's country is the school's country, else the author's; stories with
neither belong to no country and are read only by an unbounded reader (Admin).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.fy import get_fy_date_range

from .models import MostSignificantChangeStory, MSCSStatus

DECISIONS = (
    ("approve", "Approve — counts as evidence of change"),
    ("return", "Return to the author"),
    ("reject", "Reject — not evidence of change"),
)
EVENT_REVIEWED = "mscs.story_reviewed"

#: The SSA domains spiritual formation is read through (see
#: apps.impact.framework.PROPOSED_OUTCOME_AREAS).
SPIRITUAL_DOMAINS = ("christlike_behaviour", "exposure_to_word_of_god")

REVIEWABLE = (MSCSStatus.SUBMITTED,)


def _uid(principal) -> str:
    return str(getattr(principal, "id", "") or getattr(principal, "user_id", ""))


def visible_stories(principal):
    """Stories in the reader's country: the school's country, else the
    author's. Admin and other unbounded readers see every story; a reader
    with no country authority sees none."""
    from apps.core.scoping import country_bound, country_user_ids, resolve_user_scope

    scope = resolve_user_scope(principal)
    stories = MostSignificantChangeStory.objects.all()
    if country_bound(scope):
        return stories.filter(
            Q(school__region__country=scope.country)
            | Q(school__isnull=True, user_id__in=country_user_ids(scope))
            | Q(school__isnull=True, country=scope.country)
        )
    if scope.country_scope:
        return stories
    return stories.none()


def spiritual_story_q() -> Q:
    """Approved stories that evidence spiritual formation: tagged with one of
    its SSA domains, or with an outcome area read through them."""
    from apps.impact.models import OutcomeAreaDomain

    return Q(intervention__in=SPIRITUAL_DOMAINS) | Q(
        outcome_area__in=OutcomeAreaDomain.objects.filter(
            intervention__in=SPIRITUAL_DOMAINS
        ).values("area__code")
    )


def fy_q(fy: str) -> Q:
    start, end = get_fy_date_range(fy)
    return Q(story_date__gte=start.date(), story_date__lt=end.date())


def outcome_area_options() -> list[tuple[str, str]]:
    """Outcome areas a story may be tagged with: the current version of each
    code that is not retired, drafts marked so the reviewer knows."""
    from apps.impact.models import DefinitionStatus, OutcomeArea

    seen: dict[str, tuple[str, str]] = {}
    for area in OutcomeArea.objects.exclude(
        status__in=(DefinitionStatus.RETIRED, DefinitionStatus.SUPERSEDED)
    ).order_by("code", "-version"):
        if area.code in seen:
            continue
        suffix = (
            "" if area.status == DefinitionStatus.APPROVED else " (not yet approved)"
        )
        seen[area.code] = (area.code, f"{area.name}{suffix}")
    return sorted(seen.values(), key=lambda pair: pair[1].lower())


def story_country(story) -> str:
    school = getattr(story, "school", None)
    region = getattr(school, "region", None) if school else None
    country = (getattr(region, "country", "") or "").strip()
    if country:
        return country
    if (story.country or "").strip():
        return story.country.strip()
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.filter(user_id=story.user_id)
        .values_list("country", flat=True)
        .first()
        or ""
    ).strip()


def review_basis(principal, story) -> str | None:
    from apps.impact.review import reviewer_basis

    if story.status not in REVIEWABLE:
        return None
    return reviewer_basis(
        principal, author_id=story.user_id, country=story_country(story)
    )


def decide(
    principal,
    story_id: str,
    *,
    decision: str,
    note: str = "",
    outcome_area: str = "",
    intervention: str = "",
):
    """Approve, return or reject a submitted story."""
    from apps.audit.services import log as audit_log
    from apps.impact.review import assert_can_review

    if decision not in {key for key, _label in DECISIONS}:
        raise BadRequest("Choose approve, return or reject.")
    note = (note or "").strip()
    outcome_area = (outcome_area or "").strip()
    intervention = (intervention or "").strip()
    if decision in ("return", "reject") and not note:
        raise BadRequest(
            "Tell the author why: a returned or rejected story needs a reason."
        )
    if intervention and intervention not in SsaIntervention.values:
        raise BadRequest("Choose an SSA domain from the list.")
    if decision == "approve":
        if outcome_area and outcome_area not in {c for c, _ in outcome_area_options()}:
            raise BadRequest("Choose an outcome area from the list.")
        if not (outcome_area or intervention):
            raise BadRequest(
                "Tag the outcome area (or SSA domain) this story evidences, so it "
                "counts toward that outcome."
            )

    with transaction.atomic():
        story = (
            visible_stories(principal)
            .select_for_update(of=("self",))
            .select_related("school__region")
            .filter(id=story_id)
            .first()
        )
        if story is None:
            raise NotFoundError("That story is not in your country.")
        if story.status not in REVIEWABLE:
            raise BadRequest(
                f"This story is {story.get_status_display().lower()}; only a "
                "submitted story is reviewed."
            )
        country = story_country(story)
        basis = assert_can_review(principal, author_id=story.user_id, country=country)
        story.status = {
            "approve": MSCSStatus.APPROVED,
            "return": MSCSStatus.RETURNED,
            "reject": MSCSStatus.REJECTED,
        }[decision]
        story.reviewed_by = _uid(principal)
        story.reviewed_at = timezone.now()
        story.return_reason = note[:512] if decision != "approve" else None
        story.country = country
        if decision == "approve":
            story.outcome_area = outcome_area
            story.intervention = intervention
        story.save(
            update_fields=[
                "status",
                "reviewed_by",
                "reviewed_at",
                "return_reason",
                "country",
                "outcome_area",
                "intervention",
                "updated_at",
            ]
        )
        audit_log(
            action=f"mscs.story_{story.status}",
            subject_kind="MostSignificantChangeStory",
            subject_id=str(story.id),
            actor_id=_uid(principal),
            actor_role=getattr(principal, "active_role", None),
            reason=note or None,
            payload={
                "decision": decision,
                "review_basis": basis,
                "outcome_area": story.outcome_area,
                "intervention": story.intervention,
                "author_id": story.user_id,
                "country": country,
            },
        )
        transaction.on_commit(lambda: _after_decision(story, decision))
    return story


def _after_decision(story, decision: str) -> None:
    """Tell the author, and refresh their target ledger (best effort: a
    notice or a ledger rebuild never undoes the decision; the nightly ledger
    sync catches up anything missed)."""
    try:
        from apps.notifications.services import WorkflowNotificationService

        title = {
            "approve": "Your change story was approved",
            "return": "Your change story was returned",
            "reject": "Your change story was not accepted",
        }[decision]
        body = story.title
        if story.return_reason:
            body = f"{story.title}: {story.return_reason}"
        if decision == "return":
            body += " Submit it again with what the reviewer asked for."
        WorkflowNotificationService.trigger(
            event_type=EVENT_REVIEWED,
            category="targets",
            priority="normal" if decision == "approve" else "high",
            title=title,
            body=body[:500],
            context_type="MostSignificantChangeStory",
            context_id=story.id,
            recipients=[story.user_id],
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from apps.accounts.models import User
        from apps.core.fy import get_operational_fy
        from apps.targets.my_targets import TargetAchievementService

        author = User.objects.filter(id=story.user_id).first()
        if author is not None:
            TargetAchievementService.rebuild(
                author, get_operational_fy(story.story_date)
            )
    except Exception:  # noqa: BLE001
        pass


def assert_readable(principal, story_id: str):
    story = (
        visible_stories(principal)
        .select_related("school__region")
        .filter(id=story_id)
        .first()
    )
    if story is None:
        raise NotFoundError("That story is not in your country.")
    return story


__all__ = [
    "DECISIONS",
    "EVENT_REVIEWED",
    "decide",
    "fy_q",
    "outcome_area_options",
    "review_basis",
    "spiritual_story_q",
    "story_country",
    "visible_stories",
]
