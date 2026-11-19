"""Write the Closure Readiness Workspace's golden: /activities/closure
(closure_views.closure_readiness_queue_view over ClosureEligibilityService
.with_facts, pages/closure/readiness_queue.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/closurepages/testdata/queue_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gclq", the first officer's work in each state the queue sorts
into: verified staff visits with a Salesforce ID and an SSA visit that has
no Salesforce record (ready); a priced visit whose advance was accounted for
without its NetSuite code (accountability); a completed visit not yet
verified (analytics); one verified as published but missing its Salesforce
ID (blocked); a priced cancelled visit whose advance was paid out, and one
cancelled with nothing paid (left out); and a closed visit (left out). It
asks the page of readers who plan and of readers it refuses, writes the
answers with the rows as the database held them (`tables`), and deletes the
rows. internal/integration/closure_queue_test.go files them again and asks Go.
"""

import json
import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("queue_golden.py runs only against a _test database")

User = get_user_model()
P = "gclq"
PAGE = "/activities/closure"
READERS = (
    "cceo1@edify.org",
    "pl1@edify.org",
    "coordinator@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "accountant@edify.org",
    "partner@edify.org",
    "hr@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = (
    "activity",
    "activity_schedule_cost_line",
    "advance_request",
    "analytics_publish_record",
)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(today):
    from apps.activities.closure_models import AnalyticsPublishRecord
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import AdvanceRequest

    officer = User.objects.get(email="cceo1@edify.org")
    sp = StaffProfile.objects.get(user=officer)
    school = (
        Activity.objects.filter(
            deleted_at__isnull=True, responsible_staff_id__in=[officer.id, sp.id]
        )
        .exclude(school=None)
        .first()
        .school
    )
    fy = str(today.year + 1 if today.month >= 10 else today.year)

    def activity(key, status, **kw):
        return Activity.objects.create(
            id=P + key,
            activity_type=kw.pop("activity_type", "school_visit"),
            status=status,
            delivery_type="staff",
            responsible_staff_id=kw.pop("staff", sp.id),
            school=kw.pop("school", school),
            planned_date=today,
            fy=fy,
            **kw,
        )

    def priced(work, advance_status, netsuite=None):
        line = ActivityScheduleCostLine.objects.create(
            id=P + "line_" + work.id[len(P) :],
            activity=work,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=Decimal(50000),
            amount=Decimal(50000),
            month=today.month,
        )
        if advance_status:
            AdvanceRequest.objects.create(
                id=P + "adv_" + work.id[len(P) :],
                activity=work,
                budget_line=line,
                fy=fy,
                quarter="Q1",
                amount=50000,
                status=advance_status,
                responsible_user_id=officer.id,
                accountability_netsuite_id=netsuite,
            )

    activity("ready", "ia_verified", salesforce_activity_id="SF-GCLQ-1")
    activity(
        "ready_ssa",
        "ia_verified",
        activity_type="ssa_support",
        salesforce_record_type_snapshot="NONE",
        school=None,
        staff=officer.id,
    )
    priced(
        activity("account", "ia_verified", salesforce_activity_id="SF-GCLQ-2"),
        "accounted",
    )
    activity("analytics", "completed", salesforce_activity_id="SF-GCLQ-3")
    blocked = activity("blocked", "completed")
    AnalyticsPublishRecord.objects.create(
        id=P + "pub_blocked", activity=blocked, status="published"
    )
    priced(activity("called_off_paid", "cancelled"), "disbursed")
    priced(activity("called_off", "cancelled"), None)
    activity("closed", "closed")


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
    os.environ["WEB_QUERIES"] = "[{}]"
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
