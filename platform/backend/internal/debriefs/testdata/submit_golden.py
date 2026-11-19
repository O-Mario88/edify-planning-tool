"""Write the Daily Debrief's golden: /debriefs/submit (debrief_views
.field_debrief_submit_view over DailyDebriefFlowService.get_state,
pages/debriefs/submit.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/debriefs/testdata/submit_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdbf", the first officer's work for today (one in progress, one
scheduled at a time with a focus intervention, one cancelled) and an overdue
visit to carry in; the first Lead's work for today and a debrief submitted
over it; the partner's work for today and a draft debrief; and the Project
Coordinator's debrief returned for clarification; and the Admin's reviewed
debrief that covered no other work. It asks each submitter the
page bare and carrying in the overdue visit, and readers who may not submit;
writes the answers with the rows as the database held them (`tables`), and
deletes the rows. internal/integration/debrief_submit_test.go files them
again and asks Go.
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
from apps.core.scoping import resolve_user_scope

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("submit_golden.py runs only against a _test database")

User = get_user_model()
P = "gdbf"
PAGE = "/debriefs/submit"
READERS = (
    "cceo1@edify.org",
    "pl1@edify.org",
    "partner@edify.org",
    "coordinator@edify.org",
    "admin@edify.org",
    "cd@edify.org",
    "hr@edify.org",
    "accountant@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("activity", "daily_debrief", "daily_debrief_activity_link")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def staff_id(email):
    user = User.objects.get(email=email)
    sp = StaffProfile.objects.filter(user=user).first()
    return user, (sp.id if sp else user.id)


def school_of(ids):
    work = (
        Activity.objects.filter(deleted_at__isnull=True, responsible_staff_id__in=ids)
        .exclude(school=None)
        .first()
    )
    return work.school if work else None


def file_rows(today):
    fy = str(today.year + 1 if today.month >= 10 else today.year)
    officer, officer_sp = staff_id("cceo1@edify.org")
    school = school_of([officer.id, officer_sp])
    at_ten = timezone.make_aware(datetime.combine(today, time(10, 30)))

    def activity(key, staff, status, **kw):
        kw.setdefault("planned_date", today)
        kw.setdefault("school", school)
        return Activity.objects.create(
            id=P + key,
            activity_type=kw.pop("activity_type", "school_visit"),
            status=status,
            delivery_type=kw.pop("delivery_type", "staff"),
            responsible_staff_id=staff,
            fy=fy,
            **kw,
        )

    activity("cceo_a", officer_sp, "in_progress")
    activity(
        "cceo_b",
        officer_sp,
        "scheduled",
        scheduled_date=at_ten,
        focus_intervention="leadership",
        activity_type="coaching_visit",
    )
    activity("cceo_c", officer_sp, "cancelled")
    activity(
        "cceo_over", officer_sp, "scheduled", planned_date=today - timedelta(days=5)
    )

    lead, lead_sp = staff_id("pl1@edify.org")
    lead_work = activity("pl_a", lead_sp, "completed")
    activity("pl_b", lead_sp, "scheduled")

    partner = User.objects.get(email="partner@edify.org")
    partner_ids = list(resolve_user_scope(partner).partner_ids)
    partner_work = None
    if partner_ids:
        partner_work = activity(
            "partner_a",
            officer_sp,
            "scheduled",
            delivery_type="partner",
            assigned_partner_id=partner_ids[0],
        )

    from apps.debriefs.field_debrief_service import _daily_midnight
    from apps.debriefs.models import DailyDebrief, DailyDebriefActivityLink

    def debrief(key, user, role, status, **kw):
        return DailyDebrief.objects.create(
            id=P + key,
            fy=fy,
            date=_daily_midnight(today),
            submitted_by_user_id=user.id,
            submitted_by_role=role,
            kind="daily",
            status=status,
            title="Daily Debrief",
            submitted_at=timezone.make_aware(datetime.combine(today, time(16, 5))),
            **kw,
        )

    submitted = debrief(
        "pl",
        lead,
        "Program Lead",
        "submitted",
        other_work_description="Covered a colleague's visit.",
        what_went_well="The head teacher joined.\nTeachers stayed late.",
        challenges_faced="The road flooded.",
    )
    DailyDebriefActivityLink.objects.create(
        id=P + "link_pl", debrief=submitted, activity=lead_work
    )
    draft = debrief(
        "partner",
        partner,
        "PartnerFieldOfficer",
        "draft",
        what_went_well="Good turnout.",
        recommendations="Start earlier.",
    )
    if partner_work:
        DailyDebriefActivityLink.objects.create(
            id=P + "link_partner", debrief=draft, activity=partner_work
        )
    coordinator = User.objects.get(email="coordinator@edify.org")
    debrief(
        "pc",
        coordinator,
        "ProjectCoordinator",
        "clarification_requested",
        what_did_not_go_well="Funds came late.",
    )
    debrief(
        "admin",
        User.objects.get(email="admin@edify.org"),
        "Admin",
        "reviewed",
        recommendations="Share the route plan.",
    )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows(timezone.localdate())
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [{}, {"activity": P + "cceo_over"}, {"activity": P + "pl_b"}]
    )
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
