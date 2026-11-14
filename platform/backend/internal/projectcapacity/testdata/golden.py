"""Write project_capacity_golden.json: Project Capacity as the existing
application answers it over projects and allocations the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/project_capacity_golden.json \\
    python manage.py shell < platform/backend/internal/projectcapacity/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpc", three projects the coordinator runs (one with enough
allocations to page, full, near capacity and available, names in both cases;
one paused; one with none), staff of every planning role and none, a deleted
People record, and schools enrolled against the allocations; asks the app's
feed as three accounts; writes the rows and the answers to GOLDEN_OUT and
deletes the rows. internal/integration/project_capacity_test.go files the
same rows and compares.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.mobile_feed.views import read_page
from apps.projects.models import (
    Project,
    ProjectSchoolAssignment,
    ProjectStaffCapacity,
)
from apps.schools.models import School

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/projects/capacity"
#: Children first.
TABLES = (
    "activity",
    "project_school_assignment",
    "project_staff_capacity",
    "project",
    "staff_profile",
    "user",
)


def clear():
    Activity.all_objects.filter(id__startswith="gpc").delete()
    ProjectSchoolAssignment.objects.filter(id__startswith="gpc").delete()
    ProjectStaffCapacity.objects.filter(id__startswith="gpc").delete()
    Project.all_objects.filter(id__startswith="gpc").delete()
    StaffProfile.all_objects.filter(id__startswith="gpc").delete()
    User.all_objects.filter(id__startswith="gpc").delete()


def file_rows():
    coordinator = StaffProfile.objects.get(user__email="coordinator@edify.org")
    pc_user = coordinator.user
    now = dj_timezone.now()
    big = Project.objects.create(
        id="gpcp1",
        name="Golden Capacity <A>",
        code="SP-GOLD",
        status="active",
        manager_staff_id=coordinator.id,
    )
    paused = Project.objects.create(
        id="gpcp2",
        name="golden paused",
        status="paused",
        manager_staff_id=coordinator.id,
    )
    Project.objects.create(
        id="gpcp3",
        name="Golden Empty",
        code="",
        status="scaling",
        manager_staff_id=coordinator.id,
    )
    Project.objects.create(
        id="gpcp4",
        name="Golden Closed",
        status="closed",
        manager_staff_id=coordinator.id,
    )
    people = []
    for i in range(53):
        user = User.objects.create(
            id=f"gpcu{i:03d}",
            email=f"gpc{i:03d}@example.org",
            # Names in both cases, so the table's case-folded order shows.
            name=(f"golden staff {i:02d}" if i % 2 else f"Golden Staff {i:02d}"),
            roles=[["CCEO"], ["Program Lead"], [], ["CCEO", "Program Lead"]][i % 4],
            active_role=["CCEO", "Program Lead", "Accountant", "CCEO"][i % 4],
            is_active=True,
            status="active",
        )
        people.append(
            StaffProfile.objects.create(
                id=f"gpcs{i:03d}",
                user=user,
                country="Uganda",
                deleted_at=now if i == 7 else None,
            )
        )
    seed = [
        StaffProfile.objects.get(user__email="cceo1@edify.org"),
        StaffProfile.objects.get(user__email="pl1@edify.org"),
    ]
    schools = list(School.objects.filter(deleted_at__isnull=True).order_by("id")[:40])
    k = 0
    # (maximum, enrolled): full, near capacity, available, one place used.
    shapes = [(5, 5), (5, 4), (3, 2), (3, 1), (2, 0)]
    for i, staff in enumerate(people + seed):
        maximum, enrolled = shapes[i % 5] if i < 8 else (1 + i % 4, 0)
        ProjectStaffCapacity.objects.create(
            id=f"gpcc{i:03d}",
            max_schools=maximum,
            set_by=pc_user.id,
            set_by_role="ProjectCoordinator",
            project=big,
            staff=staff,
        )
        for _ in range(enrolled):
            ProjectSchoolAssignment.objects.create(
                id=f"gpca{k:03d}",
                project=big,
                school=schools[k],
                assigned_staff=staff,
                assigned_by=staff.user_id,
            )
            k += 1
    # A school added outside the allocations.
    ProjectSchoolAssignment.objects.create(
        id=f"gpca{k:03d}", project=big, school=schools[k], assigned_by=pc_user.id
    )
    for i, staff in enumerate(seed):
        ProjectStaffCapacity.objects.create(
            id=f"gpcd{i:03d}",
            max_schools=2,
            set_by=pc_user.id,
            set_by_role="ProjectCoordinator",
            project=paused,
            staff=staff,
        )
    file_visits(people, schools)


def file_visits(people, schools):
    """Counted visits in the operational year for two of the staff (the
    Programme Lead past their 280), one filed under the account's id, and
    work that does not count: partner-delivered, cancelled, another year."""
    fy = get_operational_fy()
    cceo, lead = people[0], people[1]
    rows = []

    def visit(n, staff_ref, **extra):
        fields = {
            "activity_type": "follow_up_visit",
            "school": schools[n % len(schools)],
            "fy": fy,
            "planned_date": dj_timezone.localdate(),
            "status": "scheduled",
            "responsible_staff_id": staff_ref,
        }
        fields.update(extra)
        rows.append(Activity(id=f"gpcv{len(rows):04d}", **fields))

    for n in range(12):
        visit(n, cceo.id)
    visit(0, cceo.user_id)
    for n in range(283):
        visit(n, lead.id)
    visit(1, cceo.id, delivery_type="partner")
    visit(2, cceo.id, status="cancelled")
    visit(3, cceo.id, fy=str(int(fy) - 1))
    Activity.objects.bulk_create(rows)


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpc%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


# The staff table's page key ("staff_page-<project id>") is never asked: it
# holds a hyphen, which the feed's QUERY_KEY drops, so the app cannot pass it.
QUESTIONS = {
    "coordinator@edify.org": [
        {},
        {"project": "gpcp1"},
        {"project": " gpcp2 "},
        {"project": "gpcp3"},
        {"project": "gpcp4"},
        {"project": "nothing"},
    ],
    "admin@edify.org": [{}, {"project": "gpcp1"}, {"project": "gpcp2"}],
    "ia@edify.org": [{}, {"project": "gpcp1"}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for query in asked:
                status, body = read_page(user, PATH, query)
                answers.append(
                    {
                        "email": email,
                        "path": PATH,
                        "query": query,
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
