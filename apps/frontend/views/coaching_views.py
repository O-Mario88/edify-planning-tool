"""Screens for a Programme Lead's coaching of their officers (owner, 2026-09-13).

/team/coaching is the lead's coaching log: this month's one-to-one with each
officer, and every conversation, observation and piece of feedback they
recorded, shared and followed up. The Country Director and the Regional Lead
read the shared coaching in their reach from the same page, with no write
controls. /my-coaching is the officer's side: what their lead shared with them,
acknowledged with a response.

Rules, permissions and audit rows live in apps.cce_leadership.coaching; these
views render and route, so a refusal the service raises is the message the
reader sees. Pages reuse the CCE leadership register template and drawers the
one-column form drawer (partials/hr/form_drawer.html).

A To-Do or a notification links a page with ?open=<record id> (and
&step=share|follow-up) or ?open=new with the prefill parameters; the page builds
the drawer URL itself from those whitelisted values and opens it on load.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.cce_leadership import coaching
from apps.cce_leadership.models import (
    OBSERVATION_CRITERIA,
    RATING_SCALE,
    CoachingKind,
)
from apps.cce_leadership.services import PROGRAM_LEAD, training_label
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import (
    SERVICE_ERRORS,
    _drawer,
    _field,
)

TEAM_URL = "/team/coaching"
MY_URL = "/my-coaching"
WORKSPACE_TEMPLATE = "pages/cce_leadership/workspace.html"
PANEL_TEMPLATE = "partials/coaching/one_to_ones.html"

KIND_LABELS = coaching.KIND_LABELS
RATING_LABELS = dict(RATING_SCALE)
# The prefill a link may carry into the new-coaching drawer.
PREFILL_PARAMS = ("cceo", "kind", "debrief", "activity")
# Parameters that only open a drawer; a form posted from that drawer returns
# to the register without them, or the drawer would open again.
AUTOLOAD_PARAMS = ("open", "step", "kind", "debrief", "activity")


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.coaching_views:_metric",
        label,
        value,
        helper=helper,
        tone=tone,
    )


def _cell(heading: str, text, *, primary=False, tone="") -> dict:
    """One register cell: its column heading and its text, with an optional
    tone for status words (the plain-table rule: text, never pills)."""
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _is_lead(request) -> bool:
    return request.user.active_role == PROGRAM_LEAD


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _render(request, context: dict):
    rows = context.get("rows", [])
    return render(
        request,
        WORKSPACE_TEMPLATE,
        {
            "header_actions": [],
            "notice": None,
            "filters": None,
            "rhythm": None,
            "panel_template": None,
            "autoload_drawer": "",
            **context,
            "has_row_actions": any(row.get("actions") for row in rows),
        },
    )


def safe_return_url(request, fallback: str, *, drop=AUTOLOAD_PARAMS) -> str:
    """The page a drawer's form returns to: the posted `next` when it is on
    this site, without the parameters that opened the drawer, else `fallback`.

    The rebuilt path is checked again with Django's own host check, so a path
    a browser reads as another host ("/\\evil.example") is refused too.
    """
    target = (request.POST.get("next") or "").strip()
    parsed = urlparse(target) if target else None
    if parsed and parsed.path.startswith("/"):
        same_site = not parsed.netloc.strip() or parsed.netloc == request.get_host()
        if same_site:
            query = urlencode(
                [
                    (key, value)
                    for key, value in parse_qsl(parsed.query)
                    if key not in drop
                ]
            )
            url = parsed.path + (f"?{query}" if query else "")
            if url_has_allowed_host_and_scheme(
                url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ) and not url.startswith(("//", "/\\")):
                return url
    return fallback


def _return(request, fallback: str):
    """Back to the register the drawer was opened from, never off-site, and
    without the parameters that opened the drawer."""
    return redirect(safe_return_url(request, fallback))


def _refused(request, exc, fallback):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _return(request, fallback)


def _names_by_staff(staff_ids) -> dict[str, str]:
    from apps.accounts.models import StaffProfile

    ids = {i for i in staff_ids if i}
    if not ids:
        return {}
    return dict(StaffProfile.objects.filter(id__in=ids).values_list("id", "user__name"))


def _names_by_user(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = {i for i in user_ids if i}
    if not ids:
        return {}
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def _record_facts(record, *, officer, author, for_officer=False) -> list[dict]:
    """What a coaching record says, in reading order. The officer does not
    see the lead's follow-up note, only that the follow-up was closed."""
    facts = [
        {"label": "Officer", "value": officer},
        {"label": "Programme Lead", "value": author},
        {"label": "Kind", "value": KIND_LABELS.get(record.kind, record.kind)},
        {"label": "Held on", "value": _day(record.held_on)},
        {"label": "Subject", "value": record.subject},
    ]
    if record.activity_id:
        facts.append({"label": "Activity", "value": training_label(record.activity)})
    if record.debrief_id:
        facts.append(
            {"label": "Field debrief", "value": coaching.debrief_label(record.debrief)}
        )
    if record.ratings:
        for name, label, _hint in OBSERVATION_CRITERIA:
            facts.append(
                {"label": label, "value": RATING_LABELS.get(getattr(record, name), "")}
            )
        facts.append(
            {"label": "Average rating", "value": f"{record.average_rating} of 4"}
        )
    facts += [
        {"label": "Strengths", "value": record.strengths},
        {"label": "Areas to grow", "value": record.growth_areas},
        {"label": "Actions agreed", "value": record.agreed_actions},
        {"label": "Follow up by", "value": _day(record.follow_up_due)},
        {"label": "Shared", "value": _day(record.shared_at)},
        {"label": "Acknowledged", "value": _day(record.acknowledged_at)},
        {"label": "Officer's response", "value": record.cceo_response},
        {"label": "Follow-up closed", "value": _day(record.follow_up_done_at)},
    ]
    if not for_officer:
        facts.append({"label": "Follow-up note", "value": record.follow_up_note})
    return facts


def _record_queryset(visible):
    return visible.select_related(
        "activity__school", "activity__cluster", "debrief", "source_engagement"
    )


# ── The lead's coaching log ──────────────────────────────────────────────────
def _autoload(request, visible, base: str, *, lead: bool) -> str:
    """The drawer a ?open= link asks for, built from whitelisted values."""
    target = (request.GET.get("open") or "").strip()
    if not target:
        return ""
    if target == "new":
        if not lead or base != TEAM_URL:
            return ""
        params = {
            key: request.GET.get(key, "").strip()
            for key in PREFILL_PARAMS
            if request.GET.get(key, "").strip()
        }
        return f"{TEAM_URL}/new" + (f"?{urlencode(params)}" if params else "")
    if not visible.filter(id=target).exists():
        return ""
    step = request.GET.get("step") or ""
    if lead and step in ("share", "follow-up"):
        return f"{base}/{target}/{step}"
    return f"{base}/{target}"


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def team_coaching_view(request):
    """The Programme Lead's coaching log, and the shared coaching the Country
    Director, the Regional Lead and Admin read."""
    today = timezone.localdate()
    user = request.user
    lead = _is_lead(request)
    members = coaching._team(user) if lead else []
    team_ids = [m.id for m in members] if lead else None
    visible = coaching.coaching_visible_to(user, team_ids=team_ids)

    if lead:
        officer_names = {m.id: getattr(m.user, "name", "") for m in members}
        user_to_staff = {m.user_id: m.id for m in members}
    else:
        officer_names = _names_by_staff(
            visible.order_by().values_list("cceo_staff_id", flat=True).distinct()[:500]
        )
        user_to_staff = {}

    cceo = (request.GET.get("cceo") or "").strip()
    cceo = user_to_staff.get(cceo, cceo)
    kind = request.GET.get("kind") or ""
    state = request.GET.get("state") or ""
    records = visible
    if cceo in officer_names:
        records = records.filter(cceo_staff_id=cceo)
    else:
        cceo = ""
    if kind in CoachingKind.values:
        records = records.filter(kind=kind)
    if state in dict(coaching.STATE_CHOICES):
        records = coaching.with_state(records, state, today=today)
    records = list(records.order_by("-held_on", "-created_at")[:500])
    authors = {} if lead else _names_by_user(r.author_id for r in records)

    rows = []
    for record in records:
        label, tone = coaching.state_of(record, today=today)
        cells = [
            _cell("Coaching", record.subject, primary=True),
            _cell("Officer", officer_names.get(record.cceo_staff_id, "")),
        ]
        if not lead:
            cells.append(_cell("Programme Lead", authors.get(record.author_id, "")))
        cells += [
            _cell("Kind", KIND_LABELS.get(record.kind, record.kind)),
            _cell("Held", _day(record.held_on)),
            _cell(
                "Follow up by",
                f"Closed {_day(record.follow_up_done_at)}"
                if record.follow_up_done_at
                else _day(record.follow_up_due),
            ),
            _cell("State", label, tone=tone),
        ]
        actions = [{"label": "Open", "drawer": f"{TEAM_URL}/{record.id}"}]
        if lead and not record.shared_at:
            actions.append(
                {"label": "Share", "drawer": f"{TEAM_URL}/{record.id}/share"}
            )
        elif lead and record.follow_up_due and not record.follow_up_done_at:
            actions.append(
                {"label": "Follow up", "drawer": f"{TEAM_URL}/{record.id}/follow-up"}
            )
        rows.append({"cells": cells, "actions": actions})

    counts = coaching.coaching_counts(visible, today=today)
    panel = None
    if lead:
        month = coaching.monthly_one_to_ones(user, today=today, members=members)
        panel = _one_to_one_panel(user, month, visible, team_ids, today)
        one_to_one_metric = _metric(
            "One-to-Ones Held This Month",
            f"{month['held']} / {len(members)}",
            f"{_plural(month['due'], 'officer')} due"
            if month["due"]
            else f"due from {month['due_from']:%-d %B} with each officer",
            "danger" if month["due"] else "success" if members else "info",
        )
    else:
        month_start = today.replace(day=1)
        coached = (
            visible.filter(kind=CoachingKind.ONE_TO_ONE, held_on__gte=month_start)
            .order_by()
            .values("cceo_staff_id")
            .distinct()
            .count()
        )
        one_to_one_metric = _metric(
            "One-to-Ones Held This Month",
            coached,
            "officers with a shared one-to-one this month",
        )
    metrics = [
        one_to_one_metric,
        _metric(
            "Coaching Notes Not Yet Shared",
            counts["drafts"],
            "drafts only you can read" if lead else "drafts stay with the lead",
            "warning" if lead and counts["drafts"] else "info",
        ),
        _metric(
            "Coaching Awaiting Officer Acknowledgement",
            counts["awaiting"],
            "shared, not yet acknowledged",
            "warning" if counts["awaiting"] else "info",
        ),
        _metric(
            "Coaching Follow-Ups Due",
            counts["follow_ups_due"],
            "agreed actions to check on",
            "danger" if counts["follow_ups_due"] else "info",
        ),
    ]

    notice = None
    if not lead:
        notice = {
            "tone": "info",
            "text": (
                "Read only. Each officer's Programme Lead writes their coaching; "
                "you read what the lead has shared with the officer."
            ),
        }
    elif not members:
        notice = {
            "tone": "info",
            "text": (
                "No officers are assigned to you yet. Coaching opens for the "
                "officers HR records you as the supervisor of."
            ),
        }

    kind_options = list(CoachingKind.choices)
    return _render(
        request,
        {
            "title": "Coaching",
            "eyebrow": "Performance & coaching",
            "description": (
                "Monthly one-to-ones, school visit and training observations, and "
                "feedback for the officers you line-manage. Share each record with "
                "the officer; they acknowledge it and say what they will do."
                if lead
                else "Coaching Programme Leads have shared with their officers, "
                "and what each officer said they will do."
            ),
            "metrics": metrics,
            "rows": rows,
            "register_title": "Coaching log",
            "empty_title": "No coaching recorded yet"
            if lead
            else "No shared coaching in your reach",
            "empty_body": (
                "Log a one-to-one or record an observation; it stays private until "
                "you share it with the officer."
                if lead
                else "Coaching appears here once a Programme Lead shares it with an officer."
            ),
            "header_actions": [
                {"label": "Log coaching", "drawer": f"{TEAM_URL}/new"},
                {
                    "label": "Record an observation",
                    "drawer": f"{TEAM_URL}/new?kind={CoachingKind.FIELD_OBSERVATION}",
                },
            ]
            if lead and members
            else [],
            "notice": notice,
            "filters": {
                "fields": [
                    {
                        "name": "cceo",
                        "label": "Officer",
                        "value": cceo,
                        "blank": "Every officer",
                        "options": sorted(
                            officer_names.items(), key=lambda item: item[1] or ""
                        ),
                    },
                    {
                        "name": "kind",
                        "label": "Kind",
                        "value": kind,
                        "blank": "Every kind",
                        "options": kind_options,
                    },
                    {
                        "name": "state",
                        "label": "State",
                        "value": state,
                        "blank": "Every state",
                        "options": list(coaching.STATE_CHOICES)
                        if lead
                        else [
                            c
                            for c in coaching.STATE_CHOICES
                            if c[0] != coaching.STATE_DRAFT
                        ],
                    },
                ]
            },
            "panel_template": PANEL_TEMPLATE if panel else None,
            "panel": panel,
            "autoload_drawer": _autoload(request, visible, TEAM_URL, lead=lead),
        },
    )


def _one_to_one_panel(user, month, visible, team_ids, today) -> dict:
    last = coaching.last_coaching_by_cceo(
        user, [row["staff_id"] for row in month["rows"]], team_ids=team_ids
    )
    open_counts = coaching.per_officer_counts(visible, today=today)
    rows = []
    for entry in month["rows"]:
        latest = last.get(entry["staff_id"])
        counts = open_counts.get(entry["staff_id"], {})
        held = entry["state"] == "held"
        rows.append(
            {
                "cells": [
                    _cell("Officer", entry["name"], primary=True),
                    _cell(
                        f"{month['month']:%B} one-to-one",
                        entry["state_label"],
                        tone=entry["tone"],
                    ),
                    _cell(
                        "Last coaching",
                        f"{latest['held_on']:%-d %b} · {latest['kind_label']}"
                        if latest
                        else "Not coached yet",
                    ),
                    _cell(
                        "Awaiting acknowledgement",
                        counts.get("awaiting", 0),
                        tone="warning" if counts.get("awaiting") else "",
                    ),
                    _cell(
                        "Follow-ups due",
                        counts.get("follow_ups_due", 0),
                        tone="danger" if counts.get("follow_ups_due") else "",
                    ),
                ],
                "actions": [
                    {
                        "label": "Log coaching" if held else "Log one-to-one",
                        "drawer": f"{TEAM_URL}/new?"
                        + urlencode(
                            {"cceo": entry["staff_id"]}
                            if held
                            else {"cceo": entry["staff_id"], "kind": "one_to_one"}
                        ),
                    },
                    {
                        "label": "History",
                        "href": f"{TEAM_URL}?cceo={entry['staff_id']}",
                    },
                ],
            }
        )
    return {
        "title": f"{month['month']:%B} one-to-ones",
        "subtitle": (
            f"{month['held']} of {len(month['rows'])} held · due from "
            f"{month['due_from']:%-d %B}"
        ),
        "rows": rows,
        "empty_title": "No officers on your team",
        "empty_body": "Officers appear here once HR records you as their supervisor.",
    }


# ── Drawers: record, open, share, follow up ──────────────────────────────────
def _officer_label(members, owner_id) -> str:
    for member in members:
        if owner_id in (member.id, member.user_id):
            return getattr(member.user, "name", "") or ""
    return ""


def _activity_options(members, *, member=None, selected="", instance=None):
    from apps.activities.models import Activity

    scope = [member] if member else list(members)
    activities = list(coaching.officer_activities(scope)[:200])
    options = []
    for activity in activities:
        label = training_label(activity)
        if member is None:
            owner = _officer_label(
                scope, activity.responsible_staff_id
            ) or _officer_label(scope, activity.monitored_by_staff_id)
            label = f"{owner} · {label}" if owner else label
        options.append((activity.id, label))
    known = {option[0] for option in options}
    if (
        instance is not None
        and instance.activity_id
        and instance.activity_id not in known
    ):
        options.insert(0, (instance.activity_id, training_label(instance.activity)))
        known.add(instance.activity_id)
    if selected and selected not in known and scope:
        owners = [i for m in scope for i in (m.id, m.user_id) if i]
        extra = (
            Activity.objects.filter(id=selected, deleted_at__isnull=True)
            .filter(
                Q(responsible_staff_id__in=owners) | Q(monitored_by_staff_id__in=owners)
            )
            .select_related("school", "cluster")
            .first()
        )
        if extra is not None:
            options.insert(0, (extra.id, training_label(extra)))
    return options


def _debrief_options(members, *, member=None, selected="", instance=None):
    from apps.debriefs.models import DailyDebrief

    scope = [member] if member else list(members)
    names = {m.user_id: getattr(m.user, "name", "") for m in scope}
    options = []
    for debrief in coaching.officer_debriefs(scope)[:100]:
        label = coaching.debrief_label(debrief)
        if member is None and names.get(debrief.submitted_by_user_id):
            label = f"{names[debrief.submitted_by_user_id]} · {label}"
        options.append((debrief.id, label))
    known = {option[0] for option in options}
    if (
        instance is not None
        and instance.debrief_id
        and instance.debrief_id not in known
    ):
        options.insert(
            0, (instance.debrief_id, coaching.debrief_label(instance.debrief))
        )
        known.add(instance.debrief_id)
    if selected and selected not in known and scope:
        extra = DailyDebrief.objects.filter(
            id=selected,
            deleted_at__isnull=True,
            submitted_by_user_id__in=[m.user_id for m in scope if m.user_id],
        ).first()
        if extra is not None:
            options.insert(0, (extra.id, coaching.debrief_label(extra)))
    return options


def _coaching_fields(
    request, members, *, member=None, kind="", record=None, prefill=None
):
    """The one-column form for a coaching record. Observations take the five
    ratings and the activity watched; everything else takes the debrief or
    activity it answers, if any."""
    prefill = prefill or {}
    today = timezone.localdate()
    rated = kind in coaching.RATED_KINDS
    fields = []
    if record is None:
        fields.append(
            _field(
                "cceo_staff_id",
                "Officer",
                type="select",
                required=True,
                value=member.id if member else "",
                options=[(m.id, getattr(m.user, "name", "")) for m in members],
                blank="Choose the officer",
            )
        )
        kinds = [
            choice
            for choice in CoachingKind.choices
            if choice[0] in coaching.RECORDABLE_KINDS
            and (choice[0] in coaching.RATED_KINDS) == rated
        ]
        fields.append(
            _field(
                "kind",
                "What was observed" if rated else "Kind of coaching",
                type="select",
                required=True,
                value=kind,
                options=kinds,
                blank="Choose the kind",
            )
        )
    fields.append(
        _field(
            "held_on",
            "Observed on" if rated else "Held on",
            type="date",
            required=True,
            value=(record.held_on if record else today).isoformat(),
        )
    )
    activity_options = _activity_options(
        members,
        member=member,
        selected=prefill.get("activity", ""),
        instance=record,
    )
    fields.append(
        _field(
            "activity_id",
            "Training or visit observed" if rated else "Activity it concerns",
            type="select",
            value=record.activity_id if record else prefill.get("activity", ""),
            options=activity_options,
            blank="No activity" if not rated else "Choose the activity",
            help=(
                "Required for a training observation."
                if rated
                else "Optional: a recent activity of the officer's this coaching is about."
            ),
        )
    )
    if rated:
        for name, label, hint in OBSERVATION_CRITERIA:
            fields.append(
                _field(
                    name,
                    label,
                    type="select",
                    required=True,
                    value=getattr(record, name) if record else "",
                    options=RATING_SCALE,
                    blank="Rate from 1 to 4",
                    help=hint,
                )
            )
    else:
        fields.append(
            _field(
                "debrief_id",
                "Field debrief it answers",
                type="select",
                value=record.debrief_id if record else prefill.get("debrief", ""),
                options=_debrief_options(
                    members,
                    member=member,
                    selected=prefill.get("debrief", ""),
                    instance=record,
                ),
                blank="No field debrief",
                help="Optional: for feedback on a debrief the officer submitted.",
            )
        )
    fields += [
        _field(
            "subject",
            "Subject",
            value=record.subject if record else "",
            maxlength=255,
            placeholder="Filled in from the kind and the officer when left empty",
        ),
        _field(
            "strengths",
            "Strengths",
            type="textarea",
            rows=3,
            value=record.strengths if record else "",
            placeholder="What the officer did well",
        ),
        _field(
            "growth_areas",
            "Areas to grow",
            type="textarea",
            rows=3,
            value=record.growth_areas if record else "",
            placeholder="What to strengthen, and why it matters for schools",
        ),
        _field(
            "agreed_actions",
            "Actions agreed",
            type="textarea",
            rows=3,
            value=record.agreed_actions if record else "",
            placeholder="What the officer will do, with whom, by when",
        ),
        _field(
            "follow_up_due",
            "Follow up by",
            type="date",
            value=record.follow_up_due.isoformat()
            if record and record.follow_up_due
            else "",
            help="When you will check the actions agreed. You are reminded on the day.",
        ),
    ]
    if record is None or not record.shared_at:
        fields.append(
            _field(
                "share_now",
                "Share with the officer now",
                type="checkbox",
                help=(
                    "They are notified and asked to acknowledge it. You can still "
                    "correct it until they do."
                ),
            )
        )
    return fields


def _not_htmx_redirect(request, **params):
    query = urlencode({k: v for k, v in params.items() if v})
    return redirect(f"{TEAM_URL}?{query}" if query else TEAM_URL)


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def coaching_new_drawer(request):
    if not _is_htmx(request):
        # A plain link (the debrief page's "Log coaching") opens the log with
        # the drawer on top instead of a bare drawer fragment.
        return _not_htmx_redirect(
            request,
            open="new",
            **{key: request.GET.get(key, "") for key in PREFILL_PARAMS},
        )
    title = "Log coaching"
    subtitle = "A one-to-one, observation or feedback for an officer on your team"
    if not _is_lead(request):
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="Only the officer's Programme Lead records coaching.",
        )
    members = coaching._team(request.user)
    if not members:
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="No officers are assigned to you yet.",
        )
    prefill = {key: (request.GET.get(key) or "").strip() for key in PREFILL_PARAMS}
    member = coaching.officer_for(request.user, prefill["cceo"])
    kind = prefill["kind"] if prefill["kind"] in coaching.RECORDABLE_KINDS else ""
    rated = kind in coaching.RATED_KINDS
    return _drawer(
        request,
        title="Record an observation" if rated else title,
        subtitle=(f"For {member.user.name}" if member else subtitle),
        action=f"{TEAM_URL}/record",
        submit="Record observation" if rated else "Record coaching",
        fields=_coaching_fields(
            request, members, member=member, kind=kind, prefill=prefill
        ),
        note=(
            "Rate what you saw against the same rubric the Regional Lead uses for "
            "trainings, then write what to keep and what to change."
            if rated
            else "The record stays private to you until you share it with the officer."
        ),
    )


def _data(request) -> dict:
    return {key: request.POST.get(key) for key in request.POST}


@require_page_permission("team_coaching")
@require_POST
def coaching_record(request):
    data = _data(request)
    try:
        record = coaching.record_coaching(request.user, data)
        if data.get("share_now"):
            coaching.share_coaching(request.user, record.id)
            messages.success(request, "Coaching recorded and shared with the officer.")
        else:
            messages.success(
                request, "Coaching recorded. Share it when the officer should read it."
            )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, TEAM_URL)
    return _return(request, TEAM_URL)


def _visible_record(request, record_id):
    return (
        _record_queryset(coaching.coaching_visible_to(request.user))
        .filter(id=record_id)
        .first()
    )


def _people(record) -> tuple[str, str]:
    officer = _names_by_staff([record.cceo_staff_id]).get(record.cceo_staff_id, "")
    author = _names_by_user([record.author_id]).get(record.author_id, "")
    return officer, author


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def coaching_drawer(request, record_id):
    if not _is_htmx(request):
        return _not_htmx_redirect(request, open=record_id)
    record = _visible_record(request, record_id)
    if record is None:
        return _drawer(
            request,
            title="Coaching",
            subtitle="Performance & coaching",
            empty="This coaching record is not in your reach.",
        )
    officer, author = _people(record)
    editable = (
        _is_lead(request)
        and record.author_id == request.user.id
        and not record.acknowledged_at
    )
    if not editable:
        return _drawer(
            request,
            title=record.subject,
            subtitle=KIND_LABELS.get(record.kind, record.kind),
            facts=_record_facts(record, officer=officer, author=author),
            empty=(
                "Acknowledged by the officer, so it can no longer be changed."
                if record.acknowledged_at
                else "Read only."
            ),
        )
    members = coaching._team(request.user)
    member = next((m for m in members if m.id == record.cceo_staff_id), None)
    label, _tone = coaching.state_of(record)
    return _drawer(
        request,
        title=record.subject,
        subtitle=f"{KIND_LABELS.get(record.kind, record.kind)} · {officer}",
        facts=[
            {"label": "Officer", "value": officer},
            {"label": "State", "value": label},
            {"label": "Officer's response", "value": record.cceo_response},
        ],
        action=f"{TEAM_URL}/{record.id}/update",
        submit="Save",
        fields=_coaching_fields(
            request, members, member=member, kind=record.kind, record=record
        ),
        note=(
            "The officer can already read this record; saving tells them it changed."
            if record.shared_at
            else "The record stays private to you until you share it."
        ),
        note_tone="warning" if record.shared_at else "info",
    )


@require_page_permission("team_coaching")
@require_POST
def coaching_update(request, record_id):
    data = _data(request)
    try:
        record = coaching.update_coaching(request.user, record_id, data)
        if data.get("share_now") and not record.shared_at:
            coaching.share_coaching(request.user, record.id)
            messages.success(request, "Coaching saved and shared with the officer.")
        else:
            messages.success(request, "Coaching saved.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, TEAM_URL)
    return _return(request, TEAM_URL)


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def coaching_share_drawer(request, record_id):
    if not _is_htmx(request):
        return _not_htmx_redirect(request, open=record_id, step="share")
    record = _visible_record(request, record_id)
    if record is None:
        return _drawer(
            request,
            title="Share coaching",
            subtitle="Performance & coaching",
            empty="This coaching record is not in your reach.",
        )
    officer, author = _people(record)
    if not (_is_lead(request) and record.author_id == request.user.id):
        refusal = "Only the Programme Lead who wrote this coaching shares it."
    elif record.shared_at:
        refusal = f"Already shared with {officer} on {_day(record.shared_at)}."
    else:
        refusal = ""
    if refusal:
        return _drawer(
            request,
            title="Share coaching",
            subtitle=record.subject,
            facts=_record_facts(record, officer=officer, author=author),
            empty=refusal,
        )
    return _drawer(
        request,
        title="Share coaching",
        subtitle=record.subject,
        facts=_record_facts(record, officer=officer, author=author, for_officer=True),
        action=f"{TEAM_URL}/{record.id}/share/save",
        submit=f"Share with {officer or 'the officer'}",
        note=(
            "The officer is notified and asked to acknowledge it with a response. "
            "You can still correct the record until they do."
        ),
    )


@require_page_permission("team_coaching")
@require_POST
def coaching_share(request, record_id):
    try:
        coaching.share_coaching(request.user, record_id)
        messages.success(request, "Coaching shared. The officer has been told.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, TEAM_URL)
    return _return(request, TEAM_URL)


@require_page_permission("team_coaching")
@require_http_methods(["GET"])
def coaching_follow_up_drawer(request, record_id):
    if not _is_htmx(request):
        return _not_htmx_redirect(request, open=record_id, step="follow-up")
    record = _visible_record(request, record_id)
    if record is None:
        return _drawer(
            request,
            title="Follow up agreed actions",
            subtitle="Performance & coaching",
            empty="This coaching record is not in your reach.",
        )
    officer, author = _people(record)
    if not (_is_lead(request) and record.author_id == request.user.id):
        refusal = "Only the Programme Lead who wrote this coaching follows it up."
    elif not record.follow_up_due:
        refusal = "This coaching has no follow-up date."
    elif record.follow_up_done_at:
        refusal = f"Follow-up closed on {_day(record.follow_up_done_at)}."
    else:
        refusal = ""
    facts = [
        {"label": "Officer", "value": officer},
        {"label": "Subject", "value": record.subject},
        {"label": "Actions agreed", "value": record.agreed_actions},
        {"label": "Follow up by", "value": _day(record.follow_up_due)},
        {"label": "Officer's response", "value": record.cceo_response},
    ]
    if refusal:
        return _drawer(
            request,
            title="Follow up agreed actions",
            subtitle=record.subject,
            facts=facts + [{"label": "Follow-up note", "value": record.follow_up_note}],
            empty=refusal,
        )
    return _drawer(
        request,
        title="Follow up agreed actions",
        subtitle=f"With {officer}" if officer else record.subject,
        facts=facts,
        action=f"{TEAM_URL}/{record.id}/follow-up/save",
        submit="Close follow-up",
        fields=[
            _field(
                "follow_up_note",
                "What you found",
                type="textarea",
                required=True,
                rows=4,
                placeholder="Done, in progress or not started — and what happens next",
                help="Kept in your log; the officer sees that the follow-up was closed.",
            )
        ],
    )


@require_page_permission("team_coaching")
@require_POST
def coaching_follow_up(request, record_id):
    try:
        coaching.complete_follow_up(
            request.user, record_id, request.POST.get("follow_up_note", "")
        )
        messages.success(request, "Follow-up closed.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, TEAM_URL)
    return _return(request, TEAM_URL)


# ── The officer's coaching ───────────────────────────────────────────────────
@require_page_permission("my_coaching")
@require_http_methods(["GET"])
def my_coaching_view(request):
    """Coaching the officer's Programme Lead shared with them."""
    today = timezone.localdate()
    visible = coaching.coaching_visible_to(request.user)
    officer = request.user.active_role == coaching.CCEO
    kind = request.GET.get("kind") or ""
    state = request.GET.get("state") or ""
    records = visible
    if kind in CoachingKind.values:
        records = records.filter(kind=kind)
    states = [
        (coaching.STATE_AWAITING, "Awaiting your acknowledgement"),
        (coaching.STATE_ACKNOWLEDGED, "Acknowledged"),
    ]
    if state in dict(states):
        records = coaching.with_state(records, state, today=today)
    records = list(records.order_by("-held_on", "-created_at")[:500])
    authors = _names_by_user(r.author_id for r in records)
    officers = {} if officer else _names_by_staff(r.cceo_staff_id for r in records)

    rows = []
    for record in records:
        label, tone = coaching.state_of(record, today=today, officer_view=officer)
        cells = [_cell("Coaching", record.subject, primary=True)]
        if not officer:
            cells.append(_cell("Officer", officers.get(record.cceo_staff_id, "")))
        cells += [
            _cell("Kind", KIND_LABELS.get(record.kind, record.kind)),
            _cell("Held", _day(record.held_on)),
            _cell("From", authors.get(record.author_id, "")),
            _cell("Follow up by", _day(record.follow_up_due)),
            _cell("State", label, tone=tone),
        ]
        action = "Acknowledge" if officer and not record.acknowledged_at else "Open"
        rows.append(
            {
                "cells": cells,
                "actions": [{"label": action, "drawer": f"{MY_URL}/{record.id}"}],
            }
        )

    counts = coaching.coaching_counts(visible, today=today)
    metrics = [
        _metric(
            "Coaching Awaiting My Acknowledgement",
            counts["awaiting"],
            "shared with you, not yet answered",
            "warning" if counts["awaiting"] else "info",
        ),
        _metric(
            "Coaching I Have Acknowledged",
            counts["acknowledged"],
            "with your response",
            "success",
        ),
        _metric(
            "Agreed Coaching Actions Open",
            counts["follow_ups_open"],
            "your lead will follow these up",
        ),
    ]
    return _render(
        request,
        {
            "title": "My Coaching",
            "eyebrow": "My performance",
            "description": (
                "What your Programme Lead shared from your one-to-ones, the visits "
                "and trainings they observed, and feedback passed on from the "
                "Regional Lead. Acknowledge each one and say what you will do."
            ),
            "metrics": metrics,
            "rows": rows,
            "register_title": "Coaching shared with you"
            if officer
            else "Shared coaching",
            "empty_title": "No coaching shared with you yet",
            "empty_body": "Coaching appears here when your Programme Lead shares it with you.",
            "filters": {
                "fields": [
                    {
                        "name": "kind",
                        "label": "Kind",
                        "value": kind,
                        "blank": "Every kind",
                        "options": list(CoachingKind.choices),
                    },
                    {
                        "name": "state",
                        "label": "State",
                        "value": state,
                        "blank": "Every state",
                        "options": states,
                    },
                ]
            },
            "autoload_drawer": _autoload(request, visible, MY_URL, lead=False),
        },
    )


@require_page_permission("my_coaching")
@require_http_methods(["GET"])
def my_coaching_drawer(request, record_id):
    if not _is_htmx(request):
        return redirect(f"{MY_URL}?open={record_id}")
    record = _visible_record(request, record_id)
    if record is None:
        return _drawer(
            request,
            title="Coaching",
            subtitle="My performance",
            empty="This coaching was not shared with you.",
        )
    officer, author = _people(record)
    facts = _record_facts(record, officer=officer, author=author, for_officer=True)
    can_acknowledge = (
        request.user.active_role == coaching.CCEO and not record.acknowledged_at
    )
    if not can_acknowledge:
        return _drawer(
            request,
            title=record.subject,
            subtitle=f"From {author}" if author else "Coaching",
            facts=facts,
            empty="Acknowledged." if record.acknowledged_at else "Read only.",
        )
    return _drawer(
        request,
        title=record.subject,
        subtitle=f"From {author}" if author else "Coaching",
        facts=facts,
        action=f"{MY_URL}/{record.id}/acknowledge",
        submit="Acknowledge coaching",
        fields=[
            _field(
                "response",
                "Your response",
                type="textarea",
                required=True,
                rows=4,
                placeholder="What you will keep doing, what you will change, and by when",
            )
        ],
    )


@require_page_permission("my_coaching")
@require_POST
def my_coaching_acknowledge(request, record_id):
    try:
        coaching.acknowledge_coaching(
            request.user, record_id, request.POST.get("response", "")
        )
        messages.success(
            request, "Coaching acknowledged. Your Programme Lead has been told."
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, MY_URL)
    return _return(request, MY_URL)
