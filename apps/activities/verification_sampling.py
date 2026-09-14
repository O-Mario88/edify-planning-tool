"""Sample checks: a second look at a share of verified work (2026-09-03).

`draw_samples` runs weekly and picks a configurable share of the activities
verified in the last week that have not been sampled before. A verifier
other than the original one records whether the certification stands.
Outcomes are read by `verification_analytics` against the original
verifier.

IA review (owner, 2026-09-13):

- Draws are made per country, each with its own once-a-day lock. The draw read
  every country's verifications under one global lock, so one country's press
  of "Draw this week now" blocked every other country's.
- Confirmed SSA records are sampled too (`subject_type="ssa_record"`): the
  scores are the collection data every outcome rests on, and the activity that
  collected them was the only thing ever re-checked.
- A dispute changes something. A disputed SSA is returned to its collector
  (`apps.ssa.services.return_record`), so it leaves every confirmed-only
  reading until it is re-keyed and confirmed. A disputed activity is flagged
  out of analytics (`VerificationHistory.analytics_included = False`) until a
  verifier resolves the dispute (`resolve_dispute`).
- A field back-check (`method="field"`) never schedules into a portfolio: it
  opens the schedule drawer, which files an owner-approved visit request.
- Grading is bounded to the verifier's country, and nobody grades their own
  certification or scores they collected.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.activities.ia_models import VerificationHistory, VerificationSample
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.scoping import activity_country_q, resolve_user_scope

DEFAULT_SHARE_PCT = 10
SUBJECT_ACTIVITY = "activity"
SUBJECT_SSA = "ssa_record"


def sample_share_pct() -> int:
    return int(getattr(settings, "IA_VERIFICATION_SAMPLE_SHARE_PCT", DEFAULT_SHARE_PCT))


def _sample_country_q(country: str) -> Q:
    """Samples placed in `country`: by the activity's school, cluster or
    responsible person, or by the sampled SSA's school."""
    from apps.accounts.models import StaffProfile

    staff = StaffProfile.objects.filter(country=country).values("id")
    return (
        Q(activity__school__region__country=country)
        | Q(activity__cluster__region__country=country)
        | Q(
            activity__school__isnull=True,
            activity__cluster__isnull=True,
            activity__responsible_staff_id__in=staff,
        )
        | Q(ssa_record__school__region__country=country)
    )


def _activity_countries(histories) -> dict[str, str]:
    """{activity id: country} for verification history rows, in two queries:
    the activity's school or cluster region, else its responsible person's
    profile (either id space)."""
    from apps.accounts.models import StaffProfile

    places = list(
        Activity.objects.filter(id__in={h.activity_id for h in histories}).values_list(
            "id",
            "school__region__country",
            "cluster__region__country",
            "responsible_staff_id",
        )
    )
    people = {p[3] for p in places if p[3]}
    staff_country: dict[str, str] = {}
    for profile_id, user_id, country in StaffProfile.objects.filter(
        Q(id__in=people) | Q(user_id__in=people)
    ).values_list("id", "user_id", "country"):
        staff_country[str(profile_id)] = country or ""
        if user_id:
            staff_country[str(user_id)] = country or ""
    return {
        aid: school_country or cluster_country or staff_country.get(str(person), "")
        for aid, school_country, cluster_country, person in places
    }


def draw_samples(
    days: int = 7,
    share_pct: int | None = None,
    actor: str = "system",
    country: str | None = None,
) -> int:
    """Draw the share from the last `days` of verified activities and
    confirmed SSA records, per country. Idempotent per subject: work already
    sampled is never drawn twice. `country` limits the draw to one country
    (the page's button); None draws every country (the weekly job)."""
    share = sample_share_pct() if share_pct is None else int(share_pct)
    if share <= 0:
        return 0
    from apps.ssa.models import SsaRecord

    since = timezone.now() - timedelta(days=days)
    histories = list(
        VerificationHistory.objects.filter(verified_at__gte=since)
        .exclude(
            activity_id__in=VerificationSample.objects.filter(
                activity__isnull=False
            ).values("activity_id")
        )
        .order_by("verified_at", "id")
    )
    # One history row per activity: an activity verified twice is one subject.
    seen: set[str] = set()
    histories = [
        h for h in histories if not (h.activity_id in seen or seen.add(h.activity_id))
    ]
    activity_country = _activity_countries(histories) if histories else {}
    records = list(
        SsaRecord.objects.filter(
            verification_status="confirmed",
            deleted_at__isnull=True,
            verified_at__gte=since,
            verified_by_user_id__isnull=False,
        )
        .exclude(
            id__in=VerificationSample.objects.filter(ssa_record__isnull=False).values(
                "ssa_record_id"
            )
        )
        .values_list("id", "verified_by_user_id", "school__region__country")
        .order_by("verified_at", "id")
    )

    frames: dict[str, dict[str, list]] = defaultdict(
        lambda: {"activity": [], "ssa": []}
    )
    for h in histories:
        frames[activity_country.get(h.activity_id, "")]["activity"].append(h)
    for record_id, verifier, record_country in records:
        frames[record_country or ""]["ssa"].append((record_id, verifier))

    created = 0
    today = timezone.localdate()
    for place, frame in sorted(frames.items()):
        if country is not None and place != country:
            continue
        created += _draw_country(place, frame, share=share, today=today, actor=actor)
    return created


def _draw_country(place: str, frame: dict, *, share: int, today, actor: str) -> int:
    # One draw per country per day: a re-run on the same day (the scheduler
    # retrying, or someone pressing the button twice) must not keep topping
    # the sample up — and one country's draw must not block another's.
    drawn_today = VerificationSample.objects.filter(sampled_at__date=today)
    drawn_today = (
        drawn_today.filter(_sample_country_q(place))
        if place
        else drawn_today.exclude(
            Q(activity__school__region__isnull=False)
            | Q(activity__cluster__region__isnull=False)
            | Q(ssa_record__isnull=False)
        )
    )
    if drawn_today.exists():
        return 0
    # Seeded by the draw date and country so a re-run draws the same set.
    rng = random.Random(f"{today.isoformat()}:{place}")
    created = 0
    with transaction.atomic():
        activities = frame["activity"]
        if activities:
            take = max(1, math.ceil(len(activities) * share / 100))
            for h in rng.sample(activities, min(take, len(activities))):
                _, made = VerificationSample.objects.get_or_create(
                    activity_id=h.activity_id,
                    subject_type=SUBJECT_ACTIVITY,
                    defaults={"original_verifier": h.verified_by, "sampled_by": actor},
                )
                created += int(made)
        ssa = frame["ssa"]
        if ssa:
            take = max(1, math.ceil(len(ssa) * share / 100))
            for record_id, verifier in rng.sample(ssa, min(take, len(ssa))):
                _, made = VerificationSample.objects.get_or_create(
                    ssa_record_id=record_id,
                    subject_type=SUBJECT_SSA,
                    defaults={"original_verifier": verifier, "sampled_by": actor},
                )
                created += int(made)
    return created


def samples_for(principal):
    """Samples in the principal's reach, newest first: activities in their
    country and SSA records of schools in their country."""
    from apps.core.scoping import scoped_school_queryset
    from apps.schools.models import School

    scope = resolve_user_scope(principal)
    reach = Activity.objects.filter(activity_country_q(scope)).values("id")
    schools = scoped_school_queryset(
        scope, School.objects.filter(deleted_at__isnull=True)
    )
    return (
        VerificationSample.objects.filter(
            Q(activity__in=reach) | Q(ssa_record__school__in=schools.values("id"))
        )
        .select_related(
            "activity", "activity__school", "ssa_record", "ssa_record__school"
        )
        .order_by("status", "-sampled_at")
    )


def _assert_may_grade(sample, principal) -> None:
    """The original verifier never grades their own certification, the
    collector never grades their own scores, and the sample must be in the
    grader's country (IA review, 2026-09-13)."""
    from apps.core.permissions import RolePermissionService

    if str(sample.original_verifier) == str(principal.user_id):
        raise Forbidden("The original verifier cannot grade their own check.")
    if sample.subject_type == SUBJECT_SSA and sample.ssa_record_id:
        from apps.ssa.services import _assert_may_decide

        try:
            _assert_may_decide(principal, sample.ssa_record)
        except Forbidden as exc:
            raise Forbidden(f"You may not grade this SSA sample: {exc}") from exc
        return
    if not RolePermissionService.can_verify_ia(principal, sample.activity):
        raise Forbidden("Only a verifier may record a sample outcome.")
    if not samples_for(principal).filter(id=sample.id).exists():
        raise Forbidden("This sample belongs to work outside your country.")


def grading_flags(principal, samples) -> dict[str, str]:
    """{sample id: refusal} for a page of samples already in the principal's
    reach — an empty refusal means they may grade it. The same rules as
    `_assert_may_grade`, decided for the whole page in at most two queries."""
    from apps.core.permissions import (
        has_permission,
        ia_officer_staff_ids,
        verifies_own_ssa,
        verifies_own_work,
    )
    from apps.core.rbac import EdifyRole, Permission
    from apps.ssa.models import SsaRecord
    from apps.ssa.services import ia_collected_q

    samples = list(samples)
    uid = str(principal.user_id)
    is_ia = has_permission(principal, Permission.IA_VERIFY.value)
    is_cd = getattr(principal, "active_role", "") == EdifyRole.COUNTRY_DIRECTOR.value
    ia_staff: set[str] = set()
    ia_records: set[str] = set()
    if is_cd and not is_ia:
        scope = resolve_user_scope(principal)
        ia_staff = {str(i["id"]) for i in ia_officer_staff_ids(scope.country or None)}
        ia_records = set(
            SsaRecord.objects.filter(
                id__in=[s.ssa_record_id for s in samples if s.ssa_record_id]
            )
            .filter(ia_collected_q())
            .values_list("id", flat=True)
        )
    flags: dict[str, str] = {}
    for sample in samples:
        if str(sample.original_verifier) == uid:
            flags[sample.id] = "Your own certification: a colleague grades it."
        elif sample.subject_type == SUBJECT_SSA and sample.ssa_record_id:
            if verifies_own_ssa(principal, sample.ssa_record):
                flags[sample.id] = "Your own scores: a colleague grades them."
            elif is_ia or sample.ssa_record_id in ia_records:
                flags[sample.id] = ""
            else:
                flags[sample.id] = "Impact Assessment grades this sample."
        elif sample.activity is not None and verifies_own_work(
            principal, sample.activity
        ):
            flags[sample.id] = "Your own field work: a colleague grades it."
        elif is_ia or (
            sample.activity is not None
            and str(sample.activity.responsible_staff_id or "") in ia_staff
        ):
            flags[sample.id] = ""
        else:
            flags[sample.id] = "Impact Assessment grades this sample."
    return flags


def record_outcome(
    sample_id: str, status: str, note: str, principal
) -> VerificationSample:
    """A second verifier confirms or disputes. The original verifier may not
    grade their own certification. A dispute returns a sampled SSA to its
    collector, or takes a sampled activity out of analytics until resolved."""
    status = (status or "").strip().lower()
    if status not in ("confirmed", "disputed"):
        raise BadRequest("Choose confirmed or disputed.")
    note = (note or "").strip()
    if status == "disputed" and not note:
        raise BadRequest("Say what did not hold up.")
    with transaction.atomic():
        sample = (
            # The activity link is nullable since SSA records are sampled too,
            # and Postgres refuses FOR UPDATE on the nullable side of a join.
            VerificationSample.objects.select_for_update(of=("self",))
            .select_related("activity", "ssa_record", "ssa_record__school")
            .filter(id=sample_id)
            .first()
        )
        if sample is None:
            raise BadRequest("Sample not found.")
        if sample.status != "pending":
            raise BadRequest("This sample already has an outcome.")
        _assert_may_grade(sample, principal)
        sample.status = status
        sample.outcome_note = note
        sample.checked_by = principal.user_id
        sample.checked_at = timezone.now()
        sample.save(
            update_fields=[
                "status",
                "outcome_note",
                "checked_by",
                "checked_at",
                "updated_at",
            ]
        )
        if sample.subject_type == SUBJECT_SSA and sample.ssa_record_id:
            # The QA columns on the record were never written; a graded sample
            # is exactly the independent review they describe.
            from apps.ssa.models import SsaRecord

            SsaRecord.objects.filter(id=sample.ssa_record_id).update(
                qa_reviewed_by_user_id=principal.user_id,
                qa_reviewed_at=sample.checked_at,
            )
        if status == "disputed":
            _apply_dispute(sample, note, principal)
    return sample


def _apply_dispute(sample, note: str, principal) -> None:
    from apps.audit.services import log as audit_log

    if sample.subject_type == SUBJECT_SSA and sample.ssa_record_id:
        from apps.ssa.services import return_record

        return_record(sample.ssa_record, principal, f"Sample check disputed: {note}")
        return
    if sample.activity_id:
        VerificationHistory.objects.filter(activity_id=sample.activity_id).update(
            analytics_included=False
        )
        audit_log(
            action="verification_sample_excluded",
            subject_kind="Activity",
            subject_id=str(sample.activity_id),
            actor_id=str(principal.user_id),
            actor_role=getattr(principal, "active_role", None),
            reason=note,
            payload={"sampleId": sample.id},
        )


def excluded_activity_ids():
    """Activities a disputed sample took out of analytics, unevaluated.

    Outcome and contribution readers exclude these until the dispute is
    resolved (`resolve_dispute` puts the activity back)."""
    return VerificationHistory.objects.filter(analytics_included=False).values(
        "activity_id"
    )


def resolve_dispute(sample_id: str, note: str, principal) -> VerificationSample:
    """Put a disputed activity back into analytics once it is corrected.

    Resolved by a verifier other than the original one — the same people who
    may grade the sample — with a note saying what was corrected. A disputed
    SSA has no resolution here: it was returned, and it counts again when it
    is re-keyed and confirmed.
    """
    from apps.audit.services import log as audit_log

    note = (note or "").strip()
    if not note:
        raise BadRequest("Say what was corrected.")
    with transaction.atomic():
        sample = (
            VerificationSample.objects.select_for_update(of=("self",))
            .select_related("activity")
            .filter(id=sample_id)
            .first()
        )
        if sample is None:
            raise BadRequest("Sample not found.")
        if sample.status != "disputed" or sample.subject_type != SUBJECT_ACTIVITY:
            raise BadRequest("Only a disputed activity sample can be resolved.")
        _assert_may_grade(sample, principal)
        excluded = VerificationHistory.objects.filter(
            activity_id=sample.activity_id, analytics_included=False
        )
        if not excluded.exists():
            raise BadRequest("This dispute is already resolved.")
        excluded.update(analytics_included=True)
        stamp = timezone.localdate()
        sample.outcome_note = (
            f"{sample.outcome_note}\nResolved {stamp:%-d %b %Y}: {note}".strip()
        )
        sample.save(update_fields=["outcome_note", "updated_at"])
        audit_log(
            action="verification_sample_resolved",
            subject_kind="VerificationSample",
            subject_id=str(sample.id),
            actor_id=str(principal.user_id),
            actor_role=getattr(principal, "active_role", None),
            reason=note,
            payload={"activityId": sample.activity_id},
        )
    return sample


def request_field_check(sample_id: str, principal) -> VerificationSample:
    """Mark a pending sample as a field back-check. The visit itself is an
    owner-approved visit request made from the schedule drawer; nothing is
    scheduled here."""
    from apps.audit.services import log as audit_log

    with transaction.atomic():
        sample = (
            VerificationSample.objects.select_for_update(of=("self",))
            .select_related(
                "activity", "activity__school", "ssa_record", "ssa_record__school"
            )
            .filter(id=sample_id)
            .first()
        )
        if sample is None:
            raise BadRequest("Sample not found.")
        if sample.status != "pending":
            raise BadRequest("This sample already has an outcome.")
        _assert_may_grade(sample, principal)
        school = sample_school(sample)
        if school is None:
            raise BadRequest(
                "This sample has no school to visit; check it from the record."
            )
        if sample.method != "field":
            sample.method = "field"
            sample.save(update_fields=["method", "updated_at"])
            audit_log(
                action="verification_sample_field_check",
                subject_kind="VerificationSample",
                subject_id=str(sample.id),
                actor_id=str(principal.user_id),
                actor_role=getattr(principal, "active_role", None),
                payload={"schoolId": school.id},
            )
    return sample


def sample_school(sample):
    if sample.subject_type == SUBJECT_SSA and sample.ssa_record_id:
        return sample.ssa_record.school
    activity = sample.activity
    return getattr(activity, "school", None) if activity is not None else None
