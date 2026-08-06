"""HR Dashboard — the people-operations cockpit.

Everything derives live from the real people/leave workflow: headcount,
who is out today, what awaits HR approval, coverage clashes with scheduled
field work, upcoming public holidays and the staff-setup queue. No storage,
no fabricated figures.
"""

from __future__ import annotations

from datetime import date, timedelta
from django.db.models import Count, Q

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffProfile,
    User,
)
from apps.hr.models import (
    Application,
    Vacancy,
    OnboardingPlan,
    OnboardingTask,
    PerformanceReview,
    PerformanceImprovementPlan,
    CPDAssignment,
    EmployeeComplianceRecord,
    ComplianceRequirement,
    PayrollReadinessRecord,
    EmployeeRelationsCase,
)

ROLE_LABELS = {
    "CCEO": "CCEOs",
    "Program Lead": "Program Leads",
    "CountryDirector": "Country Director",
    "RegionalVicePresident": "RVP",
    "ImpactAssessment": "Impact Assessment",
    "Accountant": "Accountants",
    "HumanResources": "HR",
    "ProjectCoordinator": "Project Coordinators",
    "PartnerFieldOfficer": "Partner Officers",
    "PartnerAdmin": "Partner Admins",
    "Admin": "Admins",
}

COUNTRY_FLAGS = {
    "Uganda": "🇺🇬",
    "Rwanda": "🇷🇼",
    "Kenya": "🇰🇪",
    "Ethiopia": "🇪🇹",
}

LEAVE_TYPE_LABELS = {
    "personal_time_off": "Personal Time Off",
    "sick_leave": "Sick Leave",
    "maternity_leave": "Maternity Leave",
    "paternity_leave": "Paternity Leave",
    "bereavement_leave": "Bereavement",
}

# Application.stage's documented value set (see apps/hr/models.py:55), bucketed
# into the funnel's 5 real stages. "Hired (This Month)" is scoped to the
# current month via updated_at — the moment the application's stage last
# changed to "Hired".
RECRUITMENT_FUNNEL_STAGES = [
    ("Applications", None),
    ("Screening", ("Screened", "Shortlisted")),
    ("Interviewing", ("Interview 1", "Interview 2", "Assessment", "Reference Check")),
    ("Offer Issued", ("Recommended", "Offer")),
    ("Hired (This Month)", ("Hired",)),
]


class HRDashboardService:
    @staticmethod
    def get_dashboard(user, fy=None, month=None, country=None, department=None) -> dict:
        today = date.today()
        today_iso = today.isoformat()
        wk_end_iso = (today + timedelta(days=7)).isoformat()

        # Base user filter
        staff_query = Q(is_active=True, deleted_at__isnull=True)

        staff = User.objects.filter(staff_query)
        headcount = staff.count()

        # 12 KPIs Calculation
        # KPI 1: Active Employees
        active_employees = headcount

        # KPI 2: Open Positions
        open_positions = Vacancy.objects.filter(status="Open").count()

        # KPI 3: New Hires Onboarding
        new_hires_onboarding = OnboardingPlan.objects.filter(
            status__in=[
                "Initiated",
                "Documents Pending",
                "Orientation Pending",
                "Role Training Pending",
            ]
        ).count()

        # KPI 4: Staff On Track — derived from completed PerformanceReview
        # ratings (the real Strong/Fair/At Risk classification HR already
        # runs), not a target-pacing engine — see report for the judgment call.
        completed_reviews = PerformanceReview.objects.filter(status="Completed")
        completed_reviews_total = completed_reviews.count()
        staff_on_track_pct = (
            round(
                (
                    completed_reviews.filter(rating__startswith="Strong").count()
                    / completed_reviews_total
                )
                * 100
            )
            if completed_reviews_total
            else 0
        )

        # KPI 5: High-Risk Staff
        high_risk_staff = PerformanceImprovementPlan.objects.filter(
            status="Active"
        ).count()

        # KPI 6: On Leave Today
        on_leave_today_qs = Leave.objects.filter(
            status="approved", start_date__lte=today_iso, end_date__gte=today_iso
        )
        employees_on_leave = on_leave_today_qs.count()

        # KPI 7: Coverage Clashes (7d)
        coverage_conflicts = HRDashboardService._coverage_clashes(today, wk_end_iso)

        # KPI 8: Pending Leave Approvals
        pending_leave_approvals = Leave.objects.filter(status="pending").count()

        # KPI 9: Performance Reviews Due
        reviews_due = PerformanceReview.objects.exclude(status="Completed").count()

        # KPI 10: Compliance Completion
        compliance_total = EmployeeComplianceRecord.objects.count()
        if compliance_total > 0:
            compliant_count = EmployeeComplianceRecord.objects.filter(
                status="Compliant"
            ).count()
            compliance_completion_pct = round(
                (compliant_count / compliance_total) * 100
            )
        else:
            compliance_completion_pct = 0

        # KPI 11: CPD Completion
        cpd_total = CPDAssignment.objects.count()
        if cpd_total > 0:
            cpd_done = CPDAssignment.objects.filter(
                status__in=["Completed", "Verified"]
            ).count()
            cpd_completion_pct = round((cpd_done / cpd_total) * 100)
        else:
            cpd_completion_pct = 0

        # KPI 12: Payroll Readiness — real PayrollReadinessRecord rows for the
        # current payroll period (period keys are "YYYY-MM", see model).
        current_payroll_period = today.strftime("%Y-%m")
        payroll_qs = PayrollReadinessRecord.objects.filter(
            payroll_period=current_payroll_period
        )
        payroll_total = payroll_qs.count()
        payroll_ready_pct = (
            round(
                (payroll_qs.filter(is_payroll_ready=True).count() / payroll_total) * 100
            )
            if payroll_total
            else 0
        )

        kpi_strip_items = [
            {
                "label": "Active Employees",
                "value": str(active_employees),
                "icon": "users",
                "variant": "primary",
                "helper": "across East Africa",
            },
            {
                "label": "Open Positions",
                "value": str(open_positions),
                "icon": "briefcase",
                "variant": "warning",
                "helper": "approved vacancies",
            },
            {
                "label": "New Hires Onboarding",
                "value": str(new_hires_onboarding),
                "icon": "clock",
                "variant": "info",
                "helper": "documents pending",
            },
            {
                "label": "Staff On Track",
                "value": f"{staff_on_track_pct}%",
                "icon": "report",
                "variant": "success",
                "helper": "achieving targets",
            },
            {
                "label": "High-Risk Staff",
                "value": str(high_risk_staff),
                "icon": "warning",
                "variant": "danger",
                "helper": "overdue visits > 3",
            },
            {
                "label": "On Leave Today",
                "value": str(employees_on_leave),
                "icon": "calendar",
                "variant": "info",
                "helper": "out today",
            },
            {
                "label": "Coverage Clashes (7d)",
                "value": str(coverage_conflicts),
                "icon": "shield",
                "variant": "danger",
                "helper": "leave vs scheduled",
            },
            {
                "label": "Pending Leave Approvals",
                "value": str(pending_leave_approvals),
                "icon": "check",
                "variant": "warning",
                "helper": "awaiting HR action",
            },
            {
                "label": "Performance Reviews Due",
                "value": str(reviews_due),
                "icon": "document",
                "variant": "warning",
                "helper": "due this period",
            },
            {
                "label": "Compliance Completion",
                "value": f"{compliance_completion_pct}%",
                "icon": "shield",
                "variant": "success",
                "helper": "documents verified",
            },
            {
                "label": "CPD Completion",
                "value": f"{cpd_completion_pct}%",
                "icon": "book",
                "variant": "primary",
                "helper": "courses completed",
            },
            {
                "label": "Payroll Readiness",
                "value": f"{payroll_ready_pct}%",
                "icon": "report",
                "variant": "success",
                "helper": "verified payout records",
            },
        ]

        # Workforce Overview — real trailing-6-month headcount/hires/exits,
        # reconstructed from StaffProfile.created_at/deleted_at (no historical
        # snapshot table exists, so this is the honest reconstruction from the
        # timestamps actually on record).
        workforce_overview = HRDashboardService._workforce_overview_6mo(today)

        # Workforce by Country — real StaffProfile.country breakdown.
        workforce_by_country = HRDashboardService._workforce_by_country(today_iso)

        # Headcount by Department — real StaffProfile.department breakdown.
        headcount_by_department, department_names = (
            HRDashboardService._headcount_by_department()
        )

        # Job Level Distribution — StaffProfile has no job-level field, so
        # there is no real query to run here. Rather than invent a taxonomy
        # (a product decision this fix can't make unilaterally), this is left
        # as an honest empty state; the template already renders an empty
        # list as a blank section, not a fabricated one.
        job_levels = []

        # Leave Overview — real Leave.type breakdown (approved leave only).
        leave_overview = HRDashboardService._leave_overview()

        # Performance Overview — real PerformanceReview.rating breakdown,
        # "All Staff" plus the top real departments by headcount.
        performance_overview = HRDashboardService._performance_overview(
            department_names
        )

        # Upcoming Reviews & Probations — real PerformanceReview rows.
        upcoming_reviews = HRDashboardService._upcoming_reviews(today)

        # Compliance Status Table — real EmployeeComplianceRecord counts.
        compliance_status = HRDashboardService._compliance_status()

        # Recruitment Funnel — real Application.stage counts.
        recruitment_funnel = HRDashboardService._recruitment_funnel(today)

        # Pending HR Actions — real counts; reuses the same KPI values above
        # for "Performance Reviews" / "Leave Coverage Conflicts" so the two
        # widgets never disagree about the same underlying number.
        documents_expiring = EmployeeComplianceRecord.objects.filter(
            status="Due Soon"
        ).count()
        pending_actions = [
            {
                "label": "Onboarding Tasks",
                "count": OnboardingTask.objects.filter(is_completed=False).count(),
                "url": "/onboarding",
            },
            {
                "label": "Performance Reviews",
                "count": reviews_due,
                "url": "/performance-reviews",
            },
            {
                "label": "CPD Verifications",
                "count": CPDAssignment.objects.filter(status="Completed").count(),
                "url": "/cpd-learning",
            },
            {
                "label": "Compliance Expiries",
                "count": documents_expiring
                + EmployeeComplianceRecord.objects.filter(status="Expired").count(),
                "url": "/compliance-register",
            },
            {
                "label": "Leave Coverage Conflicts",
                "count": coverage_conflicts,
                "url": "/leave/coverage",
            },
            {
                "label": "Employee Relations Cases",
                "count": EmployeeRelationsCase.objects.exclude(
                    status__in=["Resolved", "Closed"]
                ).count(),
                "url": "/employee-relations",
            },
        ]

        # Quick Actions — every url must resolve to a real registered route
        # (see apps/frontend/urls.py). Previously several pointed at
        # sub-paths ("/recruitment/create-vacancy", "/onboarding/start",
        # "/performance-reviews/create", "/cpd-learning/assign") that were
        # never wired, so the links 404'd. Point them at the real HCOS pages
        # that actually exist instead of a dead end.
        quick_actions = [
            {"label": "Create Vacancy Request", "url": "/recruitment", "icon": "plus"},
            {
                "label": "Add New Employee",
                "url": "/admin-panel/users",
                "icon": "user-add",
            },
            {"label": "Start Onboarding", "url": "/onboarding", "icon": "play"},
            {
                "label": "Record Performance Review",
                "url": "/performance-reviews",
                "icon": "document",
            },
            {"label": "Assign CPD", "url": "/cpd-learning", "icon": "book"},
            {"label": "Generate HR Report", "url": "/reports", "icon": "report"},
        ]

        # Leadership Attention banner — real counts driving the previously
        # hardcoded "Leadership Attention Required" cards (templates/partials
        # /dashboards/hr/body.html). "High-risk countries" = countries with at
        # least one active PIP in workforce_by_country.
        high_risk_countries = [
            row["country"] for row in workforce_by_country if row["at_risk"] > 0
        ]
        if not high_risk_countries:
            high_risk_countries_label = "No countries currently flagged"
        elif len(high_risk_countries) == 1:
            high_risk_countries_label = f"{high_risk_countries[0]} alerts"
        else:
            high_risk_countries_label = (
                ", ".join(high_risk_countries[:-1])
                + f" & {high_risk_countries[-1]} alerts"
            )

        # Approved leave lists
        pending = (
            Leave.objects.filter(status="pending")
            .select_related("staff__user")
            .order_by("start_date")
        )
        upcoming_leave = (
            Leave.objects.filter(
                status="approved", start_date__gt=today_iso, start_date__lte=wk_end_iso
            )
            .select_related("staff__user")
            .order_by("start_date")
        )

        def leave_row(lv):
            return {
                "id": lv.id,
                "name": (lv.staff.user.name if lv.staff and lv.staff.user else "Staff"),
                "role": (
                    lv.staff.user.active_role if lv.staff and lv.staff.user else ""
                ),
                "type": (lv.type or "leave").title(),
                "range": f"{lv.start_date} → {lv.end_date}",
                "status": lv.status,
            }

        # Two independent holiday sources — PublicHoliday rows and
        # CalendarBlock(PUBLIC_HOLIDAY) rows — must be unioned; a holiday
        # added only via the /public-holidays admin surface (a CalendarBlock)
        # is otherwise silently missing from this list.
        holiday_days = {
            h.date: h.name for h in PublicHoliday.objects.filter(date__gte=today)
        }
        for b in CalendarBlock.objects.filter(
            block_type="PUBLIC_HOLIDAY", is_active=True, end_date__gte=today
        ):
            d = max(b.start_date, today)
            while d <= b.end_date:
                holiday_days.setdefault(d, b.title)
                d += timedelta(days=1)
        holidays = [
            {"date": d, "name": name} for d, name in sorted(holiday_days.items())
        ]

        # Build roles counts list as expected by tests
        role_counts = (
            User.objects.filter(is_active=True, deleted_at__isnull=True)
            .values("active_role")
            .annotate(count=Count("id"))
        )
        roles_list = []
        for r in role_counts:
            r_val = r["active_role"]
            roles_list.append(
                {
                    "role": r_val,
                    "label": ROLE_LABELS.get(r_val, r_val),
                    "count": r["count"],
                }
            )
        if not roles_list:
            roles_list = [{"role": "CCEO", "label": "CCEOs", "count": headcount}]

        from apps.debriefs.rollup_service import field_debrief_intelligence_summary

        field_debrief_intel = field_debrief_intelligence_summary(user)

        return {
            "kpi_strip_items": kpi_strip_items,
            "workforce_overview": workforce_overview,
            "workforce_by_country": workforce_by_country,
            "headcount_by_department": headcount_by_department,
            "job_levels": job_levels,
            "leave_overview": leave_overview,
            "performance_overview": performance_overview,
            "upcoming_reviews": upcoming_reviews,
            "compliance_status": compliance_status,
            "recruitment_funnel": recruitment_funnel,
            "pending_actions": pending_actions,
            "quick_actions": quick_actions,
            "pending_leaves": [leave_row(lv) for lv in pending[:6]],
            "pending_total": pending.count(),
            "on_leave_now": [leave_row(lv) for lv in on_leave_today_qs[:6]],
            "upcoming_leave": [leave_row(lv) for lv in upcoming_leave[:6]],
            "holidays": holidays,
            "roles": roles_list,
            "field_debrief_intel": field_debrief_intel,
            # Leadership Attention banner values (real, reused from the KPIs above).
            "open_positions": open_positions,
            "reviews_due": reviews_due,
            "employees_on_leave": employees_on_leave,
            "coverage_conflicts": coverage_conflicts,
            "documents_expiring": documents_expiring,
            "high_risk_countries": high_risk_countries,
            "high_risk_countries_label": high_risk_countries_label,
        }

    @staticmethod
    def _coverage_clashes(today, wk_end_iso) -> int:
        """Approved leave in the next 7 days overlapping the staff member's own
        scheduled activities — the real coverage risk HR must resolve."""
        from apps.activities.models import Activity

        clashes = 0
        leaves = Leave.objects.filter(
            status="approved",
            start_date__lte=wk_end_iso,
            end_date__gte=today.isoformat(),
        ).select_related("staff")
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

    @staticmethod
    def _workforce_overview_6mo(today: date) -> dict:
        """Real trailing-6-month headcount/hires/exits, reconstructed from
        StaffProfile.created_at (hire) and StaffProfile.deleted_at (exit) —
        there is no historical headcount snapshot table, so this is the
        honest reconstruction from the timestamps that actually exist."""
        month_starts = []
        y, m = today.year, today.month
        for _ in range(6):
            month_starts.append(date(y, m, 1))
            m -= 1
            if m == 0:
                m, y = 12, y - 1
        month_starts.reverse()

        def _next_month(d: date) -> date:
            return date(
                d.year + (1 if d.month == 12 else 0),
                1 if d.month == 12 else d.month + 1,
                1,
            )

        months, headcount, new_hires, exits = [], [], [], []
        for start in month_starts:
            end_exclusive = _next_month(start)
            months.append(start.strftime("%b %Y"))
            new_hires.append(
                StaffProfile.all_objects.filter(
                    created_at__date__gte=start, created_at__date__lt=end_exclusive
                ).count()
            )
            exits.append(
                StaffProfile.all_objects.filter(
                    deleted_at__date__gte=start, deleted_at__date__lt=end_exclusive
                ).count()
            )
            headcount.append(
                StaffProfile.all_objects.filter(created_at__date__lt=end_exclusive)
                .filter(
                    Q(deleted_at__isnull=True) | Q(deleted_at__date__gte=end_exclusive)
                )
                .count()
            )
        return {
            "months": months,
            "headcount": headcount,
            "new_hires": new_hires,
            "exits": exits,
        }

    @staticmethod
    def _workforce_by_country(today_iso: str) -> list[dict]:
        countries = (
            StaffProfile.objects.exclude(country="")
            .exclude(country__isnull=True)
            .values_list("country", flat=True)
            .distinct()
        )
        rows = []
        for country in sorted(countries):
            staff_ids = list(
                StaffProfile.objects.filter(country=country).values_list(
                    "id", flat=True
                )
            )
            reviews = PerformanceReview.objects.filter(
                staff_id__in=staff_ids, status="Completed"
            )
            reviews_total = reviews.count()
            on_track_pct = (
                round(
                    (
                        reviews.filter(rating__startswith="Strong").count()
                        / reviews_total
                    )
                    * 100
                )
                if reviews_total
                else 0
            )
            rows.append(
                {
                    "country": country,
                    "flag": COUNTRY_FLAGS.get(country, "🌍"),
                    "headcount": len(staff_ids),
                    "on_track": on_track_pct,
                    "at_risk": PerformanceImprovementPlan.objects.filter(
                        staff_id__in=staff_ids, status="Active"
                    ).count(),
                    "on_leave": Leave.objects.filter(
                        staff_id__in=staff_ids,
                        status="approved",
                        start_date__lte=today_iso,
                        end_date__gte=today_iso,
                    ).count(),
                    "vacancies": Vacancy.objects.filter(
                        country=country, status="Open"
                    ).count(),
                }
            )
        return rows

    @staticmethod
    def _headcount_by_department() -> tuple[dict, list[str]]:
        rows = list(
            StaffProfile.objects.values("department")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        labels = [r["department"] or "Unspecified" for r in rows]
        counts = [r["count"] for r in rows]
        department_names = [r["department"] for r in rows if r["department"]]
        return {"labels": labels, "counts": counts}, department_names

    @staticmethod
    def _leave_overview() -> dict:
        rows = list(
            Leave.objects.filter(status="approved")
            .values("type")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        labels = [
            LEAVE_TYPE_LABELS.get(
                r["type"], (r["type"] or "Other").replace("_", " ").title()
            )
            for r in rows
        ]
        counts = [r["count"] for r in rows]
        return {"labels": labels, "counts": counts}

    @staticmethod
    def _performance_overview(department_names: list[str]) -> dict:
        def _bucket(qs):
            return (
                qs.filter(rating__startswith="Strong").count(),
                qs.filter(rating__startswith="Fair").count(),
                qs.filter(rating__startswith="At Risk").count(),
            )

        categories = ["All Staff"] + department_names[:4]
        base = PerformanceReview.objects.filter(status="Completed")
        strong, fair, at_risk = [], [], []
        for label in categories:
            qs = base if label == "All Staff" else base.filter(staff__department=label)
            s, f, a = _bucket(qs)
            strong.append(s)
            fair.append(f)
            at_risk.append(a)
        return {
            "categories": categories,
            "strong": strong,
            "fair": fair,
            "at_risk": at_risk,
        }

    @staticmethod
    def _upcoming_reviews(today: date) -> list[dict]:
        rows = (
            PerformanceReview.objects.exclude(status__in=["Completed", "Closed"])
            .select_related("staff__user")
            .order_by("due_date")[:6]
        )
        out = []
        for r in rows:
            staff = r.staff
            user = staff.user if staff else None
            due = r.due_date
            days_left = (due - today).days if due else None
            if days_left is None:
                status, status_class = (
                    "Scheduled",
                    "edify-primary-soft edify-primary-text",
                )
            elif days_left < 0:
                status, status_class = "Overdue", "bg-rose-100 text-rose-700"
            elif days_left <= 5:
                status, status_class = "Due Soon", "bg-amber-100 text-amber-700"
            else:
                status, status_class = (
                    "Upcoming",
                    "edify-primary-soft edify-primary-text",
                )
            out.append(
                {
                    "name": user.name if user else "—",
                    "role": (
                        staff.title
                        if staff and staff.title
                        else (user.active_role if user else "")
                    ),
                    "country": staff.country if staff else "",
                    "type": r.review_type,
                    "due_date": due.strftime("%b %d, %Y") if due else "—",
                    "days_left": days_left,
                    "status": status,
                    "status_class": status_class,
                }
            )
        return out

    @staticmethod
    def _compliance_status() -> list[dict]:
        out = []
        for req in ComplianceRequirement.objects.all().order_by("name"):
            records = EmployeeComplianceRecord.objects.filter(requirement=req)
            out.append(
                {
                    "requirement": req.name,
                    "compliant": records.filter(status="Compliant").count(),
                    "due_soon": records.filter(status="Due Soon").count(),
                    "expired": records.filter(status="Expired").count(),
                    "total": records.count(),
                }
            )
        return out

    @staticmethod
    def _recruitment_funnel(today: date) -> list[dict]:
        total_applications = Application.objects.count()
        out = []
        for label, stages in RECRUITMENT_FUNNEL_STAGES:
            if stages is None:
                count = total_applications
            elif label == "Hired (This Month)":
                count = Application.objects.filter(
                    stage__in=stages,
                    updated_at__year=today.year,
                    updated_at__month=today.month,
                ).count()
            else:
                count = Application.objects.filter(stage__in=stages).count()
            out.append({"stage": label, "count": count})
        return out
