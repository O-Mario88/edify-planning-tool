"""Sample checks: a second look at a share of verified work (2026-09-03).

`draw_samples` runs weekly and picks a configurable share of the activities
verified in the last week that have not been sampled before. A verifier
other than the original one records whether the certification stands.
Outcomes are read by `verification_analytics` against the original
verifier.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.activities.ia_models import VerificationHistory, VerificationSample
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.scoping import activity_country_q, resolve_user_scope

DEFAULT_SHARE_PCT = 10


def sample_share_pct() -> int:
    return int(getattr(settings, "IA_VERIFICATION_SAMPLE_SHARE_PCT", DEFAULT_SHARE_PCT))


def draw_samples(
    days: int = 7, share_pct: int | None = None, actor: str = "system"
) -> int:
    """Draw the share from the last `days` of verifications. Idempotent per
    activity: work already sampled is never drawn twice."""
    share = sample_share_pct() if share_pct is None else int(share_pct)
    if share <= 0:
        return 0
    # One draw per day: a re-run on the same day (the scheduler retrying, or
    # someone pressing the button twice) must not keep topping the sample up.
    if VerificationSample.objects.filter(
        sampled_at__date=timezone.localdate()
    ).exists():
        return 0
    since = timezone.now() - timedelta(days=days)
    already = VerificationSample.objects.values("activity_id")
    candidates = list(
        VerificationHistory.objects.filter(verified_at__gte=since)
        .exclude(activity_id__in=already)
        .order_by("verified_at", "id")
    )
    if not candidates:
        return 0
    take = max(1, math.ceil(len(candidates) * share / 100))
    # Seeded by the draw date so a re-run on the same day draws the same set.
    rng = random.Random(timezone.localdate().isoformat())
    chosen = rng.sample(candidates, min(take, len(candidates)))
    created = 0
    with transaction.atomic():
        for h in chosen:
            _, made = VerificationSample.objects.get_or_create(
                activity_id=h.activity_id,
                defaults={"original_verifier": h.verified_by, "sampled_by": actor},
            )
            created += int(made)
    return created


def samples_for(principal):
    """Samples in the principal's reach, newest first."""
    scope = resolve_user_scope(principal)
    reach = Activity.objects.filter(activity_country_q(scope)).values("id")
    return (
        VerificationSample.objects.filter(activity__in=reach)
        .select_related("activity", "activity__school")
        .order_by("status", "-sampled_at")
    )


def record_outcome(
    sample_id: str, status: str, note: str, principal
) -> VerificationSample:
    """A second verifier confirms or disputes. The original verifier may not
    grade their own certification."""
    from apps.core.permissions import RolePermissionService

    status = (status or "").strip().lower()
    if status not in ("confirmed", "disputed"):
        raise BadRequest("Choose confirmed or disputed.")
    note = (note or "").strip()
    if status == "disputed" and not note:
        raise BadRequest("Say what did not hold up.")
    with transaction.atomic():
        sample = (
            VerificationSample.objects.select_for_update()
            .select_related("activity")
            .filter(id=sample_id)
            .first()
        )
        if sample is None:
            raise BadRequest("Sample not found.")
        if sample.status != "pending":
            raise BadRequest("This sample already has an outcome.")
        if str(sample.original_verifier) == str(principal.user_id):
            raise Forbidden("The original verifier cannot grade their own check.")
        if not RolePermissionService.can_verify_ia(principal, sample.activity):
            raise Forbidden("Only a verifier may record a sample outcome.")
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
    return sample
