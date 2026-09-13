"""The Regional HR Director Dashboard.

The HR role is the Regional Human Resource Director (owner, 2026-09-12). They
work with the Regional Vice President and the Country Directors of a region to
staff, develop and care for Edify's people, and they administer the HR
programmes by name: compensation, benefits, leave, disciplinary matters,
disputes and investigations, performance and talent, productivity, recognition
and morale, occupational health and safety, and training and development, in
compliance with each country's employment law.

This page used to be an organisation-wide people cockpit. Its figures matched
strings nothing writes ("Open", "Completed", "Strong", "Initiated", "Active"),
so most tiles read zero whatever happened; the recruitment funnel, workforce
trend, leave and performance charts ignored the director's region; and it had
nothing at all on employee relations, safety, morale, development or policy
(HR audit, 2026-09-13).

Every figure now comes from the workflow records the HR registers write,
bounded by ``apps.hr.reach.people_reach`` and narrowed by the page's filters.
A filter can narrow the reach, never widen it. The sections follow the role
description: staffing and retention, performance and talent, employee
relations and wellbeing, policy and compliance, then leave, pay and benefits.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from functools import cached_property
from statistics import median

from django.db.models import Count, Q, Sum

from apps.accounts.models import CalendarBlock, Leave, PublicHoliday, StaffProfile
from apps.core.metrics import render_precomputed_metric_item
from apps.core.metrics.ratio import percentage

ROLE_LABELS = {
    "CCEO": "CCEOs",
    "Program Lead": "Program Leads",
    "RegionalProgramLead": "Regional Programme Leads",
    "CountryDirector": "Country Directors",
    "RegionalVicePresident": "RVPs",
    "ImpactAssessment": "Impact Assessment",
    "Accountant": "Accountants",
    "HumanResources": "HR",
    "ProjectCoordinator": "Project Coordinators",
    "PartnerFieldOfficer": "Partner Officers",
    "PartnerAdmin": "Partner Admins",
    "Admin": "Admins",
}

LEAVE_TYPE_LABELS = {
    "personal_time_off": "Personal time off",
    "annual_leave": "Annual leave",
    "sick_leave": "Sick leave",
    "maternity_leave": "Maternity leave",
    "paternity_leave": "Paternity leave",
    "bereavement_leave": "Bereavement",
}

#: Review stages a completed review rests in.
DONE_REVIEW_STAGES = ("closed", "employee_acknowledged", "signed_and_archived")

#: The review journey, folded into the steps a director follows a cycle by.
REVIEW_STAGE_BUCKETS = (
    (
        "priorities",
        "Setting priorities",
        ("not_started", "priorities_draft", "priorities_manager_review"),
    ),
    (
        "reflection",
        "Agreed, in reflection",
        ("priorities_agreed", "employee_reflection"),
    ),
    (
        "assessment",
        "With managers",
        (
            "manager_assessment",
            "manager_review_complete",
            "functional_manager_complete",
        ),
    ),
    (
        "calibration",
        "Calibration",
        (
            "calibration",
            "hr_quality_review",
            "ready_for_slt_calibration",
            "slt_calibrated",
        ),
    ),
    (
        "acknowledgement",
        "Awaiting acknowledgement",
        ("awaiting_acknowledgement", "final_rating_confirmed"),
    ),
    ("complete", "Complete", DONE_REVIEW_STAGES),
)

#: Final ratings (PerformanceRating), grouped Exceeds / Met / Below.
RATING_BUCKETS = (
    ("exceeds", "Exceeds", ("far_exceeds", "exceeds")),
    ("met", "Met", ("met",)),
    ("below", "Below", ("met_some", "did_not_meet")),
)

#: Application stages (ApplicationStage), in the order a candidate moves.
RECRUITMENT_STAGES = (
    ("Applied", ("applied",)),
    ("Screening", ("screening",)),
    ("Interview and assessment", ("interview", "assessment")),
    ("Reference check", ("reference_check",)),
    ("Offer", ("offer", "accepted")),
)

ACTIVE_RECOVERY_STATUSES = ("active", "progress_review", "extended")
CLOSED_CASE_STATUSES = ("resolved", "closed")
GRIEVANCE_CASE_TYPES = ("grievance", "dispute", "conflict")
SERIOUS_SEVERITIES = ("high", "critical")

#: A morale score under these reads as a warning, then as a concern.
MORALE_WARNING = 3.5
MORALE_CONCERN = 3.0
#: FY-to-date turnover at or over these reads as a warning, then a concern.
TURNOVER_WARNING = 10.0
TURNOVER_CONCERN = 20.0
#: How far ahead the deadline list and the pay-review count look.
DEADLINE_DAYS = 30
PAY_REVIEW_DAYS = 60


def _clean(value):
    value = (value or "").strip()
    return None if value in ("", "all", "All") else value


def _turnover_rate(leavers, population):
    """Leavers as a share of the people employed, to one decimal: at a
    country's headcount one leaver moves the rate by whole points, so the
    shared whole-number percentage would hide it."""
    if not population:
        return None
    return round(leavers * 100 / population, 1)


def _first_of_next_month(day: date) -> date:
    return date(
        day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1
    )


class _Frame:
    """What one render of the dashboard reads: who, when and where."""

    def __init__(self, user, fy, country, department):
        from apps.core.fy import get_fy_date_range, get_operational_fy
        from apps.hr.reach import people_reach

        self.user = user
        self.today = date.today()
        self.fy = fy or get_operational_fy()
        start, end = get_fy_date_range(self.fy)
        self.fy_start = start.date()
        self.fy_end = end.date()  # exclusive
        # Figures "this FY" count up to today, never into the future.
        self.to_date_end = min(self.today + timedelta(days=1), self.fy_end)
        self.reach = people_reach(user)
        self.country = _clean(country)
        self.department = _clean(department)
        self.profiles = HRDashboardService._visible_profiles(
            user, self.country, self.department
        )
        self.profile_ids = self.profiles.values("id")
        self.active = self.profiles.exclude(onboarding_state="exited").filter(
            user__is_active=True
        )

    @cached_property
    def countries(self) -> list[str]:
        """The countries this render reports on, in order."""
        if self.reach.is_everything:
            names = set(
                self.profiles.exclude(country="").values_list("country", flat=True)
            )
            if self.country:
                names &= {self.country}
            return sorted(names)
        names = list(self.reach.countries)
        if self.country:
            names = [c for c in names if c == self.country]
        return names

    def by_country(self, queryset, field="country"):
        """Narrow a record that carries its own country to the reach and filter."""
        from apps.hr.reach import scope_by_country

        queryset = scope_by_country(queryset, self.reach, field)
        if self.country:
            queryset = queryset.filter(**{field: self.country})
        return queryset

    def by_department(self, queryset, field):
        if self.department:
            queryset = queryset.filter(**{field: self.department})
        return queryset

    def in_fy(self, field):
        """A Q for a date field inside the FY, up to today."""
        return Q(**{f"{field}__gte": self.fy_start, f"{field}__lt": self.to_date_end})


class HRDashboardService:
    @staticmethod
    def _visible_profiles(user, country=None, department=None):
        """The staff this viewer may see, honouring the page's own filters.

        Every figure on this page used to be organisation-wide. HR is a
        country function, yet the leave panel named employees and their leave
        type for every country in the org, and the CSV export stamped the
        requested country into a Context column while exporting all of them
        (2026-08-20 HR audit, Critical).
        """
        from apps.hr.reach import people_reach, scope_profiles

        profiles = scope_profiles(
            StaffProfile.objects.select_related("user").filter(
                user__deleted_at__isnull=True
            ),
            people_reach(user),
        )
        # A filter may narrow the scope; it may never widen it.
        if _clean(country):
            profiles = profiles.filter(country=country)
        if _clean(department):
            profiles = profiles.filter(department=department)
        return profiles

    @staticmethod
    def filter_options(user) -> dict:
        """Countries and departments the filter bar may offer: the reach's own."""
        from apps.hr.reach import people_reach, scope_profiles

        reach = people_reach(user)
        departments = (
            scope_profiles(StaffProfile.objects.all(), reach)
            .exclude(department__isnull=True)
            .exclude(department="")
            .values_list("department", flat=True)
            .distinct()
        )
        return {
            "countries": list(reach.filter_options()),
            "departments": sorted(departments),
        }

    @staticmethod
    def get_dashboard(user, fy=None, country=None, department=None) -> dict:
        frame = _Frame(user, fy, country, department)
        visible_count = frame.profiles.count()
        scope_label, scope_warning = HRDashboardService._scope_label(
            user, frame.country, frame.department, visible_count
        )

        staffing = _staffing(frame)
        recruitment = _recruitment(frame)
        for row in staffing["rows"]:
            row["open_roles"] = recruitment["open_by_country"].get(row["country"], 0)
            row["awaiting_approval"] = recruitment["pending_by_country"].get(
                row["country"], 0
            )
        performance = _performance(frame)
        development = _development(frame, staffing["headcount"])
        relations = _relations(frame)
        safety = _safety(frame)
        morale = _morale(frame)
        recognition = _recognition(frame)
        leave = _leave(frame)
        compensation = _compensation(frame, staffing["headcount"])
        compliance = _compliance(frame)
        policies = _policies(frame)
        deadlines = _deadlines(frame)
        hr_today = _hr_today(user)
        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        # The people and capacity signals CCEOs, Programme Leads and partners
        # raise in their field debriefs, through the debriefs' own role scope.
        # The HR sidebar leaves Field Debrief to the people who file them, so
        # this card is where the director reads it (apps/core/navigation.py).
        field_signals = field_debrief_intelligence_summary(user)

        motivation = _motivation_rows(
            frame, staffing, morale, relations, safety, recognition, leave
        )
        attention = _attention(
            staffing,
            recruitment,
            performance,
            development,
            relations,
            safety,
            morale,
            leave,
            compensation,
            compliance,
            policies,
        )

        return {
            "fy": frame.fy,
            "scope_label": scope_label,
            "scope_warning": scope_warning,
            "reach_assigned": frame.reach.assigned,
            "reach_countries": frame.countries,
            "kpi_strip_items": _kpi_items(
                staffing,
                recruitment,
                performance,
                relations,
                safety,
                morale,
                compliance,
            ),
            "attention": attention,
            "hr_today": hr_today,
            "staffing": staffing,
            "workforce_by_country": staffing["rows"],
            "workforce_overview": staffing["trend"],
            "headcount_by_role": staffing["roles"],
            "headcount_by_department": staffing["departments"],
            "recruitment": recruitment,
            "recruitment_funnel": recruitment["funnel"],
            "performance": performance,
            "performance_overview": performance["ratings_chart"],
            "development": development,
            "relations": relations,
            "safety": safety,
            "morale": morale,
            "recognition": recognition,
            "motivation_rows": motivation,
            "leave": leave,
            "leave_overview": leave["by_type"],
            "holidays": leave["holidays"],
            "compensation": compensation,
            "compliance": compliance,
            "compliance_status": compliance["requirements"],
            "policies": policies,
            "deadlines": deadlines,
            "field_debrief_intel": field_signals,
            "quick_actions": QUICK_ACTIONS,
            "roles": staffing["roles_list"],
            # Headline values the view and the mobile home read directly.
            "open_positions": recruitment["open"],
            "reviews_due": performance["open"],
            "reviews_overdue": performance["overdue"],
            "employees_on_leave": leave["on_leave_today"],
            "coverage_conflicts": leave["coverage_clashes"],
            "documents_expiring": compliance["due_soon"],
        }

    @staticmethod
    def _scope_label(user, country, department, visible_count):
        """Say plainly whose figures these are, and why there are none."""
        from apps.hr.reach import NONE, people_reach

        reach = people_reach(user)
        if reach.kind != NONE:
            where = reach.label()
        else:
            return (
                "No scope",
                "Your account has no People record, so there is no country or "
                "team to report on. Ask an administrator to create your staff "
                "profile.",
            )
        parts = [where]
        if _clean(country):
            parts.append(country)
        if _clean(department):
            parts.append(department)
        label = " · ".join(dict.fromkeys(parts))
        if not visible_count:
            return label, f"No staff records match {label}."
        return label, ""

    @staticmethod
    def _coverage_clashes(today, wk_end_iso, profile_ids=None) -> int:
        """Approved leave in the next 7 days overlapping the staff member's own
        scheduled activities — the real coverage risk HR must resolve."""
        from apps.activities.models import Activity

        clashes = 0
        leaves = Leave.objects.filter(
            status="approved",
            start_date__lte=wk_end_iso,
            end_date__gte=today.isoformat(),
        ).select_related("staff")
        if profile_ids is not None:
            leaves = leaves.filter(staff_id__in=profile_ids)
        for lv in leaves:
            ids = {lv.staff_id}
            if lv.staff and lv.staff.user_id:
                ids.add(lv.staff.user_id)
            if (
                Activity.objects.filter(
                    responsible_staff_id__in=ids,
                    deleted_at__isnull=True,
                    scheduled_date__date__gte=lv.start_date,
                    scheduled_date__date__lte=lv.end_date,
                )
                .exclude(status__in=("cancelled", "completed", "closed"))
                .exists()
            ):
                clashes += 1
        return clashes


# ── Staffing, recruiting and retention ───────────────────────────────────────
def _staffing(frame: _Frame) -> dict:
    """Headcount, joiners, leavers and turnover, by country and by month."""
    from apps.hr.models import VOLUNTARY_EXIT_REASONS, OffboardingPlan, OnboardingPlan

    profiles = list(
        frame.profiles.values_list(
            "id",
            "country",
            "onboarding_state",
            "user__is_active",
            "created_at",
            "department",
            "user__active_role",
        )
    )
    exits = {
        staff_id: (country, last_day, reason, status)
        for staff_id, country, last_day, reason, status in OffboardingPlan.objects.filter(
            staff_id__in=frame.profile_ids
        ).values_list(
            "staff_id", "staff__country", "last_working_day", "exit_reason", "status"
        )
    }
    starts = {
        staff_id: (start or created.date())
        for staff_id, start, created in OnboardingPlan.objects.filter(
            staff_id__in=frame.profile_ids
        ).values_list("staff_id", "start_date", "created_at")
    }

    headcount = Counter()
    population = Counter()
    joiners = Counter()
    leavers = Counter()
    voluntary = Counter()
    leaving_soon = Counter()
    roles = Counter()
    departments = Counter()
    for staff_id, country, state, is_active, created, department, role in profiles:
        exit_row = exits.get(staff_id)
        last_day = exit_row[1] if exit_row else None
        if state != "exited" and is_active:
            headcount[country] += 1
            roles[role or "Unassigned"] += 1
            departments[department or "No department recorded"] += 1
        # Employed at some point this FY: joined before today and not gone
        # before the FY began. An exited record with no exit date cannot be
        # placed in time and is left out rather than guessed.
        if created.date() < frame.to_date_end and not (
            (last_day and last_day < frame.fy_start)
            or (state == "exited" and not last_day)
        ):
            population[country] += 1
        start = starts.get(staff_id)
        if start and frame.fy_start <= start < frame.to_date_end:
            joiners[country] += 1
        if last_day and frame.fy_start <= last_day < frame.to_date_end:
            leavers[country] += 1
            if exit_row[2] in VOLUNTARY_EXIT_REASONS:
                voluntary[country] += 1
        if (
            exit_row
            and exit_row[3] != "Closed"
            and last_day
            and last_day >= frame.today
        ):
            leaving_soon[country] += 1

    rows = []
    for country in frame.countries:
        turnover = _turnover_rate(leavers[country], population[country])
        rows.append(
            {
                "country": country,
                "headcount": headcount[country],
                "joiners": joiners[country],
                "leavers": leavers[country],
                "voluntary": voluntary[country],
                "turnover": turnover,
                "leaving_soon": leaving_soon[country],
                "tone": _turnover_tone(turnover),
            }
        )
    total_turnover = _turnover_rate(sum(leavers.values()), sum(population.values()))
    return {
        "rows": rows,
        "headcount": sum(headcount.values()),
        "joiners": sum(joiners.values()),
        "leavers": sum(leavers.values()),
        "voluntary": sum(voluntary.values()),
        "leaving_soon": sum(leaving_soon.values()),
        "population": sum(population.values()),
        "turnover": total_turnover,
        "turnover_tone": _turnover_tone(total_turnover),
        "trend": _workforce_trend(frame, profiles, exits, starts),
        "roles": {
            "rows": [
                {
                    "role": r,
                    "label": ROLE_LABELS.get(r, r),
                    "count": n,
                    "pct": percentage(n, sum(roles.values())) or 0,
                }
                for r, n in roles.most_common()
            ],
        },
        "roles_list": [
            {"role": r, "label": ROLE_LABELS.get(r, r), "count": n}
            for r, n in roles.most_common()
        ],
        "departments": {
            "labels": [d for d, _ in departments.most_common()],
            "counts": [n for _, n in departments.most_common()],
        },
    }


def _turnover_tone(turnover) -> str:
    if turnover is None:
        return "neutral"
    if turnover >= TURNOVER_CONCERN:
        return "danger"
    if turnover >= TURNOVER_WARNING:
        return "warning"
    return "success"


def _workforce_trend(frame: _Frame, profiles, exits, starts) -> dict:
    """Month by month through the FY: headcount at month end, joiners, leavers.

    There is no headcount snapshot table, so a month's headcount is rebuilt
    from when each record was created and the last working day on its
    offboarding plan.
    """
    months = []
    cursor = frame.fy_start
    last = min(frame.today, frame.fy_end - timedelta(days=1))
    while cursor <= last:
        months.append((cursor, _first_of_next_month(cursor)))
        cursor = _first_of_next_month(cursor)

    labels, headcount, new_hires, departures = [], [], [], []
    for start, end in months:
        labels.append(start.strftime("%b %Y"))
        count = 0
        for staff_id, _country, state, _active, created, _dept, _role in profiles:
            exit_row = exits.get(staff_id)
            last_day = exit_row[1] if exit_row else None
            if created.date() >= end:
                continue
            if last_day and last_day < end:
                continue
            if state == "exited" and not last_day:
                continue
            count += 1
        headcount.append(count)
        new_hires.append(sum(1 for day in starts.values() if start <= day < end))
        departures.append(
            sum(1 for row in exits.values() if row[1] and start <= row[1] < end)
        )
    return {
        "months": labels,
        "headcount": headcount,
        "new_hires": new_hires,
        "exits": departures,
    }


def _recruitment(frame: _Frame) -> dict:
    """Vacancies, the candidate pipeline and how long a hire takes."""
    from apps.hr.models import Application, Vacancy

    vacancies = frame.by_department(
        frame.by_country(Vacancy.objects.all()), "department"
    )
    by_status = Counter()
    open_by_country = Counter()
    pending_by_country = Counter()
    replacements = 0
    for country, status, kind in vacancies.values_list(
        "country", "status", "replacement_or_new_role"
    ):
        status = (status or "").lower()
        by_status[status] += 1
        if status == "open":
            open_by_country[country] += 1
            if kind == "replacement":
                replacements += 1
        elif status == "pending_approval":
            pending_by_country[country] += 1

    applications = frame.by_department(
        frame.by_country(Application.objects.all(), "vacancy__country"),
        "vacancy__department",
    )
    stages = dict(applications.values_list("stage").annotate(n=Count("id")))
    hired = list(
        applications.filter(stage="hired")
        .filter(
            frame.in_fy("provisioned_at__date")
            | (Q(provisioned_at__isnull=True) & frame.in_fy("updated_at__date"))
        )
        .values_list("provisioned_at", "vacancy__approved_at", "vacancy__created_at")
    )
    days = [
        (provisioned.date() - (approved or created).date()).days
        for provisioned, approved, created in hired
        if provisioned and (approved or created)
    ]
    funnel = [
        {"stage": label, "count": sum(stages.get(code, 0) for code in codes)}
        for label, codes in RECRUITMENT_STAGES
    ]
    funnel.append({"stage": "Hired this FY", "count": len(hired)})
    return {
        "open": by_status["open"],
        "pending_approval": by_status["pending_approval"],
        "approved": by_status["approved"],
        "replacements": replacements,
        "open_by_country": dict(open_by_country),
        "pending_by_country": dict(pending_by_country),
        "in_pipeline": sum(item["count"] for item in funnel[:-1]),
        "hired": len(hired),
        "median_days_to_hire": round(median(days)) if days else None,
        "funnel": funnel,
    }


# ── Performance, talent and development ──────────────────────────────────────
def _performance(frame: _Frame) -> dict:
    from apps.hr.models import PerformanceImprovementPlan, PerformanceReview

    reviews = PerformanceReview.objects.filter(staff_id__in=frame.profile_ids).filter(
        Q(fy=frame.fy)
        | Q(fy__isnull=True, due_date__gte=frame.fy_start, due_date__lt=frame.fy_end)
    )
    stages = dict(reviews.values_list("stage").annotate(n=Count("id")))
    total = sum(stages.values())
    buckets = []
    for key, label, codes in REVIEW_STAGE_BUCKETS:
        count = sum(stages.get(code, 0) for code in codes)
        buckets.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "pct": percentage(count, total) or 0,
            }
        )
    complete = buckets[-1]["count"]
    overdue = (
        reviews.exclude(stage__in=DONE_REVIEW_STAGES)
        .filter(due_date__lt=frame.today)
        .count()
    )

    rating_codes = [code for _, _, codes in RATING_BUCKETS for code in codes]
    by_country = defaultdict(Counter)
    for country, rating, n in (
        reviews.filter(rating__in=rating_codes)
        .values_list("staff__country", "rating")
        .annotate(n=Count("id"))
    ):
        for key, _, codes in RATING_BUCKETS:
            if rating in codes:
                by_country[country][key] += n
                by_country["All staff"][key] += n
    categories = ["All staff"] + [c for c in frame.countries if by_country.get(c)][:5]
    ratings_chart = {
        "categories": categories,
        "strong": [by_country[c]["exceeds"] for c in categories],
        "fair": [by_country[c]["met"] for c in categories],
        "at_risk": [by_country[c]["below"] for c in categories],
    }
    rated = sum(by_country["All staff"].values())

    plans = list(
        PerformanceImprovementPlan.objects.filter(
            staff_id__in=frame.profile_ids, status__in=ACTIVE_RECOVERY_STATUSES
        ).values_list("plan_type", "end_date")
    )
    soon = frame.today + timedelta(days=DEADLINE_DAYS)
    return {
        "total": total,
        "complete": complete,
        "open": total - complete,
        "completion": percentage(complete, total),
        "overdue": overdue,
        "stages": buckets,
        "rated": rated,
        "ratings": [
            {
                "key": key,
                "label": label,
                "count": by_country["All staff"][key],
                "pct": percentage(by_country["All staff"][key], rated) or 0,
            }
            for key, label, _ in RATING_BUCKETS
        ],
        "ratings_chart": ratings_chart,
        "recovery_active": len(plans),
        "recovery_formal": sum(1 for kind, _ in plans if kind == "formal"),
        "recovery_informal": sum(1 for kind, _ in plans if kind != "formal"),
        "recovery_ending_soon": sum(
            1 for _, end in plans if end and frame.today <= end <= soon
        ),
        "recovery_past_end": sum(1 for _, end in plans if end and end < frame.today),
    }


def _development(frame: _Frame, headcount: int) -> dict:
    """Professional development requests for the FY (apps.professional_development)."""
    from apps.professional_development.hr_dashboard_service import (
        EMPLOYEE_DONE_STATUSES,
        IN_PROGRESS_STATUSES,
        INACTIVE_STATUSES,
        PENDING_CERT_STATUSES,
        SIGNED_OFF_STATUSES,
    )
    from apps.professional_development.models import (
        PDStatus,
        ProfessionalDevelopmentRequest,
    )

    requests = ProfessionalDevelopmentRequest.objects.filter(
        fy=frame.fy, staff_id__in=frame.profile_ids
    ).exclude(status=PDStatus.DRAFT)
    statuses = dict(requests.values_list("status").annotate(n=Count("id")))

    def total(codes):
        return sum(statuses.get(code, 0) for code in codes)

    participants = (
        requests.exclude(status__in=INACTIVE_STATUSES)
        .values("staff_id")
        .distinct()
        .count()
    )
    return {
        "requests": sum(statuses.values()),
        "awaiting_hr": total((PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION)),
        "awaiting_signoff": statuses.get(PDStatus.AWAITING_HR_SIGNOFF, 0),
        "in_progress": total(IN_PROGRESS_STATUSES) + total(PENDING_CERT_STATUSES),
        "completed": total(EMPLOYEE_DONE_STATUSES) + total(SIGNED_OFF_STATUSES),
        "participants": participants,
        "participation": percentage(participants, headcount),
    }


# ── Employee relations, safety, morale and recognition ───────────────────────
def _relations(frame: _Frame) -> dict:
    """Counts over every case in the director's countries, confidential ones
    included, exactly as the Employee Relations register counts them: the
    director knows a confidential case exists without seeing whom it concerns.
    """
    from apps.hr.models import EmployeeRelationsCase

    cases = frame.by_department(
        frame.by_country(EmployeeRelationsCase.objects.all()),
        "subject_staff__department",
    )
    open_rows = list(
        cases.exclude(status__in=CLOSED_CASE_STATUSES).values_list(
            "country", "case_type", "severity", "status", "opened_at", "created_at"
        )
    )
    oldest = None
    by_country = defaultdict(Counter)
    for country, case_type, severity, status, opened, created in open_rows:
        by_country[country]["open"] += 1
        if case_type == "disciplinary":
            by_country[country]["disciplinary"] += 1
        if case_type in GRIEVANCE_CASE_TYPES:
            by_country[country]["grievances"] += 1
        age = (frame.today - (opened or created).date()).days
        oldest = age if oldest is None else max(oldest, age)
    statuses = Counter(row[3] for row in open_rows)
    return {
        "open": len(open_rows),
        "awaiting_triage": statuses["submitted"] + statuses["triage"],
        "investigating": statuses["investigation"] + statuses["findings"],
        "deciding": statuses["action"] + statuses["appeal"],
        "disciplinary": sum(1 for row in open_rows if row[1] == "disciplinary"),
        "grievances": sum(1 for row in open_rows if row[1] in GRIEVANCE_CASE_TYPES),
        "serious": sum(1 for row in open_rows if row[2] in SERIOUS_SEVERITIES),
        "oldest_days": oldest,
        "closed_fy": cases.filter(status__in=CLOSED_CASE_STATUSES)
        .filter(frame.in_fy("closed_at__date"))
        .count(),
        "by_country": {c: dict(v) for c, v in by_country.items()},
    }


def _safety(frame: _Frame) -> dict:
    from apps.hr.models import SafetyIncident

    incidents = frame.by_department(
        frame.by_country(SafetyIncident.objects.all()), "affected_staff__department"
    )
    open_rows = list(
        incidents.exclude(status="closed").values_list("country", "severity")
    )
    this_fy = incidents.filter(frame.in_fy("incident_date"))
    fy_rows = list(this_fy.values_list("country", "category", "days_lost"))
    open_by_country = Counter(country for country, _ in open_rows)
    return {
        "open": len(open_rows),
        "serious": sum(
            1 for _, severity in open_rows if severity in SERIOUS_SEVERITIES
        ),
        "reported_fy": len(fy_rows),
        "near_misses_fy": sum(
            1 for _, category, _ in fy_rows if category == "near_miss"
        ),
        "days_lost_fy": sum(days or 0 for _, _, days in fy_rows),
        "open_by_country": dict(open_by_country),
    }


def _pulse_scores(responses) -> tuple[float | None, list[tuple[str, float]]]:
    """Mean of the per-statement averages, as the survey drawer computes it."""
    from apps.hr.models import PULSE_QUESTIONS

    averages = []
    for key, statement in PULSE_QUESTIONS:
        values = [r.get(key) for r in responses if r.get(key)]
        if values:
            averages.append((statement, round(sum(values) / len(values), 1)))
    if not averages:
        return None, []
    return round(sum(a for _, a in averages) / len(averages), 1), averages


def _morale(frame: _Frame) -> dict:
    """The latest pulse result for each country, above the anonymity floor.

    A country's score is shown only once at least PULSE_MIN_RESPONSES people in
    that country answered the same survey, so no one's answer can be inferred.
    """
    from apps.hr.models import PULSE_MIN_RESPONSES, PulseResponse, PulseSurvey

    countries = set(frame.countries)
    surveys = [
        survey
        for survey in PulseSurvey.objects.order_by("-closes_on", "-created_at")[:40]
        if countries & set(survey.countries or [])
    ]
    open_surveys = [
        s for s in surveys if s.status == "open" and s.closes_on >= frame.today
    ]
    answers = defaultdict(list)
    for survey_id, country, scores in PulseResponse.objects.filter(
        survey_id__in=[s.id for s in surveys], country__in=countries
    ).values_list("survey_id", "country", "scores"):
        answers[(survey_id, country)].append(scores or {})

    by_country = {}
    for country in frame.countries:
        for survey in surveys:
            responses = answers.get((survey.id, country), [])
            if len(responses) >= PULSE_MIN_RESPONSES:
                score, statements = _pulse_scores(responses)
                lowest = (
                    min(statements, key=lambda item: item[1]) if statements else None
                )
                by_country[country] = {
                    "score": score,
                    "responses": len(responses),
                    "survey": survey.title,
                    "closes_on": survey.closes_on,
                    "lowest": {"statement": lowest[0], "score": lowest[1]}
                    if lowest
                    else None,
                    "tone": _morale_tone(score),
                }
                break

    overall = None
    for survey in surveys:
        responses = [
            scores
            for country in countries
            for scores in answers.get((survey.id, country), [])
        ]
        if len(responses) >= PULSE_MIN_RESPONSES:
            score, statements = _pulse_scores(responses)
            overall = {
                "score": score,
                "responses": len(responses),
                "survey": survey.title,
                "closes_on": survey.closes_on,
                "statements": [{"statement": s, "score": v} for s, v in statements],
                "tone": _morale_tone(score),
            }
            break
    return {
        "overall": overall,
        "by_country": by_country,
        "open_surveys": len(open_surveys),
        "open_answers": sum(
            len(answers.get((s.id, country), []))
            for s in open_surveys
            for country in countries
        ),
        "low_countries": [
            country
            for country, result in by_country.items()
            if result["score"] is not None and result["score"] < MORALE_CONCERN
        ],
        "min_responses": PULSE_MIN_RESPONSES,
    }


def _morale_tone(score) -> str:
    if score is None:
        return "neutral"
    if score < MORALE_CONCERN:
        return "danger"
    if score < MORALE_WARNING:
        return "warning"
    return "success"


def _recognition(frame: _Frame) -> dict:
    from apps.hr.models import StaffRecognition

    recognitions = frame.by_department(
        frame.by_country(StaffRecognition.objects.all()), "staff__department"
    ).filter(frame.in_fy("awarded_on"))
    rows = list(recognitions.values_list("country", "staff_id"))
    return {
        "fy": len(rows),
        "people": len({staff for _, staff in rows}),
        "by_country": dict(Counter(country for country, _ in rows)),
    }


def _motivation_rows(frame, staffing, morale, relations, safety, recognition, leave):
    """What to raise with each Country Director and the RVP, country by country."""
    headcount = {row["country"]: row["headcount"] for row in staffing["rows"]}
    voluntary = {row["country"]: row["voluntary"] for row in staffing["rows"]}
    rows = []
    for country in frame.countries:
        cases = relations["by_country"].get(country, {})
        sick_days = leave["sick_days_by_country"].get(country, 0)
        people = headcount.get(country, 0)
        rows.append(
            {
                "country": country,
                "morale": morale["by_country"].get(country),
                "sick_days": sick_days,
                "sick_days_per_head": round(sick_days / people, 1) if people else None,
                "grievances": cases.get("grievances", 0),
                "disciplinary": cases.get("disciplinary", 0),
                "safety_open": safety["open_by_country"].get(country, 0),
                "voluntary_exits": voluntary.get(country, 0),
                "recognitions": recognition["by_country"].get(country, 0),
            }
        )
    return rows


# ── Leave, pay and benefits ──────────────────────────────────────────────────
def _leave(frame: _Frame) -> dict:
    today_iso = frame.today.isoformat()
    leaves = Leave.objects.filter(staff_id__in=frame.profile_ids)
    approved_fy = leaves.filter(
        status="approved",
        start_date__gte=frame.fy_start.isoformat(),
        start_date__lt=frame.to_date_end.isoformat(),
    )
    by_type = list(
        approved_fy.values_list("type")
        .annotate(days=Sum("days"), n=Count("id"))
        .order_by("-days")
    )
    sick = dict(
        approved_fy.filter(type="sick_leave")
        .values_list("staff__country")
        .annotate(days=Sum("days"))
    )
    week_end = (frame.today + timedelta(days=7)).isoformat()
    return {
        "pending": leaves.filter(status="pending").count(),
        "on_leave_today": leaves.filter(
            status="approved", start_date__lte=today_iso, end_date__gte=today_iso
        ).count(),
        "coverage_clashes": HRDashboardService._coverage_clashes(
            frame.today, week_end, frame.profile_ids
        ),
        "days_fy": sum(days or 0 for _, days, _ in by_type),
        "sick_days_fy": sum(sick.values()),
        "sick_days_by_country": {k: v or 0 for k, v in sick.items()},
        "by_type": {
            "labels": [
                LEAVE_TYPE_LABELS.get(kind, (kind or "Other").replace("_", " ").title())
                for kind, _, _ in by_type
            ],
            "counts": [days or 0 for _, days, _ in by_type],
        },
        "holidays": _holidays(frame.today, frame.countries),
    }


def _holidays(today: date, countries) -> list[dict]:
    """Upcoming public holidays from both sources, PublicHoliday rows and
    CalendarBlock(PUBLIC_HOLIDAY) rows, which must be unioned."""
    days = {}
    for holiday in PublicHoliday.objects.filter(date__gte=today).order_by("date")[:20]:
        days[holiday.date] = holiday.name
    for block in CalendarBlock.objects.filter(
        block_type="PUBLIC_HOLIDAY", is_active=True, end_date__gte=today
    )[:20]:
        day = max(block.start_date, today)
        while day <= block.end_date:
            days.setdefault(day, block.title)
            day += timedelta(days=1)
    return [{"date": d, "name": name} for d, name in sorted(days.items())[:5]]


def _compensation(frame: _Frame, headcount: int) -> dict:
    from apps.hr.models import CompensationRecord

    records = list(
        CompensationRecord.objects.filter(
            staff_id__in=frame.active.values("id")
        ).values_list("status", "medical_cover", "next_review_date")
    )
    soon = frame.today + timedelta(days=PAY_REVIEW_DAYS)
    covered = sum(1 for _, cover, _ in records if cover and cover != "none")
    return {
        "records": len(records),
        "in_review": sum(1 for status, _, _ in records if status == "HR Review"),
        "reviews_due": sum(
            1 for _, _, day in records if day and frame.today <= day <= soon
        ),
        "reviews_overdue": sum(1 for _, _, day in records if day and day < frame.today),
        "without_record": max(headcount - len(records), 0),
        "medical_cover": percentage(covered, headcount),
    }


# ── Policy and employment-law compliance ─────────────────────────────────────
def _compliance(frame: _Frame) -> dict:
    """Evidence against each requirement, with the employees who have none.

    Completion is compliant records over every obligation: each record, plus
    each mandatory requirement an employee has no record against at all.
    """
    from apps.hr.compliance_service import compliance_gaps, visible_requirements
    from apps.hr.models import EmployeeComplianceRecord

    records = EmployeeComplianceRecord.objects.filter(staff_id__in=frame.profile_ids)
    counts = defaultdict(Counter)
    for requirement_id, status, n in records.values_list(
        "requirement_id", "status"
    ).annotate(n=Count("id")):
        counts[requirement_id][status] += n
    visible = set(frame.profiles.values_list("id", flat=True))
    gaps = Counter(
        requirement.id
        for profile, requirement in compliance_gaps(frame.user)
        if profile.id in visible
    )
    requirements = []
    for requirement in visible_requirements(frame.user).order_by("country", "name"):
        if frame.country and requirement.country not in ("All", frame.country):
            continue
        row = counts.get(requirement.id, Counter())
        missing = row["Missing"] + gaps.get(requirement.id, 0)
        requirements.append(
            {
                "requirement": requirement.name,
                "country": requirement.country,
                "compliant": row["Compliant"],
                "due_soon": row["Due Soon"],
                "expired": row["Expired"],
                "missing": missing,
                "total": sum(row.values()) + gaps.get(requirement.id, 0),
            }
        )
    compliant = sum(r["compliant"] for r in requirements)
    obligations = sum(r["total"] for r in requirements)
    return {
        "requirements": requirements,
        "compliant": compliant,
        "due_soon": sum(r["due_soon"] for r in requirements),
        "expired": sum(r["expired"] for r in requirements),
        "missing": sum(r["missing"] for r in requirements),
        "obligations": obligations,
        "completion": percentage(compliant, obligations),
    }


def _policies(frame: _Frame) -> dict:
    """Policies and manuals for the director's countries, as the Policies page
    reads them: acknowledgement coverage of the people overseen, reviews due."""
    from apps.documents.models import (
        AcknowledgementState,
        DocumentAcknowledgement,
        DocumentAsset,
        DocumentStatus,
        DocumentType,
    )

    documents = DocumentAsset.objects.filter(
        document_type__in=[DocumentType.POLICY, DocumentType.MANUAL]
    ).exclude(status=DocumentStatus.ARCHIVED)
    if not frame.reach.is_everything:
        documents = documents.filter(
            Q(country="") | Q(country__in=list(frame.reach.countries))
        )
    if frame.country:
        documents = documents.filter(Q(country="") | Q(country=frame.country))
    rows = list(
        documents.values_list(
            "current_version_id", "status", "current_version__review_date"
        )
    )
    version_ids = [version for version, _, _ in rows if version]
    states = Counter(
        dict(
            DocumentAcknowledgement.objects.filter(
                version_id__in=version_ids,
                user_id__in=frame.active.exclude(user_id=None).values("user_id"),
            )
            .values_list("state")
            .annotate(n=Count("id"))
        )
    )
    asked = sum(states.values())
    soon = frame.today + timedelta(days=PAY_REVIEW_DAYS)
    return {
        "published": sum(
            1
            for _, status, _ in rows
            if status in (DocumentStatus.PUBLISHED, DocumentStatus.EFFECTIVE)
        ),
        "in_review": sum(
            1
            for _, status, _ in rows
            if status
            in (
                DocumentStatus.DRAFT,
                DocumentStatus.UNDER_REVIEW,
                DocumentStatus.RETURNED,
            )
        ),
        "reviews_due": sum(1 for _, _, day in rows if day and day <= soon),
        "acknowledged": states[AcknowledgementState.AGREED],
        "pending": states[AcknowledgementState.PENDING],
        "disagreed": states[AcknowledgementState.DISAGREED],
        "asked": asked,
        "acknowledgement_rate": percentage(states[AcknowledgementState.AGREED], asked),
    }


# ── Deadlines, HR Today and attention ────────────────────────────────────────
def _deadline(name, country, kind, day, today, url):
    days_left = (day - today).days
    if days_left < 0:
        status, tone = "Overdue", "danger"
    elif days_left <= 5:
        status, tone = "Due Soon", "warning"
    else:
        status, tone = "Upcoming", "neutral"
    return {
        "name": name,
        "country": country or "",
        "type": kind,
        "date": day,
        "due_date": day.strftime("%b %d, %Y"),
        "days_left": days_left,
        "status": status,
        "tone": tone,
        "url": url,
    }


def _deadlines(frame: _Frame, limit: int = 8) -> list[dict]:
    """The next people deadlines in the reach: reviews, probation decisions,
    recovery plan end dates, compliance expiries and last working days."""
    from apps.hr.models import (
        EmployeeComplianceRecord,
        OffboardingPlan,
        OnboardingPlan,
        PerformanceImprovementPlan,
        PerformanceReview,
    )

    horizon = frame.today + timedelta(days=DEADLINE_DAYS)
    today = frame.today
    out = []
    for review in (
        PerformanceReview.objects.filter(
            staff_id__in=frame.profile_ids, due_date__lte=horizon
        )
        .exclude(stage__in=DONE_REVIEW_STAGES)
        .exclude(status__in=("Completed", "Closed"))
        .select_related("staff__user")
        .order_by("due_date")[:limit]
    ):
        out.append(
            _deadline(
                review.staff.user.name,
                review.staff.country,
                review.get_review_type_display(),
                review.due_date,
                today,
                "/performance-reviews",
            )
        )
    for plan in (
        OnboardingPlan.objects.filter(
            staff_id__in=frame.profile_ids,
            probation_review_date__isnull=False,
            probation_review_date__lte=horizon,
        )
        .exclude(status="closed")
        .select_related("staff__user")
        .order_by("probation_review_date")[:limit]
    ):
        out.append(
            _deadline(
                plan.staff.user.name,
                plan.staff.country,
                "Probation decision",
                plan.probation_review_date,
                today,
                "/onboarding",
            )
        )
    for plan in (
        PerformanceImprovementPlan.objects.filter(
            staff_id__in=frame.profile_ids,
            status__in=ACTIVE_RECOVERY_STATUSES,
            end_date__lte=horizon,
        )
        .select_related("staff__user")
        .order_by("end_date")[:limit]
    ):
        out.append(
            _deadline(
                plan.staff.user.name,
                plan.staff.country,
                "Recovery plan outcome",
                plan.end_date,
                today,
                "/recovery-plans",
            )
        )
    for record in (
        EmployeeComplianceRecord.objects.filter(
            staff_id__in=frame.profile_ids,
            expiry_date__isnull=False,
            expiry_date__lte=horizon,
        )
        .select_related("staff__user", "requirement")
        .order_by("expiry_date")[:limit]
    ):
        out.append(
            _deadline(
                record.staff.user.name,
                record.staff.country,
                f"{record.requirement.name} expires",
                record.expiry_date,
                today,
                "/compliance-register",
            )
        )
    for plan in (
        OffboardingPlan.objects.filter(
            staff_id__in=frame.profile_ids,
            last_working_day__isnull=False,
            last_working_day__gte=today,
            last_working_day__lte=horizon,
        )
        .exclude(status="Closed")
        .select_related("staff__user")
        .order_by("last_working_day")[:limit]
    ):
        out.append(
            _deadline(
                plan.staff.user.name,
                plan.staff.country,
                "Last working day",
                plan.last_working_day,
                today,
                "/offboarding",
            )
        )
    out.sort(key=lambda row: (row["date"], row["name"]))
    return out[:limit]


def _hr_today(user) -> dict:
    """HR Today's four queues, counted by the engine that builds that page."""
    from apps.hr.hr_exceptions import grouped_hr_exceptions

    data = grouped_hr_exceptions(user)
    return {
        "groups": [
            {"key": group["key"], "label": group["label"], "count": len(group["items"])}
            for group in data["groups"]
        ],
        "total": data["total"],
        "critical": data["critical_count"],
    }


def _attention(
    staffing,
    recruitment,
    performance,
    development,
    relations,
    safety,
    morale,
    leave,
    compensation,
    compliance,
    policies,
) -> list[dict]:
    """What needs the director this week, most serious first. Only real
    counts above zero appear; an empty list is a calm page, not a broken one."""
    items = []

    def add(tone, rank, title, body, url, action):
        items.append(
            {
                "tone": tone,
                "rank": rank,
                "title": title,
                "body": body,
                "url": url,
                "action": action,
            }
        )

    if safety["serious"]:
        add(
            "danger",
            0,
            f"{safety['serious']} serious safety incident{'s' if safety['serious'] != 1 else ''} open",
            "High or critical incidents still waiting on corrective action.",
            "/health-safety",
            "Open Health & Safety",
        )
    if relations["awaiting_triage"]:
        add(
            "danger" if relations["serious"] else "warning",
            1,
            f"{relations['awaiting_triage']} case{'s' if relations['awaiting_triage'] != 1 else ''} awaiting triage",
            "Employee-relations concerns that have not had a first assessment"
            + (
                f"; {relations['serious']} open case{'s are' if relations['serious'] != 1 else ' is'} high or critical."
                if relations["serious"]
                else "."
            ),
            "/employee-relations",
            "Open Employee Relations",
        )
    if morale["low_countries"]:
        countries = ", ".join(morale["low_countries"])
        add(
            "danger",
            2,
            f"Low staff morale in {countries}",
            f"The latest pulse survey scored under {MORALE_CONCERN:.1f} of 5. Worth raising with the Country Director.",
            "/pulse-surveys",
            "Open Staff Pulse Surveys",
        )
    missing = compliance["missing"] + compliance["expired"]
    if missing:
        add(
            "danger",
            3,
            f"{missing} employment-law obligation{'s' if missing != 1 else ''} unmet",
            "Missing or expired evidence against a country requirement.",
            "/compliance-register",
            "Open Employment Compliance",
        )
    if staffing["turnover_tone"] == "danger":
        add(
            "danger",
            4,
            f"Turnover at {staffing['turnover']}% this FY",
            f"{staffing['leavers']} leaver{'s' if staffing['leavers'] != 1 else ''}, {staffing['voluntary']} voluntary. Review retention with country leadership.",
            "/workforce-planning",
            "Open Workforce Planning",
        )
    if performance["overdue"]:
        add(
            "warning",
            5,
            f"{performance['overdue']} performance review{'s' if performance['overdue'] != 1 else ''} overdue",
            "Reviews past their due date and not yet complete.",
            "/performance-reviews",
            "Open Performance Reviews",
        )
    if recruitment["pending_approval"]:
        add(
            "warning",
            6,
            f"{recruitment['pending_approval']} vacancy request{'s' if recruitment['pending_approval'] != 1 else ''} awaiting approval",
            "Staffing requests waiting on the Country Director.",
            "/recruitment",
            "Open Recruitment",
        )
    waiting = development["awaiting_hr"] + development["awaiting_signoff"]
    if waiting:
        add(
            "warning",
            7,
            f"{waiting} development request{'s' if waiting != 1 else ''} waiting on HR",
            "Professional development requests to approve or sign off.",
            "/cpd-learning",
            "Open CPD & Learning",
        )
    if leave["coverage_clashes"]:
        add(
            "warning",
            8,
            f"{leave['coverage_clashes']} leave coverage clash{'es' if leave['coverage_clashes'] != 1 else ''} this week",
            "Approved leave overlapping the person's own scheduled field work.",
            "/leave/coverage",
            "Open Leave Coverage",
        )
    if compensation["reviews_overdue"]:
        add(
            "warning",
            9,
            f"{compensation['reviews_overdue']} pay review{'s' if compensation['reviews_overdue'] != 1 else ''} overdue",
            "Compensation records past their next review date.",
            "/compensation-benefits",
            "Open Compensation & Benefits",
        )
    if policies["reviews_due"]:
        add(
            "warning",
            10,
            f"{policies['reviews_due']} polic{'ies' if policies['reviews_due'] != 1 else 'y'} due for review",
            f"Policies and manuals with a review date inside {PAY_REVIEW_DAYS} days.",
            "/policies",
            "Open Policies & Documents",
        )
    items.sort(key=lambda item: item["rank"])
    return items[:6]


def _kpi_items(
    staffing, recruitment, performance, relations, safety, morale, compliance
) -> list[dict]:
    """The people pulse: eight headline figures, one per programme family.

    Leave, recovery plans and development sit in their own cards and in the
    attention band; a tray of twelve tiles hid two thirds of itself behind a
    swipe (2026-09-13).
    """
    turnover = staffing["turnover"]
    overall = morale["overall"]
    return [
        render_precomputed_metric_item(
            "accounts_hr_dashboard_service_active_employees",
            str(staffing["headcount"]),
            icon="users",
            variant="primary",
            helper=f"{staffing['joiners']} joined this FY",
        ),
        render_precomputed_metric_item(
            "accounts_hr_dashboard_service_open_positions",
            str(recruitment["open"]),
            icon="briefcase",
            variant="warning",
            helper=f"{recruitment['pending_approval']} awaiting approval",
        ),
        render_precomputed_metric_item(
            "hr_director_staff_turnover",
            f"{turnover:g}%" if turnover is not None else "—",
            icon="report",
            variant="danger" if staffing["turnover_tone"] == "danger" else "info",
            helper=(
                f"{staffing['leavers']} left, {staffing['voluntary']} voluntary"
                if turnover is not None
                else "no staff records this FY"
            ),
            raw_value=turnover,
        ),
        render_precomputed_metric_item(
            "hr_director_staff_morale",
            f"{overall['score']:.1f}" if overall else "—",
            icon="users",
            variant="success",
            helper=(
                f"of 5 · {overall['responses']} answers"
                if overall
                else "no pulse result yet"
            ),
            raw_value=overall["score"] if overall else None,
        ),
        render_precomputed_metric_item(
            "accounts_hr_dashboard_service_performance_reviews_due",
            str(performance["open"]),
            icon="document",
            variant="warning",
            helper=f"{performance['overdue']} overdue",
        ),
        render_precomputed_metric_item(
            "hr_director_open_er_cases",
            str(relations["open"]),
            icon="shield",
            variant="danger",
            helper=f"{relations['disciplinary']} disciplinary",
        ),
        render_precomputed_metric_item(
            "hr_director_open_safety_incidents",
            str(safety["open"]),
            icon="warning",
            variant="danger",
            helper=f"{safety['serious']} serious",
        ),
        render_precomputed_metric_item(
            "accounts_hr_dashboard_service_compliance_completion",
            f"{compliance['completion']}%"
            if compliance["completion"] is not None
            else "—",
            icon="shield",
            variant="success",
            helper=(
                f"{compliance['missing'] + compliance['expired']} missing or expired"
                if compliance["obligations"]
                else "no requirements set"
            ),
            raw_value=compliance["completion"],
        ),
    ]


#: Drawer-backed actions for the programmes the director runs. Each drawer is
#: served by apps/frontend/views/hr_programme_views.py and returns here.
QUICK_ACTIONS = (
    {
        "label": "Request a vacancy",
        "url": "/recruitment/new",
        "icon": "users",
        "drawer": True,
    },
    {
        "label": "Open a case",
        "url": "/employee-relations/new",
        "icon": "shield",
        "drawer": True,
    },
    {
        "label": "Report an incident",
        "url": "/health-safety/new",
        "icon": "warning",
        "drawer": True,
    },
    {
        "label": "Recognise someone",
        "url": "/recognition/new",
        "icon": "certificate",
        "drawer": True,
    },
    {
        "label": "Open a pulse survey",
        "url": "/pulse-surveys/new",
        "icon": "chart",
        "drawer": True,
    },
    {
        "label": "Record compliance evidence",
        "url": "/compliance-register/new",
        "icon": "accountability",
        "drawer": True,
    },
    {
        "label": "Start an offboarding",
        "url": "/offboarding/new",
        "icon": "calendar",
        "drawer": True,
    },
    {"label": "Open HR Today", "url": "/hr-today", "icon": "clock", "drawer": False},
)
