"""Write golden.json: Personal Time Off (/personal-time-off/) as the existing
feed reads it, over leave the development seed lacks.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/personaltimeoff/testdata/golden.py

Only against a database whose name ends in "_test". The seed holds no leave at
all, and the page writes a reader's balances when it opens on none (and
rewrites them every time, with the same values once they are current). It
files, every id starting "gpto": an officer's leave (pending ahead, approved
past with a cover, approved ahead over their planned work, rejected), a
colleague's leave the officer covers, a cover each way, an upcoming blackout, and every reader's balances as the existing
service writes them, renamed; asks the page of each reader; writes the rows
and the answers to GOLDEN_OUT and deletes the rows. Dates sit around the day
it was written, so internal/integration/personal_time_off_test.go compares
within half an hour.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    StaffProfile,
    TemporaryCoverageAssignment,
)
from apps.hr.leave_services import LeaveBalanceService
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/personal-time-off/"
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()
YEAR = TODAY.year
TABLES = ("leave_balance", "temporary_coverage_assignment", "calendar_block", "leave")
READERS = (
    "cceo1@edify.org",
    "cceo2@edify.org",
    "pl1@edify.org",
    "cd@edify.org",
    "hr@edify.org",
    "admin@edify.org",
    "accountant@edify.org",
    "ia@edify.org",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', ["gpto%"])


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


def file_rows():
    officer = StaffProfile.objects.get(user__email="cceo1@edify.org")
    colleague = StaffProfile.objects.get(user__email="cceo2@edify.org")
    reviewer = User.objects.get(email="pl1@edify.org")
    leaves = [
        ("gptoL1", "personal_time_off", day(20), day(22), 3, "pending", None, None),
        (
            "gptoL2",
            "sick_leave",
            day(-40),
            day(-39),
            2,
            "approved",
            colleague,
            reviewer.id,
        ),
        (
            "gptoL3",
            "personal_time_off",
            day(2),
            day(3),
            2,
            "approved",
            colleague,
            reviewer.id,
        ),
        (
            "gptoL4",
            "personal_time_off",
            day(-90),
            day(-90),
            1,
            "rejected",
            None,
            reviewer.id,
        ),
        (
            "gptoL5",
            "personal_time_off",
            day(-1),
            day(4),
            4,
            "approved",
            officer,
            reviewer.id,
        ),
    ]
    for i, (key, kind, start, end, days, status, cover, reviewed) in enumerate(leaves):
        Leave.objects.create(
            id=key,
            staff=colleague if key == "gptoL5" else officer,
            type=kind,
            start_date=start,
            end_date=end,
            days=days,
            status=status,
            reason=f"Golden leave {i}",
            covering_staff=cover,
            reviewed_by_user_id=reviewed,
            coverage_status="Accepted" if cover else "Not Required",
        )
        Leave.objects.filter(id=key).update(created_at=NOW - timedelta(hours=10 - i))
    TemporaryCoverageAssignment.objects.create(
        id="gptoC1",
        original_staff=officer,
        covering_staff=colleague,
        start_datetime=NOW - timedelta(days=1),
        end_datetime=NOW + timedelta(days=5),
        status="active",
        leave_request_id="gptoL3",
    )
    TemporaryCoverageAssignment.objects.create(
        id="gptoC2",
        original_staff=colleague,
        covering_staff=officer,
        start_datetime=NOW - timedelta(days=1),
        end_datetime=NOW + timedelta(days=5),
        status="active",
        leave_request_id="gptoL5",
    )
    CalendarBlock.objects.create(
        id="gptoB1",
        title="Golden blackout",
        block_type="BLACKOUT",
        start_date=TODAY + timedelta(days=10),
        end_date=TODAY + timedelta(days=11),
        is_active=True,
    )
    for email in READERS:
        user = User.objects.get(email=email)
        sp = StaffProfile.objects.filter(user=user).first()
        if not sp:
            continue
        LeaveBalanceService.recalculate_balances(sp, YEAR)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE leave_balance SET id = 'gpto' || substr(id, 5) WHERE id NOT LIKE 'gpto%%' AND year = %s",
            [YEAR],
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gpto%"],
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def ask(reader, query):
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
    }


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email in READERS:
        answers.append(ask(User.objects.get(email=email), {}))
    answers.append(ask(User.objects.get(email="cceo1@edify.org"), {"tab": "past"}))
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {
            "today": TODAY.isoformat(),
            "written": NOW.isoformat(),
            "rows": rows,
            "answers": answers,
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
