"""Impact Assessment's Measurement Framework page (IA review, owner, 2026-09-13).

/ia/framework/ is where IA defines what success means and how each programme
step is judged: four tabs over apps.impact.framework — Outcome areas,
Indicators, Measurement rules and Loan purposes. The rules, permissions,
review and audit rows live in the services; these views render and route, so
a refusal a service raises is the message the reader sees.

Who does what: an Impact Assessment officer drafts and submits; a second
officer in the same country reviews; the Country Director acknowledges only
where the country has a single officer; Admin reads. Drawers are the platform's
one-column form drawer (partials/hr/form_drawer.html via hr_programme_views);
the measurement rule drawer keeps its own template for its checkbox groups and
version history (apps/frontend/views/ssa_mapping_views.py).
"""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.enums import SsaIntervention
from apps.core.exceptions import NotFoundError
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.impact import framework as fw
from apps.impact.models import (
    DefinitionStatus,
    IndicatorDefinition,
    IndicatorLevel,
    IndicatorSource,
    OutcomeArea,
)

FRAMEWORK_URL = "/ia/framework/"

TABS = (
    ("areas", "Outcome areas"),
    ("indicators", "Indicators"),
    ("rules", "Measurement rules"),
    ("purposes", "Loan purposes"),
)
TAB_KEYS = {key for key, _ in TABS}

REVIEW_DECISIONS = (
    ("approve", "Approve"),
    ("return", "Return with a note"),
)


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.ia_framework_views:_metric",
        label,
        value,
        helper=helper,
        tone=tone,
    )


def _cell(heading: str, text, *, primary=False, tone="") -> dict:
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _back(request, fallback: str = FRAMEWORK_URL):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, fallback, drop=("open",)))


def _refused(request, exc, fallback: str = FRAMEWORK_URL):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


def _tab_url(tab: str, **params) -> str:
    from urllib.parse import urlencode

    query = urlencode({"tab": tab, **{k: v for k, v in params.items() if v}})
    return f"{FRAMEWORK_URL}?{query}"


# ── The page ────────────────────────────────────────────────────────────────


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def framework_page(request):
    """The measurement framework: what success means and how it is judged."""
    tab = request.GET.get("tab") or "areas"
    if tab not in TAB_KEYS:
        tab = "areas"
    counts = fw.framework_counts(request.user)
    metrics = [
        _metric(
            "Activities Without a Measurement Rule",
            counts["items_unmapped"],
            "school-outcome activities with no live rule",
            "danger" if counts["items_unmapped"] else "info",
        ),
        _metric(
            "Measurement Rules Published",
            counts["rules_published"],
            "reviewed by a second person",
        ),
        _metric(
            "Published Rules Without a Follow-up Window",
            counts["rules_without_window"],
            "judged on any later reading",
            "warning" if counts["rules_without_window"] else "info",
        ),
        _metric(
            "Indicators Approved",
            counts["indicators_approved"],
            "current approved definitions",
        ),
        _metric(
            "Loan Purposes Without Measurement",
            counts["loan_purposes_undefined"],
            "active purposes with no measurement profile",
            "danger" if counts["loan_purposes_undefined"] else "info",
        ),
    ]
    builder = {
        "areas": _areas_tab,
        "indicators": _indicators_tab,
        "rules": _rules_tab,
        "purposes": _purposes_tab,
    }[tab]
    context = builder(request)
    return render(
        request,
        "pages/ia/framework.html",
        {
            "tab": tab,
            "tabs": [
                {"key": key, "label": label, "url": _tab_url(key), "active": key == tab}
                for key, label in TABS
            ],
            "metrics": metrics,
            "may_author": fw.may_author(request.user),
            "autoload_drawer": _autoload(request),
            **context,
        },
    )


def _autoload(request) -> str:
    """The drawer a To-Do or notification link (?open=<kind>-<id>) asks for,
    when that record exists. The drawer view applies its own permission."""
    from apps.activity_catalogue.models import ActivityInterventionMapping

    target = (request.GET.get("open") or "").strip()
    kind, _, record_id = target.partition("-")
    if not record_id:
        return ""
    if kind == "rule":
        row = ActivityInterventionMapping.objects.filter(id=record_id).first()
        if row is None:
            return ""
        if row.status == "in_review":
            return f"/priorities/ssa-mapping/rules/{row.id}/review"
        return f"/priorities/ssa-mapping/{row.catalogue_item_id}/history"
    if kind == "area" and OutcomeArea.objects.filter(id=record_id).exists():
        return f"{FRAMEWORK_URL}areas/{record_id}/"
    if (
        kind == "indicator"
        and IndicatorDefinition.objects.filter(id=record_id).exists()
    ):
        return f"{FRAMEWORK_URL}indicators/{record_id}/"
    return ""


def _status_filter(value, options):
    return {
        "name": "status",
        "label": "Status",
        "value": value,
        "blank": "Every status",
        "options": list(options),
    }


def _areas_tab(request):
    status = request.GET.get("status") or ""
    rows = []
    for entry in fw.definitions_register(request.user, "area", status=status):
        record = entry["record"]
        actions = [{"label": "Open", "drawer": f"{FRAMEWORK_URL}areas/{record.id}/"}]
        if entry["can_submit"]:
            actions.append(
                {"label": "Submit", "drawer": f"{FRAMEWORK_URL}area/{record.id}/submit"}
            )
        if entry["can_review"]:
            actions.append(
                {"label": "Review", "drawer": f"{FRAMEWORK_URL}area/{record.id}/review"}
            )
        rows.append(
            {
                "cells": [
                    _cell("Outcome area", record.name, primary=True),
                    _cell("SSA domains (proxy)", entry["domains"]),
                    _cell("Version", f"v{record.version}"),
                    _cell("Status", entry["state"], tone=entry["tone"]),
                    _cell("Written by", entry["author"]),
                    _cell("Reviewed by", entry["reviewer"]),
                ],
                "actions": actions,
            }
        )
    header_actions = []
    notice = None
    if fw.may_author(request.user):
        header_actions.append(
            {"label": "New outcome area", "drawer": f"{FRAMEWORK_URL}areas/new"}
        )
        existing = set(OutcomeArea.objects.values_list("code", flat=True))
        if any(p["code"] not in existing for p in fw.PROPOSED_OUTCOME_AREAS):
            notice = {
                "tone": "info",
                "text": (
                    "Three outcome areas are proposed for review: spiritual formation "
                    "(CB, WOG), educational quality (LE, TE, LSHIP) and sustainability "
                    "(FH, GR, ENR). Draft them, adjust the definitions, and submit "
                    "each for a second officer's review."
                ),
                "post": f"{FRAMEWORK_URL}areas/propose",
                "post_label": "Draft the proposed areas",
            }
    return {
        "rows": rows,
        "register_title": "Outcome areas",
        "empty_title": "No outcome areas defined",
        "empty_body": (
            "An outcome area names a dimension of transformation Edify measures and "
            "the SSA domains read as its school-level proxy."
        ),
        "header_actions": header_actions,
        "notice": notice,
        "filters": {
            "tab": "areas",
            "fields": [_status_filter(status, DefinitionStatus.choices)],
        },
        "description": (
            "The long-term change in partner schools Edify exists for. SSA domains "
            "are school-level proxies for each area, never proof of it on their own."
        ),
    }


def _indicators_tab(request):
    status = request.GET.get("status") or ""
    rows = []
    for entry in fw.definitions_register(request.user, "indicator", status=status):
        record = entry["record"]
        actions = [
            {"label": "Open", "drawer": f"{FRAMEWORK_URL}indicators/{record.id}/"}
        ]
        if entry["can_submit"]:
            actions.append(
                {
                    "label": "Submit",
                    "drawer": f"{FRAMEWORK_URL}indicator/{record.id}/submit",
                }
            )
        if entry["can_review"]:
            actions.append(
                {
                    "label": "Review",
                    "drawer": f"{FRAMEWORK_URL}indicator/{record.id}/review",
                }
            )
        rows.append(
            {
                "cells": [
                    _cell("Indicator", record.name, primary=True),
                    _cell("Level", record.get_level_display()),
                    _cell(
                        "Outcome area",
                        record.outcome_area.name if record.outcome_area_id else "",
                    ),
                    _cell("Source", record.get_source_display()),
                    _cell("Version", f"v{record.version}"),
                    _cell("Scope", record.country or "All countries"),
                    _cell("Status", entry["state"], tone=entry["tone"]),
                    _cell("Reviewed by", entry["reviewer"]),
                ],
                "actions": actions,
            }
        )
    return {
        "rows": rows,
        "register_title": "Indicators",
        "empty_title": "No indicators defined",
        "empty_body": (
            "Each indicator states what is counted, over which population and "
            "denominator, from which baseline, how often, and what it cannot show."
        ),
        "header_actions": (
            [{"label": "New indicator", "drawer": f"{FRAMEWORK_URL}indicators/new"}]
            if fw.may_author(request.user)
            else []
        ),
        "notice": None,
        "filters": {
            "tab": "indicators",
            "fields": [_status_filter(status, DefinitionStatus.choices)],
        },
        "description": (
            "Measures of success, versioned append-only: a changed definition is a "
            "new version, so earlier results keep the definition they were measured by."
        ),
    }


def _rules_tab(request):
    programme = request.GET.get("programme") or ""
    status = request.GET.get("status") or ""
    register = fw.rules_register(request.user, programme=programme, status=status)
    may_manage = fw.may_author(request.user)
    rows = []
    for entry in register["rows"]:
        item = entry["item"]
        actions = []
        if may_manage:
            actions.append(
                {
                    "label": "Edit rule"
                    if entry["state"] != "Mapping required"
                    else "Link intervention",
                    "drawer": f"/priorities/ssa-mapping/{item.id}/drawer",
                }
            )
        if entry["can_review"]:
            actions.append(
                {
                    "label": "Review",
                    "drawer": f"/priorities/ssa-mapping/rules/{entry['pending'].id}/review",
                }
            )
        actions.append(
            {"label": "History", "drawer": f"/priorities/ssa-mapping/{item.id}/history"}
        )
        rows.append(
            {
                "cells": [
                    _cell("Programme", entry["programme"]),
                    _cell("Activity", item.display_name, primary=True),
                    _cell("SSA domain", entry["intervention"]),
                    _cell("Success looks like", entry["direction"]),
                    _cell("Follow-up window", entry["window"]),
                    _cell("Meaningful change", entry["threshold"]),
                    _cell("Scope", entry["scope"]),
                    _cell("Version", entry["version"]),
                    _cell("Status", entry["state"], tone=entry["tone"]),
                    _cell("Reviewed by", entry["reviewed_by"]),
                ],
                "actions": actions,
            }
        )
    fields = []
    programmes = [p for p in register["programmes"] if p]
    if programmes:
        fields.append(
            {
                "name": "programme",
                "label": "Programme",
                "value": programme,
                "blank": "Every programme",
                "options": [(p, p) for p in programmes],
            }
        )
    fields.append(_status_filter(status, fw.RULE_STATUS_FILTERS))
    return {
        "rows": rows,
        "register_title": "Measurement rules",
        "empty_title": "No school-outcome activities match",
        "empty_body": "Clear the filters to see every activity with a school outcome.",
        "header_actions": [],
        "notice": {
            "tone": "info",
            "text": (
                "Only a published rule measures anything, and nobody publishes their "
                "own: save a draft, submit it with the reason for the change, and a "
                "second officer reviews it. Enrolments keep the rule stamped at their "
                "first verified delivery. Where no threshold is approved, any change "
                "counts, and readings under 120 days apart are not compared."
            ),
        },
        "filters": {"tab": "rules", "fields": fields},
        "description": (
            "Which SSA domain each school-facing, cluster or training activity is "
            "meant to move, how long before a follow-up means anything, and what "
            "counts as change."
        ),
    }


def _purposes_tab(request):
    rows = []
    for entry in fw.loan_purposes_register(request.user):
        purpose = entry["purpose"]
        actions = []
        if fw.may_author(request.user) and entry["in_country"]:
            actions.append(
                {
                    "label": "Define measurement",
                    "drawer": f"{FRAMEWORK_URL}purposes/{purpose.id}/",
                }
            )
        if entry["can_review"]:
            actions.append(
                {
                    "label": "Review",
                    "drawer": f"{FRAMEWORK_URL}indicator/{entry['record'].id}/review",
                }
            )
        if entry["record"] is not None and fw.may_author(request.user):
            record = entry["record"]
            if record.status in fw.PENDING and record.author_id == str(request.user.id):
                actions.append(
                    {
                        "label": "Submit",
                        "drawer": f"{FRAMEWORK_URL}indicator/{record.id}/submit",
                    }
                )
        rows.append(
            {
                "cells": [
                    _cell("Loan purpose", purpose.label, primary=True),
                    _cell("Kind", entry["edtech"] or "Lending"),
                    _cell("Impact indicators", entry["indicators"]),
                    _cell("Verification", entry["verification"]),
                    _cell("Follow-up", entry["follow_up"]),
                    _cell("Countries", entry["countries"]),
                    _cell("Status", entry["state"], tone=entry["tone"]),
                ],
                "actions": actions,
            }
        )
    return {
        "rows": rows,
        "register_title": "Loan purposes",
        "empty_title": "No active loan purposes",
        "empty_body": "Loan purposes are created through the lending purpose request.",
        "header_actions": [],
        "notice": {
            "tone": "info",
            "text": (
                "A new purpose keeps its own route (lending partner request, BT review, "
                "IA definition, Country Director approval). For a purpose already in "
                "use, IA defines its measurement here and a second reviewer approves it."
            ),
        },
        "filters": None,
        "description": (
            "What each lending purpose is measured by: impact indicators, the "
            "evidence required, how it is verified and when it is followed up."
        ),
    }


# ── Outcome area drawers ────────────────────────────────────────────────────


def _area_fields(area=None):
    chosen = [d.intervention for d in area.domains.all()] if area else []
    return [
        _field(
            "name",
            "Name",
            required=True,
            value=getattr(area, "name", ""),
            maxlength=120,
        ),
        _field(
            "definition",
            "Definition",
            type="textarea",
            required=True,
            value=getattr(area, "definition", ""),
            rows=5,
            help="What change in a partner school this area means, in plain words.",
        ),
        _field(
            "interventions",
            "SSA domains read as its proxy",
            type="multiselect",
            required=True,
            value=chosen,
            options=SsaIntervention.choices,
            rows=8,
        ),
        _field(
            "change_reason",
            "Why (change reason)",
            type="textarea",
            value=getattr(area, "change_reason", "")
            if area and area.status in fw.PENDING
            else "",
            rows=2,
        ),
    ]


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def area_new_drawer(request):
    if not fw.may_author(request.user):
        return _drawer(
            request,
            title="New outcome area",
            subtitle="Measurement framework",
            empty="Only Impact Assessment defines outcome areas.",
        )
    return _drawer(
        request,
        title="New outcome area",
        subtitle="Saved as a draft; a second reviewer approves it",
        action=f"{FRAMEWORK_URL}areas/save",
        submit="Save draft",
        fields=_area_fields(),
    )


@require_page_permission("ia_framework")
@require_POST
def area_save(request, area_id=None):
    area = None
    if area_id:
        area = OutcomeArea.objects.filter(id=area_id).first()
        if area is None:
            raise Http404
    try:
        record = fw.save_outcome_area(
            request.user,
            {
                "name": request.POST.get("name"),
                "definition": request.POST.get("definition"),
                "interventions": request.POST.getlist("interventions"),
                "change_reason": request.POST.get("change_reason"),
            },
            area=area,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc)
    messages.success(request, f"{record.name} v{record.version} saved as a draft.")
    return _back(request, _tab_url("areas"))


@require_page_permission("ia_framework")
@require_POST
def areas_propose(request):
    try:
        created = fw.propose_default_areas(request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url("areas"))
    messages.success(
        request,
        f"{len(created)} proposed outcome area{'s' if len(created) != 1 else ''} "
        "drafted for review.",
    )
    return redirect(_tab_url("areas"))


def _review_facts(record) -> list[dict]:
    from apps.accounts.models import User

    names = dict(
        User.objects.filter(
            id__in=[i for i in (record.author_id, record.reviewed_by_id) if i]
        ).values_list("id", "name")
    )
    facts = [
        {"label": "Version", "value": f"v{record.version}"},
        {"label": "Status", "value": record.get_status_display()},
        {"label": "Written by", "value": names.get(record.author_id, "—")},
        {"label": "Why", "value": record.change_reason},
    ]
    if record.reviewed_by_id:
        facts.append(
            {
                "label": "Reviewed by",
                "value": f"{names.get(record.reviewed_by_id, '—')} · "
                f"{record.get_review_basis_display()}",
            }
        )
    if record.review_note:
        facts.append({"label": "Review note", "value": record.review_note})
    return facts


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def area_drawer(request, area_id):
    area = OutcomeArea.objects.filter(id=area_id).prefetch_related("domains").first()
    if area is None:
        raise Http404
    facts = [
        {"label": "Definition", "value": area.definition},
        {
            "label": "SSA domains (proxy)",
            "value": ", ".join(
                dict(SsaIntervention.choices).get(d.intervention, d.intervention)
                for d in area.domains.all()
            ),
        },
        *_review_facts(area),
    ]
    editable = fw.may_author(request.user) and (
        area.status == DefinitionStatus.APPROVED
        or (area.status in fw.PENDING and area.author_id == str(request.user.id))
    )
    if not editable:
        return _drawer(request, title=area.name, subtitle="Outcome area", facts=facts)
    return _drawer(
        request,
        title=area.name,
        subtitle=(
            "Editing an approved area drafts a new version"
            if area.status == DefinitionStatus.APPROVED
            else "Draft — a second reviewer approves it"
        ),
        action=f"{FRAMEWORK_URL}areas/{area.id}/save",
        submit="Save draft",
        facts=facts,
        fields=_area_fields(area),
    )


# ── Indicator drawers ───────────────────────────────────────────────────────


def _indicator_fields(record=None):
    areas = [
        (a.id, f"{a.name} (v{a.version})")
        for a in OutcomeArea.objects.exclude(
            status__in=(DefinitionStatus.SUPERSEDED, DefinitionStatus.RETIRED)
        ).order_by("name", "-version")
    ]

    def value(name, default=""):
        return getattr(record, name, default) if record is not None else default

    fields = []
    if record is None:
        fields.append(
            _field(
                "key",
                "Key",
                value="",
                maxlength=80,
                help="Letters, numbers and hyphens; left empty it is made from the name.",
            )
        )
    fields += [
        _field("name", "Name", required=True, value=value("name"), maxlength=160),
        _field(
            "level",
            "Level",
            type="select",
            required=True,
            value=value("level"),
            options=IndicatorLevel.choices,
            blank="Choose a level",
            help="Counting delivered work is an output; change in schools is an outcome.",
        ),
        _field(
            "outcome_area",
            "Outcome area",
            type="select",
            value=value("outcome_area_id") or "",
            options=areas,
            blank="None",
        ),
        _field(
            "source",
            "Evidence source",
            type="select",
            required=True,
            value=value("source"),
            options=IndicatorSource.choices,
            blank="Choose a source",
        ),
        _field("unit", "Unit", required=True, value=value("unit"), maxlength=48),
        _field(
            "calculation",
            "Calculation",
            type="textarea",
            required=True,
            value=value("calculation"),
            rows=3,
        ),
        _field(
            "population",
            "Population",
            type="textarea",
            value=value("population"),
            rows=2,
        ),
        _field(
            "denominator",
            "Denominator",
            type="textarea",
            value=value("denominator"),
            rows=2,
        ),
        _field(
            "baseline_rule",
            "Baseline rule",
            type="textarea",
            value=value("baseline_rule"),
            rows=2,
        ),
        _field("frequency", "Frequency", value=value("frequency"), maxlength=64),
        _field(
            "disaggregation",
            "Disaggregation",
            type="textarea",
            value=value("disaggregation"),
            rows=2,
        ),
        _field(
            "limitations",
            "Limitations",
            type="textarea",
            value=value("limitations"),
            rows=3,
        ),
        _field(
            "data_owner_role",
            "Data owner role",
            value=value("data_owner_role"),
            maxlength=32,
        ),
        _field(
            "effective_from",
            "Effective from",
            type="date",
            value=value("effective_from") or "",
        ),
        _field(
            "change_reason",
            "Why (change reason)",
            type="textarea",
            value=value("change_reason")
            if record is not None and record.status in fw.PENDING
            else "",
            rows=2,
        ),
    ]
    return fields


def _indicator_data(request) -> dict:
    keys = (
        "key",
        "name",
        "level",
        "outcome_area",
        "source",
        "unit",
        "calculation",
        *fw.INDICATOR_TEXT_FIELDS,
        "effective_from",
        "change_reason",
    )
    return {key: request.POST.get(key, "") for key in keys}


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def indicator_new_drawer(request):
    if not fw.may_author(request.user):
        return _drawer(
            request,
            title="New indicator",
            subtitle="Measurement framework",
            empty="Only Impact Assessment defines indicators.",
        )
    return _drawer(
        request,
        title="New indicator",
        subtitle="Saved as a draft; a second reviewer approves it",
        action=f"{FRAMEWORK_URL}indicators/save",
        submit="Save draft",
        fields=_indicator_fields(),
    )


@require_page_permission("ia_framework")
@require_POST
def indicator_save(request, indicator_id=None):
    record = None
    if indicator_id:
        record = IndicatorDefinition.objects.filter(id=indicator_id).first()
        if record is None:
            raise Http404
    try:
        saved = fw.save_indicator(
            request.user, _indicator_data(request), indicator=record
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url("indicators"))
    messages.success(request, f"{saved.name} v{saved.version} saved as a draft.")
    return _back(request, _tab_url("indicators"))


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def indicator_drawer(request, indicator_id):
    record = (
        IndicatorDefinition.objects.filter(id=indicator_id)
        .select_related("outcome_area")
        .first()
    )
    if record is None:
        raise Http404
    facts = [
        {"label": "Key", "value": record.key},
        {"label": "Level", "value": record.get_level_display()},
        {"label": "Source", "value": record.get_source_display()},
        {"label": "Calculation", "value": record.calculation},
        {"label": "Denominator", "value": record.denominator},
        {"label": "Limitations", "value": record.limitations},
        {"label": "Scope", "value": record.country or "All countries"},
        *_review_facts(record),
    ]
    history = IndicatorDefinition.objects.filter(key=record.key).order_by("-version")
    facts.append(
        {
            "label": "Versions",
            "value": "\n".join(
                f"v{h.version} · {h.get_status_display()}"
                + (f" · from {h.effective_from:%-d %b %Y}" if h.effective_from else "")
                for h in history
            ),
        }
    )
    editable = (
        fw.may_author(request.user)
        and not record.key.startswith(fw.LOAN_PURPOSE_KEY_PREFIX)
        and (
            record.status == DefinitionStatus.APPROVED
            or (
                record.status in fw.PENDING and record.author_id == str(request.user.id)
            )
        )
    )
    if not editable:
        return _drawer(request, title=record.name, subtitle="Indicator", facts=facts)
    return _drawer(
        request,
        title=record.name,
        subtitle=(
            "Editing an approved indicator drafts a new version"
            if record.status == DefinitionStatus.APPROVED
            else "Draft — a second reviewer approves it"
        ),
        action=f"{FRAMEWORK_URL}indicators/{record.id}/save",
        submit="Save draft",
        facts=facts,
        fields=_indicator_fields(record),
    )


# ── Loan purpose drawer ─────────────────────────────────────────────────────


def _purpose(purpose_id):
    from apps.business_transformation.models import LoanPurpose

    purpose = LoanPurpose.objects.filter(id=purpose_id, active=True).first()
    if purpose is None:
        raise Http404
    return purpose


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def purpose_drawer(request, purpose_id):
    purpose = _purpose(purpose_id)
    record = (
        IndicatorDefinition.objects.filter(key=fw.loan_purpose_key(purpose))
        .order_by("-version")
        .first()
    )
    source = (
        record
        if record is not None and record.status != DefinitionStatus.APPROVED
        else None
    )
    facts = [
        {"label": "Purpose", "value": f"{purpose.label} ({purpose.code})"},
        {"label": "Unit", "value": purpose.unit_of_measure},
        {
            "label": "Current indicators",
            "value": "\n".join(purpose.impact_indicators or []) or "Not defined",
        },
        {
            "label": "Current verification",
            "value": purpose.verification_method or "Not defined",
        },
    ]
    if record is not None:
        facts += _review_facts(record)
    if not fw.may_author(request.user):
        return _drawer(
            request, title=purpose.label, subtitle="Loan purpose", facts=facts
        )
    if record is not None and record.status == DefinitionStatus.IN_REVIEW:
        return _drawer(
            request,
            title=purpose.label,
            subtitle="Loan purpose measurement",
            facts=facts,
            empty="This measurement is with a reviewer.",
        )
    fields = [
        _field(
            "impact_indicators",
            "Impact indicators (one per line)",
            type="textarea",
            required=True,
            rows=4,
            value=(
                source.calculation
                if source
                else "\n".join(purpose.impact_indicators or [])
            ),
        ),
        _field(
            "required_evidence",
            "Required evidence (one per line)",
            type="textarea",
            required=True,
            rows=3,
            value=(
                source.disaggregation
                if source
                else "\n".join(purpose.required_evidence or [])
            ),
        ),
        _field(
            "verification_method",
            "Verification method",
            type="textarea",
            required=True,
            rows=3,
            value=(source.baseline_rule if source else purpose.verification_method),
        ),
        _field(
            "follow_up_days",
            "Follow-up, days after disbursement",
            type="number",
            required=True,
            min=1,
            value=purpose.follow_up_days,
        ),
        _field(
            "limitations",
            "Limitations",
            type="textarea",
            rows=2,
            value=(source.limitations if source else ""),
        ),
        _field(
            "change_reason",
            "Why (change reason)",
            type="textarea",
            rows=2,
            value=(source.change_reason if source else ""),
        ),
    ]
    return _drawer(
        request,
        title=purpose.label,
        subtitle="Saved as a draft; a second reviewer approves it",
        action=f"{FRAMEWORK_URL}purposes/{purpose.id}/save",
        submit="Save draft",
        facts=facts,
        fields=fields,
    )


@require_page_permission("ia_framework")
@require_POST
def purpose_save(request, purpose_id):
    purpose = _purpose(purpose_id)
    try:
        record = fw.save_loan_purpose_measurement(
            request.user,
            purpose,
            {
                key: request.POST.get(key, "")
                for key in (
                    "impact_indicators",
                    "required_evidence",
                    "verification_method",
                    "follow_up_days",
                    "limitations",
                    "change_reason",
                )
            },
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url("purposes"))
    messages.success(
        request, f"Measurement for {purpose.label} saved as draft v{record.version}."
    )
    return _back(request, _tab_url("purposes"))


# ── Submit and review (outcome areas, indicators, loan purposes) ────────────


def _record_or_404(kind, record_id):
    try:
        return fw.get_record(kind, record_id)
    except NotFoundError as exc:
        raise Http404 from exc


def _tab_for(record) -> str:
    if isinstance(record, OutcomeArea):
        return "areas"
    if record.key.startswith(fw.LOAN_PURPOSE_KEY_PREFIX):
        return "purposes"
    return "indicators"


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def submit_drawer(request, kind, record_id):
    record = _record_or_404(kind, record_id)
    if not (
        fw.may_author(request.user)
        and record.status in fw.PENDING
        and record.author_id == str(request.user.id)
    ):
        return _drawer(
            request,
            title=f"Submit {record.name}",
            subtitle="Measurement framework",
            facts=_review_facts(record),
            empty="Only the officer who wrote a draft submits it for review.",
        )
    return _drawer(
        request,
        title=f"Submit {record.name}",
        subtitle="A second Impact Assessment officer reviews it",
        action=f"{FRAMEWORK_URL}{kind}/{record.id}/submit/save",
        submit="Submit for review",
        facts=_review_facts(record),
        fields=[
            _field(
                "change_reason",
                "What this establishes or changes, and why",
                type="textarea",
                required=True,
                rows=3,
                value=record.change_reason,
            )
        ],
    )


@require_page_permission("ia_framework")
@require_POST
def submit_action(request, kind, record_id):
    record = _record_or_404(kind, record_id)
    try:
        fw.submit(request.user, record, request.POST.get("change_reason", ""))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(_tab_for(record)))
    messages.success(request, f"{record.name} submitted for review.")
    return _back(request, _tab_url(_tab_for(record)))


@require_page_permission("ia_framework")
@require_http_methods(["GET"])
def review_drawer(request, kind, record_id):
    record = _record_or_404(kind, record_id)
    resolver = fw.ReviewerResolver(request.user)
    country = (getattr(record, "country", "") or "") or fw._author_country(record)
    basis = (
        resolver.basis(author_id=record.author_id, country=country)
        if record.status == DefinitionStatus.IN_REVIEW
        else None
    )
    facts = _review_facts(record)
    if isinstance(record, IndicatorDefinition):
        facts = [
            {"label": "Calculation", "value": record.calculation},
            {"label": "Limitations", "value": record.limitations},
            *facts,
        ]
    else:
        facts = [{"label": "Definition", "value": record.definition}, *facts]
    if not basis:
        return _drawer(
            request,
            title=f"Review {record.name}",
            subtitle="Measurement framework",
            facts=facts,
            empty=(
                "A second Impact Assessment officer in the author's country reviews "
                "this; the Country Director acknowledges only where there is none."
            ),
        )
    return _drawer(
        request,
        title=f"Review {record.name}",
        subtitle=(
            "Acknowledge as Country Director (no second IA officer in the country)"
            if basis == "cd_fallback"
            else "Review as a second Impact Assessment officer"
        ),
        action=f"{FRAMEWORK_URL}{kind}/{record.id}/review/save",
        submit="Record decision",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                options=REVIEW_DECISIONS,
                value="approve",
            ),
            _field(
                "note",
                "Review note",
                type="textarea",
                rows=3,
                help="Required when returning it.",
            ),
        ],
    )


@require_page_permission("ia_framework")
@require_POST
def review_action(request, kind, record_id):
    record = _record_or_404(kind, record_id)
    decision = request.POST.get("decision", "")
    try:
        fw.review(
            request.user, record, decision=decision, note=request.POST.get("note", "")
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(_tab_for(record)))
    messages.success(
        request,
        f"{record.name} {'approved' if decision == 'approve' else 'returned to its author'}.",
    )
    return _back(request, _tab_url(_tab_for(record)))
