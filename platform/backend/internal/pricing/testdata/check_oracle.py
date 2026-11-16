"""Write check_oracle.json: the existing day check's answers (the pricing's
refusal, where it is met, whether the day pools the visit, whether it is an
online training), from apps.daily_visit_batches.gateway_relay._probe, for
saves Go is about to make, so that Go's pricing.DayCheck can answer them
the same way.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    ORACLE_OUT=/path/to/check_oracle.json \\
    python manage.py shell < platform/backend/internal/pricing/testdata/check_oracle.py

Only against a database whose name ends in "_test". It files day_oracle.py's
days (ids "gpd") and, with ids starting "gpc", what the day check asks of a
day's money: a paid transport (one at a different amount, one at the
amount the day will owe), a member whose advance has been disbursed, one
whose advance is with the accountant, one carried by a submitted weekly
request and one by a submitted monthly request, a week of the Country
Director's already sent for approval, and the live card's rates again on the
newest card, in force from 2027 (the preview reads the newest card whatever
its dates, and the dated card that lacks the lunch would refuse them all). Then it asks the probe (each in a
transaction it rolls back) of: a visit joining every filed day; a visit in
the sent week; a visit on a day whose card lacks a rate and that has no day
yet; every Activity Catalogue item at a school or a cluster (with and
without a head count, online and not); and every member of staff at three
schools. The rows and the answers go to ORACLE_OUT and the rows are deleted.
internal/integration/day_check_test.go files the same rows and asks Go.
"""

import json
import os
import runpy
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget.costing_service import _rate_card, active_catalogue
from apps.core.fy import get_operational_fy
from apps.daily_visit_batches.districts import accommodation_key_for_staff
from apps.daily_visit_batches.gateway_relay import _probe
from apps.daily_visit_batches.pricing import compute_daily_pool

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("check_oracle.py runs only against a _test database")

User = get_user_model()
HERE = "platform/backend/internal/pricing/testdata/day_oracle.py"
days = runpy.run_path(HERE, run_name="day_fixtures")
clone = days["clone"]
#: Children first.
TABLES = (
    "fund_request_item",
    "weekly_fund_request_line",
    "advance_request",
    "transport_payment",
    "activity_schedule_cost_line",
    "fund_request",
    "weekly_fund_request",
    "cost_setting",
    "cost_catalogue",
)
EAT = timezone(timedelta(hours=3))


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gpc%%'")  # noqa: S608  # nosec B608
    days["clear"]()


def file_money(cd, cceo):
    with connection.cursor() as cursor:
        # The live card's rates on the newest card, in force only from 2027:
        # the preview (asked with no date) reads the newest card, so the
        # dated card day_oracle.py files, which lacks the lunch, would
        # otherwise refuse every preview before its day is reached.
        live = active_catalogue(on_date=date(2026, 5, 5))
        clone(
            cursor,
            "cost_catalogue",
            live.id,
            {
                "id": "gpccop",
                "fy": "2030",
                "version": 1,
                "effective_from": "2027-01-01",
                "effective_to": None,
            },
        )
        cursor.execute(
            "SELECT id FROM cost_setting WHERE catalogue_id = %s ORDER BY id", [live.id]
        )
        for n, (setting_id,) in enumerate(cursor.fetchall()):
            clone(
                cursor,
                "cost_setting",
                setting_id,
                {"id": f"gpcs{n:03d}", "catalogue_id": "gpccop"},
            )
        cursor.execute("SELECT id FROM activity_schedule_cost_line ORDER BY id LIMIT 1")
        base_line = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM advance_request ORDER BY id LIMIT 1")
        base_advance = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM weekly_fund_request ORDER BY id LIMIT 1")
        base_week = cursor.fetchone()[0]

        def line(n, activity):
            clone(
                cursor,
                "activity_schedule_cost_line",
                base_line,
                {"id": f"gpcl{n}", "activity_id": activity},
            )

        def advance(n, status):
            clone(
                cursor,
                "advance_request",
                base_advance,
                {
                    "id": f"gpcv{n}",
                    "budget_line_id": f"gpcl{n}",
                    "status": status,
                    "weekly_fund_request_id": None,
                    "disbursed_amount": None,
                    "accounted_amount": None,
                    "returned_amount": None,
                    "reimbursed_amount": None,
                },
            )

        def week(n, user, start, status):
            clone(
                cursor,
                "weekly_fund_request",
                base_week,
                {
                    "id": f"gpcw{n}",
                    "responsible_user": user,
                    "week_start_date": start.isoformat(),
                    "week_end_date": (start + timedelta(days=6)).isoformat(),
                    "status": status,
                },
            )

        # A member whose advance has been disbursed (day 2), one whose advance
        # is with the accountant (day 3).
        line(2, "gpda20")
        advance(2, "disbursed")
        line(3, "gpda30")
        advance(3, "confirmed_for_advance")
        # A member carried by a weekly request sent for approval (day 4).
        line(4, "gpda40")
        week(4, cceo.id, date(2027, 1, 4), "submitted_to_pl")
        cursor.execute(
            """INSERT INTO weekly_fund_request_line (id, created_at, updated_at, line_item_type,
               description, quantity, unit_cost, total_cost, currency, activity_budget_line_id,
               weekly_fund_request_id)
               VALUES ('gpcwl4', now(), now(), 'transport', 'gpc', 1, 0, 0, 'UGX', 'gpcl4', 'gpcw4')"""
        )
        # A member carried by a monthly request submitted (day 7).
        line(7, "gpda70")
        cursor.execute(
            """INSERT INTO fund_request (id, created_at, updated_at, fy, period, period_key, scope,
               submitted_by_user_id, submitted_by_role, total_amount, activity_count, status)
               VALUES ('gpcf7', now(), now(), '2026', 'monthly', 'gpc-2026-M7', 'own', %s, 'cceo',
                       0, 0, 'submitted')""",
            [cceo.id],
        )
        cursor.execute(
            """INSERT INTO fund_request_item (id, created_at, updated_at, activity_id,
               activity_schedule_cost_line_id, amount, period, period_key, added_after_generation,
               fund_request_id)
               VALUES ('gpci7', now(), now(), 'gpda70', 'gpcl7', 0, 'monthly', 'gpc-2026-M7', false,
                       'gpcf7')"""
        )
        # The Country Director's week of 11 May, sent for approval.
        week(9, cd.id, date(2026, 5, 11), "submitted_to_pl")

        # Day 1's transport paid at an amount it will not owe; day 6's at
        # the amount it will owe once a visit at a school joins it alone.
        rates, _settings = _rate_card(active_catalogue(on_date=date(2026, 4, 21)))
        pool = compute_daily_pool(rates, "primary", accommodation_key_for_staff(cd.id))
        owed = sum(int(v) for k, v in pool.items() if "transport" in k)
        for n, batch, amount in ((1, "gpdb1", 1), (6, "gpdb6", owed)):
            cursor.execute(
                """INSERT INTO transport_payment (id, created_at, updated_at, provider_name, amount,
                   status, payment_method, payment_reference, netsuite_expense_id, notes, batch_id)
                   VALUES (%s, now(), now(), 'gpc', %s, 'paid', 'bank', '', '', '', %s)""",
                [f"gpct{n}", amount, batch],
            )


def dump_rows():
    rows = days["dump_rows"]()
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpc%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = rows.get(table, []) + [
                json.loads(r[0]) for r in cursor.fetchall()
            ]
    return rows


def proposals(cd, cceo):
    """The saves to ask about: (id, fields)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM staff_profile WHERE user_id = %s", [cd.id])
        cd_profile = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM staff_profile WHERE user_id = %s", [cceo.id])
        cceo_profile = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM school WHERE district_id IS NOT NULL ORDER BY id LIMIT 3"
        )
        schools = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT id FROM cluster WHERE district_id IS NOT NULL ORDER BY id LIMIT 1"
        )
        cluster = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM staff_profile WHERE deleted_at IS NULL AND user_id IS NOT NULL ORDER BY id"
        )
        staff = [r[0] for r in cursor.fetchall()]
    visit_item = (
        ActivityCatalogueItem.objects.filter(costing_profile="STAFF_SCHOOL_VISIT")
        .order_by("id")
        .first()
    )
    n = 0

    def fields(profile, day, item, *, school=None, cluster_id=None, **over):
        nonlocal n
        n += 1
        planned = date.fromisoformat(day)
        return (
            f"gpcp{n:04d}",
            {
                "id": f"gpcp{n:04d}",
                "activity_type": item.activity_type,
                "fy": get_operational_fy(planned),
                "quarter": "Q3",
                "delivery_type": "staff",
                "executor_type": "staff",
                "status": "scheduled",
                "school_id": school,
                "cluster_id": cluster_id,
                "responsible_staff_id": profile,
                "scheduled_date": datetime(
                    planned.year, planned.month, planned.day, 10, tzinfo=EAT
                ),
                "planned_date": planned,
                "catalogue_item_id": item.id,
                "catalogue_version": 1,
                "costing_profile_snapshot": item.costing_profile,
                **over,
            },
        )

    out = []
    # A visit joining every filed day.
    for profile, day in (
        (cd_profile, "2026-04-06"),
        (cd_profile, "2026-04-07"),
        (cd_profile, "2026-04-14"),
        (cd_profile, "2026-04-15"),
        (cd_profile, "2026-04-20"),
        (cd_profile, "2026-04-21"),
        (cceo_profile, "2026-04-22"),
    ):
        out.append(fields(profile, day, visit_item, school=schools[0]))
    # The sent week; a day whose card lacks the lunch and has no day yet.
    out.append(fields(cd_profile, "2026-05-12", visit_item, school=schools[0]))
    out.append(fields(cceo_profile, "2026-04-20", visit_item, school=schools[1]))
    # Every catalogue item.
    for item in ActivityCatalogueItem.objects.order_by("id"):
        at_cluster = item.costing_profile in (
            "CLUSTER_TRAINING",
            "CLUSTER_MEETING",
            "ONLINE_TRAINING",
        )
        if not at_cluster:
            out.append(fields(cd_profile, "2026-05-05", item, school=schools[2]))
            continue
        for head_count in (None, 20):
            for mode in ("", "online"):
                out.append(
                    fields(
                        cceo_profile,
                        "2026-05-05",
                        item,
                        cluster_id=cluster,
                        expected_participants=head_count,
                        printing_pages=3 if head_count else None,
                        programme_delivery_mode=mode or None,
                    )
                )
    # Every member of staff at three schools.
    for profile in staff:
        for school in schools:
            out.append(fields(profile, "2026-05-06", visit_item, school=school))
    return out


def answer(pid, fields):
    try:
        verdict = _probe(dict(fields))
    except Exception as exc:  # noqa: BLE001 — recorded, and Go is not asked
        return {"id": pid, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "id": pid,
        "error": "",
        "refusal": verdict["refusal"],
        "stage": verdict["stage"],
        "pooled": verdict["pooled"],
        "online": "online" in verdict,
    }


def wire(fields):
    """The fields as Go's test reads them."""
    out = {}
    for key, value in fields.items():
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        out[key] = value
    return out


cd = User.objects.get(email="cd@edify.org")
cceo = User.objects.get(email="cceo1@edify.org")
clear()
try:
    days["file_rows"]()
    file_money(cd, cceo)
    rows = dump_rows()
    asked = proposals(cd, cceo)
    answers = [{**answer(pid, fields), "fields": wire(fields)} for pid, fields in asked]
finally:
    clear()
with open(os.environ["ORACLE_OUT"], "w") as handle:
    json.dump(
        {
            "today": dj_timezone.localdate().isoformat(),
            "rows": rows,
            "proposals": answers,
        },
        handle,
        ensure_ascii=False,
        default=str,
    )
refused = sum(1 for a in answers if a.get("refusal"))
errors = sum(1 for a in answers if a["error"])
print(f"{len(answers)} saves asked, {refused} refused, {errors} errors")
