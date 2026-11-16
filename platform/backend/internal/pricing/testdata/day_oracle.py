"""Write day_oracle.json: days a visit shares, planned as the existing pricing
plans them (apps.daily_visit_batches.services._plan_day and the member costs
_write_day_lines writes), for Go's pricing.PlanDay to plan the same way.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    ORACLE_OUT=/path/to/day_oracle.json \\
    python manage.py shell < platform/backend/internal/pricing/testdata/day_oracle.py

Only against a database whose name ends in "_test". Every id starts "gpd";
the activities are copies of one stored visit. For the Country Director
(head office, read against the Kampala, Wakiso and Mukono zone, the second
night rate) it files a primary day of three visits and a cancelled one, a
Mixed day (a visit and a field event in Gulu), two secondary days in a row
(the second the day the traveller comes home), a day whose card lacks the
lunch (a card in force that day only) and an empty day; for a CCEO a day of
a OneTest visit and a cluster meeting with a headcount. It plans every day,
writes the rows and the answers to ORACLE_OUT and deletes the rows.
internal/integration/pricing_oracle_test.go files the same rows and plans
each day with Go.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.budget.costing import ActivityCost, CostLine
from apps.budget.costing_service import active_catalogue
from apps.core.exceptions import BadRequest
from apps.daily_visit_batches.models import DailyVisitBatch
from apps.daily_visit_batches.pricing import KEY_LABELS, allocate_pool, day_line_label
from apps.daily_visit_batches.services import _plan_day

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("day_oracle.py runs only against a _test database")

User = get_user_model()
#: Children first.
TABLES = ("activity", "daily_visit_batch", "cost_setting", "cost_catalogue")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gpd%%'")  # noqa: S608  # nosec B608


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '  # noqa: S608  # nosec B608
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def file_rows():
    cd = User.objects.get(email="cd@edify.org")
    cceo = User.objects.get(email="cceo1@edify.org")
    live = active_catalogue()
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM staff_profile WHERE user_id = %s", [cd.id])
        cd_profile = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM staff_profile WHERE user_id = %s", [cceo.id])
        cceo_profile = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM district WHERE name = 'Gulu'")
        gulu = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM district WHERE name = 'Arua'")
        arua = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM school WHERE district_id IS NOT NULL ORDER BY id LIMIT 3"
        )
        schools = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT id FROM cluster WHERE district_id IS NOT NULL ORDER BY id LIMIT 1"
        )
        cluster = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND delivery_type = 'staff' "
            "AND deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        base = cursor.fetchone()[0]

        # A card in force on 20 April only, without the lunch.
        clone(
            cursor,
            "cost_catalogue",
            live.id,
            {
                "id": "gpdcop",
                "fy": "2029",
                "version": 1,
                "effective_from": "2026-04-20",
                "effective_to": "2026-04-20",
            },
        )
        cursor.execute(
            "SELECT id FROM cost_setting WHERE catalogue_id = %s AND key <> 'lunch_per_day' ORDER BY id",
            [live.id],
        )
        for n, (setting_id,) in enumerate(cursor.fetchall()):
            clone(
                cursor,
                "cost_setting",
                setting_id,
                {"id": f"gpds{n:03d}", "catalogue_id": "gpdcop"},
            )

        def day(suffix, user, date, stored_type="primary", count=0):
            cursor.execute(
                """INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date,
                   district_type, rate_snapshot, daily_pool_amount, school_count, per_school_amount,
                   workload_snapshot)
                   VALUES (%s, now(), now(), %s, %s, %s, '{}', 0, %s, 0, '{}')""",
                [f"gpdb{suffix}", user, date, stored_type, count],
            )

        def member(suffix, batch, profile, date, **fields):
            clone(
                cursor,
                "activity",
                base,
                {
                    "id": f"gpda{suffix}",
                    "paired_school_visit_id": None,
                    "salesforce_activity_id": None,
                    "status": "scheduled",
                    "daily_visit_batch_id": f"gpdb{batch}",
                    "responsible_staff_id": profile,
                    "scheduled_date": f"{date}T10:00:00+03:00",
                    "planned_date": date,
                    "end_date": None,
                    "cluster_id": None,
                    "event_district_id": None,
                    "costing_profile_snapshot": None,
                    "catalogue_item_id": None,
                    "expected_participants": None,
                    "teachers_attended": 0,
                    "leaders_attended": 0,
                    "other_participants": 0,
                    **fields,
                },
            )

        day("1", cd.id, "2026-04-06")
        for i, school in enumerate(schools):
            member(f"1{i}", "1", cd_profile, "2026-04-06", school_id=school)
        member(
            "19",
            "1",
            cd_profile,
            "2026-04-06",
            school_id=schools[0],
            status="cancelled",
        )
        day("2", cd.id, "2026-04-07")
        member("20", "2", cd_profile, "2026-04-07", school_id=schools[0])
        member(
            "21",
            "2",
            cd_profile,
            "2026-04-07",
            activity_type="field_event",
            school_id=None,
            event_district_id=gulu,
        )
        day("3", cd.id, "2026-04-14", "secondary", 2)
        member(
            "30",
            "3",
            cd_profile,
            "2026-04-14",
            activity_type="field_event",
            school_id=None,
            event_district_id=gulu,
        )
        member(
            "31",
            "3",
            cd_profile,
            "2026-04-14",
            activity_type="field_event",
            school_id=None,
            event_district_id=arua,
        )
        day("4", cd.id, "2026-04-15", "secondary", 1)
        member(
            "40",
            "4",
            cd_profile,
            "2026-04-15",
            activity_type="field_event",
            school_id=None,
            event_district_id=arua,
        )
        day("5", cd.id, "2026-04-20")
        member("50", "5", cd_profile, "2026-04-20", school_id=schools[1])
        day("6", cd.id, "2026-04-21")
        day("7", cceo.id, "2026-04-22")
        member(
            "70",
            "7",
            cceo_profile,
            "2026-04-22",
            school_id=schools[2],
            costing_profile_snapshot="ONETEST",
        )
        member(
            "71",
            "7",
            cceo_profile,
            "2026-04-22",
            activity_type="cluster_meeting",
            school_id=None,
            cluster_id=cluster,
            expected_participants=12,
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpd%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def priced(cost):
    return {
        "amount": int(cost.amount),
        "cost_missing": cost.cost_missing,
        "missing_items": list(cost.missing_items),
        "lines": [
            {
                "label": line.label,
                "key": line.key,
                "unit": line.unit,
                "qty": line.qty,
                "amount": line.amount,
                "missing": line.missing,
            }
            for line in cost.lines
        ],
    }


def plan(batch):
    """_plan_day, then the member costs as _write_day_lines builds them."""
    try:
        day = _plan_day(batch, None, batch.responsible_user)
    except BadRequest as exc:
        return {"id": batch.id, "refused": True, "message": str(exc)}
    activities, pool, mark = day["activities"], day["pool"], day["day_mark"]
    n = len(activities)
    members = []
    for index, (activity, alloc) in enumerate(zip(activities, allocate_pool(pool, n))):
        _input, own = day["recipes"][activity.id]
        lines = [
            CostLine(
                label=day_line_label(key, mark),
                key=key,
                unit=amount,
                qty=1,
                amount=amount,
                missing=False,
            )
            for key, amount in alloc.items()
        ]
        lines.extend(line for line in own.lines if line.key not in KEY_LABELS)
        missing = [key for key in own.missing_items if key not in KEY_LABELS]
        cost = ActivityCost(
            amount=sum(line.amount for line in lines),
            lines=lines,
            cost_missing=bool(missing),
            missing_items=missing,
        )
        members.append({"id": activity.id, "cost": priced(cost)})
    return {
        "id": batch.id,
        "refused": False,
        "mark": mark,
        "district": batch.district_type,
        "returnDay": bool(day["is_away"])
        and not (
            set(pool)
            & {
                "secondary_accommodation_per_night",
                "management_accommodation_per_night",
            }
        ),
        "pool": [[key, amount] for key, amount in pool.items()],
        "card": day["catalogue"].id if day["catalogue"] else None,
        "members": members,
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        days = [
            plan(batch)
            for batch in DailyVisitBatch.objects.filter(id__startswith="gpd").order_by(
                "id"
            )
        ]
    finally:
        clear()
    with open(os.environ["ORACLE_OUT"], "w") as handle:
        json.dump(
            {"today": dj_timezone.localdate().isoformat(), "rows": rows, "days": days},
            handle,
            ensure_ascii=False,
            default=str,
        )
    print(f"{len(days)} days planned")


main()
