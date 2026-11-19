"""Write page_golden.json: Acting Leadership (/acting-leadership) as the
existing feed reads it, for every reader the page opens to and one it
refuses.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/page_golden.json \\
    python manage.py shell < platform/backend/internal/acting/testdata/page_golden.py

Only against a database whose name ends in "_test". Everything happens in
one transaction that is rolled back. It files, every id starting "gac",
acting appointments the seed lacks (by SQL, so no audit row is written): the
first Programme Lead's officer acting this month, another next month, one
whose month has ended, one cancelled, and the Country Director's Lead acting
as Country Director next month. It asks the page as the Programme Lead, the
officer appointed for next month, the Country Director, HR, IA, the Admin and
the Accountant it refuses (the officer acting this month works in the acting
seat, which the existing application answers), and writes the rows and the answers.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("page_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/acting-leadership"
NOW = dj_timezone.now()
TODAY = dj_timezone.localdate()


def month(offset):
    y, m = TODAY.year, TODAY.month + offset
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    start = date(y, m, 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = date.fromordinal(date(ny, nm, 1).toordinal() - 1)
    return start, end


def profile(email):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT u.id, sp.id, COALESCE(sp.country, '') FROM \"user\" u "
            "JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL WHERE u.email = %s",
            [email],
        )
        return cursor.fetchone()


def officers(lead_staff):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT u.id FROM staff_supervisor_assignment l JOIN staff_profile sp ON sp.id = l.supervisee_id "
            "JOIN \"user\" u ON u.id = sp.user_id WHERE l.supervisor_id = %s AND u.roles @> ARRAY['CCEO']::varchar[] "
            "ORDER BY u.email",
            [lead_staff],
        )
        return [r[0] for r in cursor.fetchall()]


def file(
    n,
    role_key,
    acting_role,
    appointee,
    appointee_role,
    by,
    by_role,
    scope,
    seat,
    country,
    offset,
    cancelled=False,
):
    start, end = month(offset)
    # A second apart, so appointments starting the same month list in one
    # order (start date, then newest first) on both sides, never the plan's.
    stamp = (NOW - timedelta(seconds=n)).isoformat()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO acting_assignment (id, created_at, updated_at, role_key, acting_role, appointee_id, appointee_role, "
            "appointed_by_id, appointed_by_role, scope_type, seat_id, country, start_date, end_date, cancelled_at, "
            "cancelled_by_id, cancel_reason, in_capacity, grant_snapshot, revisions) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true, '{}', '[]')",
            [
                f"gac{n:02d}",
                stamp,
                stamp,
                role_key,
                acting_role,
                appointee,
                appointee_role,
                by,
                by_role,
                scope,
                seat,
                country,
                start,
                end,
                stamp if cancelled else None,
                by if cancelled else None,
                "Plans changed" if cancelled else "",
            ],
        )


def dump():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM acting_assignment t WHERE id LIKE 'gac%%' ORDER BY ctid"
        )
        return {"acting_assignment": [json.loads(r[0]) for r in cursor.fetchall()]}


answers = []
with transaction.atomic():
    pl_user, pl_staff, pl_country = profile("pl1@edify.org")
    cd_user, cd_staff, cd_country = profile("cd@edify.org")
    team = officers(pl_staff)
    first, second = team[0], team[1] if len(team) > 1 else team[0]
    file(
        1,
        "acting_pl",
        "Program Lead",
        first,
        "CCEO",
        pl_user,
        "Program Lead",
        "pl_team",
        pl_staff,
        pl_country,
        0,
    )
    file(
        2,
        "acting_pl",
        "Program Lead",
        second,
        "CCEO",
        pl_user,
        "Program Lead",
        "pl_team",
        pl_staff,
        pl_country,
        1,
    )
    file(
        3,
        "acting_pl",
        "Program Lead",
        first,
        "CCEO",
        pl_user,
        "Program Lead",
        "pl_team",
        pl_staff,
        pl_country,
        -2,
    )
    file(
        4,
        "acting_pl",
        "Program Lead",
        second,
        "CCEO",
        pl_user,
        "Program Lead",
        "pl_team",
        pl_staff,
        pl_country,
        2,
        cancelled=True,
    )
    file(
        5,
        "acting_cd",
        "CountryDirector",
        pl_user,
        "Program Lead",
        cd_user,
        "CountryDirector",
        "country",
        cd_staff,
        cd_country,
        1,
    )
    rows = dump()
    # The officer acting this month works in the acting seat, which the
    # existing application answers everywhere; the one appointed for next
    # month reads the page in their own role.
    next_email = User.objects.get(id=second).email
    readers = [
        "pl1@edify.org",
        next_email,
        "cd@edify.org",
        "hr@edify.org",
        "ia@edify.org",
        "admin@edify.org",
        "accountant@edify.org",
    ]
    for email in dict.fromkeys(readers):
        user = User.objects.get(email=email)
        with transaction.atomic():
            status, body = read_page(user, PATH, {})
            transaction.set_rollback(True)
        answers.append(
            {"email": email, "path": PATH, "query": {}, "status": status, "body": body}
        )
    transaction.set_rollback(True)

with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {
            "written": NOW.isoformat(),
            "today": TODAY.isoformat(),
            "rows": rows,
            "answers": answers,
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
