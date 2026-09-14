"""Impact Assessment's School Evidence page (IA review, owner, 2026-09-13).

/ia/school-evidence/ holds the evidence of school progress the SSA does not
capture, in three tabs over apps.impact.evidence_services: Learning results,
Discipleship and EdTech. Impact Assessment records (one-column drawers, and a
CSV upload for class results); a second IA officer in the school's country
confirms or returns each record, the Country Director where the recorder is
that country's only officer; Admin reads. Each tab lists the school-level
summary above its register: learning results compared year on year for the
same class and subject, discipleship practice beside approved change stories,
each deployment beside its latest check.

The OneTest drawers at the end of this module are the other door: whoever may
complete a delivered OneTest diagnostic visit records that visit's class
results from the visit (/my-plan/<id>/learning-results), linked to it.

Rules, scope, permissions and audit rows live in the service, so a refusal it
raises is the message the reader sees. Every POST returns to the page it came
from with that message.
"""

from __future__ import annotations

import csv
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.fy import fy_options, get_operational_fy
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.pagination import paginate_rows
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.impact import evidence_services as ev
from apps.impact.models import (
    EdTechAssetType,
    EdTechFunding,
    LearningAssessmentType,
)

PAGE_URL = "/ia/school-evidence/"

TABS = (
    (ev.LEARNING, "Learning results"),
    (ev.DISCIPLESHIP, "Discipleship"),
    (ev.EDTECH, "EdTech"),
)
TAB_KEYS = {key for key, _label in TABS}
KINDS = set(ev.MODELS)
YES_NO = (("yes", "Yes"), ("no", "No"))

ASSESSMENT_LABELS = dict(LearningAssessmentType.choices)
ASSET_LABELS = dict(EdTechAssetType.choices)
FUNDING_LABELS = dict(EdTechFunding.choices)


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        "apps.frontend.views.ia_school_evidence_views:_metric",
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


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


def _num(value, suffix="") -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        value = f"{value:g}"
    return f"{value}{suffix}"


def _yes_no(value) -> str:
    return {True: "Yes", False: "No"}.get(value, "")


def _back(request, fallback: str = PAGE_URL):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, fallback, drop=("open",)))


def _refused(request, exc, fallback: str = PAGE_URL):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


def _tab_url(tab: str, **params) -> str:
    query = urlencode({"tab": tab, **{k: v for k, v in params.items() if v}})
    return f"{PAGE_URL}?{query}"


def _kind_or_404(kind: str) -> str:
    if kind not in KINDS:
        raise Http404("Unknown evidence type.")
    return kind


# ── The page ────────────────────────────────────────────────────────────────


@require_page_permission("ia_school_evidence")
@require_http_methods(["GET"])
def school_evidence_page(request):
    """Learning results, discipleship practice and EdTech rollout."""
    tab = request.GET.get("tab") or ev.LEARNING
    if tab not in TAB_KEYS:
        tab = ev.LEARNING
    fy_choices = [o for o in fy_options() if int(o) > 2025] or fy_options()
    fy = request.GET.get("fy") or ""
    if fy not in fy_choices:
        fy = get_operational_fy()
    status = request.GET.get("status") or ""
    if status not in ev.STATUS_LABELS:
        status = ""

    counts = ev.counts(request.user)
    pending = sum(c["pending"] for c in counts.values())
    returned = sum(c["returned"] for c in counts.values())
    metrics = [
        _metric(
            "School Evidence Awaiting Verification",
            pending,
            "confirmed by someone other than the recorder",
            "warning" if pending else "info",
        ),
        _metric(
            "Schools With Confirmed Learning Results",
            counts[ev.LEARNING]["schools"],
            "class-level results, any year",
        ),
        _metric(
            "Schools With Confirmed Discipleship Records",
            counts[ev.DISCIPLESHIP]["schools"],
            "observed practice, any year",
        ),
        _metric(
            "Schools With Confirmed EdTech Deployments",
            counts[ev.EDTECH]["schools"],
            f"{counts[ev.CHECK]['confirmed']} confirmed check"
            f"{'s' if counts[ev.CHECK]['confirmed'] != 1 else ''}",
        ),
        _metric(
            "School Evidence Returned for Correction",
            returned,
            "waiting for the recorder",
            "danger" if returned else "info",
        ),
    ]
    builder = {
        ev.LEARNING: _learning_tab,
        ev.DISCIPLESHIP: _discipleship_tab,
        ev.EDTECH: _edtech_tab,
    }[tab]
    context = builder(request, fy=fy, status=status)
    for key in ("summary", "register", "extra_table"):
        if context.get(key):
            context[key]["has_actions"] = any(
                row["actions"] for row in context[key]["rows"]
            )
    may_record = ev.may_record(request.user)
    filters = [
        {
            "name": "fy",
            "label": "Financial year",
            "value": fy,
            "blank": "",
            "options": [(o, f"FY{o}") for o in fy_choices],
        },
        {
            "name": "status",
            "label": "Status",
            "value": status,
            "blank": "Every status",
            "options": list(ev.STATUS_LABELS.items()),
        },
        *context.pop("filters", []),
    ]
    return render(
        request,
        "pages/ia/school_evidence.html",
        {
            "tab": tab,
            "tabs": [
                {"key": key, "label": label, "url": _tab_url(key), "active": key == tab}
                for key, label in TABS
            ],
            "metrics": metrics,
            "may_record": may_record,
            "filters": {"tab": tab, "fields": filters},
            "fy": fy,
            "autoload_drawer": _autoload(request),
            **context,
        },
    )


def _autoload(request) -> str:
    """The drawer a To-Do or notification asked for (?open=<kind>-<id>),
    when the record is one the reader may read."""
    target = (request.GET.get("open") or "").strip()
    kind, _, record_id = target.partition("-")
    if kind not in KINDS or not record_id:
        return ""
    if ev.visible(request.user, kind).filter(id=record_id).exists():
        return f"{PAGE_URL}{kind}/{record_id}/"
    return ""


def _register_rows(request, kind: str, queryset) -> tuple[list[dict], dict]:
    """One database page of the register, decorated in bulk."""
    from apps.analytics.ia_collection import db_page

    page = db_page(queryset, request.GET.get("register_page"))
    decorated = ev.decorate(request.user, page.pop("rows"))
    return decorated, page


def _status_cell(entry) -> dict:
    record = entry["record"]
    text = entry["status_label"]
    if record.verification_status == ev.RETURNED and record.return_reason:
        text = f"{text}: {record.return_reason}"
    return _cell("Status", text, tone=entry["status_tone"])


def _row_actions(kind: str, entry) -> list[dict]:
    record = entry["record"]
    actions = [{"label": "Open", "drawer": f"{PAGE_URL}{kind}/{record.id}/"}]
    if entry["can_verify"]:
        actions[0]["label"] = "Verify"
    return actions


def _learning_tab(request, *, fy: str, status: str) -> dict:
    subject = (request.GET.get("subject") or "").strip()
    subjects = sorted(
        {
            s.strip()
            for s in ev.visible(request.user, ev.LEARNING)
            .order_by()
            .values_list("subject", flat=True)
            .distinct()
            if s and s.strip()
        },
        key=str.lower,
    )
    if subject and subject not in subjects:
        subject = ""
    queryset = ev.register(
        request.user,
        ev.LEARNING,
        status=status,
        fy=fy,
        extra={"subject__iexact": subject},
    )
    entries, pager = _register_rows(request, ev.LEARNING, queryset)
    rows = []
    for entry in entries:
        r = entry["record"]
        result = []
        if r.mean_score is not None:
            result.append(
                f"mean {_num(r.mean_score)}"
                + (f" of {_num(r.max_score)}" if r.max_score is not None else "")
            )
        if r.learners_proficient is not None:
            result.append(f"{r.learners_proficient} proficient")
        rows.append(
            {
                "cells": [
                    _cell("School", r.school.name, primary=True),
                    _cell("Assessment", ASSESSMENT_LABELS.get(r.assessment_type, "")),
                    _cell("Class · subject", f"{r.grade_level} · {r.subject}"),
                    _cell("Assessed", _day(r.assessed_on)),
                    _cell("Learners", r.learners_tested),
                    _cell("Result", " · ".join(result)),
                    _cell("Recorded by", entry["recorded_by"]),
                    _status_cell(entry),
                ],
                "actions": _row_actions(ev.LEARNING, entry),
            }
        )

    comparisons = ev.learning_summary(request.user, fy, subject=subject)
    summary_page = paginate_rows(
        comparisons, page=_page(request, "summary_page"), page_size=25
    )
    summary_rows = []
    for c in summary_page.pop("rows"):
        if c["state"] == "compared":
            change = f"{c['change']:+g}{'pp' if c['measure'] == 'score' else 'pp proficient'}"
            tone = {"improved": "success", "declined": "danger"}.get(
                c["classification"], "neutral"
            )
        elif c["state"] == "withheld":
            change, tone = (
                f"Withheld (fewer than {ev.MIN_LEARNERS} learners)",
                "neutral",
            )
        elif c["state"] == "one_year":
            change, tone = "One year only", "neutral"
        else:
            change, tone = "Not comparable (different measures)", "neutral"

        def side(score, proficient, learners):
            if learners is None:
                return "Not measured"
            parts = []
            if score is not None:
                parts.append(f"{score:g}%")
            if proficient is not None:
                parts.append(f"{proficient:g}% proficient")
            return f"{' · '.join(parts) or 'recorded'} ({learners} learners)"

        summary_rows.append(
            {
                "cells": [
                    _cell("School", c["school"], primary=True),
                    _cell(
                        "Assessment", ASSESSMENT_LABELS.get(c["assessment_type"], "")
                    ),
                    _cell("Class · subject", f"{c['grade_level']} · {c['subject']}"),
                    _cell(
                        f"FY{int(fy) - 1}",
                        side(
                            c["score_before"],
                            c["proficient_before"],
                            c["learners_before"],
                        ),
                    ),
                    _cell(
                        f"FY{fy}",
                        side(
                            c["score_after"], c["proficient_after"], c["learners_after"]
                        ),
                    ),
                    _cell("Change", change, tone=tone),
                ],
                "actions": [],
            }
        )
    return {
        "description": (
            "Class-level results — OneTest, national examinations and the school's own "
            "assessments — with no pupil names. The same class and subject are compared "
            f"year on year; a side with fewer than {ev.MIN_LEARNERS} learners is withheld. "
            f"{ev.LEARNING_RULE_LABEL}."
        ),
        "summary": {
            "title": f"Year on year: FY{int(fy) - 1} against FY{fy}",
            "subtitle": "Confirmed results only",
            "rows": summary_rows,
            "pager": summary_page,
            "param": "summary_page",
            "empty_title": "No confirmed results to compare",
            "empty_body": "Once results for the same class and subject are confirmed in two years, they are compared here.",
        },
        "register": {
            "title": "Learning results",
            "rows": rows,
            "pager": pager,
            "param": "register_page",
            "empty_title": "No learning results recorded",
            "empty_body": "Record a class result, upload a CSV, or ask field staff to record results from a OneTest visit.",
        },
        "header_actions": (
            [
                {
                    "label": "Record learning result",
                    "drawer": f"{PAGE_URL}{ev.LEARNING}/new",
                }
            ]
            if ev.may_record(request.user)
            else []
        ),
        "show_upload": ev.may_record(request.user),
        "filters": [
            {
                "name": "subject",
                "label": "Subject",
                "value": subject,
                "blank": "Every subject",
                "options": [(s, s) for s in subjects],
            }
        ],
    }


def _page(request, param: str) -> int:
    try:
        return max(1, int(request.GET.get(param) or 1))
    except (TypeError, ValueError):
        return 1


def _discipleship_tab(request, *, fy: str, status: str) -> dict:
    queryset = ev.register(request.user, ev.DISCIPLESHIP, status=status, fy=fy)
    entries, pager = _register_rows(request, ev.DISCIPLESHIP, queryset)
    rows = []
    for entry in entries:
        r = entry["record"]
        rows.append(
            {
                "cells": [
                    _cell("School", r.school.name, primary=True),
                    _cell("Observed", _day(r.observed_on)),
                    _cell("Devotions a week", _num(r.devotions_per_week)),
                    _cell("Active groups", _num(r.discipleship_groups_active)),
                    _cell(
                        "Learners in groups",
                        f"{r.learners_in_groups} of {r.learners_enrolled}"
                        if r.learners_in_groups is not None and r.learners_enrolled
                        else _num(r.learners_in_groups),
                    ),
                    _cell("Spiritual lead", _yes_no(r.spiritual_lead_in_post)),
                    _cell("Recorded by", entry["recorded_by"]),
                    _status_cell(entry),
                ],
                "actions": _row_actions(ev.DISCIPLESHIP, entry),
            }
        )
    summary = ev.discipleship_summary(request.user, fy)
    summary_page = paginate_rows(
        summary, page=_page(request, "summary_page"), page_size=25
    )
    summary_rows = []
    for s in summary_page.pop("rows"):
        r = s["record"]
        if s["share_change"] is not None:
            change = f"{s['share_change']:+d} pts on FY{int(fy) - 1}"
            tone = (
                "success"
                if s["share_change"] > 0
                else "danger"
                if s["share_change"] < 0
                else "neutral"
            )
        else:
            change, tone = "No comparable record last year", "neutral"
        summary_rows.append(
            {
                "cells": [
                    _cell("School", s["school"], primary=True),
                    _cell("Latest observed", _day(r.observed_on)),
                    _cell("Devotions a week", _num(r.devotions_per_week)),
                    _cell("Active groups", _num(r.discipleship_groups_active)),
                    _cell(
                        "Learners in groups",
                        _num(s["share_in_groups"], "%")
                        if s["share_in_groups"] is not None
                        else "Not measured",
                    ),
                    _cell("Change", change, tone=tone),
                    _cell("Staff in devotions", _num(r.staff_in_devotions_pct, "%")),
                    _cell(
                        "Bible lessons timetabled", _yes_no(r.bible_lessons_timetabled)
                    ),
                    _cell("Approved change stories", s["stories"]),
                ],
                "actions": [],
            }
        )
    return {
        "description": (
            "Observable discipleship practice beside the SSA's self-scored Christ-like "
            "Behaviour and Word of God domains, and the Most Significant Change stories "
            "Impact Assessment approved for each school this year."
        ),
        "summary": {
            "title": f"Each school's latest confirmed record, FY{fy}",
            "subtitle": "Compared with the school's latest record the year before",
            "rows": summary_rows,
            "pager": summary_page,
            "param": "summary_page",
            "empty_title": "No confirmed discipleship record this year",
            "empty_body": "Records count here once a second verifier confirms them.",
        },
        "register": {
            "title": "Discipleship records",
            "rows": rows,
            "pager": pager,
            "param": "register_page",
            "empty_title": "No discipleship records",
            "empty_body": "Record what a visit observed: devotions, groups, a spiritual lead.",
        },
        "header_actions": (
            [
                {
                    "label": "Record discipleship practice",
                    "drawer": f"{PAGE_URL}{ev.DISCIPLESHIP}/new",
                }
            ]
            if ev.may_record(request.user)
            else []
        ),
    }


def _edtech_tab(request, *, fy: str, status: str) -> dict:
    asset_type = request.GET.get("asset_type") or ""
    if asset_type not in ASSET_LABELS:
        asset_type = ""
    queryset = ev.register(
        request.user,
        ev.EDTECH,
        status=status,
        fy=fy,
        extra={"asset_type": asset_type},
    )
    entries, pager = _register_rows(request, ev.EDTECH, queryset)
    rows = []
    for entry in entries:
        r = entry["record"]
        rows.append(
            {
                "cells": [
                    _cell("School", r.school.name, primary=True),
                    _cell(
                        "Technology",
                        f"{r.quantity} × {ASSET_LABELS.get(r.asset_type, '')}",
                    ),
                    _cell("Deployed", _day(r.deployed_on)),
                    _cell("Funding", FUNDING_LABELS.get(r.funding, "")),
                    _cell("Learners with access", _num(r.learners_with_access)),
                    _cell("Recorded by", entry["recorded_by"]),
                    _status_cell(entry),
                ],
                "actions": _row_actions(ev.EDTECH, entry),
            }
        )
    check_rows = []
    checks = (
        ev.register(request.user, ev.CHECK, status=status)
        .select_related("deployment")
        .filter(fy=fy)
    )
    for entry in ev.decorate(request.user, list(checks[:50])):
        r = entry["record"]
        check_rows.append(
            {
                "cells": [
                    _cell("School", r.school.name, primary=True),
                    _cell(
                        "Deployment",
                        f"{r.deployment.quantity} × {ASSET_LABELS.get(r.deployment.asset_type, '')}",
                    ),
                    _cell("Checked", _day(r.checked_on)),
                    _cell("Units working", r.units_functional),
                    _cell("Teachers using", _num(r.teachers_using)),
                    _cell("Learners using", _num(r.learners_using)),
                    _cell("Recorded by", entry["recorded_by"]),
                    _status_cell(entry),
                ],
                "actions": _row_actions(ev.CHECK, entry),
            }
        )

    summary = ev.edtech_summary(request.user, asset_type=asset_type)
    summary_page = paginate_rows(
        summary, page=_page(request, "summary_page"), page_size=25
    )
    summary_rows = []
    may_record = ev.may_record(request.user)
    for s in summary_page.pop("rows"):
        d = s["deployment"]
        checked = s["checked_on"] is not None
        summary_rows.append(
            {
                "cells": [
                    _cell("School", s["school"], primary=True),
                    _cell(
                        "Technology",
                        f"{d.quantity} × {ASSET_LABELS.get(d.asset_type, '')}",
                    ),
                    _cell("Deployed", _day(d.deployed_on)),
                    _cell(
                        "Latest check",
                        _day(s["checked_on"]) if checked else "Not checked yet",
                    ),
                    _cell(
                        "Working",
                        f"{s['units_functional']} of {d.quantity} ({s['functional_pct']}%)"
                        if checked
                        else "Not measured",
                        tone=(
                            "success"
                            if checked and s["functional_pct"] >= 80
                            else "danger"
                            if checked and s["functional_pct"] < 50
                            else "warning"
                            if checked
                            else "neutral"
                        ),
                    ),
                    _cell(
                        "Teachers using",
                        _num(s["teachers_using"]) if checked else "Not measured",
                    ),
                    _cell(
                        "Learners using",
                        (
                            f"{s['learners_using']} of {d.learners_with_access}"
                            if d.learners_with_access
                            and s["learners_using"] is not None
                            else _num(s["learners_using"])
                        )
                        if checked
                        else "Not measured",
                    ),
                    _cell("Checks awaiting verification", s["pending_checks"]),
                ],
                "actions": (
                    [
                        {
                            "label": "Record check",
                            "drawer": f"{PAGE_URL}{ev.EDTECH}/{d.id}/check",
                        }
                    ]
                    if may_record
                    else []
                ),
            }
        )
    return {
        "description": (
            "What each school received for teaching and learning, and whether it works "
            "and is used: the latest confirmed check of each confirmed deployment. "
            "Deployment is delivery, not impact; use is the first sign it reaches learners."
        ),
        "summary": {
            "title": "Deployments and their latest check",
            "subtitle": "Confirmed deployments; a check is recorded once a deployment is confirmed",
            "rows": summary_rows,
            "pager": summary_page,
            "param": "summary_page",
            "empty_title": "No confirmed deployment",
            "empty_body": "Record a deployment; once confirmed, record checks of use.",
        },
        "register": {
            "title": "Deployments",
            "rows": rows,
            "pager": pager,
            "param": "register_page",
            "empty_title": "No EdTech deployments recorded",
            "empty_body": "Record the technology a school received, its funding and who has access.",
        },
        "extra_table": {
            "title": "Checks of use",
            "subtitle": f"FY{fy}, newest first (up to 50)",
            "rows": check_rows,
            "pager": paginate_rows(check_rows, page=1, page_size=50),
            "param": "checks_page",
            "empty_title": "No checks recorded this year",
            "empty_body": "Record a check from a confirmed deployment above.",
        },
        "header_actions": (
            [{"label": "Record deployment", "drawer": f"{PAGE_URL}{ev.EDTECH}/new"}]
            if may_record
            else []
        ),
        "filters": [
            {
                "name": "asset_type",
                "label": "Technology",
                "value": asset_type,
                "blank": "Every technology",
                "options": list(EdTechAssetType.choices),
            }
        ],
    }


# ── Drawers: fields ─────────────────────────────────────────────────────────


def _common_fields(record=None):
    return [
        _field(
            "evidence_reference",
            "Evidence reference",
            value=getattr(record, "evidence_reference", ""),
            maxlength=512,
            placeholder="Salesforce record, report or file reference",
        ),
        _field(
            "notes",
            "Notes",
            type="textarea",
            rows=3,
            value=getattr(record, "notes", ""),
            maxlength=4000,
        ),
    ]


def _school_field(record=None):
    if record is not None:
        return []
    return [
        _field(
            "school_id",
            "School ID",
            required=True,
            maxlength=64,
            help="The school's directory ID; the school must be in your country.",
        )
    ]


def _value(record, name, default=""):
    value = getattr(record, name, None) if record is not None else None
    if value is None:
        return default
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def learning_fields(record=None, *, with_school=True):
    return [
        *(_school_field(record) if with_school else []),
        _field(
            "assessment_type",
            "Assessment",
            type="select",
            required=True,
            options=LearningAssessmentType.choices,
            value=_value(record, "assessment_type", LearningAssessmentType.ONETEST),
        ),
        _field(
            "assessed_on",
            "Assessed on",
            type="date",
            required=True,
            value=_value(record, "assessed_on"),
        ),
        _field(
            "grade_level",
            "Class or grade",
            required=True,
            maxlength=32,
            placeholder="e.g. P6",
            value=_value(record, "grade_level"),
        ),
        _field(
            "subject",
            "Subject",
            required=True,
            maxlength=64,
            placeholder="e.g. Literacy",
            value=_value(record, "subject"),
        ),
        _field(
            "learners_tested",
            "Learners tested",
            type="number",
            required=True,
            min=1,
            value=_value(record, "learners_tested"),
        ),
        _field(
            "mean_score",
            "Mean score",
            type="number",
            min=0,
            step="0.01",
            value=_value(record, "mean_score"),
            help="Record the mean score, the learners proficient, or both.",
        ),
        _field(
            "max_score",
            "Maximum possible score",
            type="number",
            min=0,
            step="0.01",
            value=_value(record, "max_score"),
            help="Lets results on different scales be compared as a percentage.",
        ),
        _field(
            "learners_proficient",
            "Learners proficient",
            type="number",
            min=0,
            value=_value(record, "learners_proficient"),
        ),
        *_common_fields(record),
    ]


def _yes_no_field(name, label, record):
    value = _value(record, name, None)
    return _field(
        name,
        label,
        type="select",
        options=YES_NO,
        blank="Not observed",
        value={True: "yes", False: "no"}.get(value, ""),
    )


def discipleship_fields(record=None):
    return [
        *_school_field(record),
        _field(
            "observed_on",
            "Observed on",
            type="date",
            required=True,
            value=_value(record, "observed_on"),
        ),
        _field(
            "devotions_per_week",
            "Whole-school devotions a week",
            type="number",
            min=0,
            value=_value(record, "devotions_per_week"),
        ),
        _field(
            "discipleship_groups_active",
            "Active discipleship or Bible groups",
            type="number",
            min=0,
            value=_value(record, "discipleship_groups_active"),
        ),
        _field(
            "learners_in_groups",
            "Learners in those groups",
            type="number",
            min=0,
            value=_value(record, "learners_in_groups"),
        ),
        _field(
            "learners_enrolled",
            "Learners enrolled",
            type="number",
            min=0,
            value=_value(record, "learners_enrolled"),
        ),
        _field(
            "staff_in_devotions_pct",
            "Staff taking part in devotions (%)",
            type="number",
            min=0,
            value=_value(record, "staff_in_devotions_pct"),
        ),
        _yes_no_field("spiritual_lead_in_post", "A spiritual lead is in post", record),
        _yes_no_field(
            "bible_lessons_timetabled", "Bible lessons are timetabled", record
        ),
        *_common_fields(record),
    ]


def _project_options(request):
    from apps.projects.models import Project

    return list(
        Project.objects.filter(deleted_at__isnull=True)
        .order_by("name")
        .values_list("id", "name")
    )


def edtech_fields(request, record=None):
    return [
        *_school_field(record),
        _field(
            "asset_type",
            "Technology",
            type="select",
            required=True,
            options=EdTechAssetType.choices,
            blank="Choose",
            value=_value(record, "asset_type"),
        ),
        _field(
            "quantity",
            "Units deployed",
            type="number",
            required=True,
            min=1,
            value=_value(record, "quantity"),
        ),
        _field(
            "deployed_on",
            "Deployed on",
            type="date",
            required=True,
            value=_value(record, "deployed_on"),
        ),
        _field(
            "funding",
            "Funded by",
            type="select",
            required=True,
            options=EdTechFunding.choices,
            blank="Choose",
            value=_value(record, "funding"),
        ),
        _field(
            "project",
            "Special project",
            type="select",
            options=_project_options(request),
            blank="None",
            value=_value(record, "project_id"),
            help="Required when a special project funded it.",
        ),
        _field(
            "teachers_trained",
            "Teachers trained to use it",
            type="number",
            min=0,
            value=_value(record, "teachers_trained"),
        ),
        _field(
            "learners_with_access",
            "Learners with access",
            type="number",
            min=0,
            value=_value(record, "learners_with_access"),
        ),
        *_common_fields(record),
    ]


def check_fields(record=None):
    return [
        _field(
            "checked_on",
            "Checked on",
            type="date",
            required=True,
            value=_value(record, "checked_on"),
        ),
        _field(
            "units_functional",
            "Units working",
            type="number",
            required=True,
            min=0,
            value=_value(record, "units_functional"),
        ),
        _field(
            "teachers_using",
            "Teachers using them",
            type="number",
            min=0,
            value=_value(record, "teachers_using"),
        ),
        _field(
            "learners_using",
            "Learners using them",
            type="number",
            min=0,
            value=_value(record, "learners_using"),
        ),
        _field(
            "weekly_use_hours",
            "Hours of use a week",
            type="number",
            min=0,
            step="0.1",
            value=_value(record, "weekly_use_hours"),
        ),
        _field(
            "issues",
            "Issues found",
            type="textarea",
            rows=3,
            value=_value(record, "issues"),
            maxlength=4000,
        ),
        *_common_fields(record),
    ]


def _fields_for(request, kind, record=None):
    if kind == ev.LEARNING:
        return learning_fields(record)
    if kind == ev.DISCIPLESHIP:
        return discipleship_fields(record)
    if kind == ev.EDTECH:
        return edtech_fields(request, record)
    return check_fields(record)


def _facts(kind, record, entry) -> list[dict]:
    facts = [
        {"label": "School", "value": record.school.name},
        {"label": "Financial year", "value": f"FY{record.fy}"},
    ]
    if kind == ev.LEARNING:
        facts += [
            {
                "label": "Assessment",
                "value": ASSESSMENT_LABELS.get(record.assessment_type, ""),
            },
            {"label": "Assessed on", "value": _day(record.assessed_on)},
            {
                "label": "Class · subject",
                "value": f"{record.grade_level} · {record.subject}",
            },
            {"label": "Learners tested", "value": record.learners_tested},
            {"label": "Mean score", "value": _num(record.mean_score)},
            {"label": "Maximum score", "value": _num(record.max_score)},
            {"label": "Learners proficient", "value": _num(record.learners_proficient)},
        ]
    elif kind == ev.DISCIPLESHIP:
        facts += [
            {"label": "Observed on", "value": _day(record.observed_on)},
            {"label": "Devotions a week", "value": _num(record.devotions_per_week)},
            {
                "label": "Active groups",
                "value": _num(record.discipleship_groups_active),
            },
            {"label": "Learners in groups", "value": _num(record.learners_in_groups)},
            {"label": "Learners enrolled", "value": _num(record.learners_enrolled)},
            {
                "label": "Staff in devotions",
                "value": _num(record.staff_in_devotions_pct, "%"),
            },
            {
                "label": "Spiritual lead in post",
                "value": _yes_no(record.spiritual_lead_in_post),
            },
            {
                "label": "Bible lessons timetabled",
                "value": _yes_no(record.bible_lessons_timetabled),
            },
        ]
    elif kind == ev.EDTECH:
        facts += [
            {
                "label": "Technology",
                "value": f"{record.quantity} × {ASSET_LABELS.get(record.asset_type, '')}",
            },
            {"label": "Deployed on", "value": _day(record.deployed_on)},
            {"label": "Funded by", "value": FUNDING_LABELS.get(record.funding, "")},
            {"label": "Special project", "value": getattr(record.project, "name", "")},
            {"label": "Teachers trained", "value": _num(record.teachers_trained)},
            {
                "label": "Learners with access",
                "value": _num(record.learners_with_access),
            },
        ]
    else:
        facts += [
            {
                "label": "Deployment",
                "value": f"{record.deployment.quantity} × {ASSET_LABELS.get(record.deployment.asset_type, '')}, deployed {_day(record.deployment.deployed_on)}",
            },
            {"label": "Checked on", "value": _day(record.checked_on)},
            {"label": "Units working", "value": record.units_functional},
            {"label": "Teachers using", "value": _num(record.teachers_using)},
            {"label": "Learners using", "value": _num(record.learners_using)},
            {"label": "Hours of use a week", "value": _num(record.weekly_use_hours)},
            {"label": "Issues", "value": record.issues},
        ]
    if record.source_activity_id:
        facts.append(
            {
                "label": "Recorded from",
                "value": "The OneTest diagnostic visit it came from",
            }
        )
    facts += [
        {"label": "Evidence reference", "value": record.evidence_reference},
        {"label": "Notes", "value": record.notes},
        {"label": "Recorded by", "value": entry["recorded_by"]},
        {"label": "Status", "value": entry["status_label"]},
    ]
    if record.verified_by_user_id:
        facts.append(
            {
                "label": "Returned by"
                if record.verification_status == ev.RETURNED
                else "Confirmed by",
                "value": f"{entry['verified_by']} · {_day(record.verified_at)}",
            }
        )
    if record.return_reason:
        facts.append({"label": "What to correct", "value": record.return_reason})
    return facts


# ── Drawers: views ──────────────────────────────────────────────────────────


@require_page_permission("ia_school_evidence")
@require_http_methods(["GET"])
def new_drawer(request, kind):
    kind = _kind_or_404(kind)
    if kind == ev.CHECK:
        raise Http404("A check is recorded from its deployment.")
    title = {
        ev.LEARNING: "Record a learning result",
        ev.DISCIPLESHIP: "Record discipleship practice",
        ev.EDTECH: "Record an EdTech deployment",
    }[kind]
    if not ev.may_record(request.user):
        return _drawer(
            request,
            title=title,
            subtitle="School evidence",
            empty="Only Impact Assessment records school evidence.",
        )
    return _drawer(
        request,
        title=title,
        subtitle="School evidence · pending until a second person confirms it",
        action=f"{PAGE_URL}{kind}/save",
        fields=_fields_for(request, kind),
        submit="Record",
        note=(
            "Class-level results only: no pupil names or records."
            if kind == ev.LEARNING
            else ""
        ),
    )


@require_page_permission("ia_school_evidence")
@require_POST
def create_action(request, kind):
    kind = _kind_or_404(kind)
    try:
        row = ev.record(request.user, kind, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(ev.KIND_TAB[kind]))
    messages.success(
        request,
        f"{ev.KIND_LABELS[kind]} recorded for {row.school.name}; it counts once "
        "someone else confirms it.",
    )
    return _back(request, _tab_url(ev.KIND_TAB[kind]))


def _visible_record(request, kind, record_id):
    related = ["school"]
    if kind == ev.CHECK:
        related.append("deployment")
    if kind == ev.EDTECH:
        related.append("project")
    return (
        ev.visible(request.user, kind)
        .select_related(*related)
        .filter(id=record_id)
        .first()
    )


@require_page_permission("ia_school_evidence")
@require_http_methods(["GET"])
def record_drawer(request, kind, record_id):
    kind = _kind_or_404(kind)
    record = _visible_record(request, kind, record_id)
    if record is None:
        return _drawer(
            request,
            title=ev.KIND_LABELS[kind],
            subtitle="School evidence",
            empty="This record is not in your country.",
        )
    entry = ev.decorate(request.user, [record])[0]
    facts = _facts(kind, record, entry)
    subtitle = f"{record.school.name} · {entry['status_label']}"
    if entry["can_verify"]:
        return _drawer(
            request,
            title=f"Verify {ev.KIND_LABELS[kind].lower()}",
            subtitle=subtitle,
            action=f"{PAGE_URL}{kind}/{record.id}/decide",
            facts=facts,
            fields=[
                _field(
                    "decision",
                    "Decision",
                    type="select",
                    required=True,
                    options=(
                        ("confirm", "Confirm — it counts as evidence"),
                        ("return", "Return to the recorder to correct"),
                    ),
                    value="confirm",
                ),
                _field(
                    "reason",
                    "What needs correcting",
                    type="textarea",
                    rows=3,
                    maxlength=4000,
                    help="Required when you return it; the recorder reads it.",
                ),
            ],
            submit="Save decision",
            note="Check the figures against the evidence reference before confirming.",
        )
    if entry["can_correct"]:
        fields = _fields_for(request, kind, record) + [
            _field(
                "withdraw",
                "Withdraw this record instead",
                type="checkbox",
                help="It was recorded in error; it will not count and stays in the audit trail.",
            )
        ]
        return _drawer(
            request,
            title=f"Correct {ev.KIND_LABELS[kind].lower()}",
            subtitle=subtitle,
            action=f"{PAGE_URL}{kind}/{record.id}/correct",
            facts=facts[:1] + [f for f in facts if f["label"] == "What to correct"],
            fields=fields,
            submit="Save and send for verification",
            note=(
                "You recorded this, so someone else confirms it. Saving sends it back "
                "for verification."
            ),
            note_tone="warning"
            if record.verification_status == ev.RETURNED
            else "info",
        )
    note = "Read only."
    if entry["is_mine"] and record.verification_status == ev.PENDING:
        note = "You recorded this, so a second Impact Assessment officer confirms it."
    elif record.verification_status == ev.PENDING:
        note = (
            "A second Impact Assessment officer in this country confirms it; the "
            "Country Director confirms only where the recorder is the country's one officer."
        )
    return _drawer(
        request,
        title=ev.KIND_LABELS[kind],
        subtitle=subtitle,
        facts=facts,
        empty=note,
    )


@require_page_permission("ia_school_evidence")
@require_POST
def decide_action(request, kind, record_id):
    kind = _kind_or_404(kind)
    decision = request.POST.get("decision") or ""
    try:
        row = ev.decide(
            request.user,
            kind,
            record_id,
            decision=decision,
            reason=request.POST.get("reason", ""),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(ev.KIND_TAB[kind]))
    messages.success(
        request,
        f"{ev.KIND_LABELS[kind]} for {row.school.name} "
        f"{'confirmed' if decision == 'confirm' else 'returned to the recorder'}.",
    )
    return _back(request, _tab_url(ev.KIND_TAB[kind]))


@require_page_permission("ia_school_evidence")
@require_POST
def correct_action(request, kind, record_id):
    """Save the recorder's correction, or withdraw the record when they ticked
    "Withdraw" (a soft delete: nobody has confirmed it, so nothing counted)."""
    kind = _kind_or_404(kind)
    withdrawing = bool(request.POST.get("withdraw"))
    try:
        if withdrawing:
            row = ev.withdraw(request.user, kind, record_id)
        else:
            row = ev.correct(request.user, kind, record_id, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(ev.KIND_TAB[kind]))
    messages.success(
        request,
        f"{ev.KIND_LABELS[kind]} for {row.school.name} "
        f"{'withdrawn' if withdrawing else 'sent for verification'}.",
    )
    return _back(request, _tab_url(ev.KIND_TAB[kind]))


@require_page_permission("ia_school_evidence")
@require_http_methods(["GET"])
def check_drawer(request, deployment_id):
    deployment = _visible_record(request, ev.EDTECH, deployment_id)
    title = "Record an EdTech check"
    if deployment is None:
        return _drawer(
            request,
            title=title,
            subtitle="School evidence",
            empty="This deployment is not in your country.",
        )
    if not ev.may_record(request.user):
        return _drawer(
            request,
            title=title,
            subtitle=deployment.school.name,
            empty="Only Impact Assessment records checks.",
        )
    if deployment.verification_status != ev.CONFIRMED:
        return _drawer(
            request,
            title=title,
            subtitle=deployment.school.name,
            empty="Check a deployment once it is confirmed.",
        )
    return _drawer(
        request,
        title=title,
        subtitle=f"{deployment.school.name} · {deployment.quantity} × {ASSET_LABELS.get(deployment.asset_type, '')}",
        action=f"{PAGE_URL}{ev.EDTECH}/{deployment.id}/check/save",
        fields=check_fields(),
        submit="Record check",
    )


@require_page_permission("ia_school_evidence")
@require_POST
def check_create_action(request, deployment_id):
    try:
        row = ev.record_check(request.user, deployment_id, request.POST)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, _tab_url(ev.EDTECH))
    messages.success(
        request,
        f"Check recorded for {row.school.name}; it counts once someone else confirms it.",
    )
    return _back(request, _tab_url(ev.EDTECH))


@require_page_permission("ia_school_evidence")
@require_POST
def learning_upload_action(request):
    fallback = _tab_url(ev.LEARNING)
    try:
        result = ev.upload_learning_csv(request.user, request.FILES.get("results_file"))
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    if result["errors"]:
        shown = result["errors"][:10]
        more = len(result["errors"]) - len(shown)
        messages.error(
            request,
            "Nothing was recorded — fix these rows and upload the file again: "
            + " ".join(shown)
            + (f" …and {more} more." if more > 0 else ""),
        )
    else:
        messages.success(
            request,
            f"{result['created']} learning result{'s' if result['created'] != 1 else ''} "
            "recorded; each counts once someone else confirms it.",
        )
    return _back(request, fallback)


@require_page_permission("ia_school_evidence")
@require_http_methods(["GET"])
def learning_template_csv(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        'attachment; filename="learning_results_template.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(ev.LEARNING_CSV_COLUMNS)
    sample_day = f"{int(get_operational_fy()) - 1}-11-15"
    writer.writerow(
        [
            "SCH-0001",
            "onetest",
            sample_day,
            "P6",
            "Literacy",
            "42",
            "54.5",
            "100",
            "18",
            "",
            "",
        ]
    )
    return response


# ── OneTest: results recorded from the visit ───────────────────────────────


def _onetest_activity(request, activity_id):
    from apps.activities.models import Activity

    activity = get_object_or_404(
        Activity.objects.select_related("school__region", "catalogue_item"),
        id=activity_id,
        deleted_at__isnull=True,
    )
    return activity


@require_page_permission("my_plan")
@require_http_methods(["GET"])
def onetest_results_drawer(request, activity_id):
    """Record (or correct) the class results of a delivered OneTest visit."""
    activity = _onetest_activity(request, activity_id)
    title = "Record learning results"
    if not ev.may_record_for_activity(request.user, activity):
        return _drawer(
            request,
            title=title,
            subtitle="OneTest diagnostic visit",
            empty=(
                "Learning results are recorded from a delivered OneTest visit by "
                "someone who may complete it."
            ),
        )
    from apps.impact.models import LearningAssessmentResult

    existing = list(
        LearningAssessmentResult.objects.filter(source_activity=activity).order_by(
            "grade_level", "subject"
        )
    )
    facts = [{"label": "School", "value": activity.school.name}]
    for r in existing:
        status = ev.STATUS_LABELS.get(r.verification_status, "")
        if r.return_reason and r.verification_status == ev.RETURNED:
            status = f"{status}: {r.return_reason}"
        facts.append(
            {
                "label": f"{r.grade_level} · {r.subject}",
                "value": f"{r.learners_tested} learners · {status}",
            }
        )
    correcting = None
    wanted = (request.GET.get("result") or "").strip()
    if wanted:
        correcting = next(
            (
                r
                for r in existing
                if r.id == wanted
                and str(r.recorded_by_user_id) == str(request.user.id)
                and r.verification_status != ev.CONFIRMED
            ),
            None,
        )
    if correcting is None:
        correcting = next(
            (
                r
                for r in existing
                if r.verification_status == ev.RETURNED
                and str(r.recorded_by_user_id) == str(request.user.id)
            ),
            None,
        )
    fields = learning_fields(correcting, with_school=False)
    if correcting is None:
        for field in fields:
            if field["name"] == "assessed_on" and not field["value"]:
                delivered = activity.actual_delivery_date or activity.planned_date
                field["value"] = delivered.isoformat() if delivered else ""
    else:
        fields.append(_field("result_id", "", type="hidden", value=correcting.id))
    response = _drawer(
        request,
        title="Correct a returned learning result" if correcting else title,
        subtitle=f"OneTest · {activity.school.name}",
        action=f"/my-plan/{activity.id}/learning-results/save",
        facts=facts,
        fields=fields,
        submit="Save result" if correcting else "Record result",
        note=(
            f"Returned: {correcting.return_reason}"
            if correcting is not None and correcting.return_reason
            else "One class and subject at a time — no pupil names. Impact Assessment "
            "confirms each result before it counts."
        ),
        note_tone="warning" if correcting is not None else "info",
        next_url=f"/my-plan/{activity.id}",
    )
    if request.GET.get("completed") == "1":
        # Opened by the visit page's ?learning_results=1: drop the parameter so
        # a refresh after closing the drawer does not open it again.
        response.content += (
            b"<div hidden x-data "
            b"x-init=\"history.replaceState(null, '', window.location.pathname)\""
            b" data-onetest-autoloaded></div>"
        )
    return response


@require_page_permission("my_plan")
@require_POST
def onetest_results_save(request, activity_id):
    activity = _onetest_activity(request, activity_id)
    back = f"/my-plan/{activity.id}"
    result_id = (request.POST.get("result_id") or "").strip()
    try:
        if result_id:
            if not ev.may_record_for_activity(request.user, activity):
                raise Forbidden("You may not correct results for this visit.")
            from apps.impact.models import LearningAssessmentResult

            if not LearningAssessmentResult.objects.filter(
                id=result_id, source_activity=activity
            ).exists():
                raise NotFoundError("That result is not from this visit.")
            row = ev.correct(request.user, ev.LEARNING, result_id, request.POST)
            messages.success(
                request,
                f"Result for {row.grade_level} {row.subject} sent for verification.",
            )
        else:
            row = ev.record(
                request.user, ev.LEARNING, request.POST, source_activity=activity
            )
            messages.success(
                request,
                f"{row.grade_level} {row.subject} results recorded; Impact Assessment "
                "confirms them before they count.",
            )
    except SERVICE_ERRORS as exc:
        messages.error(request, str(getattr(exc, "detail", exc)))
        return redirect(f"{back}?learning_results=1")
    return redirect(back)
