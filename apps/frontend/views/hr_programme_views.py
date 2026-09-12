"""Actions for the Regional HR Director's programmes (2026-09-13).

The HR programme pages were read-only registers: every workflow behind them
(open and advance an employee-relations case, request and approve a vacancy,
record and advance a candidate, hire, close onboarding, decide probation,
close an offboarding) existed as a tested service that no screen called. This
module gives each one a drawer and a POST handler, and nothing else: rules,
permissions and audit rows stay in the services, so a refusal the service
raises is the message the director reads.

Every drawer renders `partials/hr/form_drawer.html`; every POST redirects back
to the register it came from with a message.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission

SERVICE_ERRORS = (BadRequest, ConflictError, Forbidden, NotFoundError)


# ── Shared helpers ───────────────────────────────────────────────────────────
def _field(
    name,
    label,
    *,
    type="text",
    required=False,
    value="",
    options=None,
    blank=None,
    help="",
    placeholder="",
    maxlength=None,
    rows=None,
    min=None,
    step=None,
):
    return {
        "name": name,
        "label": label,
        "type": type,
        "required": required,
        "value": value,
        "options": list(options or []),
        "blank": blank,
        "help": help,
        "placeholder": placeholder,
        "maxlength": maxlength,
        "rows": rows,
        "min": min,
        "step": step,
    }


def _drawer(
    request,
    *,
    title,
    subtitle,
    action=None,
    fields=(),
    submit="Save",
    facts=(),
    note="",
    note_tone="info",
    next_url="",
    empty="",
):
    return render(
        request,
        "partials/hr/form_drawer.html",
        {
            "form_title": title,
            "form_subtitle": subtitle,
            "form_action": action,
            "form_fields": list(fields),
            "form_submit": submit,
            "form_facts": list(facts),
            "form_note": note,
            "form_note_tone": note_tone,
            "form_next": next_url or request.META.get("HTTP_HX_CURRENT_URL", ""),
            "form_empty": empty,
        },
    )


def _back(request, fallback: str):
    """Return to the page the drawer was opened from, never off-site."""
    target = (request.POST.get("next") or "").strip()
    if target:
        from urllib.parse import urlparse

        parsed = urlparse(target)
        if parsed.path.startswith("/") and not parsed.netloc.strip():
            query = f"?{parsed.query}" if parsed.query else ""
            return redirect(parsed.path + query)
        if parsed.netloc == request.get_host():
            query = f"?{parsed.query}" if parsed.query else ""
            return redirect(parsed.path + query)
    return redirect(fallback)


def _refused(request, exc, fallback):
    messages.error(request, str(getattr(exc, "detail", exc)))
    return _back(request, fallback)


def _people_options(request, *, include_blank_note=None):
    """Staff in the viewer's reach, as (id, "Name · Country") options."""
    from apps.accounts.models import StaffProfile
    from apps.hr.reach import people_reach, scope_profiles

    profiles = (
        scope_profiles(
            StaffProfile.objects.select_related("user").filter(
                user__deleted_at__isnull=True
            ),
            people_reach(request.user),
        )
        .exclude(onboarding_state="exited")
        .order_by("user__name")
    )
    return [
        (p.id, f"{p.user.name} · {p.country}" if p.country else p.user.name)
        for p in profiles[:500]
    ]


def _user_options(request):
    """HR colleagues who can be named investigator, in the viewer's reach."""
    from apps.accounts.models import User
    from apps.hr.reach import people_reach, scope_users

    users = scope_users(
        User.objects.filter(
            deleted_at__isnull=True,
            is_active=True,
            roles__overlap=["HumanResources", "CountryDirector", "Admin"],
        ),
        people_reach(request.user),
    ).order_by("name")
    return [(u.id, u.name) for u in users[:200]]


def _country_options(request):
    from apps.hr.reach import people_reach

    return [(c, c) for c in people_reach(request.user).filter_options()]


def _date(value):
    from datetime import date

    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise BadRequest("Dates use the format YYYY-MM-DD.") from exc


# ── Employee relations ───────────────────────────────────────────────────────
ER_PATH = "/employee-relations"


@require_page_permission("employee_relations")
@require_http_methods(["GET"])
def er_open_drawer(request):
    from apps.hr.models import ERCaseType, ERSeverity

    people = _people_options(request)
    return _drawer(
        request,
        title="Open a case",
        subtitle="Disciplinary matters, grievances, disputes and investigations",
        action="/employee-relations/open",
        submit="Open case",
        note=(
            "Cases are confidential by default: only the case owner and the "
            "investigator see a confidential case's details. Opening one is "
            "recorded in the HR audit log."
        ),
        fields=[
            _field(
                "case_type",
                "Case type",
                type="select",
                required=True,
                options=ERCaseType.choices,
                blank="Choose a case type",
            ),
            _field(
                "subject_staff_id",
                "Employee the case concerns",
                type="select",
                options=people,
                blank="No named individual (e.g. a whistleblowing report)",
            ),
            _field(
                "complainant_staff_id",
                "Complainant or other party",
                type="select",
                options=people,
                blank="None recorded",
                help="Required for a dispute between staff.",
            ),
            _field(
                "severity",
                "Severity",
                type="select",
                required=True,
                options=ERSeverity.choices,
                value=ERSeverity.MEDIUM,
            ),
            _field(
                "country",
                "Country",
                type="select",
                options=_country_options(request),
                blank="The employee's country",
            ),
            _field("hearing_date", "Hearing or meeting date", type="date"),
            _field(
                "description",
                "What has been reported",
                type="textarea",
                required=True,
                maxlength=5000,
                placeholder="Facts as reported, dates, and who raised it",
            ),
            _field(
                "is_confidential",
                "Keep this case confidential",
                type="checkbox",
                value=True,
            ),
        ],
    )


@require_page_permission("employee_relations")
@require_POST
def er_open(request):
    from apps.hr.employee_relations_service import open_case

    data = request.POST
    try:
        case = open_case(
            {
                "case_type": data.get("case_type"),
                "subject_staff_id": data.get("subject_staff_id"),
                "complainant_staff_id": data.get("complainant_staff_id"),
                "severity": data.get("severity"),
                "country": data.get("country"),
                "hearing_date": _date(data.get("hearing_date")),
                "description": data.get("description"),
                "is_confidential": bool(data.get("is_confidential")),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, ER_PATH)
    messages.success(
        request, f"{case.get_case_type_display()} case opened and awaiting triage."
    )
    return _back(request, ER_PATH)


def _visible_case(request, case_id):
    from apps.hr.employee_relations_service import visible_cases

    case = (
        visible_cases(request.user)
        .select_related("complainant_staff__user")
        .filter(id=case_id)
        .first()
    )
    if case is None:
        raise Http404("Case not found.")
    return case


@require_page_permission("employee_relations")
@require_http_methods(["GET"])
def er_case_drawer(request, case_id):
    from apps.hr import employee_relations_service as er
    from apps.hr.models import DisciplinarySanction, ERCaseStatus, ERCaseType

    case = _visible_case(request, case_id)
    er.record_access(request.user, what="case_detail", case_id=case.id)
    transitions = er.allowed_transitions(case)
    facts = [
        {"label": "Case type", "value": case.get_case_type_display()},
        {
            "label": "Concerns",
            "value": case.subject_staff.user.name
            if case.subject_staff
            else "No named individual",
        },
        {
            "label": "Complainant",
            "value": case.complainant_staff.user.name if case.complainant_staff else "",
        },
        {"label": "Country", "value": case.country},
        {"label": "Severity", "value": case.get_severity_display()},
        {"label": "Status", "value": case.get_status_display()},
        {
            "label": "Case owner",
            "value": case.case_owner.name if case.case_owner else "",
        },
        {
            "label": "Investigator",
            "value": case.investigator.name if case.investigator else "",
        },
        {
            "label": "Opened",
            "value": case.opened_at.date().isoformat() if case.opened_at else "",
        },
        {
            "label": "Hearing date",
            "value": case.hearing_date.isoformat() if case.hearing_date else "",
        },
        {"label": "Reported", "value": case.description},
        {"label": "Findings", "value": case.findings or ""},
        {"label": "Action taken", "value": case.action_taken or ""},
        {
            "label": "Sanction",
            "value": case.get_sanction_display() if case.sanction else "",
        },
        {"label": "Appeal", "value": case.appeal_note or ""},
    ]
    if not transitions:
        return _drawer(
            request,
            title=f"{case.get_case_type_display()} case",
            subtitle=f"{case.country} · {case.get_status_display()}",
            facts=facts,
            empty="This case is closed. Its record is kept for the retention period.",
        )
    fields = [
        _field(
            "to_status",
            "Move the case to",
            type="select",
            required=True,
            options=transitions,
        ),
    ]
    if any(value == ERCaseStatus.INVESTIGATION for value, _ in transitions):
        fields.append(
            _field(
                "investigator_id",
                "Investigator",
                type="select",
                options=_user_options(request),
                blank="Name the investigator",
                help="Required when an investigation starts.",
            )
        )
    fields.append(
        _field(
            "note",
            "Findings, action taken or appeal note",
            type="textarea",
            maxlength=5000,
            help="Required when recording findings or the action decided.",
        )
    )
    if case.case_type == ERCaseType.DISCIPLINARY and any(
        value == ERCaseStatus.ACTION for value, _ in transitions
    ):
        fields.append(
            _field(
                "sanction",
                "Sanction decided",
                type="select",
                options=DisciplinarySanction.choices,
                blank="Choose the sanction",
            )
        )
    fields.append(_field("hearing_date", "Hearing or meeting date", type="date"))
    return _drawer(
        request,
        title=f"{case.get_case_type_display()} case",
        subtitle=f"{case.country} · {case.get_status_display()}",
        action=f"/employee-relations/{case.id}/advance",
        submit="Record next step",
        facts=facts,
        fields=fields,
    )


@require_page_permission("employee_relations")
@require_POST
def er_advance(request, case_id):
    from apps.hr.employee_relations_service import advance_case

    case = _visible_case(request, case_id)
    data = request.POST
    try:
        case = advance_case(
            case.id,
            request.user,
            to_status=data.get("to_status") or "",
            note=data.get("note") or "",
            investigator_id=data.get("investigator_id") or None,
            sanction=data.get("sanction") or "",
            hearing_date=_date(data.get("hearing_date")),
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, ER_PATH)
    messages.success(request, f"Case moved to {case.get_status_display().lower()}.")
    return _back(request, ER_PATH)


# ── Recruitment: vacancies ───────────────────────────────────────────────────
RECRUITMENT_PATH = "/recruitment"
PIPELINE_PATH = "/candidate-pipeline"


def _visible_vacancy(request, vacancy_id):
    from apps.hr.models import Vacancy
    from apps.hr.reach import people_reach, scope_by_country

    vacancy = (
        scope_by_country(Vacancy.objects.all(), people_reach(request.user))
        .filter(id=vacancy_id)
        .first()
    )
    if vacancy is None:
        raise Http404("Vacancy not found.")
    return vacancy


@require_page_permission("recruitment")
@require_http_methods(["GET"])
def vacancy_request_drawer(request):
    return _drawer(
        request,
        title="Request a vacancy",
        subtitle="A staffing need for growth, or a replacement after someone leaves",
        action="/recruitment/request",
        submit="Submit for approval",
        note=(
            "A vacancy opens for applications once a Country Director or the "
            "Regional Vice President approves it. Whoever requests it cannot "
            "approve it."
        ),
        fields=[
            _field(
                "country",
                "Country",
                type="select",
                required=True,
                options=_country_options(request),
                blank="Choose the country",
            ),
            _field(
                "role", "Role", required=True, maxlength=64, placeholder="e.g. CCEO"
            ),
            _field(
                "department", "Department", maxlength=64, placeholder="e.g. Programmes"
            ),
            _field(
                "replacement_or_new_role",
                "Replacement or new role",
                type="select",
                required=True,
                options=[("replacement", "Replacement"), ("new_role", "New role")],
                value="replacement",
            ),
            _field(
                "employment_type",
                "Employment type",
                type="select",
                options=[
                    ("Full-time", "Full-time"),
                    ("Part-time", "Part-time"),
                    ("Fixed-term contract", "Fixed-term contract"),
                    ("Consultant", "Consultant"),
                ],
                value="Full-time",
            ),
            _field("target_start_date", "Target start date", type="date"),
            _field("salary_band", "Approved salary band", maxlength=64),
            _field("budget_source", "Budget source", maxlength=128),
            _field(
                "reason",
                "Why the post is needed",
                type="textarea",
                maxlength=2000,
                placeholder="Growth, turnover, a new country programme…",
            ),
            _field("required_skills", "Required skills", type="textarea", rows=3),
        ],
    )


@require_page_permission("recruitment")
@require_POST
def vacancy_request(request):
    from apps.hr.recruitment_service import request_vacancy

    data = request.POST
    try:
        vacancy = request_vacancy(
            {
                "country": data.get("country"),
                "role": data.get("role"),
                "department": data.get("department"),
                "replacement_or_new_role": data.get("replacement_or_new_role"),
                "employment_type": data.get("employment_type"),
                "target_start_date": _date(data.get("target_start_date")),
                "salary_band": data.get("salary_band"),
                "budget_source": data.get("budget_source"),
                "reason": data.get("reason"),
                "required_skills": data.get("required_skills"),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECRUITMENT_PATH)
    messages.success(request, f"{vacancy.role} vacancy submitted for approval.")
    return _back(request, RECRUITMENT_PATH)


@require_page_permission("recruitment")
@require_http_methods(["GET"])
def vacancy_drawer(request, vacancy_id):
    from apps.hr.models import VacancyStatus

    vacancy = _visible_vacancy(request, vacancy_id)
    facts = [
        {"label": "Role", "value": vacancy.role},
        {"label": "Department", "value": vacancy.department},
        {"label": "Country", "value": vacancy.country},
        {"label": "Type", "value": vacancy.get_replacement_or_new_role_display()},
        {"label": "Employment", "value": vacancy.employment_type},
        {
            "label": "Target start",
            "value": vacancy.target_start_date.isoformat()
            if vacancy.target_start_date
            else "",
        },
        {"label": "Salary band", "value": vacancy.approved_salary_band or ""},
        {"label": "Why it is needed", "value": vacancy.reason_for_vacancy or ""},
        {"label": "Status", "value": vacancy.get_status_display()},
    ]
    choices = []
    if vacancy.status == VacancyStatus.PENDING_APPROVAL:
        choices.append(("approve", "Approve and open for applications"))
    if vacancy.status in (VacancyStatus.PENDING_APPROVAL, VacancyStatus.OPEN):
        choices.append(("close", "Close the vacancy"))
    if not choices:
        return _drawer(
            request,
            title=f"{vacancy.role} vacancy",
            subtitle=f"{vacancy.country} · {vacancy.get_status_display()}",
            facts=facts,
            empty="This vacancy is no longer open.",
        )
    return _drawer(
        request,
        title=f"{vacancy.role} vacancy",
        subtitle=f"{vacancy.country} · {vacancy.get_status_display()}",
        action=f"/recruitment/{vacancy.id}/decide",
        submit="Record decision",
        facts=facts,
        fields=[
            _field(
                "decision", "Decision", type="select", required=True, options=choices
            ),
            _field("reason", "Reason", type="textarea", rows=3, maxlength=2000),
        ],
    )


@require_page_permission("recruitment")
@require_POST
def vacancy_decide(request, vacancy_id):
    from apps.hr.recruitment_service import approve_vacancy, close_vacancy

    vacancy = _visible_vacancy(request, vacancy_id)
    decision = request.POST.get("decision")
    reason = request.POST.get("reason") or ""
    try:
        if decision == "approve":
            vacancy = approve_vacancy(vacancy.id, request.user, reason=reason)
            messages.success(request, f"{vacancy.role} vacancy approved and open.")
        elif decision == "close":
            vacancy = close_vacancy(vacancy.id, request.user, reason=reason)
            messages.success(request, f"{vacancy.role} vacancy closed.")
        else:
            raise BadRequest("Choose a decision.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECRUITMENT_PATH)
    return _back(request, RECRUITMENT_PATH)


# ── Recruitment: candidates ──────────────────────────────────────────────────
@require_page_permission("candidate_pipeline")
@require_http_methods(["GET"])
def application_record_drawer(request):
    from apps.hr.models import Vacancy, VacancyStatus
    from apps.hr.reach import people_reach, scope_by_country

    vacancies = scope_by_country(
        Vacancy.objects.filter(status=VacancyStatus.OPEN), people_reach(request.user)
    ).order_by("country", "role")
    options = [(v.id, f"{v.role} · {v.country}") for v in vacancies[:200]]
    return _drawer(
        request,
        title="Record a candidate",
        subtitle="An application against an open vacancy",
        action="/candidate-pipeline/record",
        submit="Record application",
        empty="" if options else "There is no open vacancy to apply to.",
        fields=[
            _field(
                "vacancy_id",
                "Vacancy",
                type="select",
                required=True,
                options=options,
                blank="Choose an open vacancy",
            ),
            _field("name", "Candidate name", required=True, maxlength=255),
            _field("email", "Email", type="email", required=True, maxlength=254),
            _field("phone", "Phone", maxlength=64),
            _field("skills", "Skills and experience", type="textarea", rows=3),
            _field(
                "consent",
                "The candidate consented to Edify holding their details",
                type="checkbox",
                help="Applicant data belongs to someone who does not work here yet.",
            ),
        ]
        if options
        else [],
    )


@require_page_permission("candidate_pipeline")
@require_POST
def application_record(request):
    from apps.hr.recruitment_service import record_application

    data = request.POST
    try:
        application = record_application(
            {
                "vacancy_id": data.get("vacancy_id"),
                "name": data.get("name"),
                "email": data.get("email"),
                "phone": data.get("phone"),
                "skills": data.get("skills"),
                "consent": bool(data.get("consent")),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PIPELINE_PATH)
    messages.success(request, f"{application.candidate.name} recorded as applied.")
    return _back(request, PIPELINE_PATH)


def _visible_application(request, application_id):
    from apps.hr.models import Application
    from apps.hr.reach import people_reach, scope_by_country

    application = (
        scope_by_country(
            Application.objects.select_related("candidate", "vacancy"),
            people_reach(request.user),
            "vacancy__country",
        )
        .filter(id=application_id)
        .first()
    )
    if application is None:
        raise Http404("Application not found.")
    return application


@require_page_permission("candidate_pipeline")
@require_http_methods(["GET"])
def application_drawer(request, application_id):
    from apps.core.rbac import EdifyRole
    from apps.hr.models import ApplicationStage
    from apps.hr.recruitment_service import _STAGE_FLOW

    application = _visible_application(request, application_id)
    labels = dict(ApplicationStage.choices)
    next_stages = [
        (stage, labels[stage])
        for stage in ApplicationStage.values
        if stage in _STAGE_FLOW.get(application.stage, set())
        and stage != ApplicationStage.HIRED
    ]
    facts = [
        {"label": "Candidate", "value": application.candidate.name},
        {"label": "Email", "value": application.candidate.email},
        {
            "label": "Vacancy",
            "value": f"{application.vacancy.role} · {application.vacancy.country}",
        },
        {"label": "Stage", "value": application.get_stage_display()},
        {"label": "Interview panel", "value": application.interview_panel or ""},
        {"label": "Assessment", "value": application.assessment_result or ""},
        {"label": "References", "value": application.reference_check_note or ""},
        {"label": "Last decision", "value": application.decision_reason or ""},
    ]
    if application.stage == ApplicationStage.ACCEPTED:
        roles = [(r.value, r.value) for r in EdifyRole if r is not EdifyRole.ADMIN]
        return _drawer(
            request,
            title=f"Hire {application.candidate.name}",
            subtitle=f"{application.vacancy.role} · {application.vacancy.country}",
            action=f"/candidate-pipeline/{application.id}/hire",
            submit="Hire and invite",
            facts=facts,
            note=(
                "Hiring creates the employee's account from the candidate's "
                "details, sends them an invitation to set their own password, "
                "and opens their onboarding plan."
            ),
            fields=[
                _field(
                    "role",
                    "Platform role",
                    type="select",
                    required=True,
                    options=roles,
                    value=application.vacancy.role
                    if application.vacancy.role in dict(roles)
                    else "CCEO",
                ),
                _field(
                    "supervisor_staff_id",
                    "Reports to",
                    type="select",
                    options=_people_options(request),
                    blank="Assign later",
                ),
            ],
        )
    if not next_stages:
        return _drawer(
            request,
            title=application.candidate.name,
            subtitle=f"{application.vacancy.role} · {application.get_stage_display()}",
            facts=facts,
            empty="This application has reached the end of the pipeline.",
        )
    return _drawer(
        request,
        title=application.candidate.name,
        subtitle=f"{application.vacancy.role} · {application.get_stage_display()}",
        action=f"/candidate-pipeline/{application.id}/advance",
        submit="Move application",
        facts=facts,
        fields=[
            _field(
                "to_stage", "Move to", type="select", required=True, options=next_stages
            ),
            _field(
                "reason",
                "Reason",
                type="textarea",
                rows=3,
                help="Required to reject a candidate or make an offer.",
            ),
            _field("interview_panel", "Interview panel", maxlength=500),
            _field("assessment_result", "Assessment result", type="textarea", rows=2),
            _field(
                "reference_check_note", "Reference check note", type="textarea", rows=2
            ),
        ],
    )


@require_page_permission("candidate_pipeline")
@require_POST
def application_advance(request, application_id):
    from apps.hr.recruitment_service import advance_application

    application = _visible_application(request, application_id)
    data = request.POST
    try:
        application = advance_application(
            application.id,
            request.user,
            to_stage=data.get("to_stage") or "",
            reason=data.get("reason") or "",
            interview_panel=data.get("interview_panel") or "",
            assessment_result=data.get("assessment_result") or "",
            reference_check_note=data.get("reference_check_note") or "",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PIPELINE_PATH)
    messages.success(
        request,
        f"{application.candidate.name} moved to {application.get_stage_display().lower()}.",
    )
    return _back(request, PIPELINE_PATH)


@require_page_permission("candidate_pipeline")
@require_POST
def application_hire(request, application_id):
    from apps.hr.recruitment_service import hire

    application = _visible_application(request, application_id)
    try:
        hire(
            application.id,
            request.user,
            provisioning={
                "role": request.POST.get("role"),
                "supervisorStaffId": request.POST.get("supervisor_staff_id") or "",
            },
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PIPELINE_PATH)
    messages.success(
        request,
        f"{application.candidate.name} hired: their invitation is sent and "
        "onboarding has started.",
    )
    return _back(request, "/onboarding")


# ── Onboarding and probation ─────────────────────────────────────────────────
ONBOARDING_PATH = "/onboarding"


def _visible_plan(request, plan_id):
    from apps.hr.models import OnboardingPlan
    from apps.hr.reach import people_reach, scope_by_staff

    plan = (
        scope_by_staff(
            OnboardingPlan.objects.select_related("staff__user"),
            people_reach(request.user),
        )
        .filter(id=plan_id)
        .first()
    )
    if plan is None:
        raise Http404("Onboarding plan not found.")
    return plan


def _open_probation(plan):
    from apps.hr.models import PerformanceReview, ReviewStage, ReviewType

    return (
        PerformanceReview.objects.filter(
            staff=plan.staff, review_type=ReviewType.PROBATION
        )
        .exclude(stage=ReviewStage.CLOSED)
        .order_by("due_date")
        .first()
    )


@require_page_permission("onboarding")
@require_http_methods(["GET"])
def onboarding_drawer(request, plan_id):
    from apps.hr.models import OnboardingStatus, ProbationDecision

    plan = _visible_plan(request, plan_id)
    tasks = list(plan.tasks.order_by("due_date", "name"))
    facts = [
        {"label": "Employee", "value": plan.staff.user.name},
        {"label": "Country", "value": plan.staff.country},
        {
            "label": "Start date",
            "value": plan.start_date.isoformat() if plan.start_date else "",
        },
        {"label": "Status", "value": plan.get_status_display()},
        {
            "label": "Checklist",
            "value": "\n".join(
                f"{'Done' if t.is_completed else 'Open'} · {t.name}"
                + (f" (due {t.due_date.isoformat()})" if t.due_date else "")
                for t in tasks
            ),
        },
    ]
    probation = _open_probation(plan)
    actions = []
    open_tasks = [t for t in tasks if not t.is_completed]
    if open_tasks:
        actions.append(("complete_tasks", "Mark checklist items done"))
    if plan.status not in (OnboardingStatus.CLOSED,):
        actions.append(("confirm_readiness", "Confirm the employee is ready"))
        actions.append(("close", "Close onboarding and activate"))
    if probation:
        actions.append(("probation", "Decide probation"))
    if not actions:
        return _drawer(
            request,
            title=f"Onboarding · {plan.staff.user.name}",
            subtitle=plan.get_status_display(),
            facts=facts,
            empty="This onboarding is closed.",
        )
    fields = [
        _field(
            "action", "What to record", type="select", required=True, options=actions
        )
    ]
    fields += [
        _field(f"task_{task.id}", task.name, type="checkbox", help=task.category)
        for task in open_tasks
    ]
    if probation:
        fields += [
            _field(
                "decision",
                "Probation decision",
                type="select",
                options=ProbationDecision.choices,
                blank="Only for a probation decision",
            ),
            _field("extend_days", "Extend by (days)", type="number", min=0, step=1),
        ]
    fields += [
        _field(
            "reason",
            "Reason or note",
            type="textarea",
            rows=3,
            help="Required for a probation decision.",
        ),
        _field(
            "force",
            "Close even though checklist items are still open",
            type="checkbox",
        ),
    ]
    return _drawer(
        request,
        title=f"Onboarding · {plan.staff.user.name}",
        subtitle=plan.get_status_display(),
        action=f"/onboarding/{plan.id}/record",
        submit="Record",
        facts=facts,
        fields=fields,
    )


@require_page_permission("onboarding")
@require_POST
def onboarding_record(request, plan_id):
    from apps.hr import onboarding_service

    plan = _visible_plan(request, plan_id)
    data = request.POST
    action = data.get("action")
    try:
        if action == "complete_tasks":
            done = 0
            for task in plan.tasks.filter(is_completed=False):
                if data.get(f"task_{task.id}"):
                    onboarding_service.complete_task(task.id, request.user)
                    done += 1
            if not done:
                raise BadRequest("Tick the checklist items that are done.")
            messages.success(
                request, f"{done} checklist item{'s' if done != 1 else ''} marked done."
            )
        elif action == "confirm_readiness":
            onboarding_service.confirm_readiness(plan.id, request.user)
            messages.success(request, "Readiness confirmed.")
        elif action == "close":
            onboarding_service.close_onboarding(
                plan.id, request.user, force=bool(data.get("force"))
            )
            messages.success(request, "Onboarding closed and the employee activated.")
        elif action == "probation":
            probation = _open_probation(plan)
            if probation is None:
                raise BadRequest("There is no open probation review for this employee.")
            extend = data.get("extend_days") or "0"
            onboarding_service.decide_probation(
                probation.id,
                request.user,
                decision=data.get("decision") or "",
                reason=data.get("reason") or "",
                extend_days=int(extend) if extend.isdigit() else 0,
            )
            messages.success(request, "Probation decision recorded.")
        else:
            raise BadRequest("Choose what to record.")
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, ONBOARDING_PATH)
    return _back(request, ONBOARDING_PATH)


# ── Offboarding ──────────────────────────────────────────────────────────────
OFFBOARDING_PATH = "/offboarding"


@require_page_permission("offboarding")
@require_http_methods(["GET"])
def offboarding_start_drawer(request):
    from apps.hr.models import ExitReason

    people = _people_options(request)
    return _drawer(
        request,
        title="Start an offboarding",
        subtitle="Record an exit, why it is happening, and who takes over the work",
        action="/offboarding/start",
        submit="Start offboarding",
        note=(
            "The account stays active until you close the offboarding, and it "
            "cannot close while schools, activities or direct reports still point "
            "at the person."
        ),
        fields=[
            _field(
                "staff_id",
                "Employee leaving",
                type="select",
                required=True,
                options=people,
                blank="Choose the employee",
            ),
            _field("last_working_day", "Last working day", type="date", required=True),
            _field(
                "exit_reason",
                "Reason for leaving",
                type="select",
                required=True,
                options=ExitReason.choices,
                blank="Choose a reason",
            ),
            _field(
                "handover_owner_id",
                "Handover owner",
                type="select",
                options=people,
                blank="Name later",
            ),
            _field(
                "note",
                "Exit note",
                type="textarea",
                rows=3,
                help="Exit interview themes and anything a replacement needs to know.",
            ),
        ],
    )


@require_page_permission("offboarding")
@require_POST
def offboarding_start(request):
    from apps.accounts.models import StaffProfile
    from apps.hr.offboarding_service import open_offboarding

    data = request.POST
    staff = StaffProfile.objects.filter(id=data.get("staff_id") or "").first()
    handover = StaffProfile.objects.filter(
        id=data.get("handover_owner_id") or ""
    ).first()
    try:
        plan = open_offboarding(
            staff,
            request.user,
            last_working_day=_date(data.get("last_working_day")),
            exit_reason=data.get("exit_reason") or "",
            handover_owner=handover,
            note=data.get("note") or "",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, OFFBOARDING_PATH)
    messages.success(request, f"Offboarding started for {plan.staff.user.name}.")
    return _back(request, OFFBOARDING_PATH)


def _visible_offboarding(request, plan_id):
    from apps.hr.models import OffboardingPlan
    from apps.hr.reach import people_reach, scope_by_staff

    plan = (
        scope_by_staff(
            OffboardingPlan.objects.select_related(
                "staff__user", "handover_owner__user"
            ),
            people_reach(request.user),
        )
        .filter(id=plan_id)
        .first()
    )
    if plan is None:
        raise Http404("Offboarding plan not found.")
    return plan


@require_page_permission("offboarding")
@require_http_methods(["GET"])
def offboarding_drawer(request, plan_id):
    from apps.hr.offboarding_service import outstanding_work

    plan = _visible_offboarding(request, plan_id)
    remaining = outstanding_work(plan.staff)
    facts = [
        {"label": "Employee", "value": plan.staff.user.name},
        {"label": "Country", "value": plan.staff.country},
        {
            "label": "Last working day",
            "value": plan.last_working_day.isoformat() if plan.last_working_day else "",
        },
        {
            "label": "Reason",
            "value": plan.get_exit_reason_display() if plan.exit_reason else "",
        },
        {
            "label": "Handover owner",
            "value": plan.handover_owner.user.name if plan.handover_owner else "",
        },
        {"label": "Exit note", "value": plan.exit_note},
        {
            "label": "Work still attached",
            "value": ", ".join(
                f"{count} {name.replace('_', ' ')}" for name, count in remaining.items()
            )
            or "None",
        },
        {"label": "Status", "value": plan.status},
    ]
    if plan.status == "Closed":
        return _drawer(
            request,
            title=f"Offboarding · {plan.staff.user.name}",
            subtitle="Closed",
            facts=facts,
            empty="This offboarding is closed and the account is disabled.",
        )
    return _drawer(
        request,
        title=f"Offboarding · {plan.staff.user.name}",
        subtitle=plan.status,
        action=f"/offboarding/{plan.id}/close",
        submit="Close offboarding",
        facts=facts,
        note=(
            "Closing disables the account and marks the employee as exited."
            + (
                " Work is still attached: reassign it first, or close anyway and "
                "the outstanding work is recorded in the audit log."
                if remaining
                else ""
            )
        ),
        note_tone="warning" if remaining else "info",
        fields=[
            _field(
                "force",
                "Close even though work is still attached",
                type="checkbox",
            )
        ]
        if remaining
        else [],
    )


@require_page_permission("offboarding")
@require_POST
def offboarding_close(request, plan_id):
    from apps.hr.offboarding_service import complete_offboarding

    plan = _visible_offboarding(request, plan_id)
    try:
        complete_offboarding(
            plan.id, request.user, force=bool(request.POST.get("force"))
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, OFFBOARDING_PATH)
    messages.success(request, f"Offboarding closed for {plan.staff.user.name}.")
    return _back(request, OFFBOARDING_PATH)
