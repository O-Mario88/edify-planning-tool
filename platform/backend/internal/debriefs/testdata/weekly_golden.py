"""Write the Weekly Debrief Report's golden: /debriefs/weekly-report
(debrief_views.weekly_debrief_report_view over WeeklyDebriefReportService,
pages/debriefs/weekly_report.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/debriefs/testdata/weekly_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdwr", daily debriefs from the first Lead's team in the last
completed week and the week before (roads, funds, a supportive head teacher,
good turnout, a long journey named under what worked well), and builds the reports with the service itself: the Lead's
team report for the earlier week, signed with commentary, the country report
compiled from it, signed; then the Lead's draft for the last week and the
country draft over it. It asks each reader the page bare, for the earlier
week, mid-week and with a week that is no date. A Lead or Director with no
report for the week has the existing page write one as it opens: those
answers are written as handed on (302), with no body. It writes the answers
with the rows as the database held them (`tables`) and deletes the rows.
internal/integration/debrief_weekly_test.go files them again and asks Go.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("weekly_golden.py runs only against a _test database")

User = get_user_model()
P = "gdwr"
PAGE = "/debriefs/weekly-report"
READERS = (
    "pl1@edify.org",
    "pl2@edify.org",
    "cd@edify.org",
    "admin@edify.org",
    "hr@edify.org",
    "rvp@edify.org",
    "cceo1@edify.org",
    "partner@edify.org",
    "accountant@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("daily_debrief", "weekly_debrief_report")
WRITERS = ("Program Lead", "CountryDirector")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_debriefs(start, week, team, school_id):
    """Two of the team's debriefs in the week starting `start`."""
    from apps.debriefs.models import DailyDebrief

    texts = (
        {
            "challenges_faced": "The roads were flooded after the rain.",
            # A challenge named under what worked well: read at low confidence.
            "what_went_well": "The head teacher was very supportive despite the long journey.",
            "recommendations": "Start visits earlier in the day.",
        },
        {
            "challenges_faced": "Funds were delayed again this week.",
            "what_did_not_go_well": "The road to the school was impassable.",
            "what_went_well": "Good turnout from the teachers.",
        },
    )
    for n, (user, written) in enumerate(zip(team, texts)):
        on = start + timedelta(days=n + 1)
        DailyDebrief.objects.create(
            id=f"{P}{week}{n}",
            fy=str(on.year + 1 if on.month >= 10 else on.year),
            date=timezone.make_aware(datetime.combine(on, time.min)),
            submitted_by_user_id=user.id,
            submitted_by_role=user.active_role,
            kind="daily",
            status="submitted",
            title="Daily Debrief",
            submitted_at=timezone.make_aware(datetime.combine(on, time(17, 0))),
            linked_school_ids=[school_id],
            **written,
        )


def rename(report, key):
    from apps.debriefs.models import WeeklyDebriefReport

    WeeklyDebriefReport.objects.filter(pk=report.pk).update(id=P + key)
    return WeeklyDebriefReport.objects.get(pk=P + key)


def file_rows():
    from apps.debriefs.field_debrief_service import team_staff_ids
    from apps.debriefs.weekly_report_service import (
        WeeklyDebriefReportService as WRS,
        week_bounds,
    )

    lead = User.objects.get(email="pl1@edify.org")
    director = User.objects.get(email="cd@edify.org")
    sp = StaffProfile.objects.get(user=lead)
    members = [
        s.user
        for s in StaffProfile.objects.filter(id__in=team_staff_ids(sp.id))
        .select_related("user")
        .order_by("id")
        if s.user
    ]
    team = (members + [lead])[:2]
    school_id = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(school=None)
        .values_list("school_id", flat=True)
        .first()
    )
    last, _ = week_bounds(None)
    earlier = last - timedelta(days=7)
    file_debriefs(earlier, "e", team, school_id)
    file_debriefs(last, "l", team, school_id)
    report = WRS.generate_pl_report(lead, earlier)
    report = WRS.sign(rename(report, "pl_e"), lead, "Roads remain the main risk.")
    country = WRS.generate_country_report(director, earlier)
    WRS.sign(rename(country, "cd_e"), director, "Escalated the road issue.")
    rename(WRS.generate_pl_report(lead, last), "pl_l")
    rename(WRS.generate_country_report(director, last), "cd_l")
    return last, earlier


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


def writes_on_open(queries):
    """(reader, query) pairs whose page writes a report as it opens."""
    from datetime import date

    from apps.debriefs.weekly_report_service import (
        WeeklyDebriefReportService as WRS,
        week_bounds,
    )

    out = set()
    for email in READERS:
        user = User.objects.get(email=email)
        if user.active_role not in WRITERS:
            continue
        for q in queries:
            try:
                anchor = date.fromisoformat(q["week"]) if q.get("week") else None
            except ValueError:
                anchor = None
            start, _ = week_bounds(anchor)
            if WRS.visible_report(user, start) is None:
                out.add((email, json.dumps(q, sort_keys=True)))
    return out


clear()
try:
    last, earlier = file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    queries = [
        {},
        {"week": earlier.isoformat()},
        {"week": (last + timedelta(days=3)).isoformat()},
        {"week": "not-a-date"},
    ]
    handed_on = writes_on_open(queries)
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(queries)
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    for answer in out["answers"]:
        if (answer["email"], json.dumps(answer["query"], sort_keys=True)) in handed_on:
            answer["status"] = 302
            answer.pop("body", None)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(
        f"filed {sum(len(v) for v in tables.values())} rows, {len(handed_on)} handed on"
    )
finally:
    clear()
