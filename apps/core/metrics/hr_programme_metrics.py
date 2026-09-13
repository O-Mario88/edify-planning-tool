"""Metric definitions for the Regional HR Director's programme registers.

The HR register pages render their tiles through
``apps.frontend.views.hr_views._metric``, which only accepts a label the
reconciled registry knows. The registers rebuilt on 2026-09-13 count things
the old ones did not (cases awaiting triage, disciplinary matters, vacancies by
real status), so their definitions live here and are appended to the
reconciled rows in ``reconciled_registry.py``. One row per label: a label is
shared by every HR register that renders it.
"""

from __future__ import annotations

_SOURCE = "apps.frontend.views.hr_views:_metric"
_HR_ROLES = ("HumanResources", "Admin")


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.lower())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _row(
    label: str,
    *,
    definition: str,
    question: str,
    numerator: str,
    models: tuple[str, ...],
    owner_page: str,
    location: str,
    category: str = "scale",
    unit: str = "count",
    drilldown: str | None = None,
    denominator: str | None = None,
    roles: tuple[str, ...] = _HR_ROLES,
    scope: str = "The countries the Regional HR Director oversees (apps.hr.reach)",
) -> dict:
    return {
        "key": f"hr_programme_{_slug(label)}",
        "label": label,
        "source_label": label,
        "source": _SOURCE,
        "definition": definition,
        "question": question,
        "category": category,
        "unit": unit,
        "service": "apps.frontend.views.hr_views._metric",
        "source_models": models,
        "numerator": numerator,
        "denominator": denominator,
        "date_basis": "not_time_bound",
        "period": "point_in_time",
        "scope": scope,
        "owner_page": owner_page,
        "filter_behaviour": "partial",
        "drilldown": drilldown,
        "no_drilldown_reason": None
        if drilldown
        else "The register below the tile lists the records it counts.",
        "notes": "HR programme register rebuilt 2026-09-13.",
        "roles": roles,
        "source_location": location,
    }


_ER = ("apps.hr.models.EmployeeRelationsCase",)
_VACANCY = ("apps.hr.models.Vacancy",)
_APPLICATION = ("apps.hr.models.Application",)
_ONBOARDING = ("apps.hr.models.OnboardingPlan",)
_OFFBOARDING = ("apps.hr.models.OffboardingPlan",)
_COMPENSATION = ("apps.hr.models.CompensationRecord",)
_INCIDENT = ("apps.hr.models.SafetyIncident",)
_RECOGNITION = ("apps.hr.models.StaffRecognition",)
_PULSE = ("apps.hr.models.PulseSurvey", "apps.hr.models.PulseResponse")
_DOCUMENTS = (
    "apps.documents.models.DocumentAsset",
    "apps.documents.models.DocumentAcknowledgement",
)

_PEOPLE = (
    "apps.accounts.models.StaffProfile",
    "apps.accounts.models.StaffSupervisorAssignment",
)
_REVIEWS = ("apps.hr.models.PerformanceReview",)
_PLANS = ("apps.hr.models.PerformanceImprovementPlan",)
_REVIEW_PROGRESS = (
    "apps.hr.models.PerformanceReview",
    "apps.hr.models.PerformancePriority",
    "apps.hr.models.PerformanceSnapshot",
    "apps.hr.models.PerformanceCycle",
)
# A Programme Lead reads the recovery register for the people they review
# (Program Lead alignment, 2026-09-13); HR reads its reach.
_RECOVERY_SCOPE = (
    "HR: the countries in apps.hr.reach; a Programme Lead: the people they "
    "review (apps.hr.review_authority.reviewees_of, never themself)"
)
# The Programme Lead's Performance Reviews register counts the conversations
# they hold as reviewer, not HR's country list, so its tiles are their own rows.
_TEAM_REVIEW_SCOPE = (
    "The people the viewer reviews (apps.hr.review_authority.reviewees_of, "
    "never themself), for the selected FY"
)
_TEAM_REVIEW_LOCATION = "apps/frontend/views/hr_views.py:_team_performance_reviews"

HR_PROGRAMME_METRIC_ROWS: tuple[dict, ...] = (
    _row(
        "No reporting line",
        definition=(
            "People not exited, below the country leadership roles, with no "
            "supervisor recorded."
        ),
        question="Who has no reporting line for leave, reviews and oversight?",
        numerator="staff profiles without a StaffSupervisorAssignment as supervisee",
        models=_PEOPLE,
        owner_page="org_structure",
        location="apps/frontend/views/hr_views.py:org_structure_view",
        category="risk",
    ),
    _row(
        "Open roles",
        definition="Vacancies open for recruitment in the director's countries.",
        question="How many roles are being recruited for?",
        numerator="vacancies with status open",
        models=_VACANCY,
        owner_page="workforce_planning",
        location="apps/frontend/views/hr_views.py:workforce_planning_view",
        category="pending_action",
    ),
    _row(
        "Leaving in 90 days",
        definition="People whose offboarding records a last working day in the next 90 days.",
        question="Who is about to leave?",
        numerator="open offboarding plans with a last working day within 90 days",
        models=_OFFBOARDING,
        owner_page="workforce_planning",
        location="apps/frontend/views/hr_views.py:workforce_planning_view",
        category="risk",
    ),
    _row(
        "Turnover this FY",
        definition=(
            "People whose last working day fell in the fiscal year so far, as a "
            "share of the active headcount plus those leavers."
        ),
        question="How many of our people have left this year?",
        numerator="offboarding plans with a last working day in the FY up to today",
        denominator="active headcount plus the year's leavers",
        models=_OFFBOARDING,
        owner_page="workforce_planning",
        location="apps/frontend/views/hr_views.py:workforce_planning_view",
        category="risk",
        unit="percent",
    ),
    _row(
        "Awaiting calibration",
        definition="Reviews in calibration, HR quality review or ready for SLT calibration.",
        question="How many reviews wait on calibration?",
        numerator="reviews with stage calibration, hr_quality_review or ready_for_slt_calibration",
        models=_REVIEWS,
        owner_page="performance_reviews",
        location="apps/frontend/views/hr_views.py:performance_reviews_view",
        category="pending_action",
    ),
    _row(
        "Awaiting authorisation",
        definition="Formal improvement plans recommended and not yet authorised by HR.",
        question="Which formal plans wait on HR's decision?",
        numerator="recovery plans with status draft",
        models=_PLANS,
        owner_page="recovery_plans",
        location="apps/frontend/views/hr_views.py:recovery_plans_view",
        category="pending_action",
        roles=(*_HR_ROLES, "Program Lead"),
        scope=_RECOVERY_SCOPE,
    ),
    _row(
        "Ending in 30 days",
        definition="Live recovery plans whose review date falls in the next 30 days.",
        question="Which plans need an outcome soon?",
        numerator="active, progress-review or extended plans ending within 30 days",
        models=_PLANS,
        owner_page="recovery_plans",
        location="apps/frontend/views/hr_views.py:recovery_plans_view",
        category="pending_action",
        roles=(*_HR_ROLES, "Program Lead"),
        scope=_RECOVERY_SCOPE,
    ),
    _row(
        "Awaiting triage",
        definition=(
            "Open employee-relations cases that are submitted or in restricted "
            "triage, in the countries the director oversees."
        ),
        question="How many cases still need a first assessment?",
        numerator="cases with status submitted or triage",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="risk",
    ),
    _row(
        "Under investigation",
        definition=(
            "Open employee-relations cases between investigation and appeal: "
            "investigation, findings recorded, action decided or under appeal."
        ),
        question="How many cases are being investigated or decided?",
        numerator="cases with status investigation, findings, action or appeal",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="pending_action",
    ),
    _row(
        "Disciplinary matters",
        definition="Open employee-relations cases of the disciplinary type.",
        question="How many disciplinary matters are open?",
        numerator="open cases with case_type disciplinary",
        models=_ER,
        owner_page="employee_relations",
        location="apps/frontend/views/hr_views.py:employee_relations_view",
        category="risk",
    ),
    _row(
        "Replacements",
        definition=(
            "Open or pending vacancies raised to replace someone who left, rather "
            "than a new role."
        ),
        question="How many posts are waiting to replace leavers?",
        numerator="vacancies pending, approved or open with replacement_or_new_role replacement",
        models=_VACANCY,
        owner_page="recruitment",
        location="apps/frontend/views/hr_views.py:recruitment_view",
        category="capacity",
    ),
    _row(
        "Offers",
        definition="Applications at the offer stage or with an accepted offer.",
        question="How many candidates hold an offer?",
        numerator="applications with stage offer or accepted",
        models=_APPLICATION,
        owner_page="candidate_pipeline",
        location="apps/frontend/views/hr_views.py:candidate_pipeline_view",
        category="progress",
    ),
    _row(
        "Awaiting supervisor",
        definition=(
            "Onboarding plans waiting for the supervisor to confirm the new "
            "employee is ready."
        ),
        question="How many new hires are waiting on their supervisor?",
        numerator="onboarding plans with status supervisor_review",
        models=_ONBOARDING,
        owner_page="onboarding",
        location="apps/frontend/views/hr_views.py:onboarding_view",
        category="pending_action",
    ),
    _row(
        "Ready for activation",
        definition="Onboarding plans confirmed ready, which HR can close to activate.",
        question="How many new hires can HR activate now?",
        numerator="onboarding plans with status ready_for_activation",
        models=_ONBOARDING,
        owner_page="onboarding",
        location="apps/frontend/views/hr_views.py:onboarding_view",
        category="readiness",
    ),
    _row(
        "Voluntary exits",
        definition="Offboardings whose reason is a resignation or a retirement.",
        question="How many people chose to leave?",
        numerator="offboarding plans with exit_reason resignation or retirement",
        models=_OFFBOARDING,
        owner_page="offboarding",
        location="apps/frontend/views/hr_views.py:offboarding_view",
        category="risk",
    ),
    _row(
        "Pay reviews due",
        definition="Compensation records whose next pay review falls within 30 days.",
        question="Whose pay review is coming up?",
        numerator="compensation records with next_review_date on or before today + 30 days",
        models=_COMPENSATION,
        owner_page="compensation_benefits",
        location="apps/frontend/views/hr_views.py:compensation_benefits_view",
        category="pending_action",
    ),
    _row(
        "Open incidents",
        definition="Health and safety incidents not yet closed.",
        question="How many safety incidents are still being worked?",
        numerator="safety incidents with status other than closed",
        models=_INCIDENT,
        owner_page="health_safety",
        location="apps/frontend/views/hr_views.py:health_safety_view",
        category="risk",
    ),
    _row(
        "Serious incidents",
        definition="Open health and safety incidents of high or critical severity.",
        question="How many serious safety incidents are open?",
        numerator="open safety incidents with severity high or critical",
        models=_INCIDENT,
        owner_page="health_safety",
        location="apps/frontend/views/hr_views.py:health_safety_view",
        category="risk",
    ),
    _row(
        "Near misses",
        definition="Near misses reported in the last 12 months.",
        question="Are near misses being reported before they become injuries?",
        numerator="safety incidents of category near_miss dated in the last 365 days",
        models=_INCIDENT,
        owner_page="health_safety",
        location="apps/frontend/views/hr_views.py:health_safety_view",
        category="quality",
    ),
    _row(
        "Days lost",
        definition="Working days lost to health and safety incidents in the last 12 months.",
        question="What have incidents cost in working time?",
        numerator="sum of days_lost for safety incidents dated in the last 365 days",
        models=_INCIDENT,
        owner_page="health_safety",
        location="apps/frontend/views/hr_views.py:health_safety_view",
        category="outcome",
        unit="days",
    ),
    _row(
        "Recognitions",
        definition="Recognitions given to staff in the last quarter (91 days).",
        question="Is good work being recognised?",
        numerator="staff recognitions awarded in the last 91 days",
        models=_RECOGNITION,
        owner_page="recognition",
        location="apps/frontend/views/hr_views.py:recognition_view",
        category="outcome",
    ),
    _row(
        "People recognised",
        definition="Distinct staff recognised in the last quarter (91 days).",
        question="How widely is recognition reaching staff?",
        numerator="distinct staff with a recognition in the last 91 days",
        models=_RECOGNITION,
        owner_page="recognition",
        location="apps/frontend/views/hr_views.py:recognition_view",
        category="progress",
    ),
    _row(
        "Open surveys",
        definition="Staff pulse surveys currently collecting answers.",
        question="Is a pulse survey running?",
        numerator="pulse surveys with status open",
        models=_PULSE,
        owner_page="pulse_surveys",
        location="apps/frontend/views/hr_views.py:pulse_surveys_view",
        category="scale",
    ),
    _row(
        "Latest morale score",
        definition=(
            "The average score, out of 5, across the five pulse statements in the "
            "most recent survey with at least five answers."
        ),
        question="How do staff feel about their work at Edify?",
        numerator="mean of per-statement averages in the latest survey above the anonymity floor",
        models=_PULSE,
        owner_page="pulse_surveys",
        location="apps/frontend/views/hr_views.py:pulse_surveys_view",
        category="outcome",
        unit="score",
    ),
    _row(
        "Published policies",
        definition="Policies and manuals published or in effect for the director's countries.",
        question="How many policies are in force?",
        numerator="policy and manual documents with status published or effective",
        models=_DOCUMENTS,
        owner_page="policies",
        location="apps/frontend/views/hr_views.py:policies_view",
        category="scale",
    ),
    _row(
        "Policies in review",
        definition="Policies and manuals in draft, under review or returned for correction.",
        question="How many policy changes are waiting on a decision?",
        numerator="policy and manual documents with status draft, under_review or returned",
        models=_DOCUMENTS,
        owner_page="policies",
        location="apps/frontend/views/hr_views.py:policies_view",
        category="pending_action",
    ),
    _row(
        "Acknowledgement rate",
        definition=(
            "Agreed acknowledgements as a share of every acknowledgement requested "
            "on current policy versions, for the people the director oversees."
        ),
        question="Have staff acknowledged the policies that apply to them?",
        numerator="acknowledgements with state agreed on current versions",
        denominator=(
            "acknowledgements with state agreed, pending or disagreed on current "
            "versions, for people in the director's reach"
        ),
        models=_DOCUMENTS,
        owner_page="policies",
        location="apps/frontend/views/hr_views.py:policies_view",
        category="compliance",
        unit="percent",
    ),
    _row(
        "Policy reviews due",
        definition="Policies whose current version's review date falls within 60 days.",
        question="Which policies are due for review?",
        numerator="policy and manual documents whose current version review_date is within 60 days",
        models=_DOCUMENTS,
        owner_page="policies",
        location="apps/frontend/views/hr_views.py:policies_view",
        category="pending_action",
    ),
    _row(
        "Disagreements",
        definition="Staff who did not agree to a current policy version.",
        question="Who has not agreed to a policy, and needs a conversation?",
        numerator="acknowledgements with state disagreed on current versions",
        models=_DOCUMENTS,
        owner_page="policies",
        location="apps/frontend/views/hr_views.py:policies_view",
        category="risk",
    ),
    _row(
        "Officers you review",
        definition=(
            "People the viewer is the performance reviewer for under the "
            "reporting rule, excluding themself and removed accounts."
        ),
        question="Whose performance conversations am I responsible for?",
        numerator="apps.hr.performance_engine.team_review_rows rows",
        models=_PEOPLE,
        owner_page="performance_reviews",
        location=_TEAM_REVIEW_LOCATION,
        roles=("Program Lead",),
        scope=_TEAM_REVIEW_SCOPE,
    ),
    _row(
        "Waiting on you as reviewer",
        definition=(
            "People whose annual agreement waits on the reviewer to agree "
            "priorities, or whose open quarterly conversation is not yet "
            "signed off."
        ),
        question="Which conversations need my action as reviewer now?",
        numerator=(
            "team_review_rows with agreement_waiting (stage "
            "priorities_manager_review) or hold_needed (open window snapshot, "
            "not signed off)"
        ),
        models=_REVIEW_PROGRESS,
        owner_page="performance_reviews",
        location=_TEAM_REVIEW_LOCATION,
        category="pending_action",
        roles=("Program Lead",),
        scope=_TEAM_REVIEW_SCOPE,
    ),
    _row(
        "Reviews past due",
        definition=(
            "People with at least one review for the FY past its due date and "
            "not closed, acknowledged or archived."
        ),
        question="Which of my team's reviews are late?",
        numerator="team_review_rows with overdue_reviews",
        models=_REVIEWS,
        owner_page="performance_reviews",
        location=_TEAM_REVIEW_LOCATION,
        category="risk",
        roles=("Program Lead",),
        scope=_TEAM_REVIEW_SCOPE,
    ),
    _row(
        "Agreements completed",
        definition=(
            "People whose annual agreement for the FY is closed, acknowledged "
            "by the employee, or signed and archived."
        ),
        question="How many of my team's review years are finished?",
        numerator="team_review_rows whose annual review stage is in REVIEW_DONE_STAGES",
        models=_REVIEWS,
        owner_page="performance_reviews",
        location=_TEAM_REVIEW_LOCATION,
        category="progress",
        roles=("Program Lead",),
        scope=_TEAM_REVIEW_SCOPE,
    ),
)
