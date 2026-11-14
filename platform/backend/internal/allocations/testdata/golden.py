"""Write allocations_golden.json: Priorities (/my-performance) as the existing
application answers it in a year with approved allocations.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/allocations_golden.json \\
    python manage.py shell < platform/backend/internal/allocations/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpa", a country priority for this year with four live, approved
milestones (distinct schools counted; a coverage rate capped at 100; teachers
trained at client schools; one no activity counts towards) and an inactive one;
approved allocations (an officer's own, a Programme Lead's team root and the
officers' own beside it, the country's top-level ones) and a draft one;
activities on the milestones' catalogue items, planned and completed, in and
out of the officer's hands; and credits, one reversed. It asks the app's feed
as the officer, their Programme Lead, Admin, the Country Director, Impact
Assessment and HR, writes the rows and the answers to GOLDEN_OUT and deletes
the rows. internal/integration/allocations_test.go files the same rows and
compares.
"""

import json
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.fy import get_operational_fy
from apps.hr.models import (
    MilestoneActivityRule,
    MilestoneAllocation,
    MilestoneMetricDefinition,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
)
from apps.hr.team_roster import team_members
from apps.mobile_feed.views import read_page
from apps.schools.models import School

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/my-performance"
#: Children first.
TABLES = (
    "hr_milestone_progress_credit",
    "hr_milestone_allocation",
    "hr_milestone_activity_rule",
    "hr_priority_milestone",
    "hr_strategic_priority",
    "activity",
)


def clear():
    MilestoneProgressCredit.objects.filter(id__startswith="gpa").delete()
    MilestoneAllocation.objects.filter(id__startswith="gpa").delete()
    MilestoneActivityRule.objects.filter(id__startswith="gpa").delete()
    PriorityMilestone.objects.filter(id__startswith="gpa").delete()
    StrategicPriority.objects.filter(id__startswith="gpa").delete()
    Activity.all_objects.filter(id__startswith="gpa").delete()


def file_rows(fy):
    lead = User.objects.get(email="pl1@edify.org")
    officers = team_members(lead)
    officer, other = officers[0], officers[1]
    items = list(ActivityCatalogueItem.objects.order_by("id")[:2])
    c1, c2 = items
    schools = list(School.objects.filter(deleted_at__isnull=True).order_by("id")[:6])
    client = [
        s for s in schools if s.school_type in ("client", "core_trained")
    ] or schools
    today = dj_timezone.localdate()
    definition = MilestoneMetricDefinition.objects.order_by("id").first()

    priority = StrategicPriority.objects.create(
        id="gpaP1",
        fy=fy,
        level="country",
        country_id="Uganda",
        title="Golden priority",
        status="published",
    )

    def milestone(key, measurement, target, unit, weight, **extra):
        return PriorityMilestone.objects.create(
            id=f"gpaM{key}",
            priority=priority,
            code=f"GPA{key}",
            source_order=int(key),
            title=f"Golden milestone {key}",
            measurement_type=measurement,
            target_value=Decimal(target),
            target_unit=unit,
            weight=Decimal(weight),
            active=extra.pop("active", True),
            metric_definition=definition,
            definition_status=extra.pop("definition_status", "approved"),
            **extra,
        )

    m1 = milestone("1", "count", "40", "schools", "30")
    m2 = milestone("2", "percentage", "80", "%", "20", cap_at_100=True)
    m3 = milestone("3", "count", "100", "teachers", "25")
    m4 = milestone("4", "count", "6", "events", "10")
    m5 = milestone("5", "count", "9", "schools", "5", active=False)

    def rule(key, m, basis, item, **extra):
        return MilestoneActivityRule.objects.create(
            id=f"gpaR{key}",
            milestone=m,
            counting_basis=basis,
            catalogue_item=item,
            active=extra.pop("active", True),
            **extra,
        )

    r1 = rule("1", m1, "UNIQUE_SCHOOLS_SUPPORTED", c1)
    r2 = rule("2", m2, "PERCENT_OF_ELIGIBLE_SCHOOLS", c2)
    r3 = rule("3", m3, "UNIQUE_PARTICIPANTS", c1, school_type="client")
    rule("4", m3, "UNIQUE_PARTICIPANTS", c2, active=False)
    rule("5", m5, "UNIQUE_SCHOOLS_SUPPORTED", c1)

    def allocate(
        key,
        m,
        target,
        kind="employee",
        employee=None,
        team=None,
        weight="0",
        status="approved",
        **extra,
    ):
        return MilestoneAllocation.objects.create(
            id=f"gpaA{key}",
            milestone=m,
            allocated_to_type=kind,
            employee=employee,
            team_id=team,
            allocated_target=Decimal(target),
            weight=Decimal(weight),
            status=status,
            effective_date=today,
            **extra,
        )

    allocate("01", m1, "12", employee=officer, weight="30")
    allocate("02", m2, "80", employee=officer, weight="20", denominator=Decimal("20"))
    allocate("03", m3, "50", employee=officer, weight="25")
    allocate("04", m4, "5", employee=officer)
    allocate("05", m5, "3", employee=officer)
    allocate("06", m4, "7", employee=other, status="draft")
    allocate("11", m1, "40", kind="team", team=lead.staff_profile.id, weight="40")
    allocate("12", m3, "30", employee=other, weight="15")
    allocate("21", m1, "200", kind="country", weight="0")
    allocate("22", m2, "85", kind="country", denominator=Decimal("120"))

    def activity(key, item, school, status, days, **extra):
        return Activity.objects.create(
            id=f"gpaV{key}",
            activity_type="school_visit",
            catalogue_item=item,
            school=school,
            fy=fy,
            status=status,
            planned_date=today + timedelta(days=days),
            responsible_staff_id=extra.pop("responsible", officer.id),
            **extra,
        )

    v1 = activity("1", c1, schools[0], "scheduled", 5, expected_participants=15)
    activity("2", c1, schools[1], "scheduled", 6)
    v3 = activity(
        "3",
        c1,
        client[0],
        "completed",
        -5,
        teachers_attended=12,
        expected_participants=14,
    )
    v4 = activity("4", c2, schools[3], "completed", -3)
    v5 = activity(
        "5", c1, schools[4], "completed", -2, responsible=other.id, teachers_attended=9
    )
    activity("6", c1, schools[5], "cancelled", -1)
    v7 = activity(
        "7",
        c1,
        schools[2],
        "completed",
        -4,
        delivery_type="partner",
        monitored_by_staff_id=officer.id,
    )

    def credit(key, r, act, value="1", reversed_at=None):
        return MilestoneProgressCredit.objects.create(
            id=f"gpaC{key}",
            rule=r,
            activity=act,
            credited_value=Decimal(value),
            credited_at=dj_timezone.now(),
            reversed_at=reversed_at,
        )

    credit("1", r1, v3)
    credit("2", r1, v7)
    credit("3", r3, v3, value="12")
    credit("4", r2, v4)
    credit("5", r3, v5, value="9")
    credit("6", r1, v1, reversed_at=dj_timezone.now())
    return officer


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpa%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def main():
    fy = get_operational_fy()
    clear()
    try:
        officer = file_rows(fy)
        rows = dump_rows()
        readers = [
            officer.user.email,
            "pl1@edify.org",
            "admin@edify.org",
            "cd@edify.org",
            "ia@edify.org",
            "hr@edify.org",
        ]
        answers = []
        for email in readers:
            user = User.objects.get(email=email)
            status, body = read_page(user, PATH, {})
            answers.append(
                {
                    "email": email,
                    "path": PATH,
                    "query": {},
                    "status": status,
                    "body": body,
                }
            )
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
