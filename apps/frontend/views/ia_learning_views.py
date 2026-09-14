"""Impact Assessment's Programme Learning workspace (IA review, owner, 2026-09-13).

/ia/learning/ answers "what works" for Christian training, lending, EdTech and
school visits, over apps.analytics.programme_effectiveness, and keeps what IA
concludes as reviewed findings (apps.impact.findings). Tabs are links
(?view=training|lending|edtech|visits|findings) so a To-Do, a notification
and the old /ia/attribution/ bookmark land on the same tab.

Each programme tab: outputs tiles labelled "delivery, not impact"; the outcome
table (exposed and comparison schools, coverage, the median change of each,
the difference, the Holm-corrected verdict and the evidence grade); the
qualitative panel; and a "Record finding" row action for Impact Assessment.
The Training tab also carries intervention contribution — the former
attribution page — under its association caveat.

Findings: Impact Assessment records and corrects its own; a second IA officer
in the country reviews, the Country Director only where there is none; Admin
reads. A finding's figures are taken by the server from the row it came from,
never posted by the browser. Refusals raised by the service are the message
the reader sees.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.analytics import programme_effectiveness as pe
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.pagination import paginate_rows
from apps.core.permissions import require_page_permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field
from apps.impact import findings as fs

PAGE_URL = "/ia/learning/"
SOURCE = "apps.frontend.views.ia_learning_views:_metric"


def _metric(label: str, value, helper: str, tone="info") -> dict:
    return render_precomputed_metric_for_source(
        SOURCE, label, value, helper=helper, tone=tone
    )


def _cell(heading: str, text, *, primary=False, tone="") -> dict:
    return {
        "heading": heading,
        "text": "—" if text in (None, "") else str(text),
        "primary": primary,
        "tone": tone,
    }


def _signed(value) -> str:
    if value is None:
        return ""
    return f"{value:+.2f}"


def _page(request, param: str) -> int:
    try:
        return max(1, int(request.GET.get(param) or 1))
    except (TypeError, ValueError):
        return 1


def _view_url(view: str, **params) -> str:
    query = urlencode({"view": view, **{k: v for k, v in params.items() if v}})
    return f"{PAGE_URL}?{query}"


def _back(request, fallback: str):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, fallback, drop=("open",)))


def _refused(request, exc, fallback: str):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


VERDICT_TONES = {"significant": "info", "suggestive": "warning"}


# ── The page ────────────────────────────────────────────────────────────────


@require_page_permission("ia_learning")
@require_http_methods(["GET"])
def learning_page(request):
    """Training, Lending, EdTech, Visits and Findings."""
    view = request.GET.get("view") or pe.TRAINING
    if view not in pe.TAB_LABELS:
        view = pe.TRAINING
    fy = pe.resolve_fy(request.GET.get("fy"))
    may_record = fs.may_author(request.user)
    if view == pe.FINDINGS:
        context = _findings_tab(request, fy=fy)
    else:
        data = pe.build(request.user, view, {**request.GET.dict(), "fy": fy})
        context = _programme_tab(request, view, data, may_record=may_record)
    filters = [
        {
            "name": "fy",
            "label": "Financial year",
            "value": fy,
            "blank": "",
            "options": [(o, f"FY{int(o) - 1} → FY{o}") for o in pe.fy_choices()],
        },
        *context.pop("filters", []),
    ]
    for key in ("outcomes", "contribution", "register"):
        table = context.get(key)
        if table:
            table["has_actions"] = any(row["actions"] for row in table["rows"])
    return render(
        request,
        "pages/ia/learning.html",
        {
            "view": view,
            "tabs": [
                {
                    "key": key,
                    "label": label,
                    "url": _view_url(key, fy=fy),
                    "active": key == view,
                }
                for key, label in pe.TABS
            ],
            "filters": {"view": view, "fields": filters},
            "fy": fy,
            "may_record": may_record,
            "outputs_note": pe.OUTPUTS_NOTE,
            "autoload_drawer": _autoload(request),
            **context,
        },
    )


def _autoload(request) -> str:
    finding_id = (request.GET.get("open") or "").strip()
    if finding_id and fs.visible_findings(request.user).filter(id=finding_id).exists():
        return f"{PAGE_URL}findings/{finding_id}/"
    return ""


def _outcome_rows(request, rows, *, may_record: bool, fy: str) -> list[dict]:
    out = []
    for row in rows:
        exposed = row["exposed_n"]
        coverage = (
            f"{row['coverage_pct']}% of {row['reached']} reached"
            if row.get("coverage_pct") is not None
            else "Not known"
        )
        if row["median_exposed"] is None and row["median_comparison"] is None:
            medians = "Not measured"
        else:
            medians = (
                f"{_signed(row['median_exposed']) or '—'} / "
                f"{_signed(row['median_comparison']) or '—'}"
            )
        verdict = row["verdict"]
        if row.get("p_adjusted") is not None:
            verdict = f"{verdict} (p {row['p_adjusted']})"
        actions = []
        if may_record:
            actions.append(
                {
                    "label": "Record finding",
                    "drawer": f"{PAGE_URL}findings/new?"
                    + urlencode({"row": row["key"], "fy": fy}),
                }
            )
        out.append(
            {
                "cells": [
                    _cell("Programme", row["label"], primary=True),
                    _cell("Delivery", row.get("detail")),
                    _cell("Outcome", row.get("outcome")),
                    _cell(
                        "Schools (exposed / comparison)",
                        f"{exposed} / {row['comparison_n']}",
                    ),
                    _cell("Coverage", coverage),
                    _cell("Median change (exposed / comparison)", medians),
                    _cell("Difference", _signed(row["difference"])),
                    _cell(
                        "Verdict (Holm)",
                        verdict,
                        tone=VERDICT_TONES.get(row["verdict"], "neutral"),
                    ),
                    _cell("Evidence", row["grade_label"], tone=row["grade_tone"]),
                ],
                "actions": actions,
            }
        )
    return out


def _programme_tab(request, view: str, data: dict, *, may_record: bool) -> dict:
    fy = data["fy"]
    rows = data["rows"]
    page = paginate_rows(
        rows, page=_page(request, "outcomes_page"), page_size=pe.PAGE_SIZE
    )
    outcome_rows = _outcome_rows(
        request, page.pop("rows"), may_record=may_record, fy=fy
    )
    coverage = data["coverage"]
    context = {
        "description": _DESCRIPTIONS[view],
        "caveats": data["caveats"],
        "coverage": coverage,
        "period": data["period"],
        "metrics": _output_metrics(view, data),
        "outcomes": {
            "title": f"What changed · {data['period']}",
            "subtitle": pe.COMPARISON_DESIGN,
            "rows": outcome_rows,
            "pager": page,
            "param": "outcomes_page",
            "empty_title": "Nothing to compare yet",
            "empty_body": (
                f"{coverage['schools_paired']} of {coverage['schools_in_scope']} schools have "
                "comparable confirmed SSAs in both years"
                + (
                    f"; {coverage['pairs_too_close']} more were assessed too close together to compare."
                    if coverage["pairs_too_close"]
                    else "."
                )
            ),
        },
        "qualitative": data.get("qualitative") or {},
        "filters": data.get("filters") or [],
        "view_data": data,
    }
    if view == pe.TRAINING:
        contribution = paginate_rows(
            data["contribution"],
            page=_page(request, "contribution_page"),
            page_size=pe.PAGE_SIZE,
        )
        context["contribution"] = {
            "title": f"Intervention contribution (association) · {data['period']}",
            "subtitle": "Every SSA domain, all verified trainings and visits",
            "rows": [_contribution_row(r) for r in contribution.pop("rows")],
            "pager": contribution,
            "param": "contribution_page",
            "empty_title": "No confirmed SSA pairs",
            "empty_body": "Movement needs confirmed assessments in both years for the same school.",
        }
    return context


def _contribution_row(r: dict) -> dict:
    if r["withheld"]:
        change = f"n too small ({r['schools_measured']})"
    elif r["median_change"] is None:
        change = "Not measured"
    else:
        change = _signed(r["median_change"])
    return {
        "cells": [
            _cell("Intervention", r["label"], primary=True),
            _cell("Schools measured", r["schools_measured"]),
            _cell("Median change", change),
            _cell(
                "Median change without focused work",
                _signed(r["median_change_without_focus"]) or "Not enough schools",
            ),
            _cell(
                "Improved / declined",
                f"{r['improved_pct']}% / {r['declined_pct']}%"
                if r["improved_pct"] is not None
                else "",
            ),
            _cell("Focused trainings · visits", f"{r['trainings']} · {r['visits']}"),
            _cell("Change rule", r["rule_label"]),
            _cell(
                "Evidence",
                r["grade"]["label"],
                tone=pe.es.grade_tone(r["grade"]["grade"]),
            ),
        ],
        "actions": [],
    }


_DESCRIPTIONS = {
    pe.TRAINING: (
        "Christian training, grouped by the course taught, how it was delivered and "
        "who delivered it: the SSA change of weak-baseline schools each group reached, "
        "against similar schools no training focused on, with the Regional Lead's "
        "observation of delivery quality beside it."
    ),
    pe.LENDING: (
        "Schools financed inside their SSA window against similar schools never "
        "financed, on Financial Health and Enrolment; with the verified loan impact "
        "conclusions and enrolment evidence."
    ),
    pe.EDTECH: (
        "Schools reached by EdTech trainings, the EdTech Pilot, EdTech loans or a "
        "confirmed deployment, against similar schools with none of these, on the SSA "
        "Learning Environment domain; with IA's checks of the technology in use."
    ),
    pe.VISITS: (
        "Verified school visits focused on each SSA domain against similar schools "
        "no visit focused on, beside the School Visit Effectiveness cohort."
    ),
    pe.FINDINGS: (
        "What Impact Assessment concluded from the evidence, with the figures it "
        "rested on. A second officer reviews each finding; only approved findings "
        "are cited."
    ),
}


def _output_metrics(view: str, data: dict) -> list[dict]:
    o = data["outputs"]
    period = data["period"]
    if view == pe.TRAINING:
        return [
            _metric(
                "Verified Trainings in the Compared Years",
                o["verified_trainings"],
                f"IA-verified, {period}",
            ),
            _metric(
                "Schools Reached by Verified Trainings",
                o["schools_reached"],
                "in your scope",
            ),
            _metric(
                "Training Observations Shared With IA",
                o["observations"],
                "Regional Lead rubric, delivery quality",
            ),
        ]
    if view == pe.LENDING:
        return [
            _metric(
                "Schools With Disbursed School Loans",
                o["schools_financed"],
                "any disbursement not reversed",
            ),
            _metric(
                "Loan Purpose Use Verified by IA",
                o["use_verified"],
                "purpose allocations",
            ),
            _metric(
                "Loan Impact Conclusions Verified",
                o["conclusions_verified"],
                "prepared and verified by different people",
            ),
        ]
    if view == pe.EDTECH:
        return [
            _metric(
                "Verified EdTech Trainings",
                o["verified_trainings"],
                f"IA-verified, {period}",
            ),
            _metric(
                "Confirmed EdTech Deployments in Scope",
                o["deployments"],
                "confirmed by a second reader",
            ),
            _metric(
                "EdTech Units Working at Last Check",
                f"{o['functional_pct']}%" if o["functional_pct"] is not None else None,
                f"of {o['units_checked']} units checked",
            ),
            _metric(
                "EdTech Loans Disbursed to Schools",
                o["loans"],
                "schools with an EdTech-purpose loan",
            ),
        ]
    return [
        _metric(
            "Verified Visits in SSA Windows",
            o["verified_visits"],
            "between each school's two readings",
        ),
        _metric(
            "Schools With a Verified Visit in Window",
            o["schools_visited"],
            "of the schools measured",
        ),
    ]


# ── Findings tab ────────────────────────────────────────────────────────────


def _findings_tab(request, *, fy: str) -> dict:
    from apps.analytics.ia_collection import db_page

    status = request.GET.get("status") or ""
    if status not in fs.STATUS_LABELS:
        status = ""
    programme = request.GET.get("programme") or ""
    if programme not in fs.PROGRAMME_LABELS:
        programme = ""
    counts = fs.counts(request.user, fy)
    page = db_page(
        fs.register(request.user, status=status, programme=programme),
        request.GET.get("register_page"),
    )
    entries = fs.decorate(request.user, page.pop("rows"))
    rows = []
    for entry in entries:
        f = entry["finding"]
        snap = f.metric_snapshot or {}
        figures = ""
        if snap.get("exposed_n") is not None:
            figures = (
                f"{snap.get('exposed_n')} / {snap.get('comparison_n')} schools · "
                f"{snap.get('grade_label') or ''}"
            )
        action_label = "Open"
        if entry["can_review"]:
            action_label = "Review"
        elif entry["can_edit"]:
            action_label = "Edit"
        rows.append(
            {
                "cells": [
                    _cell("Finding", f.statement[:140], primary=True),
                    _cell("Programme", entry["programme_label"]),
                    _cell("Figures", figures),
                    _cell(
                        "Recommendation for",
                        fs.ACTION_OWNER_LABELS.get(f.action_owner_role, ""),
                    ),
                    _cell("Author", entry["author"]),
                    _cell(
                        "Status",
                        f"{entry['status_label']}: {f.review_note}"
                        if f.status == fs.RETURNED and f.review_note
                        else entry["status_label"],
                        tone=entry["status_tone"],
                    ),
                ],
                "actions": [
                    {"label": action_label, "drawer": f"{PAGE_URL}findings/{f.id}/"}
                ],
            }
        )
    return {
        "description": _DESCRIPTIONS[pe.FINDINGS],
        "caveats": [],
        "metrics": [
            _metric(
                "Impact Findings Awaiting Review",
                counts["in_review"],
                "reviewed by someone other than the author",
                "warning" if counts["in_review"] else "info",
            ),
            _metric(
                "Impact Findings Approved This Year",
                counts["approved_this_year"],
                f"FY{fy}",
            ),
            _metric(
                "Impact Findings Returned to Authors",
                counts["returned"],
                "waiting for the author",
                "danger" if counts["returned"] else "info",
            ),
        ],
        "register": {
            "title": "Impact findings",
            "rows": rows,
            "pager": page,
            "param": "register_page",
            "empty_title": "No findings recorded",
            "empty_body": "Record a finding from a row of a programme tab; the figures travel with it.",
        },
        "filters": [
            {
                "name": "status",
                "label": "Status",
                "value": status,
                "blank": "Every status",
                "options": list(fs.STATUS_LABELS.items()),
            },
            {
                "name": "programme",
                "label": "Programme",
                "value": programme,
                "blank": "Every programme",
                "options": list(fs.PROGRAMME_LABELS.items()),
            },
        ],
    }


# ── Finding drawers ─────────────────────────────────────────────────────────


def _finding_fields(finding=None, *, programme="", intervention="") -> list[dict]:
    from apps.core.enums import SsaIntervention

    def value(name, default=""):
        if finding is None:
            return default
        raw = getattr(finding, name)
        if name == "follow_up_due":
            return raw.isoformat() if raw else ""
        if name == "evidence_refs":
            return "\n".join(raw or [])
        return raw or ""

    return [
        _field(
            "programme",
            "Programme",
            type="select",
            required=True,
            options=list(fs.PROGRAMME_LABELS.items()),
            value=value("programme", programme),
        ),
        _field(
            "intervention",
            "SSA domain it concerns",
            type="select",
            blank="Across domains",
            options=[(v, str(label)) for v, label in SsaIntervention.choices],
            value=value("intervention", intervention),
        ),
        _field(
            "statement",
            "What the evidence shows",
            type="textarea",
            required=True,
            rows=4,
            maxlength=4000,
            value=value("statement"),
            help="Plain words a Country Director can act on. Association, never proof.",
        ),
        _field(
            "contrary_evidence",
            "Evidence that cuts against it",
            type="textarea",
            rows=3,
            maxlength=4000,
            value=value("contrary_evidence"),
            help="Figures, field reports or feedback that point the other way.",
        ),
        _field(
            "limitations",
            "Limitations",
            type="textarea",
            rows=3,
            maxlength=4000,
            value=value("limitations"),
            help="Required to submit: what this evidence cannot show.",
        ),
        _field(
            "recommendation",
            "Recommendation",
            type="textarea",
            rows=3,
            maxlength=4000,
            value=value("recommendation"),
        ),
        _field(
            "action_owner_role",
            "Who should act on it",
            type="select",
            blank="No action needed",
            options=list(fs.ACTION_OWNER_ROLES),
            value=value("action_owner_role"),
        ),
        _field(
            "follow_up_due", "Follow up by", type="date", value=value("follow_up_due")
        ),
        _field(
            "evidence_refs",
            "Evidence references",
            type="textarea",
            rows=3,
            value=value("evidence_refs"),
            help="One per line: debrief, visit feedback, report or record references.",
        ),
    ]


def _snapshot_facts(snapshot: dict) -> list[dict]:
    if not snapshot or snapshot.get("exposed_n") is None:
        return []
    facts = [
        {
            "label": "Row",
            "value": f"{snapshot.get('label', '')} · {snapshot.get('outcome', '')}",
        },
        {
            "label": "Period and design",
            "value": f"{snapshot.get('period', '')} · {snapshot.get('design', '')}",
        },
        {
            "label": "Schools",
            "value": f"{snapshot.get('exposed_n')} exposed / {snapshot.get('comparison_n')} comparison"
            + (
                f" · {snapshot['coverage_pct']}% coverage"
                if snapshot.get("coverage_pct") is not None
                else ""
            ),
        },
        {
            "label": "Median change",
            "value": f"{_signed(snapshot.get('median_exposed')) or '—'} exposed / "
            f"{_signed(snapshot.get('median_comparison')) or '—'} comparison · difference "
            f"{_signed(snapshot.get('difference')) or '—'}",
        },
        {
            "label": "Verdict",
            "value": f"{snapshot.get('verdict', '')}"
            + (
                f" (Holm p {snapshot['p_adjusted']}, raw p {snapshot.get('p')})"
                if snapshot.get("p_adjusted") is not None
                else ""
            ),
        },
        {
            "label": "Evidence grade",
            "value": f"{snapshot.get('grade_label', '')}\n"
            + "\n".join(snapshot.get("grade_reasons") or []),
        },
    ]
    if snapshot.get("generated_at"):
        facts.append(
            {
                "label": "Figures taken",
                "value": snapshot["generated_at"][:16].replace("T", " "),
            }
        )
    return facts


def _row_snapshot(row: dict) -> dict:
    return {
        **{k: row.get(k) for k in fs.SNAPSHOT_KEYS if k in row},
        "row_key": row["key"],
    }


@require_page_permission("ia_learning")
@require_http_methods(["GET"])
def finding_new_drawer(request):
    if not fs.may_author(request.user):
        return _drawer(
            request,
            title="Record a finding",
            subtitle="Programme Learning",
            empty="Only Impact Assessment records impact findings.",
        )
    row_key = (request.GET.get("row") or "").strip()
    facts, programme, intervention = [], "", ""
    if row_key:
        row, _cohort = pe.row_by_key(
            request.user, row_key, {"fy": request.GET.get("fy")}
        )
        if row is None:
            return _drawer(
                request,
                title="Record a finding",
                subtitle="Programme Learning",
                empty="That row is no longer in the table; reload the page and try again.",
            )
        facts = _snapshot_facts(_row_snapshot(row))
        programme = row_key.split(":", 1)[0]
        intervention = row.get("intervention") or ""
    return _drawer(
        request,
        title="Record a finding",
        subtitle="Draft · a second officer reviews it before it is cited",
        action=f"{PAGE_URL}findings/save",
        facts=facts,
        fields=[
            _field("row", "", type="hidden", value=row_key),
            _field("fy", "", type="hidden", value=pe.resolve_fy(request.GET.get("fy"))),
            *_finding_fields(programme=programme, intervention=intervention),
            _field(
                "submit_now",
                "Submit for review now",
                type="checkbox",
                help="Leave unticked to keep a draft you can finish later.",
            ),
        ],
        submit="Record finding",
        note=(
            "The figures above are taken again by the server when you save, from "
            "the same row."
            if facts
            else ""
        ),
    )


@require_page_permission("ia_learning")
@require_POST
def finding_create(request):
    fallback = _view_url(pe.FINDINGS)
    row_key = (request.POST.get("row") or "").strip()
    snapshot, cohort = None, None
    if row_key:
        row, cohort = pe.row_by_key(
            request.user, row_key, {"fy": request.POST.get("fy")}
        )
        if row is None:
            messages.error(
                request,
                "That row is no longer in the table; reload the page and record the finding again.",
            )
            return _back(request, fallback)
        snapshot = _row_snapshot(row)
    try:
        finding = fs.record_finding(
            request.user,
            request.POST,
            cohort_filters=cohort,
            metric_snapshot=snapshot,
            submit=bool(request.POST.get("submit_now")),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(
        request,
        "Finding submitted for review."
        if finding.status == fs.IN_REVIEW
        else "Finding saved as a draft.",
    )
    return _back(request, fallback)


def _visible_finding(request, finding_id):
    return fs.visible_findings(request.user).filter(id=finding_id).first()


@require_page_permission("ia_learning")
@require_http_methods(["GET"])
def finding_drawer(request, finding_id):
    finding = _visible_finding(request, finding_id)
    if finding is None:
        return _drawer(
            request,
            title="Impact finding",
            subtitle="Programme Learning",
            empty="This finding is not in your country.",
        )
    entry = fs.decorate(request.user, [finding])[0]
    subtitle = (
        f"{entry['programme_label']} · {entry['status_label']} · by {entry['author']}"
    )
    words = [
        {"label": "What the evidence shows", "value": finding.statement},
        {"label": "Evidence that cuts against it", "value": finding.contrary_evidence},
        {"label": "Limitations", "value": finding.limitations},
        {
            "label": "Recommendation",
            "value": (
                f"{finding.recommendation}\nFor: {fs.ACTION_OWNER_LABELS.get(finding.action_owner_role, '')}"
                + (
                    f" · follow up by {finding.follow_up_due:%-d %b %Y}"
                    if finding.follow_up_due
                    else ""
                )
                if finding.recommendation
                else ""
            ),
        },
        {
            "label": "Evidence references",
            "value": "\n".join(finding.evidence_refs or []),
        },
    ]
    if finding.review_note:
        words.append(
            {
                "label": "Review note",
                "value": f"{finding.review_note} ({entry['reviewer']})",
            }
        )
    facts = words + _snapshot_facts(finding.metric_snapshot or {})
    if entry["can_review"]:
        return _drawer(
            request,
            title="Review impact finding",
            subtitle=subtitle,
            action=f"{PAGE_URL}findings/{finding.id}/review",
            facts=facts,
            fields=[
                _field(
                    "decision",
                    "Decision",
                    type="select",
                    required=True,
                    options=(
                        ("approve", "Approve: the evidence supports it as written"),
                        ("return", "Return to the author to change"),
                    ),
                    value="approve",
                ),
                _field(
                    "note",
                    "Review note",
                    type="textarea",
                    rows=3,
                    maxlength=4000,
                    help="Required when you return it; the author reads it.",
                ),
            ],
            submit="Save decision",
            note="Check the statement against the figures and the limitations before approving.",
        )
    if entry["can_edit"]:
        return _drawer(
            request,
            title="Edit impact finding",
            subtitle=subtitle,
            action=f"{PAGE_URL}findings/{finding.id}/update",
            facts=_snapshot_facts(finding.metric_snapshot or {})
            + (
                [{"label": "Review note", "value": finding.review_note}]
                if finding.review_note
                else []
            ),
            fields=[
                *_finding_fields(finding),
                _field("submit_now", "Submit for review now", type="checkbox"),
            ],
            submit="Save",
            note_tone="warning" if finding.status == fs.RETURNED else "info",
            note=(
                "Returned by the reviewer: correct it and submit again."
                if finding.status == fs.RETURNED
                else "You wrote this, so a second officer reviews it."
            ),
        )
    if entry["can_revise"]:
        return _drawer(
            request,
            title="Impact finding",
            subtitle=subtitle,
            action=f"{PAGE_URL}findings/{finding.id}/revise",
            facts=facts,
            submit="Start a revision",
            note=(
                "Approved. A revision is a new draft; this finding stands until the "
                "revision is approved."
            ),
        )
    note = "Read only."
    if finding.status == fs.IN_REVIEW and entry["is_mine"]:
        note = "You wrote this, so a second Impact Assessment officer reviews it."
    elif finding.status == fs.IN_REVIEW:
        note = (
            "A second Impact Assessment officer in this country reviews it; the Country "
            "Director only where there is none."
        )
    return _drawer(
        request, title="Impact finding", subtitle=subtitle, facts=facts, empty=note
    )


@require_page_permission("ia_learning")
@require_POST
def finding_update(request, finding_id):
    fallback = _view_url(pe.FINDINGS)
    try:
        finding = fs.update_finding(request.user, finding_id, request.POST)
        if request.POST.get("submit_now"):
            finding = fs.submit_finding(request.user, finding.id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(
        request,
        "Finding submitted for review."
        if finding.status == fs.IN_REVIEW
        else "Finding saved.",
    )
    return _back(request, fallback)


@require_page_permission("ia_learning")
@require_POST
def finding_review(request, finding_id):
    fallback = _view_url(pe.FINDINGS)
    decision = request.POST.get("decision") or ""
    try:
        fs.review_finding(
            request.user,
            finding_id,
            decision=decision,
            note=request.POST.get("note", ""),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(
        request,
        "Finding approved."
        if decision == "approve"
        else "Finding returned to its author.",
    )
    return _back(request, fallback)


@require_page_permission("ia_learning")
@require_POST
def finding_revise(request, finding_id):
    fallback = _view_url(pe.FINDINGS)
    try:
        revision = fs.revise_finding(request.user, finding_id)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Revision started as a draft.")
    return redirect(_view_url(pe.FINDINGS, status=fs.DRAFT) + f"&open={revision.id}")
