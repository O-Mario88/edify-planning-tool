"""Write the HR programme registers' golden: Culture & Engagement, Payroll
Readiness, Succession Planning and Staff Wellness & Support (hr_views,
pages/hr/module_workspace.html) as the existing feed reads them.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/hrregister/testdata/programmes_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gprg", People records (two departments and none, active and not,
one in a country the registry does not hold (only Admin
reads it: the regional reach is every registered country), a deleted record and a deleted account) with payroll checks
over two periods, successors at every readiness (each changed on a UTC
evening, a Nairobi morning) and leave of every status, covered and not;
asks the four registers of the readers who open them and one who does not,
writes the answers with the rows as the database held them (`tables`), and
deletes the rows. internal/integration/hr_programmes_test.go files them
again and asks Go.
"""

import json
import os
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.accounts.models import Leave, StaffProfile
from apps.hr.models import PayrollReadinessRecord, SuccessionCandidate

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("programmes_golden.py runs only against a _test database")

User = get_user_model()
P = "gprg"
PAGES = (
    "/culture-engagement",
    "/payroll-readiness",
    "/succession-planning",
    "/wellness",
)
READERS = (
    "admin@edify.org",
    "hr@edify.org",
    "ia@edify.org",
    "accountant@edify.org",
    "cceo1@edify.org",
)
QUERIES = [
    {},
    {"q": "gprg"},
    {"q": "2026-09"},
    {"q": "bank"},
    {"q": "ready now"},
    {"q": "sick"},
    {"q": "approved"},
    {"q": "finance"},
    {"page": "2"},
]
#: Children first.
TABLES = (
    "leave",
    "hr_succession_candidate",
    "hr_payroll_readiness",
    "staff_profile",
    "user",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_people():
    now = timezone.now()
    profiles = []
    for i in range(10):
        user = User.objects.create(
            id=f"{P}u{i:02d}",
            email=f"{P}{i:02d}@example.org",
            name=f"Gprg Person {i:02d}",
            roles=["CCEO"],
            active_role=["CCEO", "Program Lead"][i % 2],
            is_active=True,
            status="active",
            deleted_at=now if i == 9 else None,
        )
        profiles.append(
            StaffProfile.objects.create(
                id=f"{P}p{i:02d}",
                user=user,
                title=["Field Officer", "", None][i % 3],
                department=None if i == 7 else ["Finance", "Programmes"][i % 2],
                country="Tanzania" if i == 6 else "Uganda",
                onboarding_state=["active", "pending", "active", "suspended"][i % 4],
                deleted_at=now if i == 8 else None,
            )
        )
    return profiles


def file_rows():
    profiles = file_people()
    periods = ["2026-10", "2026-09"]
    for i in range(16):
        PayrollReadinessRecord.objects.create(
            id=f"{P}y{i:02d}",
            staff=profiles[i % 10],
            payroll_period=periods[i // 10],
            has_exceptions=i % 3 == 0,
            exception_notes="Missing bank letter" if i % 5 == 0 else None,
            is_payroll_ready=i % 2 == 0,
        )
    readiness = [
        "Ready Now",
        "Ready in 6-12 Months",
        "Ready in 1-2 Years",
        "Development Required",
        "Not Currently Ready",
    ]
    positions = ["Country Director", "Programme Lead", "Finance Lead"]
    evening = datetime(2026, 9, 1, 21, 30, tzinfo=dt_timezone.utc)
    for i in range(13):
        SuccessionCandidate.objects.create(
            id=f"{P}j{i:02d}",
            position_name=positions[i % 3],
            staff_successor=profiles[i % 10],
            readiness=readiness[i % 5],
        )
        SuccessionCandidate.objects.filter(id=f"{P}j{i:02d}").update(
            updated_at=evening + timedelta(days=i, hours=i % 3)
        )
    kinds = ["annual", "sick", "maternity_leave", "compassionate"]
    statuses = ["pending", "approved", "rejected", "cancelled", "approved"]
    Leave.objects.bulk_create(
        [
            Leave(
                id=f"{P}l{i:02d}",
                staff=profiles[i % 10],
                type=kinds[i % 4],
                start_date=f"2026-11-{i + 1:02d}",
                end_date=f"2026-11-{i + 3:02d}",
                days=3,
                days_charged=None if i % 3 == 0 else 2,
                status=statuses[i % 5],
                coverage_status=["Proposed", "Confirmed", ""][i % 3],
                covering_staff=profiles[(i + 1) % 10] if i % 2 else None,
            )
            for i in range(14)
        ]
    )
    # The newest first: tomorrow, so rows written meanwhile stay older.
    start = timezone.now() + timedelta(days=1)
    for i in range(14):
        Leave.objects.filter(id=f"{P}l{i:02d}").update(
            created_at=start + timedelta(minutes=i * 7 % 15)
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = ",".join(PAGES)
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(QUERIES)
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
