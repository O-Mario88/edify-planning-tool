"""Sending a role brief: the bell always, a phone channel by choice.

One brief per person, kind and day. The bell notice opens the brief page; a
person who chose a text message or an email gets the same lines there too,
with a link to the page. Three guards, each from the proposal's risk list:

* **Each person chooses the channel** (``User.brief_channel``). The default is
  the platform only; "off" sends nothing at all.
* **Working days and hours only.** Nothing leaves the platform outside
  Monday to Friday, 07:00 to 18:00 Kampala time, or on a public holiday,
  whatever ran the job.
* **Counts and links only.** The builder never puts a name or a sum in a
  line, so a message read over someone's shoulder gives nothing away.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import builder

logger = logging.getLogger("edify.briefs")

CHANNEL_APP = "app"
CHANNEL_SMS = "sms"
CHANNEL_EMAIL = "email"
CHANNEL_OFF = "off"

WORKING_HOURS = (time(7, 0), time(18, 0))


def event_type(kind: str) -> str:
    return f"brief.{kind}"


def day_key(day: date) -> str:
    return f"br-{day.isoformat()}"


def enabled() -> bool:
    return bool(getattr(settings, "ROLE_BRIEFS_ENABLED", True))


def is_working_time(now: datetime | None = None) -> bool:
    """A working day, inside working hours, in the programme's timezone."""
    from apps.core.public_holidays import public_holiday_name

    local = timezone.localtime(now or timezone.now())
    if local.weekday() > 4 or public_holiday_name(local.date()):
        return False
    start, end = WORKING_HOURS
    return start <= local.time() <= end


def channels_open_to(user) -> list[dict]:
    """The channels this person can choose, and why one is not offered."""
    from apps.core.email import MailerService
    from apps.core.sms import sms

    phone = (getattr(user, "phone", None) or "").strip()
    return [
        {
            "channel": CHANNEL_APP,
            "name": "In the platform",
            "note": "The bell shows your brief. Nothing is sent to your phone.",
            "available": True,
        },
        {
            "channel": CHANNEL_SMS,
            "name": "Text message",
            "note": (
                f"Sent to {phone}."
                if phone and sms.is_configured
                else "Text messages are not switched on for the platform yet."
                if phone
                else "Add a phone number to your account to choose this."
            ),
            "available": bool(phone) and sms.is_configured,
        },
        {
            "channel": CHANNEL_EMAIL,
            "name": "Email",
            "note": (
                f"Sent to {user.email}."
                if MailerService().is_configured
                else "Email is not switched on for the platform yet."
            ),
            "available": bool(user.email) and MailerService().is_configured,
        },
        {
            "channel": CHANNEL_OFF,
            "name": "No brief",
            "note": "You can still open the brief from this page at any time.",
            "available": True,
        },
    ]


def set_channel(user, channel: str) -> bool:
    """Save the person's choice; False for a channel they cannot use."""
    allowed = {c["channel"] for c in channels_open_to(user) if c["available"]}
    if channel not in allowed:
        return False
    user.brief_channel = channel
    user.save(update_fields=["brief_channel", "updated_at"])
    return True


def already_sent(user_id: str, kind: str, day: date) -> bool:
    """A brief of this kind went to this person today, even if archived."""
    from apps.notifications.models import Notification

    return Notification.objects.filter(
        recipient_id=user_id,
        source_event_type=event_type(kind),
        context_id=day_key(day),
    ).exists()


def _brief_url(kind: str) -> str:
    base = (os.environ.get("APP_BASE_URL") or "").rstrip("/")
    return f"{base}/brief?kind={kind}" if base else ""


def _send_outside(user, brief: builder.Brief) -> None:
    """The person's chosen phone channel. Never raises: a failed message must
    not stop the next person's brief."""
    channel = getattr(user, "brief_channel", CHANNEL_APP)
    if channel not in (CHANNEL_SMS, CHANNEL_EMAIL) or not is_working_time():
        return
    link = _brief_url(brief.kind)
    text = brief.message + (f"\n{link}" if link else "")
    try:
        if channel == CHANNEL_SMS:
            from apps.core.sms import SmsMessage, sms

            phone = (getattr(user, "phone", None) or "").strip()
            if phone and sms.is_configured:
                sms.send(SmsMessage(to=phone, text=text))
        elif user.email:
            from apps.core.email import MailerService, MailMessage

            MailerService().send(
                MailMessage(to=user.email, subject=brief.title, text=text)
            )
    except Exception:  # noqa: BLE001 - one channel never breaks the run
        logger.exception("Brief %s could not be sent to %s", brief.kind, user.id)


def deliver(user, brief: builder.Brief) -> bool:
    """Send ``brief`` to ``user`` once for its day. True when it went."""
    from apps.notifications.models import Notification
    from apps.notifications.services import WorkflowNotificationService

    if getattr(user, "brief_channel", CHANNEL_APP) == CHANNEL_OFF:
        return False
    if already_sent(user.id, brief.kind, brief.day):
        return False

    # An earlier day's brief describes figures that have moved on.
    now = timezone.now()
    Notification.objects.filter(
        recipient_id=user.id,
        source_event_type=event_type(brief.kind),
        resolved_at__isnull=True,
    ).exclude(context_id=day_key(brief.day)).update(
        resolved_at=now, status="archived", action_required=False, updated_at=now
    )

    WorkflowNotificationService.trigger(
        event_type=event_type(brief.kind),
        category="general",
        priority="normal",
        title=brief.title,
        body=brief.body or "Open your brief.",
        context_type="brief",
        context_id=day_key(brief.day),
        recipients=[user],
    )
    transaction.on_commit(lambda: _send_outside(user, brief))
    return True


def send_briefs(kinds, *, today: date | None = None) -> int:
    """Build and send each kind to everyone who holds its role."""
    from apps.core.public_holidays import public_holiday_name
    from apps.notifications.services import role_recipients

    today = today or timezone.localdate()
    if not enabled() or today.weekday() > 4 or public_holiday_name(today):
        return 0
    sent = 0
    for kind in kinds:
        for user in role_recipients(builder.BRIEF_ROLES[kind]):
            if getattr(user, "brief_channel", CHANNEL_APP) == CHANNEL_OFF:
                continue
            if already_sent(user.id, kind, today):
                continue
            try:
                brief = builder.build(kind, user, today)
                if brief is not None and deliver(user, brief):
                    sent += 1
            except Exception:  # noqa: BLE001 - one person never stops the run
                logger.exception("Brief %s failed for %s", kind, user.id)
    return sent
