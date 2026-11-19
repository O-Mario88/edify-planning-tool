"""Write the Accounts desks' golden: what each desk page shows (the page's own
view, read as the feed reads pages: webpages/testdata/web_page.py) over the
demo seed and one record filed for each desk.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/financedesks/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdesk", an accountability record, a finance audit event, a pending
variance review and a budget amendment on one completed activity; a closed
activity; and two advances, one confirmed for disbursement and one returned
for correction. It asks the nine desks of the Accountant, the Admin, Impact Assessment
and three readers they are refused to, writes the answers with the rows as the
database held them (`tables`), and deletes the rows.
internal/integration/finance_desks_test.go files them again and asks Go.
"""

import json
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
P = "gdesk"
OFFICER = "cceo1@edify.org"
DESKS = (
    "/accounts/accountability",
    "/accounts/advances",
    "/accounts/audit-log",
    "/accounts/blocked",
    "/accounts/budget-amendments",
    "/accounts/cleared",
    "/accounts/returned",
    "/accounts/variance-review",
    "/accounts/weekly-requests",
)
READERS = (
    "accountant@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "cd@edify.org",
    "cceo1@edify.org",
    "pl1@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = (
    "activity",
    "activity_schedule_cost_line",
    "advance_request",
    "accountability_record",
    "finance_audit_log",
    "variance_review",
    "budget_amendment",
)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(today):
    from apps.budget.models import BudgetAmendment
    from apps.frontend.views.finance_operating_views import (
        AccountabilityRecord,
        FinanceAuditLog,
        VarianceReview,
    )
    from apps.fund_requests.models import AdvanceRequest

    officer = User.objects.get(email=OFFICER)
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

    def activity(key, status, days=-3):
        return Activity.objects.create(
            id=P + key,
            activity_type="school_visit",
            status=status,
            delivery_type="staff",
            responsible_staff_id=sp.id,
            school=school,
            planned_date=today + timedelta(days=days),
            fy=fy,
        )

    done = activity("done", "completed")
    activity("closed", "closed")
    advanced = activity("advance", "scheduled", 4)
    returned = activity("returned", "scheduled", 6)
    for work, status, amount in (
        (advanced, "confirmed_for_advance", 180000),
        (returned, "returned", 95000),
    ):
        from apps.activities.models import ActivityScheduleCostLine

        line = ActivityScheduleCostLine.objects.create(
            id=P + "line" + work.id[len(P) :],
            activity=work,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=Decimal(amount),
            amount=Decimal(amount),
        )
        AdvanceRequest.objects.create(
            id=P + "adv" + work.id[len(P) :],
            activity=work,
            budget_line=line,
            fy=fy,
            quarter="Q1",
            amount=amount,
            status=status,
            responsible_user_id=officer.id,
            last_note="Receipt total does not match the line."
            if status == "returned"
            else "",
        )
    AccountabilityRecord.objects.create(
        id=P + "acc",
        activity=done,
        staff_id=officer.id,
        amount_disbursed=Decimal("250000"),
        actual_spend=Decimal("231500"),
        variance=Decimal("18500"),
        submitted_at=timezone.now() - timedelta(days=1),
    )
    FinanceAuditLog.objects.create(
        id=P + "log",
        activity=done,
        event_type="disbursed",
        actor_id=User.objects.get(email="accountant@edify.org").id,
        actor_role="Accountant",
        new_value="Disbursed UGX 250,000 by Mobile Money",
        timestamp=timezone.now() - timedelta(hours=5),
    )
    VarianceReview.objects.create(
        id=P + "var",
        activity=done,
        budgeted_amount=Decimal("250000"),
        disbursed_amount=Decimal("250000"),
        actual_spend=Decimal("231500"),
        variance=Decimal("18500"),
        reason="Fewer participants than planned.",
        status="pending",
    )
    BudgetAmendment.objects.create(
        id=P + "amend",
        activity=done,
        new_date=today + timedelta(days=10),
        reason="The school moved its term dates.",
        requested_by=officer.id,
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
    os.environ["WEB_PATH"] = ",".join(DESKS)
    os.environ["WEB_READERS"] = ",".join(READERS)
    # The Blocked directory and the weekly requests run to several pages:
    # their last ones too.
    os.environ["WEB_QUERIES"] = '[{}, {"blocked_page": "6", "requests_page": "2"}]'
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
