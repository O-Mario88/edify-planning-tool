"""Metric definitions for the Regional HR Director Dashboard (2026-09-13).

The dashboard's KPI panel was twelve generated rows describing queries that
matched strings nothing writes ("Open", "Completed", "Strong", "Initiated"),
three of them for figures the role does not own (payroll readiness, legacy CPD
assignments, a "staff on track" percentage read from free-text ratings). The
panel was rebuilt around the role description, so its definitions live here,
beside the generated list rather than inside it, as the HR programme registers'
do (hr_programme_metrics.py). Keys the rebuilt panel still renders keep their
names, so the registry identity of those tiles does not change.
"""

from __future__ import annotations

_SOURCE = "apps.accounts.hr_dashboard_service.get_dashboard:get_dashboard"
_SERVICE = "apps.accounts.hr_dashboard_service.HRDashboardService.get_dashboard"
_ROLES = ("HumanResources", "Admin")
_SCOPE = (
    "The countries the Regional HR Director oversees (apps.hr.reach), narrowed "
    "by the dashboard's country and department filters"
)
_LOCATION = "apps/accounts/hr_dashboard_service.py"


def _row(
    key: str,
    label: str,
    *,
    line: int,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    drilldown: str,
    category: str,
    unit: str = "count",
    denominator: str | None = None,
    period: str = "point_in_time",
    date_basis: str = "not_time_bound",
) -> dict:
    return {
        "key": key,
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": _SERVICE,
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": date_basis,
        "period": period,
        "scope": _SCOPE,
        "owner_page": "workforce_dashboard",
        "filter_behaviour": "filtered",
        "drilldown": drilldown,
        "no_drilldown_reason": None,
        "notes": "Regional HR Director Dashboard, rebuilt 2026-09-13.",
        "roles": _ROLES,
        "source_location": f"{_LOCATION}:{line}",
    }


_PROFILE = ("apps.accounts.models.StaffProfile", "apps.accounts.models.User")

HR_DIRECTOR_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "accounts_hr_dashboard_service_active_employees",
        "Active Employees",
        line=1474,
        definition=(
            "Active people records in the director's countries: the account is "
            "active and the record has not exited."
        ),
        question="How many people does the director's region employ today?",
        numerator="staff profiles not exited, with an active account",
        models=_PROFILE,
        drilldown="/staff",
        category="scale",
    ),
    _row(
        "accounts_hr_dashboard_service_open_positions",
        "Open Positions",
        line=1481,
        definition=(
            "Vacancies open for recruitment in the director's countries. Requests "
            "still awaiting the Country Director's approval are counted apart."
        ),
        question="How many roles are being recruited for?",
        numerator="vacancies with status open",
        models=("apps.hr.models.Vacancy",),
        drilldown="/recruitment",
        category="pending_action",
    ),
    _row(
        "hr_director_staff_turnover",
        "Staff Turnover",
        line=1488,
        definition=(
            "People whose last working day fell in the fiscal year so far, as a "
            "share of everyone employed at some point in it. Voluntary exits "
            "(resignation, retirement) are named in the helper."
        ),
        question="How many of our people have left this year?",
        numerator="offboarding plans with a last working day in the FY, up to today",
        denominator=(
            "people records created before today and not gone before the FY began"
        ),
        models=(*_PROFILE, "apps.hr.models.OffboardingPlan"),
        drilldown="/workforce-planning",
        category="risk",
        unit="percent",
        period="financial_year",
        date_basis="record_created",
    ),
    _row(
        "accounts_hr_dashboard_service_performance_reviews_due",
        "Performance Reviews Due",
        line=1512,
        definition=(
            "Performance reviews for the fiscal year that are not yet complete "
            "(closed, acknowledged or signed and archived). Overdue reviews are "
            "named in the helper."
        ),
        question="How much of the review cycle is still open?",
        numerator="reviews for the FY whose stage is not a completed stage",
        models=("apps.hr.models.PerformanceReview",),
        drilldown="/performance-reviews",
        category="pending_action",
        period="financial_year",
    ),
    _row(
        "hr_director_open_er_cases",
        "Open ER Cases",
        line=1519,
        definition=(
            "Disciplinary matters, grievances, disputes and investigations not yet "
            "resolved or closed, confidential cases included as counts only."
        ),
        question="How many employee-relations matters are open?",
        numerator="employee-relations cases not resolved or closed",
        models=("apps.hr.models.EmployeeRelationsCase",),
        drilldown="/employee-relations",
        category="risk",
    ),
    _row(
        "hr_director_open_safety_incidents",
        "Open Safety Incidents",
        line=1526,
        definition=(
            "Occupational health and safety incidents, near misses and hazards not "
            "yet closed. High and critical incidents are named in the helper."
        ),
        question="Which safety incidents are still waiting on corrective action?",
        numerator="safety incidents with a status other than closed",
        models=("apps.hr.models.SafetyIncident",),
        drilldown="/health-safety",
        category="risk",
    ),
    _row(
        "hr_director_staff_morale",
        "Staff Morale",
        line=1500,
        definition=(
            "The average score, out of 5, of the latest pulse survey that at least "
            "five people in the director's countries answered. Fewer answers are "
            "never shown, so no one's answer can be inferred."
        ),
        question="How motivated are our people?",
        numerator="mean of the five statement averages of the latest survey above the anonymity floor",
        models=("apps.hr.models.PulseSurvey", "apps.hr.models.PulseResponse"),
        drilldown="/pulse-surveys",
        category="outcome",
        unit="score",
        date_basis="submission_date",
    ),
    _row(
        "accounts_hr_dashboard_service_compliance_completion",
        "Compliance Completion",
        line=1533,
        definition=(
            "Compliant evidence as a share of every employment-law obligation in "
            "the director's countries: each employee's record against a "
            "requirement, plus each mandatory requirement an employee has no "
            "record against at all."
        ),
        question="Do our people meet the employment-law requirements of their country?",
        numerator="employee compliance records with status compliant",
        denominator=(
            "employee compliance records, plus mandatory requirements with no "
            "record for an active employee in their country"
        ),
        models=(
            "apps.hr.models.ComplianceRequirement",
            "apps.hr.models.EmployeeComplianceRecord",
        ),
        drilldown="/compliance-register",
        category="compliance",
        unit="percent",
    ),
)
