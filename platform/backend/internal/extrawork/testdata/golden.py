"""Write extra_work_golden.json: Extra Assigned Work as the existing
application answers it for assignments the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/extra_work_golden.json \\
    python manage.py shell < platform/backend/internal/extrawork/testdata/golden.py

Only against a database whose name ends in "_test". It files a set of
assignments there, every id starting "gew" (every status, overdue and not,
returned with a long reason, submitted with and without evidence, verified
with points, with whole points and without points, cancelled; instructions,
outcomes and notes longer than the page cuts; enough for one officer to page;
work the Programme Lead assigned, reviews and monitors; another year's work
and a scoring policy approved for one year only), asks the app's feed
(apps.mobile_feed.views.read_page, the view, the template and the reader
unmodified) a set of questions as six accounts, writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/extra_work_test.go files the same rows, asks Go the same
questions and compares each answer as a whole message.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.core.fy import get_operational_fy
from apps.hr.models import ExtraAssignment, ExtraWorkScoringPolicy
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
TABLES = ("hr_extra_assignment", "hr_extra_work_scoring_policy")
LONG = (
    "Walk every classroom of the school with the head teacher, note what the "
    "timetable promises against what is taught, and write up what is missing "
    "with a plan the school agrees to — then share it with the cluster."
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gew%%'")  # noqa: S608  # nosec B608


def ids():
    return {
        u.email: str(u.id)
        for u in User.objects.filter(
            email__in=[
                "cd@edify.org",
                "pl1@edify.org",
                "cceo@edify.org",
                "cceo1@edify.org",
                "admin@edify.org",
                "ia@edify.org",
            ]
        )
    }


def file_rows():
    who = ids()
    cd, pl, paul, one = (
        who["cd@edify.org"],
        who["pl1@edify.org"],
        who["cceo@edify.org"],
        who["cceo1@edify.org"],
    )
    fy = get_operational_fy()
    last = str(int(fy) - 1)
    today = dj_timezone.localdate()
    at = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)
    n = [0]

    def add(assignee, assigner, reviewer, status, *, days=7, **more):
        n[0] += 1
        fields = {
            "id": f"gew{n[0]:04d}",
            "fy": fy,
            "title": f"Task {n[0]}",
            "instruction": f"Do part {n[0]} of the plan.",
            "category": "operational_support",
            "assigner_id": assigner,
            "assigner_role": "CountryDirector" if assigner == cd else "Program Lead",
            "assignee_id": assignee,
            "assignee_role": "Program Lead" if assignee == pl else "CCEO",
            "reviewer_id": reviewer,
            "due_date": today + timedelta(days=days),
            "status": status,
            **more,
        }
        ExtraAssignment.objects.create(**fields)

    # Paul (cceo@): every status, assigned by the CD and reviewed by pl1.
    add(paul, cd, pl, "assigned", days=-3, instruction=LONG)
    add(paul, cd, pl, "assigned", days=0)
    add(paul, cd, pl, "acknowledged", days=2)
    add(paul, cd, pl, "in_progress", days=-1, supervising_pl_id=pl)
    add(
        paul,
        cd,
        pl,
        "returned",
        days=4,
        return_reason=LONG,
        title="Returned & <checked>",
        supervising_pl_id=pl,
    )
    add(
        paul,
        cd,
        pl,
        "submitted",
        days=-5,
        submitted_at=at,
        outcome=LONG + " " + LONG,
        evidence_note=LONG,
        evidence_uri="https://example.org/evidence?id=1&kind=photo",
        supervising_pl_id=pl,
    )
    add(paul, cd, pl, "submitted", days=3, submitted_at=at + timedelta(days=1))
    add(
        paul,
        cd,
        pl,
        "verified",
        days=-9,
        contribution_points=Decimal("2.50"),
        supervising_pl_id=pl,
    )
    add(paul, cd, pl, "verified", days=-8, contribution_points=Decimal("1.00"))
    add(paul, cd, pl, "verified", days=-7)
    add(paul, cd, pl, "cancelled", days=-6)
    # Paul's last year: one verified piece, under an approved policy.
    add(paul, cd, pl, "verified", days=-300, fy=last, contribution_points=Decimal("1"))
    add(paul, cd, pl, "assigned", days=-200, fy=last)
    ExtraWorkScoringPolicy.objects.create(id="gewpolicy1", fy=last, status="approved")
    ExtraWorkScoringPolicy.objects.create(id="gewpolicy2", fy=fy, status="draft")
    # pl1 assigns cceo1 enough to page, and reviews it.
    for i in range(57):
        add(
            one,
            pl,
            pl,
            ["assigned", "in_progress", "submitted", "verified"][i % 4],
            days=i - 20,
            submitted_at=at + timedelta(hours=i) if i % 4 == 2 else None,
            supervising_pl_id=pl,
        )
    # The CD hands pl1 a piece, which the CD reviews.
    add(pl, cd, cd, "in_progress", days=5)


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gew%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def questions():
    fy = get_operational_fy()
    last = str(int(fy) - 1)
    return {
        "cceo@edify.org": [{}, {"fy": last}, {"fy": " " + last + " "}, {"fy": "1999"}],
        "cceo1@edify.org": [
            {},
            {"extra_work_mine_page": "2"},
            {"extra_work_mine_page": "3"},
            {"extra_work_mine_page": "9"},
            {"extra_work_mine_page": "abc"},
        ],
        "pl1@edify.org": [{}, {"fy": last}, {"extra_work_mine_page": "2"}],
        "cd@edify.org": [{}, {"fy": last}],
        "admin@edify.org": [{}],
        "ia@edify.org": [{}],
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in questions().items():
            user = User.objects.get(email=email)
            for query in asked:
                status, body = read_page(user, "/extra-work", query)
                answers.append(
                    {"email": email, "query": query, "status": status, "body": body}
                )
    finally:
        clear()
    out = {
        "today": dj_timezone.localdate().isoformat(),
        "rows": rows,
        "answers": answers,
    }
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1, default=str)
    print(f"{len(answers)} answers written")


main()
