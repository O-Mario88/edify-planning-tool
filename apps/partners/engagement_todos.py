"""Collaboration To-Dos: training partners and the Country Director's flags
(owner, 2026-09-13).

Registered in apps.command_center.todo_service.MODULE_TODO_BUILDERS. Every row
is derived from the records, so it disappears the moment the work is done —
nobody ticks it off:

* Programme Lead and Country Director: "Follow up <partner> on the agreed
  improvements" once the follow-up date of an engagement they recorded arrives
  and until they close it.
* Programme Lead: "Follow up <partner> on the Regional Lead's observation" for
  an observation shared with them of a partner-delivered training that asked
  to strengthen or replace it, until an engagement with that partner is
  recorded (engagement_services.open_observation_follow_ups — the rule the
  Partner Oversight notice reads).
* Programme Lead: "Resolve the Country Director's flag" for a flag they
  acknowledged and have not resolved. The queue's existing "Respond to CD
  Flag" row covers open flags only, so an acknowledged flag used to leave the
  queue with nothing done; resolving it now closes the loop with a note.

Rows carry the "Collaboration" responsibility
(todo_service.PL_RESPONSIBILITY_CATEGORIES). A fixed number of queries
whatever the number of records (apps/partners/test_engagement.py pins it).
"""

from __future__ import annotations

import logging
from datetime import date
from urllib.parse import urlencode

from django.utils import timezone

logger = logging.getLogger(__name__)

CATEGORY = "Collaboration"

# How many rows of one kind the queue shows; the pages list the rest.
ROW_LIMIT = 8


def _row(
    key,
    *,
    title,
    description,
    priority,
    url,
    action,
    linked,
    today,
    source,
    due=None,
    overdue=False,
):
    if overdue:
        status = ("overdue", "Overdue", "danger")
    elif due == today:
        status = ("due_today", "Due Today", "warning")
    else:
        status = ("waiting_me", "Waiting on Me", "warning")
    return {
        "id": key,
        "title": title,
        "description": (description or "")[:180],
        "category": CATEGORY,
        "priority": priority,
        "status_key": status[0],
        "status_label": status[1],
        "status_tone": status[2],
        "due_label": f"{due:%-d %b}" if due else "—",
        "due_tone": "danger" if overdue else ("warning" if due else "neutral"),
        "linked": linked,
        "action_label": action,
        "action_url": url,
        "actionable": True,
        "source": source,
        "_due_sort": due or today,
    }


def _open(path: str, **params) -> str:
    return f"{path}?{urlencode({k: v for k, v in params.items() if v})}"


def partner_engagement_todos(principal, role, today) -> list[dict]:
    from apps.partners import engagement_services as services

    if role not in services.RECORDER_ROLES:
        return []
    today = today or timezone.localdate()
    try:
        out = _follow_up_rows(principal, today)
        if role == services.PROGRAM_LEAD:
            out += _observation_rows(principal, today)
            out += _flag_rows(principal, today)
        return out
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Partner engagement To-Dos failed")
        return []


def _follow_up_rows(principal, today: date) -> list[dict]:
    from apps.partners.models import PartnerEngagement
    from apps.partners import engagement_services as services

    records = (
        PartnerEngagement.objects.filter(
            author_id=services._uid(principal),
            follow_up_due__lte=today,
            follow_up_done_at__isnull=True,
        )
        .select_related("partner")
        .order_by("follow_up_due", "created_at")[:ROW_LIMIT]
    )
    rows = []
    for record in records:
        partner = record.partner.name
        rows.append(
            _row(
                f"pengage-followup-{record.id}",
                title=f"Follow up {partner} on the agreed improvements",
                description=record.agreed_improvements or record.subject,
                priority="high" if record.follow_up_due < today else "medium",
                url=_open(
                    f"/partners/{record.partner_id}",
                    engagement=record.id,
                    step="follow-up",
                ),
                action="Follow up",
                linked=partner,
                today=today,
                source="Partner engagements",
                due=record.follow_up_due,
                overdue=record.follow_up_due < today,
            )
        )
    return rows


def _observation_rows(principal, today: date) -> list[dict]:
    from apps.partners import engagement_services as services

    rows = []
    for entry in services.open_observation_follow_ups(principal, limit=ROW_LIMIT):
        observation = entry["observation"]
        partner = entry["partner_name"]
        rows.append(
            _row(
                f"pengage-observation-{observation.id}",
                title=f"Follow up {partner} on the Regional Lead's observation",
                description=(
                    f"{entry['recommendation']}: {observation.feedback or observation.subject}"
                ),
                priority="high",
                url=_open(
                    f"/partners/{entry['partner_id']}",
                    record="1",
                    source=observation.id,
                ),
                action="Record engagement",
                linked=partner,
                today=today,
                source="Regional Lead feedback",
            )
        )
    return rows


def _flag_rows(principal, today: date) -> list[dict]:
    from apps.flags.models import CdFlag, CdFlagStatus
    from apps.flags.services import _actor_id

    rows = []
    for flag in CdFlag.objects.filter(
        assigned_to_user_id=_actor_id(principal),
        status=CdFlagStatus.ACKNOWLEDGED,
    ).order_by("created_at")[:ROW_LIMIT]:
        rows.append(
            _row(
                f"cdflag-resolve-{flag.id}",
                title="Resolve the Country Director's flag",
                description=flag.note or flag.recommended_action or "",
                priority="high" if flag.priority == "high" else "medium",
                url=_open("/quality-checks", resolve=flag.id),
                action="Resolve",
                linked=flag.scope_name or "Quality flag",
                today=today,
                source="Quality flags",
            )
        )
    return rows
