"""Write golden.json: the Field Debrief Dashboard (/debriefs) as the existing
feed reads it, over debriefs the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/debriefs/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdf", debriefs from the first Program Lead's officers, the Lead,
an officer of another team and a partner, in this period and the one
before, in each status and risk (one restricted and routed to HR, one
critical), with challenges, linked activities, open commitments, actions
owed by the Lead (one overdue), peer solutions and an open insight. Each
sits a whole number of days and one minute before the file is written, so
the answers hold for half an hour. It asks the page of every reader it
opens for with each tab, range, filter and page, and of readers it refuses;
writes the rows and the answers to GOLDEN_OUT and deletes the rows.
Each answer also keeps every tab's own table, asked with that tab open:
internal/integration/debriefs_test.go files the same rows and compares Go's
tabs with those (owner, 2026-11-16: "Fix the tabs").
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/debriefs"
NOW = dj_timezone.now()
TABLES = (
    "daily_debrief_insight",
    "daily_debrief_peer_solution",
    "daily_debrief_action",
    "daily_debrief_commitment",
    "daily_debrief_challenge",
    "daily_debrief_activity_link",
    "daily_debrief_recipient",
    "daily_debrief",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gdf%%'")


def insert(cursor, table, row, at):
    """File one row through its model, so the model's defaults apply, then
    stamp its times."""
    from django.apps import apps

    model = next(m for m in apps.get_models() if m._meta.db_table == table)
    model.objects.create(**row)
    cursor.execute(
        f'UPDATE "{table}" SET created_at = %s, updated_at = %s WHERE id = %s',
        [at, at, row["id"]],
    )


def file_rows():
    with connection.cursor() as cursor:

        def person(email):
            cursor.execute(
                'SELECT u.id, sp.id FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id '
                "WHERE u.email = %s",
                [email],
            )
            return cursor.fetchone()

        lead = person("pl1@edify.org")
        officer = person("cceo@edify.org")
        peer = person("cceo8@edify.org")
        outsider = person("cceo2@edify.org")
        hr = person("hr@edify.org")
        cursor.execute("SELECT id FROM partner ORDER BY id LIMIT 1")
        partner = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 3"
        )
        schools = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT id FROM activity WHERE deleted_at IS NULL AND activity_type IN "
            "('school_visit', 'cluster_meeting') ORDER BY activity_type, id LIMIT 2"
        )
        activities = [r[0] for r in cursor.fetchall()]

        n = {"d": 0}

        def debrief(who, days, title, *, role="CCEO", **fields):
            n["d"] += 1
            did = f"gdf{n['d']:02d}"
            at = NOW - timedelta(days=days, minutes=1)
            insert(
                cursor,
                "daily_debrief",
                {
                    "id": did,
                    "fy": "2027",
                    "date": at,
                    "submitted_at": at,
                    "submitted_by_user_id": who[0],
                    "submitted_by_role": role,
                    "staff_id": who[1],
                    "debrief_type": "staff",
                    "status": "submitted",
                    "title": title,
                    "summary": f"{title} summary",
                    "linked_school_ids": [],
                    **fields,
                },
                at,
            )
            return did

        a = debrief(
            officer,
            2,
            "Visit went well",
            completion_status="completed_as_planned",
            linked_school_ids=[schools[0]],
        )
        b = debrief(
            officer,
            3,
            "Teachers absent",
            status="action_required",
            completion_status="partially_completed",
            risk_level="pl_attention",
            linked_school_ids=[schools[0], schools[1]],
        )
        c = debrief(
            peer,
            4,
            "Transport failed",
            status="escalated",
            completion_status="unsuccessful",
            risk_level="critical",
            linked_school_ids=[schools[0]],
        )
        debrief(
            peer,
            5,
            "Safeguarding concern",
            status="restricted_incident",
            is_restricted_incident=True,
            risk_level="hr_attention",
        )
        debrief(
            officer,
            6,
            "Please clarify",
            status="clarification_requested",
            completion_status="cancelled",
        )
        debrief(lead, 7, "Lead field day", role="Program Lead", status="resolved")
        debrief(outsider, 8, "Another team", status="closed", risk_level="monitor")
        debrief(
            officer,
            9,
            "Partner joint visit",
            debrief_type="partner",
            partner_id=partner,
            staff_id=None,
            status="updated",
        )
        debrief(officer, 40, "Last period", completion_status="completed_as_planned")
        debrief(peer, 45, "Last period two", status="action_required")
        debrief(officer, 200, "Older this year", status="reviewed")

        insert(
            cursor,
            "daily_debrief_recipient",
            {
                "id": "gdfR1",
                "debrief_id": "gdf04",
                "recipient_user_id": hr[0],
                "recipient_role": "HumanResources",
            },
            NOW,
        )
        for i, (debrief_id, activity) in enumerate(
            ((a, activities[0]), (b, activities[0]), (c, activities[-1]))
        ):
            insert(
                cursor,
                "daily_debrief_activity_link",
                {"id": f"gdfL{i}", "debrief_id": debrief_id, "activity_id": activity},
                NOW,
            )
        for i, (debrief_id, kind) in enumerate(
            (
                (b, "teachers_unavailable"),
                (c, "no_transport"),
                (c, "teachers_unavailable"),
                (a, "weather"),
            )
        ):
            insert(
                cursor,
                "daily_debrief_challenge",
                {"id": f"gdfC{i}", "debrief_id": debrief_id, "challenge_type": kind},
                NOW,
            )
        for i, (debrief_id, status) in enumerate(
            ((b, "open"), (c, "open"), (a, "done"))
        ):
            insert(
                cursor,
                "daily_debrief_commitment",
                {
                    "id": f"gdfM{i}",
                    "debrief_id": debrief_id,
                    "party": "school",
                    "commitment_text": "Bring teachers",
                    "status": status,
                },
                NOW,
            )
        today = dj_timezone.localdate()
        for i, due in enumerate((today - timedelta(days=2), today + timedelta(days=2))):
            insert(
                cursor,
                "daily_debrief_action",
                {
                    "id": f"gdfA{i}",
                    "debrief_id": b,
                    "issue": "Teachers",
                    "action": "Call the head",
                    "owner_user_id": lead[0],
                    "assigned_by_user_id": lead[0],
                    "due_date": due,
                    "status": "open",
                },
                NOW,
            )
        insert(
            cursor,
            "daily_debrief_peer_solution",
            {
                "id": "gdfP1",
                "debrief_id": c,
                "author_user_id": officer[0],
                "suggestion": "Book the boda the evening before so the morning is not "
                "lost waiting for transport",
                "endorsed_by_user_ids": [lead[0], peer[0]],
            },
            NOW - timedelta(days=1, minutes=1),
        )
        insert(
            cursor,
            "daily_debrief_insight",
            {
                "id": "gdfI1",
                "scope": "country",
                "title": "Teachers missing",
                "description": "Teachers unavailable in three debriefs this week.",
                "occurrence_count": 3,
                "window_start": today - timedelta(days=7),
                "window_end": today,
                "debrief_ids": [b, c],
                "status": "open",
            },
            NOW,
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gdf%%' ORDER BY id"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def read(reader, query):
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return status, body


#: Each tab's key by its label (the review queue's label carries a count).
TAB_KEYS = {
    "All Debriefs": "all",
    "My Debriefs": "mine",
    "Team Debriefs": "team",
    "Partner Debriefs": "partner",
    "Escalated": "escalated",
    "Peer Solutions": "peer_solutions",
}


def ask(reader, query):
    """The page as asked, and each tab's own table: the existing feed draws
    every tab with the open tab's rows, so each tab is asked on its own and
    its open table kept (owner, 2026-11-16: "Fix the tabs")."""
    status, body = read(reader, query)
    tab_tables = []
    for block in (body or {}).get("blocks", []):
        if "segments" not in block:
            continue
        for segment in block["segments"]["segments"]:
            label = segment["label"]
            key = (
                "awaiting_review"
                if label.startswith("Awaiting my review")
                else TAB_KEYS[label]
            )
            _, own = read(reader, {**query, "tab": key})
            opened = next(b for b in own["blocks"] if "segments" in b)["segments"][
                "segments"
            ]
            tab_tables.append(next(s for s in opened if s["active"])["blocks"])
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
        "tab_tables": tab_tables,
    }


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    lead_asks = [
        {},
        {"tab": "awaiting_review"},
        {"tab": "mine"},
        {"tab": "team"},
        {"tab": "partner"},
        {"tab": "escalated"},
        {"tab": "peer_solutions"},
        {"range_days": "7"},
        {"range_days": "90"},
        {"range_days": "fy"},
        {"risk_level": "critical"},
        {"q": "teach"},
        {"fy": "2026"},
        {"page": "2"},
    ]
    readers = {
        "pl1@edify.org": lead_asks,
        "admin@edify.org": [{}, {"tab": "escalated"}, {"range_days": "fy"}],
        "cceo@edify.org": [{}, {"tab": "mine"}],
        "cceo8@edify.org": [{}],
        "hr@edify.org": [{}],
        "ia@edify.org": [{}],
        "cd@edify.org": [{}],
        "rvp@edify.org": [{}],
        "coordinator@edify.org": [{}],
        "accountant@edify.org": [{}],
    }
    for email, qs in readers.items():
        reader = User.objects.filter(email=email).first()
        if reader is None:
            continue
        for query in qs:
            answers.append(ask(reader, query))
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {
            "today": dj_timezone.localdate().isoformat(),
            "written": NOW.isoformat(),
            "rows": rows,
            "answers": answers,
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
