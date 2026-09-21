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
from django.utils import timezone
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
    """Return to the page the drawer was opened from, never off-site.

    A path such as "/\\evil.example" parses with an empty netloc, yet browsers
    treat it as "//evil.example"; the rebuilt target is therefore checked
    again with Django's own same-site test before it is followed.
    """
    target = (request.POST.get("next") or "").strip()
    if target:
        from urllib.parse import urlparse

        from django.utils.http import url_has_allowed_host_and_scheme

        parsed = urlparse(target)
        same_site = (
            parsed.path.startswith("/") and not parsed.netloc.strip()
        ) or parsed.netloc == request.get_host()
        if same_site:
            query = f"?{parsed.query}" if parsed.query else ""
            candidate = parsed.path + query
            if not candidate.startswith(
                ("//", "/\\")
            ) and url_has_allowed_host_and_scheme(
                candidate,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(candidate)
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


def _is_hr_or_admin(request) -> bool:
    return getattr(request.user, "active_role", "") in ("HumanResources", "Admin")


def _reviewee_profiles(request):
    """The people this viewer reviews, never themself, still employed.

    A Programme Lead's People reach is their team AND their own record, and
    any supervision link — so their recovery-plan picker offered themself and
    people they do not review (Program Lead alignment, 2026-09-13). Outside
    HR a formal plan is the reviewer's recommendation, so the reviewer's
    people are the ones offered.
    """
    from apps.hr.review_authority import reviewees_of

    return (
        reviewees_of(request.user)
        .exclude(id=getattr(request.user, "staff_profile_id", None))
        .filter(deleted_at__isnull=True, user__deleted_at__isnull=True)
        .exclude(onboarding_state="exited")
        .order_by("user__name")
    )


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


# ── Compensation and benefits ────────────────────────────────────────────────
COMPENSATION_PATH = "/compensation-benefits"


def _staff_in_reach(request, staff_id):
    from apps.accounts.models import StaffProfile
    from apps.hr.reach import people_reach, scope_profiles

    staff = (
        scope_profiles(
            StaffProfile.objects.select_related("user"), people_reach(request.user)
        )
        .filter(id=staff_id)
        .first()
    )
    if staff is None:
        raise Http404("Employee not found.")
    return staff


def _compensation_fields(request, record=None, *, choose_staff=False):
    from apps.hr.models import CompensationStatus, MedicalCover

    def value(name, default=""):
        return getattr(record, name, default) if record is not None else default

    fields = []
    if choose_staff:
        fields.append(
            _field(
                "staff_id",
                "Employee",
                type="select",
                required=True,
                options=_people_options(request),
                blank="Choose the employee",
            )
        )
    fields += [
        _field(
            "salary_band", "Salary band", value=value("salary_band") or "", maxlength=64
        ),
        _field(
            "currency",
            "Currency",
            type="select",
            options=[(c, c) for c in ("UGX", "KES", "RWF", "TZS", "USD")],
            value=value("currency", "UGX"),
        ),
        _field(
            "base_salary",
            "Base salary (monthly)",
            type="number",
            min=0,
            step="1",
            value=value("base_salary", "") or "",
        ),
        _field(
            "allowances",
            "Allowances (monthly)",
            type="number",
            min=0,
            step="1",
            value=value("allowances", "") or "",
        ),
        _field(
            "medical_cover",
            "Medical cover",
            type="select",
            options=MedicalCover.choices,
            value=value("medical_cover", MedicalCover.NONE),
        ),
        _field(
            "pension_scheme",
            "Pension or social security scheme",
            value=value("pension_scheme") or "",
            placeholder="e.g. NSSF",
            maxlength=128,
        ),
        _field(
            "other_benefits",
            "Other benefits",
            type="textarea",
            rows=2,
            value=value("other_benefits") or "",
        ),
        _field(
            "effective_date",
            "Effective from",
            type="date",
            value=value("effective_date").isoformat()
            if value("effective_date")
            else "",
        ),
        _field(
            "next_review_date",
            "Next pay review",
            type="date",
            value=value("next_review_date").isoformat()
            if value("next_review_date")
            else "",
        ),
        _field(
            "status",
            "Status",
            type="select",
            options=CompensationStatus.choices,
            value=value("status", CompensationStatus.HR_REVIEW),
        ),
    ]
    return fields


@require_page_permission("compensation_benefits")
@require_http_methods(["GET"])
def compensation_new_drawer(request):
    return _drawer(
        request,
        title="Add a compensation record",
        subtitle="Band, benefits and the next pay review",
        action="/compensation-benefits/save",
        submit="Save record",
        note="Amounts are visible only inside this record, never on the register.",
        fields=_compensation_fields(request, choose_staff=True),
    )


@require_page_permission("compensation_benefits")
@require_http_methods(["GET"])
def compensation_drawer(request, staff_id):
    from apps.hr.models import CompensationRecord

    staff = _staff_in_reach(request, staff_id)
    record = CompensationRecord.objects.filter(staff=staff).first()
    fields = [_field("staff_id", "", type="hidden", value=staff.id)]
    fields += _compensation_fields(request, record)
    return _drawer(
        request,
        title=f"Compensation · {staff.user.name}",
        subtitle=f"{staff.country} · {staff.title or staff.user.active_role}",
        action="/compensation-benefits/save",
        submit="Save record",
        fields=fields,
    )


@require_page_permission("compensation_benefits")
@require_POST
def compensation_save(request):
    from apps.hr.rewards_wellbeing_service import save_compensation

    data = request.POST
    try:
        staff = _staff_in_reach(request, data.get("staff_id") or "")
        save_compensation(
            staff,
            {
                "salary_band": data.get("salary_band"),
                "currency": data.get("currency"),
                "base_salary": data.get("base_salary"),
                "allowances": data.get("allowances"),
                "medical_cover": data.get("medical_cover"),
                "pension_scheme": data.get("pension_scheme"),
                "other_benefits": data.get("other_benefits"),
                "effective_date": _date(data.get("effective_date")),
                "next_review_date": _date(data.get("next_review_date")),
                "status": data.get("status"),
            },
            request.user,
        )
    except Http404:
        messages.error(request, "Choose an employee you oversee.")
        return _back(request, COMPENSATION_PATH)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, COMPENSATION_PATH)
    messages.success(request, f"Compensation saved for {staff.user.name}.")
    return _back(request, COMPENSATION_PATH)


# ── Health and safety ────────────────────────────────────────────────────────
SAFETY_PATH = "/health-safety"


@require_page_permission("health_safety")
@require_http_methods(["GET"])
def incident_new_drawer(request):
    from apps.hr.models import ERSeverity, SafetyIncidentCategory

    return _drawer(
        request,
        title="Report an incident",
        subtitle="An injury, road traffic incident, near miss or hazard",
        action="/health-safety/report",
        submit="Report incident",
        fields=[
            _field(
                "category",
                "What happened",
                type="select",
                required=True,
                options=SafetyIncidentCategory.choices,
                blank="Choose the kind of incident",
            ),
            _field("incident_date", "Date", type="date", required=True),
            _field(
                "affected_staff_id",
                "Employee affected",
                type="select",
                options=_people_options(request),
                blank="No one was hurt",
            ),
            _field(
                "country",
                "Country",
                type="select",
                options=_country_options(request),
                blank="The employee's country",
            ),
            _field(
                "location", "Where", maxlength=255, placeholder="School, road, office…"
            ),
            _field(
                "severity",
                "Severity",
                type="select",
                required=True,
                options=ERSeverity.choices,
                value=ERSeverity.MEDIUM,
            ),
            _field("days_lost", "Working days lost", type="number", min=0, step="1"),
            _field(
                "description",
                "Description",
                type="textarea",
                required=True,
                maxlength=5000,
            ),
            _field(
                "immediate_action",
                "Immediate action taken",
                type="textarea",
                rows=3,
            ),
        ],
    )


@require_page_permission("health_safety")
@require_POST
def incident_report(request):
    from apps.hr.rewards_wellbeing_service import report_incident

    data = request.POST
    try:
        incident = report_incident(
            {
                "category": data.get("category"),
                "incident_date": _date(data.get("incident_date")),
                "affected_staff_id": data.get("affected_staff_id"),
                "country": data.get("country"),
                "location": data.get("location"),
                "severity": data.get("severity"),
                "days_lost": data.get("days_lost"),
                "description": data.get("description"),
                "immediate_action": data.get("immediate_action"),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, SAFETY_PATH)
    messages.success(request, f"{incident.get_category_display()} reported.")
    return _back(request, SAFETY_PATH)


def _visible_incident(request, incident_id):
    from apps.hr.models import SafetyIncident
    from apps.hr.reach import people_reach, scope_by_country

    incident = (
        scope_by_country(
            SafetyIncident.objects.select_related(
                "affected_staff__user", "reported_by"
            ),
            people_reach(request.user),
        )
        .filter(id=incident_id)
        .first()
    )
    if incident is None:
        raise Http404("Incident not found.")
    return incident


@require_page_permission("health_safety")
@require_http_methods(["GET"])
def incident_drawer(request, incident_id):
    from apps.hr.rewards_wellbeing_service import incident_transitions

    incident = _visible_incident(request, incident_id)
    facts = [
        {"label": "What happened", "value": incident.get_category_display()},
        {"label": "Date", "value": incident.incident_date.isoformat()},
        {
            "label": "Employee affected",
            "value": incident.affected_staff.user.name
            if incident.affected_staff
            else "",
        },
        {"label": "Country", "value": incident.country},
        {"label": "Where", "value": incident.location},
        {"label": "Severity", "value": incident.get_severity_display()},
        {"label": "Days lost", "value": str(incident.days_lost)},
        {"label": "Description", "value": incident.description},
        {"label": "Immediate action", "value": incident.immediate_action},
        {"label": "Corrective action", "value": incident.corrective_action},
        {"label": "Status", "value": incident.get_status_display()},
    ]
    transitions = incident_transitions(incident)
    if not transitions:
        return _drawer(
            request,
            title=incident.get_category_display(),
            subtitle=f"{incident.country} · Closed",
            facts=facts,
            empty="This incident is closed.",
        )
    return _drawer(
        request,
        title=incident.get_category_display(),
        subtitle=f"{incident.country} · {incident.get_status_display()}",
        action=f"/health-safety/{incident.id}/advance",
        submit="Record",
        facts=facts,
        fields=[
            _field(
                "to_status",
                "Move to",
                type="select",
                required=True,
                options=transitions,
            ),
            _field(
                "corrective_action",
                "Corrective action",
                type="textarea",
                rows=3,
                help="Required before an incident moves to action or closes.",
            ),
        ],
    )


@require_page_permission("health_safety")
@require_POST
def incident_advance(request, incident_id):
    from apps.hr.rewards_wellbeing_service import advance_incident

    incident = _visible_incident(request, incident_id)
    try:
        incident = advance_incident(
            incident,
            request.user,
            to_status=request.POST.get("to_status") or "",
            corrective_action=request.POST.get("corrective_action") or "",
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, SAFETY_PATH)
    messages.success(
        request, f"Incident moved to {incident.get_status_display().lower()}."
    )
    return _back(request, SAFETY_PATH)


# ── Recognition ──────────────────────────────────────────────────────────────
RECOGNITION_PATH = "/recognition"


@require_page_permission("recognition")
@require_http_methods(["GET"])
def recognition_new_drawer(request):
    from apps.hr.models import RecognitionCategory

    return _drawer(
        request,
        title="Recognise someone",
        subtitle="Name good work, and why it mattered",
        action="/recognition/award",
        submit="Record recognition",
        fields=[
            _field(
                "staff_id",
                "Employee",
                type="select",
                required=True,
                options=_people_options(request),
                blank="Choose the employee",
            ),
            _field(
                "category",
                "Recognised for",
                type="select",
                required=True,
                options=RecognitionCategory.choices,
                blank="Choose a category",
            ),
            _field(
                "citation",
                "Citation",
                type="textarea",
                required=True,
                maxlength=2000,
                placeholder="What they did, and the difference it made",
            ),
            _field("awarded_on", "Date", type="date"),
        ],
    )


@require_page_permission("recognition")
@require_POST
def recognition_award(request):
    from apps.hr.rewards_wellbeing_service import recognise

    data = request.POST
    try:
        staff = _staff_in_reach(request, data.get("staff_id") or "")
        recognise(
            staff,
            {
                "category": data.get("category"),
                "citation": data.get("citation"),
                "awarded_on": _date(data.get("awarded_on")),
            },
            request.user,
        )
    except Http404:
        messages.error(request, "Choose an employee you oversee.")
        return _back(request, RECOGNITION_PATH)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECOGNITION_PATH)
    messages.success(request, f"{staff.user.name} recognised.")
    return _back(request, RECOGNITION_PATH)


# ── Pulse surveys ────────────────────────────────────────────────────────────
PULSE_PATH = "/pulse-surveys"


@require_page_permission("pulse_surveys")
@require_http_methods(["GET"])
def pulse_new_drawer(request):
    from apps.hr.models import PULSE_QUESTIONS

    return _drawer(
        request,
        title="Open a pulse survey",
        subtitle="Five anonymous statements, answered from 1 to 5",
        action="/pulse-surveys/open",
        submit="Open and notify staff",
        note=(
            "Staff in the chosen countries are notified. Answers are anonymous, and "
            "results show only once five people have answered. The statements: "
            + " ".join(f"({i}) {q}" for i, (_k, q) in enumerate(PULSE_QUESTIONS, 1))
        ),
        fields=[
            _field(
                "title",
                "Title",
                required=True,
                maxlength=255,
                placeholder="e.g. Quarter 1 staff pulse",
            ),
            *[
                _field(
                    f"country_{code}",
                    f"Survey staff in {name}",
                    type="checkbox",
                    value=True,
                )
                for code, name in _country_options(request)
            ],
            _field("closes_on", "Closes on", type="date", required=True),
        ],
    )


@require_page_permission("pulse_surveys")
@require_POST
def pulse_open(request):
    from apps.hr.reach import people_reach
    from apps.hr.rewards_wellbeing_service import open_pulse_survey

    data = request.POST
    countries = [
        country
        for country in people_reach(request.user).filter_options()
        if data.get(f"country_{country}")
    ]
    try:
        survey = open_pulse_survey(
            {
                "title": data.get("title"),
                "countries": countries,
                "closes_on": _date(data.get("closes_on")),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PULSE_PATH)
    messages.success(request, f"{survey.title} is open and staff have been notified.")
    return _back(request, PULSE_PATH)


def _visible_survey(request, survey_id):
    from apps.hr.models import PulseSurvey
    from apps.hr.reach import people_reach

    survey = PulseSurvey.objects.filter(id=survey_id).first()
    reach = people_reach(request.user)
    if survey is None or not all(
        reach.allows_country(c) for c in (survey.countries or [])
    ):
        raise Http404("Survey not found.")
    return survey


@require_page_permission("pulse_surveys")
@require_http_methods(["GET"])
def pulse_results_drawer(request, survey_id):
    from apps.hr.models import PULSE_MIN_RESPONSES, PulseSurveyStatus
    from apps.hr.rewards_wellbeing_service import survey_results

    survey = _visible_survey(request, survey_id)
    results = survey_results(survey)
    facts = [
        {"label": "Countries", "value": ", ".join(survey.countries or [])},
        {
            "label": "Open",
            "value": f"{survey.opens_on:%d %b %Y} to {survey.closes_on:%d %b %Y}",
        },
        {"label": "Responses", "value": str(results["count"])},
    ]
    if results["shown"]:
        facts.append({"label": "Overall", "value": f"{results['overall']} of 5"})
        facts += [
            {
                "label": row["statement"],
                "value": f"{row['average']} of 5 · {row['favourable']}% agree",
            }
            for row in results["rows"]
        ]
    else:
        facts.append(
            {
                "label": "Results",
                "value": f"Shown once {PULSE_MIN_RESPONSES} people have answered, "
                "so no one's answer can be inferred.",
            }
        )
    if survey.status == PulseSurveyStatus.OPEN:
        return _drawer(
            request,
            title=survey.title,
            subtitle="Open",
            action=f"/pulse-surveys/{survey.id}/close",
            submit="Close the survey",
            facts=facts,
        )
    return _drawer(
        request,
        title=survey.title,
        subtitle="Closed",
        facts=facts,
        empty="This survey is closed.",
    )


@require_page_permission("pulse_surveys")
@require_POST
def pulse_close(request, survey_id):
    from apps.hr.rewards_wellbeing_service import close_pulse_survey

    survey = _visible_survey(request, survey_id)
    try:
        close_pulse_survey(survey, request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, PULSE_PATH)
    messages.success(request, f"{survey.title} closed.")
    return _back(request, PULSE_PATH)


@require_page_permission("staff_pulse")
@require_http_methods(["GET", "POST"])
def pulse_respond(request, survey_id):
    """The page a member of staff answers a pulse survey on."""
    from apps.hr.models import PULSE_QUESTIONS, PulseSurvey
    from apps.hr.rewards_wellbeing_service import has_answered, is_open_for, respond

    survey = PulseSurvey.objects.filter(id=survey_id).first()
    if survey is None:
        raise Http404("Survey not found.")
    if request.method == "POST":
        try:
            respond(
                survey,
                request.user,
                scores={key: request.POST.get(key) for key, _q in PULSE_QUESTIONS},
                comment=request.POST.get("comment") or "",
            )
        except SERVICE_ERRORS as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))
            return redirect(f"/pulse/{survey.id}")
        messages.success(request, "Thank you. Your answer is recorded anonymously.")
        return redirect(f"/pulse/{survey.id}")
    return render(
        request,
        "pages/hr/pulse_respond.html",
        {
            "survey": survey,
            "questions": PULSE_QUESTIONS,
            "scale": [
                (1, "Strongly disagree"),
                (2, "Disagree"),
                (3, "Neutral"),
                (4, "Agree"),
                (5, "Strongly agree"),
            ],
            "is_open": is_open_for(survey, request.user),
            "answered": has_answered(survey, request.user),
        },
    )


# ── Employment compliance ────────────────────────────────────────────────────
COMPLIANCE_PATH = "/compliance-register"


@require_page_permission("compliance_register")
@require_http_methods(["GET"])
def compliance_requirement_drawer(request):
    from apps.hr.compliance_service import ALL_COUNTRIES
    from apps.hr.reach import people_reach

    options = _country_options(request)
    if people_reach(request.user).is_everything:
        options = [(ALL_COUNTRIES, "Every country"), *options]
    return _drawer(
        request,
        title="Add a requirement",
        subtitle="An employment-law obligation every employee must meet",
        action="/compliance-register/requirement/add",
        submit="Add requirement",
        fields=[
            _field(
                "country",
                "Country",
                type="select",
                required=True,
                options=options,
                blank="Choose the country",
            ),
            _field(
                "name",
                "Requirement",
                required=True,
                maxlength=255,
                placeholder="e.g. Signed employment contract",
            ),
            _field(
                "description",
                "What satisfies it",
                type="textarea",
                rows=3,
                placeholder="The law or regulation, and the evidence expected",
            ),
            _field(
                "is_mandatory",
                "Mandatory for every employee",
                type="checkbox",
                value=True,
            ),
        ],
    )


@require_page_permission("compliance_register")
@require_POST
def compliance_requirement_add(request):
    from apps.hr.compliance_service import add_requirement

    data = request.POST
    try:
        requirement = add_requirement(
            {
                "country": data.get("country"),
                "name": data.get("name"),
                "description": data.get("description"),
                "is_mandatory": data.get("is_mandatory"),
            },
            request.user,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, COMPLIANCE_PATH)
    messages.success(request, f"Requirement added: {requirement.name}.")
    return _back(request, COMPLIANCE_PATH)


def _evidence_fields(request, record=None):
    from apps.hr.compliance_service import visible_requirements

    fields = []
    if record is None:
        requirements = [
            (r.id, f"{r.name} · {r.country}")
            for r in visible_requirements(request.user).order_by("country", "name")
        ]
        fields += [
            _field(
                "staff_id",
                "Employee",
                type="select",
                required=True,
                value=request.GET.get("staff", ""),
                options=_people_options(request),
                blank="Choose the employee",
            ),
            _field(
                "requirement_id",
                "Requirement",
                type="select",
                required=True,
                value=request.GET.get("requirement", ""),
                options=requirements,
                blank="Choose the requirement",
            ),
        ]
    fields += [
        _field(
            "document_url",
            "Link to the evidence",
            value=getattr(record, "document_url", "") or "",
            maxlength=512,
            placeholder="Where the signed document is filed",
        ),
        _field(
            "expiry_date",
            "Expires on",
            type="date",
            value=record.expiry_date.isoformat()
            if record is not None and record.expiry_date
            else "",
            help="Leave blank if it does not expire.",
        ),
        _field("verified", "I have checked the evidence", type="checkbox"),
    ]
    return fields


@require_page_permission("compliance_register")
@require_http_methods(["GET"])
def compliance_evidence_drawer(request):
    return _drawer(
        request,
        title="Record evidence",
        subtitle="An employee's evidence against a requirement",
        action="/compliance-register/save",
        submit="Save",
        note="The status follows the evidence and its expiry date.",
        fields=_evidence_fields(request),
    )


def _visible_record(request, record_id):
    from apps.hr.models import EmployeeComplianceRecord
    from apps.hr.reach import people_reach, scope_by_staff

    record = (
        scope_by_staff(
            EmployeeComplianceRecord.objects.select_related(
                "staff__user", "requirement", "verified_by"
            ),
            people_reach(request.user),
        )
        .filter(id=record_id)
        .first()
    )
    if record is None:
        raise Http404("Compliance record not found.")
    return record


@require_page_permission("compliance_register")
@require_http_methods(["GET"])
def compliance_record_drawer(request, record_id):
    record = _visible_record(request, record_id)
    fields = [
        _field("staff_id", "", type="hidden", value=record.staff_id),
        _field("requirement_id", "", type="hidden", value=record.requirement_id),
        *_evidence_fields(request, record),
    ]
    return _drawer(
        request,
        title=f"{record.requirement.name}",
        subtitle=f"{record.staff.user.name} · {record.get_status_display()}",
        action="/compliance-register/save",
        submit="Save",
        facts=[
            {"label": "Requirement", "value": record.requirement.description or ""},
            {
                "label": "Verified by",
                "value": record.verified_by.name if record.verified_by else "",
            },
        ],
        fields=fields,
    )


@require_page_permission("compliance_register")
@require_POST
def compliance_evidence_save(request):
    from apps.hr.compliance_service import record_evidence
    from apps.hr.models import ComplianceRequirement

    data = request.POST
    try:
        staff = _staff_in_reach(request, data.get("staff_id") or "")
        requirement = ComplianceRequirement.objects.filter(
            id=data.get("requirement_id") or ""
        ).first()
        record = record_evidence(
            staff,
            requirement,
            {
                "document_url": data.get("document_url"),
                "expiry_date": _date(data.get("expiry_date")),
                "verified": data.get("verified"),
            },
            request.user,
        )
    except Http404:
        messages.error(request, "Choose an employee you oversee.")
        return _back(request, COMPLIANCE_PATH)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, COMPLIANCE_PATH)
    messages.success(
        request,
        f"{staff.user.name}: {record.requirement.name} is {record.get_status_display().lower()}.",
    )
    return _back(request, COMPLIANCE_PATH)


# ── Recovery plans ───────────────────────────────────────────────────────────
RECOVERY_PATH = "/recovery-plans"


def _visible_recovery_plan(request, plan_id):
    from apps.hr.models import PerformanceImprovementPlan
    from apps.hr.reach import people_reach, scope_by_staff

    plans = scope_by_staff(
        PerformanceImprovementPlan.objects.select_related(
            "staff__user", "owner__user", "escalated_case"
        ),
        people_reach(request.user),
    )
    if getattr(request.user, "active_role", "") == "Program Lead":
        # The lead follows the plans of the people they review. Their reach
        # also holds their own record, and a draft plan about them is HR's
        # until it is authorised and shared.
        plans = plans.filter(staff_id__in=_reviewee_profiles(request).values("id"))
    plan = plans.filter(id=plan_id).first()
    if plan is None:
        raise Http404("Recovery plan not found.")
    return plan


@require_page_permission("recovery_plans")
@require_http_methods(["GET"])
def recovery_new_drawer(request):
    from apps.hr.models import RecoveryCause

    return _drawer(
        request,
        title="Recommend a formal plan",
        subtitle="A draft improvement plan, authorised separately by HR",
        action="/recovery-plans/recommend",
        submit="Recommend",
        note=(
            "A score never starts a formal plan on its own. Record the evidence "
            "and the cause; HR authorises it before anything is shared."
        ),
        fields=[
            _field(
                "staff_id",
                "Employee",
                type="select",
                required=True,
                options=_people_options(request)
                if _is_hr_or_admin(request)
                else [(p.id, p.user.name) for p in _reviewee_profiles(request)[:500]],
                blank="Choose the employee",
            ),
            _field(
                "cause",
                "Cause",
                type="select",
                required=True,
                options=RecoveryCause.choices,
                blank="Choose the cause",
            ),
            _field(
                "reason",
                "Evidence and reason",
                type="textarea",
                required=True,
                rows=4,
                placeholder="What has been observed, over what period, and the support already given",
            ),
            _field("start_date", "Start date", type="date"),
        ],
    )


@require_page_permission("recovery_plans")
@require_POST
def recovery_recommend(request):
    from apps.hr.performance_engine import recommend_pip

    data = request.POST
    try:
        staff = _staff_in_reach(request, data.get("staff_id") or "")
        if (
            not _is_hr_or_admin(request)
            and not _reviewee_profiles(request).filter(id=staff.id).exists()
        ):
            # Refused in the engine too; said here in the picker's own words.
            raise Http404("Not someone you review.")
        plan = recommend_pip(
            staff,
            data.get("reason"),
            request.user,
            cause=(data.get("cause") or "other"),
            start=_date(data.get("start_date")),
        )
    except Http404:
        messages.error(
            request,
            "Choose an employee you oversee."
            if _is_hr_or_admin(request)
            else "Choose someone you review.",
        )
        return _back(request, RECOVERY_PATH)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECOVERY_PATH)
    messages.success(
        request,
        f"Formal plan recommended for {plan.staff.user.name}. It waits for HR "
        "authorisation.",
    )
    return _back(request, RECOVERY_PATH)


@require_page_permission("recovery_plans")
@require_http_methods(["GET"])
def recovery_drawer(request, plan_id):
    from apps.hr.models import RecoveryPlanType, RecoveryStatus

    plan = _visible_recovery_plan(request, plan_id)
    milestones = list(plan.milestones.all())
    facts = [
        {"label": "Cause", "value": plan.get_cause_display()},
        {"label": "Evidence", "value": plan.cause_evidence or ""},
        {"label": "Action plan", "value": plan.action_plan or ""},
        {"label": "Support offered", "value": plan.support_offered or ""},
        {
            "label": "Review window",
            "value": f"{plan.start_date:%-d %b %Y} to {plan.end_date:%-d %b %Y}",
        },
        {
            "label": "Milestones",
            "value": "; ".join(
                f"{m.description} ({m.due_date:%-d %b}{', done' if m.is_complete else ''})"
                for m in milestones
                if m.due_date
            ),
        },
    ]
    check_ins = list(plan.check_ins.order_by("-held_on", "-created_at")[:3])
    facts.append(
        {
            "label": "Check-ins",
            "value": "\n".join(f"{c.held_on:%-d %b %Y}: {c.note}" for c in check_ins)
            or "None recorded yet",
        }
    )
    if plan.escalated_case_id:
        facts.append(
            {"label": "Conduct case", "value": plan.escalated_case.get_status_display()}
        )
    subtitle = f"{plan.get_plan_type_display()} · {plan.get_status_display()}"
    live = plan.status in (
        RecoveryStatus.ACTIVE,
        RecoveryStatus.PROGRESS_REVIEW,
        RecoveryStatus.EXTENDED,
    )
    if not _is_hr_or_admin(request):
        # Authorising a plan and deciding its outcome are HR's; the drawer
        # offered those forms to anyone who could open the plan, and the
        # engine refused them after they had typed (Program Lead alignment,
        # 2026-09-13). The reviewer records the check-ins the plan promises.
        from apps.hr.review_authority import is_reviewer_of

        if live and is_reviewer_of(plan.staff, request.user):
            open_milestones = [m for m in milestones if not m.is_complete]
            fields = [
                _field(
                    "held_on",
                    "Held on",
                    type="date",
                    required=True,
                    value=f"{timezone.localdate():%Y-%m-%d}",
                ),
                _field(
                    "note",
                    "What the check-in found",
                    type="textarea",
                    required=True,
                    rows=4,
                    maxlength=4000,
                    placeholder="Progress against the action plan, support given, what happens next",
                ),
            ]
            if open_milestones:
                fields.append(
                    _field(
                        "milestone_id",
                        "Milestone reached",
                        type="select",
                        options=[
                            (
                                m.id,
                                f"{m.description} (due {m.due_date:%-d %b})"
                                if m.due_date
                                else m.description,
                            )
                            for m in open_milestones
                        ],
                        blank="None reached at this check-in",
                        help="Marks the milestone complete with this check-in.",
                    )
                )
            return _drawer(
                request,
                title=plan.staff.user.name,
                subtitle=subtitle,
                action=f"/recovery-plans/{plan.id}/check-in",
                submit="Record the check-in",
                facts=facts,
                fields=fields,
            )
        note = (
            "HR authorises this plan before anything is shared with the employee."
            if plan.status == RecoveryStatus.DRAFT
            else "HR records the outcome at the review date."
            if live
            else ""
        )
        return _drawer(
            request,
            title=plan.staff.user.name,
            subtitle=subtitle,
            facts=facts,
            empty=note,
        )
    if (
        plan.status == RecoveryStatus.DRAFT
        and plan.plan_type == RecoveryPlanType.FORMAL
    ):
        return _drawer(
            request,
            title=plan.staff.user.name,
            subtitle=subtitle,
            action=f"/recovery-plans/{plan.id}/activate",
            submit="Authorise the plan",
            facts=facts,
            note=("Authorising starts a 90-day plan with 30, 60 and 90-day reviews."),
            fields=[
                _field(
                    "action_plan",
                    "Agreed action plan",
                    type="textarea",
                    required=True,
                    rows=4,
                    value="" if plan.action_plan.startswith("(") else plan.action_plan,
                )
            ],
        )
    if live:
        options = [("completed", "Successfully completed"), ("extended", "Extend")]
        if plan.plan_type == RecoveryPlanType.FORMAL and not plan.escalated_case_id:
            options.append(("escalated", "Escalate to a conduct case"))
        return _drawer(
            request,
            title=plan.staff.user.name,
            subtitle=subtitle,
            action=f"/recovery-plans/{plan.id}/outcome",
            submit="Record the outcome",
            facts=facts,
            fields=[
                _field(
                    "outcome",
                    "Outcome",
                    type="select",
                    required=True,
                    options=options,
                    blank="Choose the outcome",
                ),
                _field(
                    "note",
                    "Decision note",
                    type="textarea",
                    required=True,
                    rows=3,
                    placeholder="What the review found and what happens next",
                ),
            ],
        )
    return _drawer(request, title=plan.staff.user.name, subtitle=subtitle, facts=facts)


@require_page_permission("recovery_plans")
@require_POST
def recovery_activate(request, plan_id):
    from apps.hr.performance_engine import activate_pip

    plan = _visible_recovery_plan(request, plan_id)
    action_plan = (request.POST.get("action_plan") or "").strip()
    if not action_plan:
        messages.error(request, "Record the agreed action plan before authorising.")
        return _back(request, RECOVERY_PATH)
    try:
        activate_pip(plan, request.user, action_plan=action_plan)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECOVERY_PATH)
    messages.success(
        request, f"Improvement plan authorised for {plan.staff.user.name}."
    )
    return _back(request, RECOVERY_PATH)


@require_page_permission("recovery_plans")
@require_POST
def recovery_outcome(request, plan_id):
    from django.db import transaction

    from apps.hr.performance_engine import pip_outcome

    plan = _visible_recovery_plan(request, plan_id)
    outcome = (request.POST.get("outcome") or "").strip()
    note = (request.POST.get("note") or "").strip()
    if not note:
        messages.error(request, "Record a decision note with the outcome.")
        return _back(request, RECOVERY_PATH)
    try:
        with transaction.atomic():
            pip_outcome(plan, outcome, note, request.user)
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECOVERY_PATH)
    messages.success(request, f"Outcome recorded for {plan.staff.user.name}.")
    return _back(request, RECOVERY_PATH)


@require_page_permission("recovery_plans")
@require_POST
def recovery_check_in(request, plan_id):
    """The reviewer records a check-in, optionally closing a milestone."""
    from apps.hr.performance_engine import record_recovery_check_in

    plan = _visible_recovery_plan(request, plan_id)
    try:
        record_recovery_check_in(
            plan,
            request.user,
            held_on=_date(request.POST.get("held_on")),
            note=request.POST.get("note") or "",
            milestone_id=(request.POST.get("milestone_id") or "").strip() or None,
        )
    except SERVICE_ERRORS as exc:
        return _refused(request, exc, RECOVERY_PATH)
    messages.success(request, f"Check-in recorded for {plan.staff.user.name}.")
    return _back(request, RECOVERY_PATH)
