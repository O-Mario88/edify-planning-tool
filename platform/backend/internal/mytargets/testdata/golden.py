"""Write golden.json: My Targets (/my-targets) as the existing feed reads it,
for an officer whose year the development seed does not measure.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/mytargets/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gmt", for one officer: an agreed priorities review with four
measured priorities (an explicit monthly target over one of them), visits in
each state the ledger and the gap reasons tell apart (verified with their
Activity SF ID, done without it, awaiting verification, returned,
scheduled), a training this month, a confirmed SSA and an approved MSCS; three operating schools assigned
to the officer, two of them Core Schools with packages part done, one with a
confirmed SSA scored below Strong in two interventions; a professional
development request; and three Projects assigned to the officer (two live,
one completed), the first also assigned to a Project Coordinator.

It then brings the officers' ledgers up to date as any reading page does
(refresh_many), then changes some of the officer's work of the year without
the signals that mark the ledger and marks it by hand, so the page's own
rebuild has something to do on every read of that year (each read rolls
back). It asks the page for this month, an earlier month, another year, an
officer with no agreement, the year after, a Project Coordinator and a
partner's field officer and administrator (logins without a People
record); writes the rows (the stored ledger rows and the mark among them)
and the answers to GOLDEN_OUT and deletes the rows. Dates sit around the day
it was written, so internal/integration/my_targets_test.go compares within
half an hour.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from decimal import Decimal

from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.hr.models import (
    ActivityPriorityLink,
    MilestoneActivityRule,
    MilestoneAllocation,
    MilestoneMetricDefinition,
    MilestonePeriodTarget,
    MilestoneProgressCredit,
    PerformancePriority,
    PerformanceReview,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.core_schools.models import CorePlan
from apps.mobile_feed.views import read_page
from apps.projects.models import (
    Project,
    ProjectSchoolAssignment,
    ProjectStaffAssignment,
)
from apps.professional_development.models import ProfessionalDevelopmentRequest
from apps.schools.lifecycle_models import OPERATING_STATUSES
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.ledger_sync import refresh_many
from apps.targets.models import (
    MonthlyPersonalTarget,
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
    TargetLedgerDirty,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/my-targets"
P = "gmt"
OFFICER = "cceo7@edify.org"
EMPTY = "cceo8@edify.org"
#: A Project Coordinator, shown the workspace strip above the page.
COORDINATOR = "coordinator@edify.org"
#: A partner's field officer and its administrator: logins without a People
#: record.
PARTNERS = ["partner@edify.org", "partner-admin@edify.org"]
TODAY = dj_timezone.localdate()
NOW = Cal.current()
FY = NOW["fy"]
MONTH = NOW["month_of_fy"]
#: The year after, where the officer holds approved milestone allocations.
NEXT = str(int(FY) + 1)
#: Children first; the ledger is found by its sources, not its ids.
TABLES = (
    "hr_activity_priority_link",
    "hr_milestone_progress_credit",
    "hr_milestone_period_target",
    "hr_milestone_allocation",
    "hr_milestone_activity_rule",
    "hr_priority_milestone",
    "hr_strategic_priority",
    "hr_strategic_priority_cycle",
    "ssa_score",
    "staff_school_assignment",
    "project_school_assignment",
    "project_staff_assignment",
    "core_plan",
    "pd_request",
    "hr_performance_priority",
    "hr_performance_review",
    "monthly_personal_target",
    "activity",
    "ssa_record",
    "mscs_story",
    "project",
)


def officer_owners():
    """The officer's account and People record: a ledger mark names either."""
    officer = StaffProfile.objects.get(user__email=OFFICER)
    return [officer.user_id, officer.id]


def clear():
    TargetAchievementLedger.objects.filter(source_id__startswith=P).delete()
    TargetLedgerDirty.objects.filter(
        owner_id__in=officer_owners(), fy__in=[FY, NEXT]
    ).delete()
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def day_of(month, day=10, fy=None):
    start, _ = Cal.month_range(fy or FY, month)
    return start + timedelta(days=day - 1)


def file_allocations(officer, schools):
    """NEXT's governed priorities: one the officer holds approved
    allocations on (a distinct-schools count phased by month and quarter, a
    capped coverage rate, and a count on a milestone since retired), one
    ready for allocation; work on the milestones' catalogue items, credited,
    one credit reversed; and a planning link."""
    c1, c2 = list(ActivityCatalogueItem.objects.order_by("id")[:2])
    definition = MilestoneMetricDefinition.objects.order_by("id").first()
    StrategicPriorityCycle.objects.bulk_create(
        [StrategicPriorityCycle(id=P + "Y1", financial_year=NEXT, title="Golden cycle")]
    )

    def priority(key, seq, title):
        return StrategicPriority.objects.create(
            id=P + key,
            fy=NEXT,
            level="country",
            country_id="Uganda",
            title=title,
            status="published",
            sequence=seq,
            cycle_id=P + "Y1",
        )

    grow, quality = (
        priority("G1", 1, "Grow the programme"),
        priority("G2", 2, "Raise quality"),
    )

    def milestone(key, pr, measurement, target, unit, weight, **extra):
        return PriorityMilestone.objects.create(
            id=P + key,
            priority=pr,
            code=P.upper() + key,
            source_order=int(key[1:]),
            title=f"Golden milestone {key}",
            measurement_type=measurement,
            target_value=Decimal(target),
            target_unit=unit,
            weight=Decimal(weight),
            active=extra.pop("active", True),
            metric_definition=definition,
            definition_status="approved",
            **extra,
        )

    m1 = milestone("M1", grow, "count", "40", "schools", "30")
    m2 = milestone("M2", grow, "percentage", "80", "%", "20", cap_at_100=True)
    m3 = milestone("M3", grow, "count", "9", "schools", "5", active=False)
    milestone("M4", quality, "count", "10", "schools", "10")
    rule = {}
    for key, m, basis, item in (
        ("R1", m1, "UNIQUE_SCHOOLS_SUPPORTED", c1),
        ("R2", m2, "PERCENT_OF_ELIGIBLE_SCHOOLS", c2),
        ("R3", m3, "UNIQUE_SCHOOLS_SUPPORTED", c1),
    ):
        rule[key] = MilestoneActivityRule.objects.create(
            id=P + key, milestone=m, counting_basis=basis, catalogue_item=item
        )

    def allocate(key, m, target, weight, **extra):
        return MilestoneAllocation.objects.create(
            id=P + key,
            milestone=m,
            allocated_to_type="employee",
            employee=officer,
            allocated_target=Decimal(target),
            weight=Decimal(weight),
            status="approved",
            effective_date=TODAY,
            **extra,
        )

    a1 = allocate("A1", m1, "12", "60")
    a2 = allocate("A2", m2, "80", "40", denominator=Decimal("20"))
    allocate("A3", m3, "5", "0")
    targets = []
    for m in range(1, 13):
        start, end = Cal.month_range(NEXT, m)
        for a, planned, achieved in (
            (a1, "1", "0"),
            (a2, "80", "25" if m == 1 else "0"),
        ):
            targets.append(
                MilestonePeriodTarget(
                    id=f"{P}T{a.id[-1]}{m:02d}",
                    milestone=a.milestone,
                    allocation=a,
                    scope="employee",
                    employee=officer,
                    period_type="month",
                    period_start=start,
                    period_end=end - timedelta(days=1),
                    planned_value=Decimal(planned),
                    achievement_percentage=Decimal(achieved),
                )
            )
    for q in (1, 2, 3, 4):
        start, _ = Cal.month_range(NEXT, q * 3 - 2)
        _, end = Cal.month_range(NEXT, q * 3)
        targets.append(
            MilestonePeriodTarget(
                id=f"{P}Q1{q}",
                milestone=m1,
                allocation=a1,
                scope="employee",
                employee=officer,
                period_type="quarter",
                period_start=start,
                period_end=end - timedelta(days=1),
                planned_value=Decimal("3"),
                actual_value=Decimal("2") if q == 1 else Decimal("0"),
            )
        )
    MilestonePeriodTarget.objects.bulk_create(targets)

    def work(key, item, school, status, month):
        return Activity.objects.create(
            id=P + key,
            activity_type="school_visit",
            catalogue_item=item,
            school=school,
            fy=NEXT,
            status=status,
            delivery_type="staff",
            responsible_staff_id=officer.id,
            planned_date=day_of(month, fy=NEXT),
        )

    v1 = work("V1", c1, schools[0], "ia_verified", 1)
    v2 = work("V2", c1, schools[1], "ia_verified", 2)
    v3 = work("V3", c2, schools[2], "ia_verified", 1)
    v4 = work("V4", c1, schools[0], "scheduled", 3)
    v5 = work("V5", c1, schools[2], "ia_verified", 4)
    MilestoneProgressCredit.objects.bulk_create(
        [
            MilestoneProgressCredit(
                id=P + key,
                rule=rule[r],
                activity=act,
                credited_value=Decimal("1"),
                credited_at=dj_timezone.now(),
                reversed_at=reversed_at,
            )
            for key, r, act, reversed_at in (
                ("C1", "R1", v1, None),
                ("C2", "R1", v2, None),
                ("C3", "R2", v3, None),
                ("C4", "R3", v1, None),
                ("C5", "R1", v5, dj_timezone.now()),
            )
        ]
    )
    ActivityPriorityLink.objects.bulk_create(
        [
            ActivityPriorityLink(
                id=P + "L1", activity=v4, allocation=a1, linked_by=officer.user_id
            )
        ]
    )


def file_projects(officer, held):
    """Three Projects assigned to the officer this year: a live one with two
    of the officer's schools (and one school that is not theirs), a planned
    and a completed activity of the officer's and one the officer monitors;
    a live one without a code, schools or interventions; and a completed
    one, which the page leaves out. The Project Coordinator is assigned the
    first."""
    coordinator = StaffProfile.objects.get(user__email=COORDINATOR)
    Project.objects.bulk_create(
        [
            Project(
                id=P + "J1",
                code="GMT-LIT",
                name="Golden Literacy",
                status="active",
                school_focus="client",
                target_interventions=["leadership", "enrolment"],
                intervention="financial_health",
            ),
            Project(
                id=P + "J2",
                name="Golden Pilot",
                status="proposed",
                school_focus="all",
                target_interventions=[],
            ),
            Project(
                id=P + "J3",
                code="GMT-OLD",
                name="Golden Archive",
                status="completed",
                school_focus="core",
                target_interventions=[],
            ),
        ]
    )
    other = (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(id__in=[s.id for s in held])
        .order_by("id")
        .first()
    )
    ProjectSchoolAssignment.objects.bulk_create(
        [
            ProjectSchoolAssignment(
                id=f"{P}Q{i}", project_id=P + "J1", school_id=sch.id
            )
            for i, sch in enumerate([held[0], held[1], other], start=1)
        ]
    )
    ProjectStaffAssignment.objects.bulk_create(
        [
            ProjectStaffAssignment(
                id=P + "K1",
                project_id=P + "J1",
                staff_id=officer.id,
                fy=FY,
                responsibility="execute",
                assigned_by_role="ImpactAssessment",
                start_date=day_of(1),
                due_date=day_of(12, 20),
            ),
            ProjectStaffAssignment(
                id=P + "K2",
                project_id=P + "J2",
                staff_id=officer.id,
                fy=FY,
                responsibility="supervise",
                assigned_by_role="Admin",
            ),
            ProjectStaffAssignment(
                id=P + "K3",
                project_id=P + "J3",
                staff_id=officer.id,
                fy=FY,
            ),
            ProjectStaffAssignment(
                id=P + "K4",
                project_id=P + "J1",
                staff_id=coordinator.id,
                fy=FY,
            ),
        ]
    )
    for key, status, extra in [
        ("JA1", "completed", {"responsible_staff_id": officer.id}),
        ("JA2", "scheduled", {"responsible_staff_id": officer.id}),
        ("JA3", "scheduled", {"monitored_by_staff_id": officer.user_id}),
    ]:
        Activity.objects.create(
            id=P + key,
            activity_type="school_visit",
            status=status,
            delivery_type="staff",
            planned_date=day_of(MONTH),
            fy=FY,
            school=held[0],
            project_id=P + "J1",
            **extra,
        )


def file_rows():
    officer = StaffProfile.objects.get(user__email=OFFICER)
    area = {a.key: a for a in TargetArea.objects.all()}
    school = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(school=None)
        .first()
        .school
    )
    cluster = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(cluster=None)
        .first()
        .cluster
    )
    review = PerformanceReview.objects.create(
        id=P + "R1",
        staff=officer,
        fy=FY,
        review_type="annual_priorities",
        due_date=day_of(12, 28),
        stage="priorities_agreed",
    )
    for seq, (metric, target, weight, statement) in enumerate(
        [
            ("direct_visits", 120, 40, "Visit my schools"),
            ("trainings", 24, 20, "Train my clusters"),
            ("ssa_coverage", 36, 25, "Collect SSAs"),
            ("mscs", 12, 15, "Tell what changed"),
        ],
        start=1,
    ):
        PerformancePriority.objects.create(
            id=f"{P}P{seq}",
            review=review,
            sequence=seq,
            outcome_statement=statement,
            metric_key=metric,
            target_number=target,
            weight=weight,
        )
    # An explicit month wins over the visits priority's annual split.
    MonthlyPersonalTarget.objects.create(
        id=P + "T1",
        user_id=officer.user_id,
        fy=FY,
        month_of_fy=1,
        target=14,
        area=area["school_visits"],
    )

    def activity(key, kind, status, month, **extra):
        place = {"cluster": cluster} if "cluster" in kind else {"school": school}
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status=status,
            delivery_type="staff",
            responsible_staff_id=officer.id,
            planned_date=day_of(month),
            fy=FY,
            **place,
            **extra,
        )

    activity("A1", "school_visit", "ia_verified", 1, salesforce_activity_id="SVE-GMT1")
    activity("A2", "school_visit", "ia_verified", 1, salesforce_activity_id="SVE-GMT2")
    activity("A3", "school_visit", "closed", MONTH, salesforce_activity_id="SVE-GMT3")
    activity("A4", "school_visit", "completed", MONTH)
    activity(
        "A5",
        "school_visit",
        "awaiting_ia_verification",
        MONTH,
        salesforce_activity_id="SVE-GMT5",
    )
    activity("A6", "school_visit", "returned_by_pl", MONTH)
    activity("A7", "school_visit", "scheduled", MONTH)
    activity("A8", "cluster_training", "scheduled", MONTH, expected_participants=20)
    SsaRecord.objects.create(
        id=P + "S1",
        school=school,
        date_of_ssa=day_of(1, 15),
        fy=FY,
        quarter="Q1",
        uploaded_by=officer.user_id,
        collected_by_user_id=officer.user_id,
        verification_status="confirmed",
        average_score=6.0,
    )
    MostSignificantChangeStory.objects.create(
        id=P + "M1",
        user_id=officer.user_id,
        title="A changed school",
        narrative="What changed.",
        story_date=day_of(1, 20),
        status="approved",
    )
    # The officer's portfolio: three operating schools, the first two Core
    # Schools, the first with a confirmed SSA below Strong in two places.
    held = list(
        School.objects.filter(
            deleted_at__isnull=True, operational_status__in=OPERATING_STATUSES
        ).order_by("id")[:3]
    )
    StaffSchoolAssignment.objects.bulk_create(
        [
            StaffSchoolAssignment(id=f"{P}Z{i}", school_id=sch.id, staff_id=officer.id)
            for i, sch in enumerate(held, start=1)
        ]
    )
    CorePlan.objects.bulk_create(
        [
            CorePlan(
                id=f"{P}C1",
                school_id=held[0].school_id,
                fy=FY,
                visits_completed=3,
                trainings_completed=1,
                baseline_average=5.75,
            ),
            CorePlan(id=f"{P}C2", school_id=held[1].school_id, fy=FY),
        ]
    )
    scored = SsaRecord.objects.create(
        id=P + "S2",
        school=held[0],
        date_of_ssa=day_of(1, 12),
        fy=FY,
        quarter="Q1",
        uploaded_by=officer.user_id,
        verification_status="confirmed",
        average_score=5.75,
    )
    SsaScore.objects.bulk_create(
        [
            SsaScore(
                id=f"{P}X1", ssa_record=scored, intervention="leadership", score=4.5
            ),
            SsaScore(id=f"{P}X2", ssa_record=scored, intervention="enrolment", score=7),
            SsaScore(
                id=f"{P}X3", ssa_record=scored, intervention="financial_health", score=9
            ),
        ]
    )
    ProfessionalDevelopmentRequest.objects.bulk_create(
        [
            ProfessionalDevelopmentRequest(
                id=P + "D1",
                fy=FY,
                staff_id=officer.id,
                staff_name=officer.user.name,
                course_name="Coaching school leaders",
                course_type="online",
                course_category="Leadership",
                institution="Edify Academy",
                relevance_to_role="I coach head teachers every week.",
                start_date=day_of(4),
                end_date=day_of(4, 12),
            )
        ]
    )
    file_allocations(officer, held)
    file_projects(officer, held)
    users = list(
        User.objects.filter(email__in=[OFFICER, EMPTY, COORDINATOR, *PARTNERS])
    )
    refresh_many(users, FY)
    refresh_many(users, NEXT)
    left = TargetLedgerDirty.objects.filter(
        owner_id__in=[officer.id, officer.user_id], fy__in=[FY, NEXT]
    )
    if left.exists():
        raise SystemExit("the ledger is still marked after the refresh")
    file_stale(officer)


def file_stale(officer):
    """Change the officer's sources after the refresh without the signals
    that mark the ledger, then mark it as those saves would: so the page
    rebuilds on every read (and the read's rollback undoes it). A visit is
    verified with its Activity SF ID, one is returned by IA, one moves to
    another month, a done visit is deleted, the approved story is rejected
    and a confirmed SSA is collected."""
    visits = Activity.objects.filter(id__startswith=P)
    visits.filter(id=P + "A7").update(
        status="ia_verified", salesforce_activity_id="SVE-GMT7"
    )
    visits.filter(id=P + "A1").update(status="returned_by_ia")
    visits.filter(id=P + "A2").update(planned_date=day_of(2))
    visits.filter(id=P + "A4").update(deleted_at=dj_timezone.now())
    MostSignificantChangeStory.objects.filter(id=P + "M1").update(status="rejected")
    # One SSA a school a year: a school with none this year.
    school = (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(id__in=SsaRecord.objects.filter(fy=FY).values("school_id"))
        .order_by("id")
        .first()
    )
    SsaRecord.objects.bulk_create(
        [
            SsaRecord(
                id=P + "S3",
                school=school,
                date_of_ssa=day_of(MONTH, 3),
                fy=FY,
                quarter=Cal.quarter_of_month(MONTH),
                uploaded_by=officer.user_id,
                collected_by_user_id=officer.user_id,
                verification_status="confirmed",
                average_score=6.5,
            )
        ]
    )
    TargetLedgerDirty.objects.create(
        owner_id=officer.user_id, fy=FY, marked_at=dj_timezone.now()
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gmt%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
        cursor.execute(
            "SELECT row_to_json(t)::text FROM target_achievement_ledger t WHERE source_id LIKE 'gmt%%' ORDER BY source_id"
        )
        rows["target_achievement_ledger"] = [
            json.loads(r[0]) for r in cursor.fetchall()
        ]
        cursor.execute(
            "SELECT row_to_json(t)::text FROM target_ledger_dirty t WHERE owner_id = ANY(%s) ORDER BY id",
            [officer_owners()],
        )
        rows["target_ledger_dirty"] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUERIES = [
    (OFFICER, {}),
    (OFFICER, {"month": "1"}),
    (OFFICER, {"fy": str(int(FY) - 1)}),
    (EMPTY, {}),
    (OFFICER, {"fy": NEXT}),
    (OFFICER, {"fy": NEXT, "month": "4"}),
    (EMPTY, {"fy": NEXT}),
    (COORDINATOR, {}),
    *[(partner, {}) for partner in PARTNERS],
]

clear()
try:
    file_rows()
    rows = dump_rows()
    answers = []
    for email, query in QUERIES:
        reader = User.objects.get(email=email)
        at = dj_timezone.now().isoformat()
        with transaction.atomic():
            status, body = read_page(reader, PATH, query)
            transaction.set_rollback(True)
        answers.append(
            {
                "email": email,
                "path": PATH,
                "query": query,
                "at": at,
                "status": status,
                "body": body,
            }
        )
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        out,
        default=str,
    )
print(f"wrote {len(answers)} answers")
