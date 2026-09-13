"""Screens for the partner engagement log (owner, 2026-09-13).

The Programme Lead "partners with … local training organizations to align
goals and build capacity". The log of that work — review meetings,
orientations on Edify's CCE framework, training quality follow-ups, joint
planning and capacity-building sessions — renders as a register on Partner
Oversight (the Programme Lead's and Country Director's partner page) and on
each partner's profile, with one-column drawers to record, change, follow up
and share an engagement.

Rules, permissions and audit rows live in apps.partners.engagement_services;
these views render and route, so a refusal the service raises is the message
the reader sees. Drawers reuse partials/hr/form_drawer.html through the
hr_programme_views helpers.

Every route is gated on `partner_detail` — the page every engagement belongs
to, open to every role — and the service narrows who may read or write each
record, so the gate never widens what a role reads.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse

from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.partners import engagement_services as services
from apps.partners.models import PartnerEngagementKind

BASE_URL = "/partner-engagements"
FALLBACK_URL = "/partner-oversight/"

# Query parameters that open a drawer on page load; dropped from the page a
# drawer's form returns to, or the drawer would open again.
AUTOLOAD_PARAMS = ("engagement", "step", "record", "source")

# Rows per register page.
PAGE_PARAM = "engagement_page"


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.partner_engagement_views:_metric",
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


def _return(request, fallback: str):
    """Back to the page the drawer was opened from — never off-site, and
    without the parameters that opened the drawer."""
    target = (request.POST.get("next") or "").strip()
    parsed = urlparse(target) if target else None
    if parsed and parsed.path.startswith("/"):
        same_site = not parsed.netloc.strip() or parsed.netloc == request.get_host()
        if same_site:
            query = urlencode(
                [
                    (key, value)
                    for key, value in parse_qsl(parsed.query)
                    if key not in AUTOLOAD_PARAMS
                ]
            )
            url = parsed.path + (f"?{query}" if query else "")
            if url_has_allowed_host_and_scheme(
                url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ) and not url.startswith(("//", "/\\")):
                return redirect(url)
    return redirect(fallback)


def _refused(request, exc, fallback: str):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _return(request, fallback)


def _author_names(author_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = {i for i in author_ids if i}
    if not ids:
        return {}
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def _observation_label(observation) -> str:
    from apps.cce_leadership.services import training_label

    recommendation = observation.get_recommendation_display()
    parts = [training_label(observation.activity)]
    if recommendation:
        parts.append(recommendation)
    return " · ".join(parts)


# ── Register (rendered inside Partner Oversight and the partner profile) ─────
def engagement_register(
    request, *, fy: str, partner_id: str | None = None, rows_in_fy: bool = False
) -> dict:
    """The engagement register's context for one page section.

    `partner_id` narrows it to one organisation (the profile, or a partner tab
    on Partner Oversight); `rows_in_fy` narrows the rows to the page's FY
    (Partner Oversight's period — the profile keeps the whole history). Bulk: the engagements, their authors' names, the
    tile aggregate and the open Regional Lead observations — a fixed number of
    queries whatever the number of rows.
    """
    user = request.user
    today = timezone.localdate()
    can_record = services.can_record(user)
    visible = services.engagements_visible_to(user)
    if partner_id:
        visible = visible.filter(partner_id=partner_id)
    if rows_in_fy:
        visible = visible.filter(fy=fy)
    engagements = list(visible.order_by("-held_on", "-created_at")[:500])
    me = services._uid(user)
    readers_see_authors = services._role(user) != services.PROGRAM_LEAD
    authors = (
        _author_names(e.author_id for e in engagements) if readers_see_authors else {}
    )

    rows = []
    for engagement in engagements:
        state, tone = services.follow_up_state(engagement, today)
        mine = engagement.author_id == me
        actions = [{"label": "Open", "drawer": f"{BASE_URL}/{engagement.id}"}]
        if (
            mine
            and engagement.follow_up_due
            and not engagement.follow_up_done_at
            and engagement.follow_up_due <= today
        ):
            actions.append(
                {
                    "label": "Follow up",
                    "drawer": f"{BASE_URL}/{engagement.id}/follow-up",
                }
            )
        if mine and not engagement.shared_with_partner_at:
            actions.append(
                {"label": "Share", "drawer": f"{BASE_URL}/{engagement.id}/share"}
            )
        cells = [
            _cell("Engagement", engagement.subject, primary=True),
            _cell("Partner", engagement.partner.name),
            _cell("Kind", services.KIND_LABELS.get(engagement.kind, engagement.kind)),
            _cell("Held", _day(engagement.held_on)),
            _cell("Agreed improvements", engagement.agreed_improvements[:120]),
            _cell("Follow-up", state, tone=tone),
            _cell(
                "Shared with partner",
                f"Shared {_day(engagement.shared_with_partner_at)}"
                if engagement.shared_with_partner_at
                else "Not shared",
                tone="success" if engagement.shared_with_partner_at else "neutral",
            ),
        ]
        if readers_see_authors:
            cells.append(_cell("Recorded by", authors.get(engagement.author_id, "")))
        rows.append({"cells": cells, "actions": actions})

    counts = services.engagement_counts(user, fy=fy, partner_id=partner_id)
    open_observations = [
        entry
        for entry in services.open_observation_follow_ups(user)
        if not partner_id or entry["partner_id"] == partner_id
    ]
    metrics = [
        _metric(
            "Partner Engagements This FY",
            counts["recorded"],
            f"FY{fy} · meetings, orientations and follow-ups",
        ),
        _metric(
            "Partners Engaged This FY",
            counts["partners_engaged"],
            "organisations with at least one engagement",
        ),
        _metric(
            "Partner Follow-Ups Due",
            counts["follow_ups_due"],
            "agreed improvements to check on",
            "danger" if counts["follow_ups_due"] else "info",
        ),
    ]
    if services._role(user) == services.PROGRAM_LEAD:
        metrics.append(
            _metric(
                "Regional Lead Observations Awaiting Partner Follow-Up",
                len(open_observations),
                "strengthen or replace, no engagement since",
                "warning" if open_observations else "info",
            )
        )

    new_url = f"{BASE_URL}/new" + (f"?partner={partner_id}" if partner_id else "")
    # The Record button sits in the register's title bar, where actions are
    # links: without HTMX it opens this page with the record drawer on load
    # (autoload_drawer reads ?record=1), keeping the page's own filters.
    kept = [
        (key, value)
        for key, value in request.GET.items()
        if key not in AUTOLOAD_PARAMS and key != PAGE_PARAM
    ]
    new_page = f"{request.path}?{urlencode([*kept, ('record', '1')])}"
    return {
        "rows": rows,
        "has_row_actions": any(row["actions"] for row in rows),
        "metrics": metrics,
        "can_record": can_record,
        "new_drawer": new_url,
        "new_page": new_page,
        "page_param": PAGE_PARAM,
        "observations": [
            {
                "partner_name": entry["partner_name"],
                "label": _observation_label(entry["observation"]),
                "held_on": _day(entry["observation"].held_on),
                "drawer": f"{BASE_URL}/new?"
                + urlencode(
                    {
                        "partner": entry["partner_id"],
                        "source": entry["observation"].id,
                        "kind": PartnerEngagementKind.QUALITY_FOLLOW_UP,
                    }
                ),
            }
            for entry in open_observations[:5]
        ],
        "observations_total": len(open_observations),
    }


def autoload_drawer(request, *, partner_id: str | None = None) -> str:
    """The drawer a To-Do or notification link asks for on page load:
    `?engagement=<id>` (with `step=follow-up|share`) for an engagement the
    reader may open, or `?record=1&source=<observation id>` to record one."""
    engagement_id = (request.GET.get("engagement") or "").strip()
    if engagement_id:
        visible = services.engagements_visible_to(request.user)
        if partner_id:
            visible = visible.filter(partner_id=partner_id)
        if not visible.filter(id=engagement_id).exists():
            return ""
        step = (request.GET.get("step") or "").strip()
        suffix = f"/{step}" if step in ("follow-up", "share") else ""
        return f"{BASE_URL}/{engagement_id}{suffix}"
    if request.GET.get("record") and services.can_record(request.user):
        params = {"partner": partner_id or request.GET.get("partner") or ""}
        source = (request.GET.get("source") or "").strip()
        if source:
            params["source"] = source
            params["kind"] = PartnerEngagementKind.QUALITY_FOLLOW_UP
        return f"{BASE_URL}/new?{urlencode({k: v for k, v in params.items() if v})}"
    return ""


# ── Drawers ──────────────────────────────────────────────────────────────────
def _fields(request, *, engagement=None, partner_id="", source_id="", kind=""):
    user = request.user
    partners = services.recordable_partners(user)
    if engagement is not None and engagement.partner_id not in {p.id for p in partners}:
        partners = [engagement.partner, *partners]
    chosen_partner = partner_id or (engagement.partner_id if engagement else "")
    observations = list(
        services.linkable_observations(user, chosen_partner or None).select_related(
            "activity", "activity__school", "activity__cluster"
        )[: services.OBSERVATION_OPTIONS_LIMIT]
    )
    today = timezone.localdate()
    fields = [
        _field(
            "partner_id",
            "Training partner",
            type="select",
            required=True,
            value=chosen_partner,
            options=[(p.id, p.name) for p in partners],
            blank="Choose a partner",
        ),
        _field(
            "kind",
            "Kind of engagement",
            type="select",
            required=True,
            value=kind or (engagement.kind if engagement else ""),
            options=PartnerEngagementKind.choices,
            blank="Choose a kind",
        ),
        _field(
            "held_on",
            "Held on",
            type="date",
            required=True,
            value=(engagement.held_on if engagement else today).isoformat(),
        ),
        _field(
            "subject",
            "Subject",
            required=True,
            maxlength=255,
            value=engagement.subject if engagement else "",
            placeholder="e.g. Quarterly review of Term 2 trainings",
        ),
        _field(
            "notes",
            "Notes",
            type="textarea",
            rows=4,
            value=engagement.notes if engagement else "",
            help="What was discussed and what you observed.",
        ),
        _field(
            "agreed_improvements",
            "Agreed improvements",
            type="textarea",
            rows=3,
            value=engagement.agreed_improvements if engagement else "",
            help="What the partner agreed to change. Required with a follow-up date.",
        ),
        _field(
            "follow_up_due",
            "Follow up by",
            type="date",
            value=(
                engagement.follow_up_due.isoformat()
                if engagement and engagement.follow_up_due
                else ""
            ),
            help="When you will check the agreed improvements were made.",
        ),
    ]
    if observations or (engagement and engagement.source_engagement_id):
        options = [(o.id, _observation_label(o)) for o in observations]
        current = source_id or (engagement.source_engagement_id if engagement else "")
        if (
            engagement
            and engagement.source_engagement_id
            and current not in {o[0] for o in options}
        ):
            options.insert(
                0,
                (engagement.source_engagement_id, engagement.source_engagement.subject),
            )
        fields.append(
            _field(
                "source_engagement_id",
                "Regional Lead observation it answers",
                type="select",
                value=current,
                options=options,
                blank="None",
                help="An observation of a training this partner delivered.",
            )
        )
    return fields


@require_page_permission("partner_detail")
@require_http_methods(["GET"])
def engagement_new_drawer(request):
    title = "Record a partner engagement"
    subtitle = "Partnership and capacity building with a training partner"
    if not services.can_record(request.user):
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="Only a Programme Lead or the Country Director records partner engagements.",
        )
    kind = (request.GET.get("kind") or "").strip()
    return _drawer(
        request,
        title=title,
        subtitle=subtitle,
        action=f"{BASE_URL}/record",
        submit="Record engagement",
        fields=_fields(
            request,
            partner_id=(request.GET.get("partner") or "").strip(),
            source_id=(request.GET.get("source") or "").strip(),
            kind=kind if kind in PartnerEngagementKind.values else "",
        ),
        note=(
            "Record a meeting once it has happened. Agree improvements with a "
            "follow-up date and the follow-up comes back to your To-Do list."
        ),
    )


def _data(request) -> dict:
    return {key: request.POST.get(key) for key in request.POST}


@require_page_permission("partner_detail")
@require_POST
def engagement_record(request):
    try:
        engagement = services.record_engagement(request.user, _data(request))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, FALLBACK_URL)
    messages.success(request, f"Engagement with {engagement.partner.name} recorded.")
    return _return(request, FALLBACK_URL)


def _visible_or_none(request, engagement_id: str):
    return (
        services.engagements_visible_to(request.user).filter(id=engagement_id).first()
    )


def _facts(engagement, today) -> list[dict]:
    state, _tone = services.follow_up_state(engagement, today)
    facts = [
        {"label": "Partner", "value": engagement.partner.name},
        {
            "label": "Kind",
            "value": services.KIND_LABELS.get(engagement.kind, engagement.kind),
        },
        {"label": "Held on", "value": _day(engagement.held_on)},
        {"label": "Subject", "value": engagement.subject},
        {"label": "Notes", "value": engagement.notes},
        {"label": "Agreed improvements", "value": engagement.agreed_improvements},
        {"label": "Follow-up", "value": state},
    ]
    if engagement.follow_up_note:
        facts.append({"label": "Follow-up finding", "value": engagement.follow_up_note})
    if engagement.source_engagement_id:
        facts.append(
            {
                "label": "Regional Lead observation",
                "value": engagement.source_engagement.subject,
            }
        )
    facts.append(
        {
            "label": "Shared with the partner",
            "value": _day(engagement.shared_with_partner_at) or "Not shared",
        }
    )
    return facts


@require_page_permission("partner_detail")
@require_http_methods(["GET"])
def engagement_drawer(request, engagement_id):
    engagement = _visible_or_none(request, engagement_id)
    title = "Partner engagement"
    if engagement is None:
        return _drawer(
            request,
            title=title,
            subtitle="Partnership record",
            empty="This engagement is not one you can open.",
        )
    today = timezone.localdate()
    subtitle = f"{engagement.partner.name} · {_day(engagement.held_on)}"
    mine = engagement.author_id == services._uid(request.user)
    if mine and services.is_editable(engagement):
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            action=f"{BASE_URL}/{engagement.id}/update",
            submit="Save changes",
            fields=_fields(request, engagement=engagement),
            note=(
                "You can change this record until you share it with the partner "
                "or close its follow-up."
            ),
        )
    return _drawer(
        request,
        title=title,
        subtitle=subtitle,
        facts=_facts(engagement, today),
    )


@require_page_permission("partner_detail")
@require_POST
def engagement_update(request, engagement_id):
    try:
        services.update_engagement(request.user, engagement_id, _data(request))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, FALLBACK_URL)
    messages.success(request, "Engagement updated.")
    return _return(request, FALLBACK_URL)


def _own_or_message(request, engagement_id):
    """The author's own engagement, or the refusal to show in the drawer."""
    try:
        return services.own_engagement(request.user, engagement_id), ""
    except (Forbidden, NotFoundError) as exc:
        return None, str(getattr(exc, "detail", exc))


@require_page_permission("partner_detail")
@require_http_methods(["GET"])
def engagement_follow_up_drawer(request, engagement_id):
    engagement, refusal = _own_or_message(request, engagement_id)
    title = "Close the follow-up"
    if engagement is None:
        return _drawer(
            request, title=title, subtitle="Partner engagement", empty=refusal
        )
    subtitle = f"{engagement.partner.name} · {engagement.subject}"
    if not engagement.follow_up_due or engagement.follow_up_done_at:
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="This engagement has no open follow-up.",
        )
    return _drawer(
        request,
        title=title,
        subtitle=subtitle,
        action=f"{BASE_URL}/{engagement.id}/follow-up/save",
        submit="Close follow-up",
        facts=[
            {"label": "Agreed improvements", "value": engagement.agreed_improvements},
            {"label": "Follow up by", "value": _day(engagement.follow_up_due)},
        ],
        fields=[
            _field(
                "follow_up_note",
                "What the follow-up found",
                type="textarea",
                required=True,
                rows=4,
                help="Were the agreed improvements made? What happens next?",
            )
        ],
    )


@require_page_permission("partner_detail")
@require_POST
def engagement_follow_up(request, engagement_id):
    try:
        engagement = services.complete_follow_up(
            request.user, engagement_id, request.POST.get("follow_up_note") or ""
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, FALLBACK_URL)
    messages.success(request, f"Follow-up with {engagement.partner.name} closed.")
    return _return(request, FALLBACK_URL)


@require_page_permission("partner_detail")
@require_http_methods(["GET"])
def engagement_share_drawer(request, engagement_id):
    engagement, refusal = _own_or_message(request, engagement_id)
    title = "Share with the partner"
    if engagement is None:
        return _drawer(
            request, title=title, subtitle="Partner engagement", empty=refusal
        )
    subtitle = f"{engagement.partner.name} · {engagement.subject}"
    if engagement.shared_with_partner_at:
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty="This engagement is already shared with the partner.",
        )
    if not engagement.partner.user_id:
        return _drawer(
            request,
            title=title,
            subtitle=subtitle,
            empty=(
                f"{engagement.partner.name} has no login on the platform, so the "
                "record cannot reach them here. Share the agreed improvements "
                "with them directly."
            ),
        )
    return _drawer(
        request,
        title=title,
        subtitle=subtitle,
        action=f"{BASE_URL}/{engagement.id}/share/save",
        submit="Share with the partner",
        facts=_facts(engagement, timezone.localdate()),
        note=(
            "The partner's login is notified and reads this record on its profile. "
            "Once shared, the record can no longer be changed."
        ),
        note_tone="warning",
    )


@require_page_permission("partner_detail")
@require_POST
def engagement_share(request, engagement_id):
    try:
        engagement = services.share_with_partner(request.user, engagement_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, FALLBACK_URL)
    messages.success(request, f"Shared with {engagement.partner.name}.")
    return _return(request, FALLBACK_URL)


__all__ = [
    "autoload_drawer",
    "engagement_register",
    "engagement_new_drawer",
    "engagement_record",
    "engagement_drawer",
    "engagement_update",
    "engagement_follow_up_drawer",
    "engagement_follow_up",
    "engagement_share_drawer",
    "engagement_share",
]
