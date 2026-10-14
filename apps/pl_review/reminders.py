"""The end-of-day reminder to verify.

Owner, 2026-10-14: "The PL should be alerted at the end of every day to
verify cceo work." Each evening every Programme Lead with completions waiting
on them is told how many and from whom; the notice opens the Completion
Reviews register. A lead with nothing waiting is told nothing.

One notice a lead a day, keyed to the day: a re-run says nothing twice, and
the evening's notice takes the place of the one from the day before, so a
queue left for a week is one notice and not seven. A lead who clears the
queue has theirs closed at the next run.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from django.utils import timezone

from apps.core.rbac import EdifyRole

from .services import _owning_staff_id, _people, _queue_queryset

VERIFY_REMINDER_EVENT = "completions_awaiting_verification"

#: How many officers the notice names before "and N more".
_NAMED = 3


def _body(count: int, by_officer: list[tuple[str, int]]) -> str:
    named = ", ".join(f"{n} from {name}" for name, n in by_officer[:_NAMED])
    more = len(by_officer) - _NAMED
    if more > 0:
        named += f" and {more} more officer{'s' if more != 1 else ''}"
    return (
        f"{count} completed activit{'y is' if count == 1 else 'ies are'} waiting "
        f"for you to verify ({named}). Check each visit ID or training ID, "
        "then mark it Verified or Return it with the reason."
    )


def send_verification_reminders(today: date | None = None) -> int:
    """Tell each Programme Lead what waits on them. Returns notices sent."""
    from apps.accounts.models import User
    from apps.notifications.models import Notification
    from apps.notifications.services import WorkflowNotificationService

    today = today or timezone.localdate()
    key = f"verify-{today.isoformat()}"
    leads = User.objects.filter(
        roles__contains=[EdifyRole.COUNTRY_PROGRAM_LEAD.value], is_active=True
    )
    sent = 0
    for lead in leads:
        owners = [
            _owning_staff_id(activity) or ""
            for activity in _queue_queryset(lead).only(
                "id", "responsible_staff_id", "monitored_by_staff_id"
            )
        ]
        earlier = Notification.objects.filter(
            recipient_id=lead.id,
            source_event_type=VERIFY_REMINDER_EVENT,
            resolved_at__isnull=True,
        ).exclude(context_id=key)
        if earlier.exists():
            # Yesterday's is answered by today's, or by an empty queue.
            now = timezone.now()
            earlier.update(
                resolved_at=now,
                status="archived",
                action_required=False,
                updated_at=now,
            )
        if not owners:
            continue
        if Notification.objects.filter(
            recipient_id=lead.id,
            source_event_type=VERIFY_REMINDER_EVENT,
            context_id=key,
        ).exists():
            continue
        names, profile_of = _people(owners)
        counts = Counter(profile_of.get(owner, owner) for owner in owners)
        by_officer = sorted(
            (
                (names.get(owner, "") or "an unnamed officer", n)
                for owner, n in counts.items()
            ),
            key=lambda pair: (-pair[1], pair[0].lower()),
        )
        count = len(owners)
        WorkflowNotificationService.trigger(
            event_type=VERIFY_REMINDER_EVENT,
            category="activity",
            priority="high",
            title=(
                f"Verify {count} completed activit{'y' if count == 1 else 'ies'} "
                "before the day ends"
            ),
            body=_body(count, by_officer),
            context_type="completion_reviews",
            context_id=key,
            recipients=[lead],
        )
        sent += 1
    return sent
