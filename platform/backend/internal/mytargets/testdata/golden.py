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
confirmed SSA scored below Strong in two interventions; and a professional
development request. It
then brings the officers' ledgers up to date as any reading page does
(refresh_many), so the page's own rebuild finds nothing to change; asks the
page for this month, an earlier month, another year and an officer with no
agreement; writes the rows (the ledger rows the refresh wrote among them,
found by their sources) and the answers to GOLDEN_OUT and deletes the rows.
Dates sit around the day it was written, so
internal/integration/my_targets_test.go compares within half an hour.
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
from apps.hr.models import PerformancePriority, PerformanceReview
from apps.core_schools.models import CorePlan
from apps.mobile_feed.views import read_page
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
TODAY = dj_timezone.localdate()
NOW = Cal.current()
FY = NOW["fy"]
MONTH = NOW["month_of_fy"]
#: Children first; the ledger is found by its sources, not its ids.
TABLES = (
    "ssa_score",
    "staff_school_assignment",
    "core_plan",
    "pd_request",
    "hr_performance_priority",
    "hr_performance_review",
    "monthly_personal_target",
    "activity",
    "ssa_record",
    "mscs_story",
)


def clear():
    TargetAchievementLedger.objects.filter(source_id__startswith=P).delete()
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def day_of(month, day=10):
    start, _ = Cal.month_range(FY, month)
    return start + timedelta(days=day - 1)


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
            SsaScore(id=f"{P}X1", ssa_record=scored, intervention="leadership", score=4.5),
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
    users = list(User.objects.filter(email__in=[OFFICER, EMPTY]))
    refresh_many(users, FY)
    left = TargetLedgerDirty.objects.filter(
        owner_id__in=[officer.id, officer.user_id], fy=FY
    )
    if left.exists():
        raise SystemExit("the ledger is still marked after the refresh")


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
    return rows


QUERIES = [
    (OFFICER, {}),
    (OFFICER, {"month": "1"}),
    (OFFICER, {"fy": str(int(FY) - 1)}),
    (EMPTY, {}),
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
