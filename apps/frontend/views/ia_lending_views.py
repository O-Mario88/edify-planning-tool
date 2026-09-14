"""Impact Assessment's Lending Evidence queue (IA review, owner, 2026-09-13).

Loan-use, enrolment, purpose-output and teacher-completion verification and
the loan impact conclusion existed as services and API endpoints only: no
screen let Impact Assessment act on them, and a conclusion was written and
approved in one act by one person. /ia/lending-evidence/ is that screen, over
the existing apps.business_transformation.lending_impact functions (which
hold every rule, scope check and audit row):

  Loan use · Enrolment · Purpose outputs · Teacher completion
      what the lending partner reported and IA has not verified yet; each row
      opens a one-column drawer that verifies (or returns, where the service
      allows it) with the service's own refusal shown in the drawer's page;
  Impact conclusions
      due conclusions to prepare (Business Transformation; Impact Assessment
      only where the country has no BT officer), prepared conclusions awaiting
      verification by someone other than the preparer (an IA officer; a second
      IA officer or the Country Director where IA prepared), and returned ones;
  Financed cohorts
      disbursement year and purpose: how long the loans have run, conclusions
      due and verified by classification, verified enrolment change, with the
      evidence grade and a maturity caveat — a young cohort is not compared
      with a mature one.

Everything is bounded to the reader's impact reach (scoped_impact_loans: the
country for IA, the Country Director and Business Transformation). The
prepare drawer is also reached from the Business Transformation Impact &
Reports page, so its routes use that page's key; the service refuses anyone
but the preparing roles.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.analytics import evidence_strength as es
from apps.business_transformation import lending_impact as li
from apps.business_transformation.models import (
    EnrolmentSnapshot,
    EnrolmentSnapshotKind,
    IAValidationStatus,
    ImpactEvidenceStatus,
    LoanDisbursement,
    LoanImpactAssessment,
    LoanImpactStatus,
    LoanPurposeAllocation,
    PurposeAllocationStatus,
    PurposeSpecificAssetOutput,
    TeacherDegreeUpgradeBeneficiary,
)
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.pagination import paginate_rows
from apps.core.permissions import has_permission, require_page_permission
from apps.core.rbac import EdifyRole, Permission
from apps.frontend.views.hr_programme_views import SERVICE_ERRORS, _drawer, _field

PAGE_URL = "/ia/lending-evidence/"
SOURCE = "apps.frontend.views.ia_lending_views:_metric"

USE = "use"
ENROLMENT = "enrolment"
OUTPUTS = "outputs"
TEACHERS = "teachers"
CONCLUSIONS = "conclusions"
COHORTS = "cohorts"

TABS = (
    (USE, "Loan use"),
    (ENROLMENT, "Enrolment"),
    (OUTPUTS, "Purpose outputs"),
    (TEACHERS, "Teacher completion"),
    (CONCLUSIONS, "Impact conclusions"),
    (COHORTS, "Financed cohorts"),
)
TAB_LABELS = dict(TABS)

TO_PREPARE = "to_prepare"
AWAITING = "awaiting"
RETURNED = "returned"
VERIFIED = "verified"
STATE_LABELS = {
    TO_PREPARE: "To prepare",
    AWAITING: "Awaiting verification",
    RETURNED: "Returned to preparer",
    VERIFIED: "Verified",
}
STATE_TONES = {
    TO_PREPARE: "warning",
    AWAITING: "warning",
    RETURNED: "danger",
    VERIFIED: "success",
}

POSITIVE = (
    LoanImpactStatus.STRONG_POSITIVE,
    LoanImpactStatus.POSITIVE,
    LoanImpactStatus.EARLY_PROGRESS,
)
NEUTRAL = (LoanImpactStatus.MIXED, LoanImpactStatus.NO_CHANGE)

COHORT_CAVEAT = (
    "Cohorts are compared within their own disbursement year and purpose. A "
    "cohort whose loans have run for less than the purpose's follow-up window "
    "is immature: its conclusions are early, not final."
)
PAGE_SIZE = 25


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


def _day(value) -> str:
    return f"{value:%-d %b %Y}" if value else ""


def _page(request, param: str) -> int:
    try:
        return max(1, int(request.GET.get(param) or 1))
    except (TypeError, ValueError):
        return 1


def _tab_url(tab: str, **params) -> str:
    query = urlencode({"tab": tab, **{k: v for k, v in params.items() if v}})
    return f"{PAGE_URL}?{query}"


def _back(request, fallback: str):
    from apps.frontend.views.coaching_views import safe_return_url

    return redirect(safe_return_url(request, fallback, drop=("open",)))


def _refused(request, exc, fallback: str):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


def _sees_money(principal) -> bool:
    return has_permission(
        principal, Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW.value
    )


# ── Queues ──────────────────────────────────────────────────────────────────


def _loan_ids(principal):
    return li.scoped_impact_loans(principal).values("id")


def use_queue(principal):
    return (
        LoanPurposeAllocation.objects.filter(
            loan_id__in=_loan_ids(principal),
            status=PurposeAllocationStatus.REPORTED,
        )
        .select_related("loan__school", "loan__mfi", "purpose")
        .order_by("updated_at")
    )


def enrolment_queue(principal):
    return (
        EnrolmentSnapshot.objects.filter(
            loan_id__in=_loan_ids(principal), status=ImpactEvidenceStatus.REPORTED
        )
        .select_related("loan__school", "loan__mfi")
        .order_by("as_of_date")
    )


def output_queue(principal):
    return (
        PurposeSpecificAssetOutput.objects.filter(
            allocation__loan_id__in=_loan_ids(principal),
            status=ImpactEvidenceStatus.REPORTED,
        )
        .select_related("allocation__loan__school", "allocation__purpose")
        .order_by("updated_at")
    )


def teacher_queue(principal):
    return (
        TeacherDegreeUpgradeBeneficiary.objects.filter(
            loan_id__in=_loan_ids(principal),
            status=ImpactEvidenceStatus.REPORTED,
            completed_on__isnull=False,
        )
        .select_related("loan__school")
        .order_by("completed_on")
    )


def _unprepared_q() -> Q:
    return (
        Q(prepared_at__isnull=True)
        | Q(prepared_by__isnull=True)
        | Q(prepared_by=li.LEGACY_PREPARER)
    )


def conclusion_state(assessment) -> str:
    if assessment.ia_status == IAValidationStatus.VERIFIED:
        return VERIFIED
    if assessment.ia_status == IAValidationStatus.RETURNED:
        return RETURNED
    if (
        not assessment.prepared_at
        or not assessment.prepared_by
        or assessment.prepared_by == li.LEGACY_PREPARER
    ):
        return TO_PREPARE
    return AWAITING


def conclusions(principal, *, state: str = ""):
    today = timezone.localdate()
    qs = LoanImpactAssessment.objects.filter(loan_id__in=_loan_ids(principal))
    if state == TO_PREPARE:
        qs = qs.filter(
            due_date__lte=today, ia_status=IAValidationStatus.PENDING
        ).filter(_unprepared_q())
    elif state == AWAITING:
        qs = qs.filter(ia_status=IAValidationStatus.PENDING).exclude(_unprepared_q())
    elif state == RETURNED:
        qs = qs.filter(ia_status=IAValidationStatus.RETURNED)
    elif state == VERIFIED:
        qs = qs.filter(ia_status=IAValidationStatus.VERIFIED)
    else:
        qs = qs.filter(Q(due_date__lte=today) | ~_unprepared_q())
    return qs.select_related(
        "loan__school__region", "loan__mfi", "loan__purpose"
    ).order_by("due_date", "created_at")


def queue_counts(principal) -> dict:
    """Tile counts: six queries, whatever the size of the queues."""
    today = timezone.localdate()
    base = LoanImpactAssessment.objects.filter(loan_id__in=_loan_ids(principal))
    conclusion_counts = base.aggregate(
        to_prepare=Count(
            "id",
            filter=Q(due_date__lte=today, ia_status=IAValidationStatus.PENDING)
            & _unprepared_q(),
        ),
        awaiting=Count(
            "id", filter=Q(ia_status=IAValidationStatus.PENDING) & ~_unprepared_q()
        ),
        returned=Count("id", filter=Q(ia_status=IAValidationStatus.RETURNED)),
    )
    evidence = {
        USE: use_queue(principal).count(),
        ENROLMENT: enrolment_queue(principal).count(),
        OUTPUTS: output_queue(principal).count(),
        TEACHERS: teacher_queue(principal).count(),
    }
    return {
        **conclusion_counts,
        "evidence": evidence,
        "evidence_total": sum(evidence.values()),
    }


# ── Financed cohorts ────────────────────────────────────────────────────────


def financed_cohorts(principal, *, today=None) -> list[dict]:
    """Disbursement year × purpose outcomes: three queries."""
    today = today or timezone.localdate()
    loan_ids = _loan_ids(principal)
    first: dict[str, dict] = {}
    for row in (
        LoanDisbursement.objects.filter(loan_id__in=loan_ids, reversal__isnull=True)
        .order_by("disbursed_on")
        .values(
            "loan_id",
            "loan__school_id",
            "loan__purpose_id",
            "loan__purpose__label",
            "loan__purpose__follow_up_days",
            "disbursed_on",
        )
    ):
        first.setdefault(row["loan_id"], row)
    if not first:
        return []
    assessments = defaultdict(list)
    for row in LoanImpactAssessment.objects.filter(loan_id__in=list(first)).values(
        "loan_id", "due_date", "ia_status", "classification"
    ):
        assessments[row["loan_id"]].append(row)
    snapshots: dict[str, dict] = defaultdict(dict)
    for row in (
        EnrolmentSnapshot.objects.filter(
            loan_id__in=list(first), status=ImpactEvidenceStatus.VERIFIED
        )
        .order_by("as_of_date")
        .values("loan_id", "kind", "learner_count")
    ):
        if row["kind"] == EnrolmentSnapshotKind.BASELINE:
            snapshots[row["loan_id"]].setdefault("baseline", row["learner_count"])
        else:
            snapshots[row["loan_id"]]["follow_up"] = row["learner_count"]

    cohorts: dict[tuple, dict] = {}
    for loan_id, row in first.items():
        key = (row["disbursed_on"].year, row["loan__purpose_id"] or "")
        c = cohorts.setdefault(
            key,
            {
                "year": row["disbursed_on"].year,
                "purpose": row["loan__purpose__label"] or "No purpose recorded",
                "follow_up_days": row["loan__purpose__follow_up_days"] or 0,
                "loans": 0,
                "schools": set(),
                "days": [],
                "due": 0,
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "insufficient": 0,
                "changes": [],
            },
        )
        c["loans"] += 1
        c["schools"].add(row["loan__school_id"])
        c["days"].append((today - row["disbursed_on"]).days)
        for a in assessments.get(loan_id, []):
            if a["due_date"] <= today:
                c["due"] += 1
            if a["ia_status"] != IAValidationStatus.VERIFIED:
                continue
            if a["classification"] in POSITIVE:
                c["positive"] += 1
            elif a["classification"] in NEUTRAL:
                c["neutral"] += 1
            elif a["classification"] == LoanImpactStatus.NEGATIVE:
                c["negative"] += 1
            else:
                c["insufficient"] += 1
        pair = snapshots.get(loan_id) or {}
        if pair.get("baseline") and pair.get("follow_up") is not None:
            c["changes"].append(
                (pair["follow_up"] - pair["baseline"]) / pair["baseline"] * 100
            )
    out = []
    for c in sorted(cohorts.values(), key=lambda c: (-c["year"], c["purpose"])):
        median_days = int(median(c["days"])) if c["days"] else 0
        immature = median_days < c["follow_up_days"]
        graded = es.grade(
            len(c["changes"]),
            confirmed_share=1.0,
            flags=(es.IMMATURE_COHORT,) if immature else (),
        )
        out.append(
            {
                **c,
                "schools": len(c["schools"]),
                "median_months": round(median_days / 30.4, 1),
                "immature": immature,
                "enrolment_pairs": len(c["changes"]),
                "median_enrolment_change_pct": (
                    round(median(c["changes"]), 1)
                    if len(c["changes"]) >= es.MIN_N
                    else None
                ),
                "grade": graded,
            }
        )
    return out


# ── The page ────────────────────────────────────────────────────────────────


@require_page_permission("ia_lending_evidence")
@require_http_methods(["GET"])
def lending_evidence_page(request):
    tab = request.GET.get("tab") or USE
    if tab not in TAB_LABELS:
        tab = USE
    counts = queue_counts(request.user)
    metrics = [
        _metric(
            "Lending Evidence Awaiting IA Verification",
            counts["evidence_total"],
            "loan use, enrolment, outputs and teacher completion",
            "warning" if counts["evidence_total"] else "info",
        ),
        _metric(
            "Loan Impact Conclusions to Prepare",
            counts["to_prepare"],
            "due, not yet prepared",
            "warning" if counts["to_prepare"] else "info",
        ),
        _metric(
            "Loan Impact Conclusions Awaiting Verification",
            counts["awaiting"],
            "verified by someone other than the preparer",
            "warning" if counts["awaiting"] else "info",
        ),
        _metric(
            "Loan Impact Conclusions Returned",
            counts["returned"],
            "waiting for the preparer",
            "danger" if counts["returned"] else "info",
        ),
    ]
    builder = {
        USE: _use_tab,
        ENROLMENT: _enrolment_tab,
        OUTPUTS: _output_tab,
        TEACHERS: _teacher_tab,
        CONCLUSIONS: _conclusion_tab,
        COHORTS: _cohort_tab,
    }[tab]
    context = builder(request)
    table = context["table"]
    table["has_actions"] = any(row["actions"] for row in table["rows"])
    return render(
        request,
        "pages/ia/lending_evidence.html",
        {
            "tab": tab,
            "tabs": [
                {
                    "key": key,
                    "label": label
                    + (
                        f" ({counts['evidence'][key]})"
                        if key in counts["evidence"] and counts["evidence"][key]
                        else ""
                    ),
                    "url": _tab_url(key),
                    "active": key == tab,
                }
                for key, label in TABS
            ],
            "metrics": metrics,
            "filters": {"tab": tab, "fields": context.pop("filters", [])},
            "autoload_drawer": _autoload(request),
            **context,
        },
    )


def _autoload(request) -> str:
    """The conclusion a notification asked for (?open=<id>), when it is in the
    reader's reach."""
    assessment_id = (request.GET.get("open") or "").strip()
    if assessment_id and _visible_conclusion(request, assessment_id) is not None:
        return f"{PAGE_URL}conclusions/{assessment_id}/"
    return ""


def _db_page(request, queryset):
    from apps.analytics.ia_collection import db_page

    return db_page(queryset, request.GET.get("page"), PAGE_SIZE)


def _table(title, rows, pager, *, empty_title, empty_body, subtitle="") -> dict:
    return {
        "title": title,
        "subtitle": subtitle,
        "rows": rows,
        "pager": pager,
        "param": "page",
        "empty_title": empty_title,
        "empty_body": empty_body,
    }


def _use_tab(request) -> dict:
    page = _db_page(request, use_queue(request.user))
    money = _sees_money(request.user)
    rows = [
        {
            "cells": [
                _cell("School", a.loan.school.name, primary=True),
                _cell("Lending partner", a.loan.mfi.name),
                _cell("Purpose", a.purpose.label),
                _cell("Planned", a.planned_amount if money else "Withheld"),
                _cell("Reported use", a.reported_amount if money else "Withheld"),
                _cell("Intended output", a.intended_output[:80]),
                _cell("Reported", _day(a.updated_at)),
            ],
            "actions": [{"label": "Verify", "drawer": f"{PAGE_URL}use/{a.id}/"}],
        }
        for a in page.pop("rows")
    ]
    return {
        "description": "Loan money the lending partner reports as used for its purpose. Verify the amount the evidence supports, or return it.",
        "table": _table(
            "Loan use to verify",
            rows,
            page,
            empty_title="No reported loan use waiting",
            empty_body="Reported purpose use appears here until Impact Assessment verifies it.",
        ),
    }


def _enrolment_tab(request) -> dict:
    page = _db_page(request, enrolment_queue(request.user))
    labels = dict(EnrolmentSnapshotKind.choices)
    rows = [
        {
            "cells": [
                _cell("School", s.loan.school.name, primary=True),
                _cell("Lending partner", s.loan.mfi.name),
                _cell("Snapshot", labels.get(s.kind, s.kind)),
                _cell("As of", _day(s.as_of_date)),
                _cell("Learners", s.learner_count),
                _cell("School record", s.loan.school.enrollment),
                _cell("Evidence", s.evidence_reference),
            ],
            "actions": [{"label": "Verify", "drawer": f"{PAGE_URL}enrolment/{s.id}/"}],
        }
        for s in page.pop("rows")
    ]
    return {
        "description": "Learner counts reported before and after financing. Check the register against the school's record before verifying.",
        "table": _table(
            "Enrolment snapshots to verify",
            rows,
            page,
            empty_title="No reported enrolment waiting",
            empty_body="Baseline and follow-up enrolment appear here until verified.",
        ),
    }


def _output_tab(request) -> dict:
    page = _db_page(request, output_queue(request.user))
    rows = [
        {
            "cells": [
                _cell("School", o.allocation.loan.school.name, primary=True),
                _cell("Purpose", o.allocation.purpose.label),
                _cell("Output", o.asset_type.replace("_", " ").capitalize()),
                _cell("Planned", o.planned_quantity),
                _cell("Reported", o.reported_quantity),
                _cell("Operational", o.reported_operational_quantity),
                _cell("Evidence", o.evidence_reference),
            ],
            "actions": [{"label": "Verify", "drawer": f"{PAGE_URL}outputs/{o.id}/"}],
        }
        for o in page.pop("rows")
    ]
    return {
        "description": "What the loan bought or built: classrooms, computers, land. Verify what exists and works.",
        "table": _table(
            "Purpose outputs to verify",
            rows,
            page,
            empty_title="No reported outputs waiting",
            empty_body="Reported purpose outputs appear here until verified.",
        ),
    }


def _teacher_tab(request) -> dict:
    page = _db_page(request, teacher_queue(request.user))
    rows = [
        {
            "cells": [
                _cell("School", t.loan.school.name, primary=True),
                _cell("Teacher reference", t.anonymized_reference),
                _cell("Programme", f"{t.programme} · {t.institution}"),
                _cell("Completed", _day(t.completed_on)),
                _cell("Evidence", t.evidence_reference),
            ],
            "actions": [{"label": "Verify", "drawer": f"{PAGE_URL}teachers/{t.id}/"}],
        }
        for t in page.pop("rows")
    ]
    return {
        "description": "Teachers whose degree upgrade a loan financed and who are reported as completed.",
        "table": _table(
            "Teacher completions to verify",
            rows,
            page,
            empty_title="No reported completions waiting",
            empty_body="Reported teacher completions appear here until verified.",
        ),
    }


def _conclusion_tab(request) -> dict:
    state = request.GET.get("state") or ""
    if state not in STATE_LABELS:
        state = ""
    page = _db_page(request, conclusions(request.user, state=state))
    rows = []
    for a in page.pop("rows"):
        s = conclusion_state(a)
        rows.append(
            {
                "cells": [
                    _cell("School", a.loan.school.name, primary=True),
                    _cell("Lending partner", a.loan.mfi.name),
                    _cell("Purpose", a.loan.purpose.label if a.loan.purpose_id else ""),
                    _cell("Due", _day(a.due_date)),
                    _cell(
                        "Classification",
                        a.get_classification_display() if s != TO_PREPARE else "",
                    ),
                    _cell(
                        "State",
                        f"{STATE_LABELS[s]}: {a.ia_note}"
                        if s == RETURNED and a.ia_note
                        else STATE_LABELS[s],
                        tone=STATE_TONES[s],
                    ),
                ],
                "actions": [
                    {"label": "Open", "drawer": f"{PAGE_URL}conclusions/{a.id}/"}
                ],
            }
        )
    return {
        "description": (
            "Business Transformation prepares each due conclusion from verified evidence "
            "(Impact Assessment only where the country has no BT officer); someone other "
            "than the preparer verifies it before the classification is published."
        ),
        "table": _table(
            "Loan impact conclusions",
            rows,
            page,
            empty_title="No conclusions due",
            empty_body="Conclusions are scheduled from each loan's first disbursement.",
        ),
        "filters": [
            {
                "name": "state",
                "label": "State",
                "value": state,
                "blank": "Due or in progress",
                "options": list(STATE_LABELS.items()),
            }
        ],
    }


def _cohort_tab(request) -> dict:
    cohorts = financed_cohorts(request.user)
    page = paginate_rows(cohorts, page=_page(request, "page"), page_size=PAGE_SIZE)
    rows = []
    for c in page.pop("rows"):
        change = (
            f"{c['median_enrolment_change_pct']:+.1f}% ({c['enrolment_pairs']} loans)"
            if c["median_enrolment_change_pct"] is not None
            else f"n too small ({c['enrolment_pairs']})"
        )
        rows.append(
            {
                "cells": [
                    _cell("Cohort", f"{c['year']} · {c['purpose']}", primary=True),
                    _cell("Loans · schools", f"{c['loans']} · {c['schools']}"),
                    _cell(
                        "Running",
                        f"{c['median_months']} months"
                        + (" (immature)" if c["immature"] else ""),
                        tone="warning" if c["immature"] else "",
                    ),
                    _cell("Conclusions due", c["due"]),
                    _cell(
                        "Verified: positive / no change / negative / insufficient",
                        f"{c['positive']} / {c['neutral']} / {c['negative']} / {c['insufficient']}",
                    ),
                    _cell("Verified enrolment change", change),
                    _cell(
                        "Evidence",
                        c["grade"]["label"],
                        tone=es.grade_tone(c["grade"]["grade"]),
                    ),
                ],
                "actions": [],
            }
        )
    return {
        "description": COHORT_CAVEAT,
        "table": _table(
            "Financed cohorts",
            rows,
            page,
            empty_title="No disbursed loans in your country",
            empty_body="Cohorts form from each loan's first confirmed disbursement.",
            subtitle="Before and after, verified evidence only",
        ),
    }


# ── Verification drawers ────────────────────────────────────────────────────


def _not_found(request, title):
    return _drawer(
        request,
        title=title,
        subtitle="Lending evidence",
        empty="This record is not in your country, or is no longer waiting.",
    )


def _may_validate(request) -> bool:
    return has_permission(
        request.user, Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value
    )


@require_page_permission("ia_lending_evidence")
@require_http_methods(["GET"])
def use_drawer(request, allocation_id):
    a = use_queue(request.user).filter(id=allocation_id).first()
    if a is None:
        return _not_found(request, "Verify loan use")
    money = _sees_money(request.user)
    facts = [
        {"label": "School", "value": f"{a.loan.school.name} · {a.loan.mfi.name}"},
        {"label": "Purpose", "value": a.purpose.label},
        {"label": "Intended output", "value": a.intended_output},
    ]
    if money:
        facts += [
            {"label": "Planned", "value": a.planned_amount},
            {"label": "Reported use", "value": a.reported_amount},
        ]
    if not _may_validate(request):
        return _drawer(
            request,
            title="Loan use",
            subtitle="Lending evidence",
            facts=facts,
            empty="Impact Assessment verifies loan use.",
        )
    return _drawer(
        request,
        title="Verify loan use",
        subtitle="Lending evidence",
        action=f"{PAGE_URL}use/{a.id}/verify",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                options=(
                    ("verified", "Verify the amount below"),
                    ("returned", "Return to the lending partner"),
                ),
                value="verified",
            ),
            _field(
                "verifiedAmount",
                "Verified amount",
                type="number",
                step="0.01",
                min=0,
                value=a.reported_amount if money else "",
                help="No more than the reported use.",
            ),
            _field(
                "note",
                "Note",
                type="textarea",
                rows=3,
                maxlength=4000,
                help="Required when you return it.",
            ),
        ],
        submit="Save decision",
    )


@require_page_permission("ia_lending_evidence")
@require_POST
def use_verify(request, allocation_id):
    fallback = _tab_url(USE)
    try:
        li.verify_purpose_use(allocation_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Loan use decision saved.")
    return _back(request, fallback)


@require_page_permission("ia_lending_evidence")
@require_http_methods(["GET"])
def enrolment_drawer(request, snapshot_id):
    s = enrolment_queue(request.user).filter(id=snapshot_id).first()
    if s is None:
        return _not_found(request, "Verify enrolment")
    facts = [
        {"label": "School", "value": f"{s.loan.school.name} · {s.loan.mfi.name}"},
        {
            "label": "Snapshot",
            "value": f"{s.get_kind_display()} as of {_day(s.as_of_date)}",
        },
        {"label": "Learners reported", "value": s.learner_count},
        {"label": "School record", "value": s.loan.school.enrollment},
        {"label": "Cohort", "value": s.cohort_definition},
        {"label": "Evidence", "value": s.evidence_reference},
    ]
    if not _may_validate(request):
        return _drawer(
            request,
            title="Enrolment snapshot",
            subtitle="Lending evidence",
            facts=facts,
            empty="Impact Assessment verifies enrolment evidence.",
        )
    return _drawer(
        request,
        title="Verify enrolment",
        subtitle="Lending evidence",
        action=f"{PAGE_URL}enrolment/{s.id}/verify",
        facts=facts,
        fields=[
            _field(
                "decision",
                "Decision",
                type="select",
                required=True,
                options=(
                    ("verified", "Verify"),
                    ("returned", "Return to the lending partner"),
                ),
                value="verified",
            ),
            _field(
                "note",
                "Note",
                type="textarea",
                rows=3,
                maxlength=4000,
                help="Required when you return it.",
            ),
        ],
        submit="Save decision",
    )


@require_page_permission("ia_lending_evidence")
@require_POST
def enrolment_verify(request, snapshot_id):
    fallback = _tab_url(ENROLMENT)
    try:
        li.verify_enrolment_snapshot(snapshot_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Enrolment decision saved.")
    return _back(request, fallback)


@require_page_permission("ia_lending_evidence")
@require_http_methods(["GET"])
def output_drawer(request, output_id):
    o = output_queue(request.user).filter(id=output_id).first()
    if o is None:
        return _not_found(request, "Verify purpose output")
    facts = [
        {"label": "School", "value": o.allocation.loan.school.name},
        {"label": "Purpose", "value": o.allocation.purpose.label},
        {"label": "Output", "value": f"{o.asset_type} ({o.unit})"},
        {
            "label": "Planned · reported · operational",
            "value": f"{o.planned_quantity} · {o.reported_quantity} · {o.reported_operational_quantity}",
        },
        {"label": "Reported state", "value": o.reported_completion_state},
        {"label": "Evidence", "value": o.evidence_reference},
    ]
    if not _may_validate(request):
        return _drawer(
            request,
            title="Purpose output",
            subtitle="Lending evidence",
            facts=facts,
            empty="Impact Assessment verifies purpose outputs.",
        )
    return _drawer(
        request,
        title="Verify purpose output",
        subtitle="Lending evidence",
        action=f"{PAGE_URL}outputs/{o.id}/verify",
        facts=facts,
        fields=[
            _field(
                "verifiedQuantity",
                "Verified quantity",
                type="number",
                required=True,
                min=0,
                value=o.reported_quantity,
            ),
            _field(
                "verifiedOperationalQuantity",
                "Verified operational quantity",
                type="number",
                min=0,
                value=o.reported_operational_quantity or 0,
            ),
            _field(
                "completionState",
                "Verified state",
                maxlength=64,
                placeholder="for example: installed and in use",
            ),
        ],
        submit="Verify output",
    )


@require_page_permission("ia_lending_evidence")
@require_POST
def output_verify(request, output_id):
    fallback = _tab_url(OUTPUTS)
    try:
        li.verify_asset_output(output_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Purpose output verified.")
    return _back(request, fallback)


@require_page_permission("ia_lending_evidence")
@require_http_methods(["GET"])
def teacher_drawer(request, beneficiary_id):
    t = teacher_queue(request.user).filter(id=beneficiary_id).first()
    if t is None:
        return _not_found(request, "Verify teacher completion")
    facts = [
        {"label": "School", "value": t.loan.school.name},
        {"label": "Teacher reference", "value": t.anonymized_reference},
        {"label": "Programme", "value": f"{t.programme} · {t.institution}"},
        {"label": "Completed", "value": _day(t.completed_on)},
        {"label": "Evidence", "value": t.evidence_reference},
    ]
    if not _may_validate(request):
        return _drawer(
            request,
            title="Teacher completion",
            subtitle="Lending evidence",
            facts=facts,
            empty="Impact Assessment verifies teacher completion.",
        )
    return _drawer(
        request,
        title="Verify teacher completion",
        subtitle="Lending evidence",
        action=f"{PAGE_URL}teachers/{t.id}/verify",
        facts=facts,
        fields=[_field("note", "Note", type="textarea", rows=3, maxlength=4000)],
        submit="Verify completion",
        note="Check the certificate reference before verifying.",
    )


@require_page_permission("ia_lending_evidence")
@require_POST
def teacher_verify(request, beneficiary_id):
    fallback = _tab_url(TEACHERS)
    try:
        li.verify_teacher_completion(beneficiary_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Teacher completion verified.")
    return _back(request, fallback)


# ── Conclusion drawers ──────────────────────────────────────────────────────


def _visible_conclusion(request, assessment_id):
    return (
        LoanImpactAssessment.objects.filter(
            id=assessment_id, loan_id__in=_loan_ids(request.user)
        )
        .select_related("loan__school__region", "loan__mfi", "loan__purpose")
        .first()
    )


def _conclusion_facts(a) -> list[dict]:
    facts = [
        {"label": "School", "value": f"{a.loan.school.name} · {a.loan.mfi.name}"},
        {
            "label": "Purpose",
            "value": a.loan.purpose.label if a.loan.purpose_id else "",
        },
        {"label": "Due", "value": _day(a.due_date)},
        {"label": "State", "value": STATE_LABELS[conclusion_state(a)]},
    ]
    if conclusion_state(a) != TO_PREPARE:
        facts += [
            {"label": "Classification", "value": a.get_classification_display()},
            {"label": "Narrative", "value": a.narrative},
            {"label": "Limitations", "value": a.limitations},
            {
                "label": "Evidence references",
                "value": "\n".join(a.evidence_references or []),
            },
            {
                "label": "Baseline → follow-up learners",
                "value": f"{(a.baseline_indicators or {}).get('learnerCount', '—')} → "
                f"{(a.follow_up_indicators or {}).get('learnerCount', '—')}",
            },
        ]
    if a.ia_note:
        facts.append({"label": "Verifier's note", "value": a.ia_note})
    return facts


def _prepare_fields(a) -> list[dict]:
    labels = dict(LoanImpactStatus.choices)
    prepared = conclusion_state(a) != TO_PREPARE
    return [
        _field(
            "classification",
            "Classification",
            type="select",
            required=True,
            blank="Choose",
            options=[(c.value, labels[c.value]) for c in li.CONCLUSION_CLASSIFICATIONS],
            value=a.classification if prepared else "",
        ),
        _field(
            "narrative",
            "What the verified evidence shows",
            type="textarea",
            required=True,
            rows=4,
            maxlength=4000,
            value=a.narrative if prepared else "",
            help="Observed after financing; do not claim the loan caused it.",
        ),
        _field(
            "limitations",
            "Limitations",
            type="textarea",
            required=True,
            rows=3,
            maxlength=4000,
            value=a.limitations if prepared else "",
        ),
        _field(
            "evidenceReferences",
            "Evidence references",
            type="textarea",
            required=True,
            rows=3,
            value="\n".join(a.evidence_references or []) if prepared else "",
            help="One per line: site visit, register, invoice or report references.",
        ),
    ]


@require_page_permission("business_transformation_reports")
@require_http_methods(["GET"])
def conclusion_drawer(request, assessment_id):
    a = _visible_conclusion(request, assessment_id)
    if a is None:
        return _not_found(request, "Loan impact conclusion")
    state = conclusion_state(a)
    subtitle = f"{a.loan.school.name} · {STATE_LABELS[state]}"
    facts = _conclusion_facts(a)
    basis = (
        li.loan_impact_verifier_basis(request.user, a) if state == AWAITING else None
    )
    if basis:
        return _drawer(
            request,
            title="Verify loan impact conclusion",
            subtitle=subtitle,
            action=f"{PAGE_URL}conclusions/{a.id}/verify",
            facts=facts,
            fields=[
                _field(
                    "decision",
                    "Decision",
                    type="select",
                    required=True,
                    options=(
                        ("verified", "Verify and publish the classification"),
                        ("returned", "Return to the preparer"),
                    ),
                    value="verified",
                ),
                _field(
                    "note",
                    "Note",
                    type="textarea",
                    rows=3,
                    maxlength=4000,
                    help="Required when you return it.",
                ),
            ],
            submit="Save decision",
            note=(
                "The Country Director acknowledges here only because this country has no "
                "second Impact Assessment officer."
                if basis == "cd_fallback"
                else "Check the classification against the verified evidence before publishing."
            ),
        )
    due = a.due_date <= timezone.localdate()
    mine = str(a.prepared_by or "") == str(request.user.id)
    may_prepare = due and li.may_prepare_loan_impact(request.user, a)
    if may_prepare and (
        state in (TO_PREPARE, RETURNED) or (state == AWAITING and mine)
    ):
        return _drawer(
            request,
            title="Prepare loan impact conclusion",
            subtitle=subtitle,
            action=f"{PAGE_URL}conclusions/{a.id}/prepare",
            facts=facts[:4] + [f for f in facts if f["label"] == "Verifier's note"],
            fields=_prepare_fields(a),
            submit="Send for verification",
            note="Someone other than you verifies it before the classification is published.",
            note_tone="warning" if state == RETURNED else "info",
        )
    note = "Read only."
    if state == AWAITING and a.prepared_by == str(request.user.id):
        note = "You prepared this, so someone else verifies it."
    elif (
        state == TO_PREPARE
        and request.user.active_role == EdifyRole.IMPACT_ASSESSMENT.value
    ):
        note = "Business Transformation prepares conclusions in this country; you verify them."
    elif state == TO_PREPARE and not due:
        note = "Not due yet."
    return _drawer(
        request,
        title="Loan impact conclusion",
        subtitle=subtitle,
        facts=facts,
        empty=note,
    )


@require_page_permission("business_transformation_reports")
@require_POST
def conclusion_prepare(request, assessment_id):
    fallback = (
        _tab_url(CONCLUSIONS)
        if request.user.active_role
        in (
            EdifyRole.IMPACT_ASSESSMENT.value,
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.ADMIN.value,
        )
        else "/business-transformation/impact-reports"
    )
    try:
        li.prepare_loan_impact(assessment_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(request, "Conclusion prepared and sent for verification.")
    return _back(request, fallback)


@require_page_permission("ia_lending_evidence")
@require_POST
def conclusion_verify(request, assessment_id):
    fallback = _tab_url(CONCLUSIONS)
    decision = request.POST.get("decision") or "verified"
    try:
        li.verify_loan_impact(assessment_id, request.POST.dict(), request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, fallback)
    messages.success(
        request,
        "Conclusion verified and published."
        if decision == "verified"
        else "Conclusion returned to its preparer.",
    )
    return _back(request, fallback)
