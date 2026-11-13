"""Write cce_leadership_golden.json: the CCE leadership registers as the
existing application answers them over records the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/cce_leadership_golden.json \\
    python manage.py shell < platform/backend/internal/ccelead/testdata/golden.py

Only against a database whose name ends in "_test". It files monthly reports
there, every id starting "gcl" (the Regional Lead's in every status, one
reviewed, another author's, other countries, enough for a reader of all of
them to page), asks the app's feed as five accounts, writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/cce_leadership_test.go files the same rows and compares.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.cce_leadership.models import (
    CceoCoaching,
    RegionalCceReport,
    RegionalEngagement,
)
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
TABLES = (
    "cce_cceo_coaching",
    "cce_regional_engagement",
    "cce_regional_report",
    "activity",
)
PATHS = ("/cce-leadership/reports", "/cce-leadership/feedback")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gcl%%'")  # noqa: S608  # nosec B608


def file_rows():
    lead = User.objects.get(email="regional-lead@edify.org")
    rvp = User.objects.get(email="rvp@edify.org")
    at = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
    statuses = ["draft", "submitted", "acknowledged", "returned"]
    for i in range(6):
        period = date(2026, 4 + i, 1)
        status = statuses[i % 4]
        RegionalCceReport.objects.create(
            id=f"gcl{i:03d}",
            author_id=lead.id,
            period=period,
            fy="2026",
            countries=[["Uganda"], ["Uganda", "Kenya"], ["Kenya"]][i % 3],
            status=status,
            submitted_at=None if status == "draft" else at - timedelta(days=30 * i),
            reviewed_by_id=rvp.id if status in ("acknowledged", "returned") else None,
            reviewed_at=at if status in ("acknowledged", "returned") else None,
        )
    for i in range(52):
        RegionalCceReport.objects.create(
            id=f"gcl{100 + i:03d}",
            author_id=f"other-author-{i % 3}",
            period=date(2020 + i // 12, 1 + i % 12, 1),
            fy="2025",
            countries=["Rwanda"] if i % 5 == 0 else ["Uganda"],
            status=statuses[i % 4],
            submitted_at=None if i % 4 == 0 else at - timedelta(days=i),
        )


def file_feedback():
    lead = User.objects.get(email="regional-lead@edify.org")
    pl = StaffProfile.objects.get(user__email="pl1@edify.org")
    pl2 = StaffProfile.objects.get(user__email="pl2@edify.org")
    from apps.partners.models import Partner
    from apps.schools.models import School

    school = School.objects.filter(deleted_at__isnull=True).order_by("id").first()
    partner = Partner.objects.order_by("id").first()
    officer_staff = StaffProfile.objects.filter(supervisor_links__supervisor=pl).first()
    trainings = []
    for k, (delivery, planned) in enumerate(
        [("partner", date(2026, 10, 3)), ("staff", date(2026, 9, 21)), ("staff", None)]
    ):
        trainings.append(
            Activity.objects.create(
                id=f"gcla{k}",
                activity_type="in_school_training",
                activity_name_snapshot="" if k else "Golden Phonics Training",
                school=school if k != 2 else None,
                fy="2027",
                planned_date=planned,
                status="scheduled",
                delivery_type=delivery,
                assigned_partner_id=partner.id
                if delivery == "partner" and partner
                else None,
                responsible_staff_id=officer_staff.id if officer_staff else None,
            )
        )
    at = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    for i in range(9):
        activity = trainings[i % 3] if i < 7 else None
        RegionalEngagement.objects.create(
            id=f"gcle{i:03d}",
            author_id=lead.id,
            kind="training_observation",
            held_on=date(2026, 10, 1 + i * 3),
            fy="2027",
            country=["Uganda", "Uganda", "Kenya", ""][i % 4],
            program_lead_ids=[pl.id] if i % 3 else [pl2.id, pl.id],
            subject=f"Golden observation {i}",
            activity=activity,
            rating_biblical_integration=[4, None, 3][i % 3],
            rating_need_alignment=[3, 2, None][i % 3],
            rating_facilitation=[4, 3, 3][i % 3],
            recommendation=["continue", "strengthen", ""][i % 3],
            feedback_shared_at=None if i in (0, 5) else at + timedelta(days=i),
            acknowledged_at=at + timedelta(days=i + 1) if i % 2 else None,
        )
    officer = StaffProfile.objects.filter(supervisor_links__supervisor=pl).first()
    if officer is not None:
        CceoCoaching.objects.create(
            id="gclc001",
            author_id=pl.user_id,
            cceo_staff_id=officer.id,
            cceo_user_id=officer.user_id,
            kind="training_observation",
            held_on=date(2026, 11, 5),
            fy="2027",
            subject="Passed on",
            source_engagement_id="gcle003",
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gcl%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "regional-lead@edify.org": [{}],
    "rvp@edify.org": [{}, {"register_page": "2"}],
    "admin@edify.org": [{}, {"register_page": "2"}, {"register_page": "x"}],
    "ia@edify.org": [{}],
    "cd@edify.org": [{}],
    "pl1@edify.org": [{}, {"open": "gcle003"}, {"open": "nothing"}],
}


def main():
    clear()
    try:
        file_rows()
        file_feedback()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for path in PATHS:
                for query in asked:
                    status, body = read_page(user, path, query)
                    answers.append(
                        {
                            "email": email,
                            "path": path,
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
