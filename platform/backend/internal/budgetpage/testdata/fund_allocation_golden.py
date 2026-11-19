"""Write the Consolidated Fund Allocation golden: /finance/fund-allocation
(finance_views.fund_allocation_view, apps.budget.services.budget_workspace
with budget_scope="country", pages/finance/fund_allocation.html) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/budgetpage/testdata/fund_allocation_golden.py

Only against a database whose name ends in "_test". Every id starts "gfa";
the activities and cost lines are copies of one of the CCEO's planned
visits and of one of its lines, written with SQL so no model signal prices
or repairs them, dated around today: this week (one a partner's training,
one cancelled), this month in another week (an event in another
district, at no school), this quarter in another month and this year in another
quarter. The year's country admin plan has two lines of one item at one
unit cost, one described only by its category, one in another quarter and
one no longer active. It asks the four periods, one district alone, another
date, another year and a reader the page refuses, writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/fund_allocation_test.go files them again and asks Go.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.core.fy import get_operational_fy

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("fund_allocation_golden.py runs only against a _test database")

User = get_user_model()
P = "gfa"
PAGE = "/finance/fund-allocation"
#: Children first.
TABLES = (
    "admin_budget_line",
    "monthly_work_plan_budget",
    "activity_schedule_cost_line",
    "activity",
)
READERS = (
    "cd@edify.org",
    "accountant@edify.org",
    "ia@edify.org",
    "rvp@edify.org",
    "admin@edify.org",
    "cceo1@edify.org",
)
QUARTERS = ((10, 11, 12), (1, 2, 3), (4, 5, 6), (7, 8, 9))


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '  # noqa: S608  # nosec B608
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def days():
    """Today, a day this month in another week, a day this quarter in
    another month, and a day this year in another quarter."""
    today = timezone.localdate()
    month_day = today.replace(day=1) if today.day > 7 else today.replace(day=25)
    quarter = next(q for q in QUARTERS if today.month in q)
    other_month = quarter[0] if quarter[0] != today.month else quarter[1]
    quarter_day = date(today.year, other_month, 10)
    fy = int(get_operational_fy())
    other_quarter = date(fy, 2, 10) if today.month in (4, 5, 6) else date(fy, 6, 10)
    return today, month_day, quarter_day, other_quarter


def file_rows():
    cceo = User.objects.get(email="cceo1@edify.org")
    cd = User.objects.get(email="cd@edify.org")
    fy = get_operational_fy()
    today, month_day, quarter_day, other_quarter = days()
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT a.id, l.id, s.district_id FROM activity a
               JOIN activity_schedule_cost_line l ON l.activity_id = a.id
               JOIN school s ON s.id = a.school_id
               WHERE l.responsible_user = %s AND a.activity_type = 'school_visit' AND a.delivery_type = 'staff'
               ORDER BY a.id, l.id LIMIT 1""",
            [cceo.id],
        )
        base_activity, base_line, district = cursor.fetchone()
        cursor.execute(
            "SELECT id FROM district WHERE id <> %s ORDER BY name, id LIMIT 1",
            [district],
        )
        elsewhere = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM partner ORDER BY id LIMIT 1")
        partner = cursor.fetchone()[0]

        def activity(suffix, day, **fields):
            clone(
                cursor,
                "activity",
                base_activity,
                {
                    "id": f"{P}a{suffix}",
                    "paired_school_visit_id": None,
                    "salesforce_activity_id": None,
                    "status": "scheduled",
                    "scheduled_date": f"{day.isoformat()}T10:00:00+03:00",
                    "planned_date": day.isoformat(),
                    "daily_visit_batch_id": None,
                    "expected_participants": None,
                    "teachers_attended": 0,
                    "leaders_attended": 0,
                    "other_participants": 0,
                    "programme_activity_type": None,
                    "fy": fy,
                    **fields,
                },
            )

        def cost(suffix, activity_id, day, key, amount, **fields):
            clone(
                cursor,
                "activity_schedule_cost_line",
                base_line,
                {
                    "id": f"{P}c{suffix}",
                    "activity_id": activity_id,
                    "cost_setting_key": key,
                    "amount": amount,
                    "unit_cost": amount,
                    "quantity": 1,
                    "planned_date": day.isoformat(),
                    "month": day.month,
                    "fiscal_year": fy,
                    "partner_id": None,
                    "responsible_user": cceo.id,
                    **fields,
                },
            )

        activity("1", today)
        cost(
            "01",
            f"{P}a1",
            today,
            "primary_transport_per_day",
            30000,
            label="Transport Primary District",
        )
        cost(
            "02", f"{P}a1", today, "lunch_per_day", 6000, label="Lunch", unit_cost=12000
        )
        activity("2", today, activity_type="training", delivery_type="partner")
        cost(
            "03",
            f"{P}a2",
            today,
            "partner_training_lump_sum",
            90000,
            label="Partner training",
            partner_id=partner,
        )
        activity("3", today, status="cancelled")
        cost("04", f"{P}a3", today, "lunch_per_day", 7000, label="Lunch")
        activity(
            "4",
            month_day,
            school_id=None,
            cluster_id=None,
            event_district_id=elsewhere,
        )
        cost(
            "05",
            f"{P}a4",
            month_day,
            "primary_transport_per_day",
            45000,
            label="Transport Primary District",
            school_id=None,
        )
        activity("5", quarter_day)
        cost(
            "06",
            f"{P}a5",
            quarter_day,
            "lunch_per_day",
            8000,
            label="Lunch",
            unit_cost=8000,
        )
        activity("6", other_quarter)
        cost(
            "07",
            f"{P}a6",
            other_quarter,
            "primary_transport_per_day",
            52000,
            label="Transport Primary District",
        )

        months = [
            (f"{P}m1", f"{today.year}-{today.month:02d}"),
            (f"{P}m2", f"{other_quarter.year}-{other_quarter.month:02d}"),
        ]
        for budget_id, key in months:
            cursor.execute(
                """INSERT INTO monthly_work_plan_budget (id, created_at, updated_at, fy, month_key, generated_at, status,
                   program_total, admin_total, regional_standard_ceiling, operational_activity_requirement,
                   strategic_reserve_requested, deferred_amount, country_funding_shortfall,
                   reference_configuration_missing_count, total_amount, activity_count, submission_version)
                   VALUES (%s, now(), now(), %s, %s, now(), 'draft', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)""",
                [budget_id, fy, key],
            )
        lines = [
            ("1", f"{P}m1", "office_rent", "", "1.50", 200000, 300000, "active"),
            (
                "2",
                f"{P}m1",
                "airtime",
                "Staff airtime",
                "2.00",
                50000,
                100000,
                "active",
            ),
            ("3", f"{P}m1", "airtime", "Staff airtime", "1.00", 50000, 50000, "active"),
            ("4", f"{P}m1", "fuel", "Generator fuel", "1.00", 90000, 90000, "archived"),
            (
                "5",
                f"{P}m2",
                "utilities",
                "Water and power",
                "1.00",
                70000,
                70000,
                "active",
            ),
        ]
        for (
            suffix,
            budget_id,
            category,
            description,
            quantity,
            unit,
            total,
            status,
        ) in lines:
            cursor.execute(
                """INSERT INTO admin_budget_line (id, created_at, updated_at, monthly_budget_id, cost_category,
                   description, quantity, unit_cost, total_cost, created_by_user_id, status)
                   VALUES (%s, now(), now(), %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    f"{P}l{suffix}",
                    budget_id,
                    category,
                    description,
                    quantity,
                    unit,
                    total,
                    cd.id,
                    status,
                ],
            )
    return district, quarter_day


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    district, quarter_day = file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            {},
            {"period": "month"},
            {"period": "quarter"},
            {"period": "fy"},
            {"district": district},
            {"period": "month", "district": district},
            {"date": quarter_day.isoformat(), "period": "month"},
            {"date": (quarter_day + timedelta(days=1)).isoformat()},
            {"fy": str(int(get_operational_fy()) - 1)},
        ]
    )
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
