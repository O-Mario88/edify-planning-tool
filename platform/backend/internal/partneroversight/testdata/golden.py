"""Write golden.json: Partner Monitoring (/partner-oversight/) with partner
work in it, as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/partneroversight/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpo", a Partner whose work cceo1 monitors at schools of their own
in this financial year, in each state the page reads apart: two hand-overs
waiting on the Partner's date (one past its grace), work the Partner dated
ahead, work a staff member dated that has passed, work in progress,
evidence uploaded, a hand-back nobody has decided, verified work awaiting
payment, and a Partner training no hand-over points at. Each carries a cost
where it is scheduled, and the forms the Partner uploaded. It asks the page
of the field officers, Programme Leads and the country's readers, over that work and over the
development seed's completed FY 2026 work, with each Partner, team member,
work tab and status, and each kind of period; writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/partner_oversight_test.go files the same rows and
compares.
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
PATH = "/partner-oversight/"
NOW = dj_timezone.now()
TODAY = dj_timezone.localdate()
READERS = [
    "cceo1@edify.org",
    "cceo2@edify.org",
    "pl1@edify.org",
    "pl2@edify.org",
    # The country's lens: every Partner's work, one Programme Lead's team at
    # a time.
    "cd@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "accountant@edify.org",
    "rvp@edify.org",
    # A region's lens: the Partner work of the reader's regions.
    "regional-lead@edify.org",
]
FY = {"period": "fy", "fy": "2026"}
PARTNER = "gpoP1"
# A row before the rows that point at it; reversed, the order they leave.
TABLES = (
    "partner",
    "activity",
    "partner_assignment",
    "activity_schedule_cost_line",
    "evidence_record",
)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gpo%%'")


def clone(cursor, table, template, overrides):
    """A copy of the template row with the overrides: every column the
    table requires keeps the template's value."""
    cursor.execute(
        f"INSERT INTO {table} SELECT (json_populate_record(NULL::{table}, "
        f"(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM {table} t WHERE t.id = %s",
        [json.dumps(overrides, default=str), template],
    )


def file_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pa.id, pa.scheduled_activity_id, pa.partner_id FROM partner_assignment pa "
            "WHERE pa.scheduled_activity_id IS NOT NULL ORDER BY pa.id LIMIT 1"
        )
        assignment, activity, partner = cursor.fetchone()
        cursor.execute("SELECT id FROM activity_schedule_cost_line ORDER BY id LIMIT 1")
        (cost_line,) = cursor.fetchone()
        cceo = User.objects.get(email="cceo1@edify.org").id
        # Client schools with no partner work of their own.
        cursor.execute(
            "SELECT s.id FROM school s WHERE s.deleted_at IS NULL AND s.school_type = 'client' "
            "AND s.school_id IS NOT NULL AND btrim(s.school_id) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.school_id = s.id) "
            "AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.delivery_type = 'partner') "
            "ORDER BY s.id LIMIT 14"
        )
        clients = [row[0] for row in cursor.fetchall()]
        # Each fixture's school, by its number: 0-8 and 17-18 are clients.
        schools = {n: clients[n] for n in range(9)}
        schools[17], schools[18], schools[19] = clients[9], clients[10], clients[11]
        schools[20], schools[21] = clients[12], clients[13]
        # A Special Project, whose work is its Project Coordinator's.
        cursor.execute(
            "SELECT id FROM project WHERE deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        (project,) = cursor.fetchone()
        # A Core school with no partner work of its own, for the Core tab.
        cursor.execute(
            "SELECT s.id FROM school s WHERE s.deleted_at IS NULL AND s.school_type = 'core' "
            "AND s.school_id IS NOT NULL AND btrim(s.school_id) <> '' "
            "AND NOT EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.school_id = s.id) "
            "AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.delivery_type = 'partner') "
            "ORDER BY s.id LIMIT 1"
        )
        schools[9] = cursor.fetchone()[0]
        # A cluster with no partner work of its own, for the Clusters tab.
        cursor.execute(
            "SELECT c.id FROM cluster c WHERE c.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.cluster_id = c.id) "
            "ORDER BY c.id LIMIT 1"
        )
        (cluster,) = cursor.fetchone()
        clone(
            cursor,
            "partner",
            partner,
            {
                "id": PARTNER,
                "name": "Gpo Partner",
                "user_id": None,
                "loan_lender_id": None,
                "deleted_at": None,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )

        def work(
            n,
            *,
            status,
            days,
            kind="school_visit",
            dated_by="",
            evidence="none",
            sf="",
            ia="pending",
            payment="none",
            cluster=None,
            project=None,
        ):
            day = TODAY + timedelta(days=days)
            clone(
                cursor,
                "activity",
                activity,
                {
                    "id": f"gpoA{n}",
                    "school_id": None if cluster else schools[n],
                    "cluster_id": cluster,
                    "assigned_partner_id": PARTNER,
                    "delivery_type": "partner",
                    "activity_type": kind,
                    "status": status,
                    "planned_date": day,
                    "scheduled_date": None,
                    "fy": "2027",
                    "quarter": "Q1",
                    "planned_month": day.month,
                    "evidence_status": evidence,
                    "salesforce_activity_id": sf or None,
                    "ia_verification_status": ia,
                    "payment_status": payment,
                    "partner_date_set_by": dated_by,
                    "monitored_by_staff_id": cceo,
                    "responsible_staff_id": cceo,
                    "actual_delivery_date": None,
                    "execution_started_at": None,
                    "submitted_to_ia_at": None,
                    "pl_reviewed_at": None,
                    "planned_date_before_completion": None,
                    "reschedule_count": 0,
                    "project_id": project,
                    "deleted_at": None,
                    "paired_school_visit_id": None,
                    "created_at": NOW,
                    "updated_at": NOW,
                },
            )
            clone(
                cursor,
                "activity_schedule_cost_line",
                cost_line,
                {
                    "id": f"gpoC{n}",
                    "activity_id": f"gpoA{n}",
                    "amount": 40000 + n * 1000,
                },
            )
            return f"gpoA{n}"

        def handover(
            n,
            *,
            status,
            activity_id=None,
            created_days=1,
            purpose="in_school_coaching",
            category=None,
            reason=None,
            cluster=None,
            project=None,
        ):
            created = NOW - timedelta(days=created_days)
            clone(
                cursor,
                "partner_assignment",
                assignment,
                {
                    "id": f"gpoH{n}",
                    "partner_id": PARTNER,
                    "school_id": None if cluster else schools[n],
                    "cluster_id": cluster,
                    "status": status,
                    "scheduled_activity_id": activity_id,
                    "monitoring_staff_id": cceo,
                    "assigning_staff_id": cceo,
                    "purpose_of_visit": purpose,
                    "expected_activity_type": "school_visit",
                    "support_type": None,
                    "visit_number": None,
                    "training_number": None,
                    "project_id": project,
                    "outside_ssa": False,
                    "training_course_id": None,
                    "catalogue_item_id": None,
                    "source_activity_id": None,
                    "focus_intervention": "leadership",
                    "return_reason_category": category,
                    "return_reason": reason,
                    "resolution": "",
                    "resolved_at": None,
                    "scheduled_date": None,
                    "created_at": created,
                    "updated_at": created,
                },
            )

        def form(n, kind="visit_form"):
            cursor.execute(
                "INSERT INTO evidence_record (id, kind, uri, storage_provider, uploaded_by, status, scan_status,"
                " quarantined, preview_status, view_count, activity_id, created_at, updated_at)"
                " VALUES (%s, %s, %s, 'local', %s, 'submitted', 'clean', false, 'ready', 0, %s, %s, %s)",
                [f"gpoE{n}", kind, f"evidence/gpoE{n}.pdf", cceo, f"gpoA{n}", NOW, NOW],
            )

        handover(0, status="assigned", created_days=2)
        handover(1, status="assigned", created_days=20)
        handover(
            2,
            status="scheduled",
            activity_id=work(2, status="partner_scheduled", days=10),
        )
        handover(
            3,
            status="scheduled",
            activity_id=work(3, status="scheduled", days=-5, dated_by="staff"),
        )
        handover(
            4, status="scheduled", activity_id=work(4, status="in_progress", days=-6)
        )
        handover(
            5,
            status="scheduled",
            activity_id=work(
                5, status="evidence_uploaded", days=-3, evidence="uploaded"
            ),
        )
        form(5)
        handover(
            6,
            status="returned_to_staff",
            category="school_unavailable",
            reason="School closed for exams",
        )
        handover(
            7,
            status="scheduled",
            activity_id=work(
                7,
                status="ia_verified",
                days=-9,
                evidence="accepted",
                sf="SVE-GPO-7",
                ia="confirmed",
                payment="pending",
            ),
        )
        form(7)
        work(8, status="partner_scheduled", days=3, kind="in_school_training")
        # Cluster work: a hand-over waiting on the Partner's date, and a
        # cluster meeting the Partner dated that no hand-over points at.
        handover(11, status="assigned", cluster=cluster, purpose="", created_days=3)
        work(
            12,
            status="partner_scheduled",
            days=6,
            kind="cluster_meeting",
            cluster=cluster,
        )

        # Work waiting for IA verification: a visit whose form is in and
        # whose Salesforce ID the reviewer enters, and SSA Support confirmed
        # in its own drawer. cceo1 monitors both; Impact Assessment verifies.
        handover(
            17,
            status="scheduled",
            activity_id=work(
                17, status="awaiting_ia_verification", days=-7, evidence="uploaded"
            ),
        )
        form(17)
        handover(
            18,
            status="scheduled",
            purpose="ssa_support",
            activity_id=work(
                18, status="awaiting_ia_verification", days=-10, evidence="uploaded"
            ),
        )

        # A hand-back staff have decided on: it reads Returned, with the
        # decision under it.
        handover(
            19,
            status="returned_to_staff",
            category="school_unavailable",
            reason="School moved to a new site",
        )
        cursor.execute(
            "UPDATE partner_assignment SET resolution = 'staff_delivery' WHERE id = 'gpoH19'"
        )

        # Special Project work: a hand-over waiting on the Partner's date
        # and work the Partner dated, both its Project Coordinator's.
        handover(20, status="assigned", project=project, created_days=2)
        handover(
            21,
            status="scheduled",
            project=project,
            activity_id=work(21, status="partner_scheduled", days=9, project=project),
        )

        # Group trainings the Partner facilitates: the officer's own work,
        # each with its facilitation fee.
        def facilitated(n, *, status, days, sf=""):
            day = TODAY + timedelta(days=days)
            clone(
                cursor,
                "activity",
                activity,
                {
                    "id": f"gpoA{n}",
                    "school_id": None,
                    "cluster_id": cluster,
                    "assigned_partner_id": None,
                    "facilitating_partner_id": PARTNER,
                    "delivery_type": "staff",
                    "activity_type": "cluster_training",
                    "status": status,
                    "planned_date": day,
                    "scheduled_date": None,
                    "fy": "2027",
                    "quarter": "Q1",
                    "planned_month": day.month,
                    "evidence_status": "none",
                    "salesforce_activity_id": sf or None,
                    "ia_verification_status": "pending",
                    "payment_status": "none",
                    "monitored_by_staff_id": cceo,
                    "responsible_staff_id": cceo,
                    "actual_delivery_date": None,
                    "execution_started_at": None,
                    "submitted_to_ia_at": None,
                    "pl_reviewed_at": None,
                    "planned_date_before_completion": None,
                    "reschedule_count": 0,
                    "project_id": None,
                    "deleted_at": None,
                    "paired_school_visit_id": None,
                    "created_at": NOW - timedelta(minutes=n),
                    "updated_at": NOW,
                },
            )
            clone(
                cursor,
                "activity_schedule_cost_line",
                cost_line,
                {
                    "id": f"gpoC{n}",
                    "activity_id": f"gpoA{n}",
                    "amount": 150000,
                    "line_item_type": "facilitation",
                },
            )

        facilitated(13, status="planned", days=14)
        facilitated(14, status="planned", days=-4)
        facilitated(15, status="awaiting_ia_verification", days=-8, sf="TS-GPO-15")
        facilitated(16, status="ia_verified", days=-12, sf="TS-GPO-16")
        # A Core school whose visit a staff member dated: still the
        # Partner's to schedule, so it may be withdrawn.
        handover(
            9,
            status="scheduled",
            activity_id=work(9, status="scheduled", days=12, dated_by="staff"),
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gpo%%' ORDER BY id"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def ask(user, query):
    with transaction.atomic():
        status, body = read_page(user, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": user.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
    }


def links(body):
    blocks = body.get("blocks", [])
    partners = [
        link["href"]
        for block in blocks
        if "panel" in block
        for item in block["panel"]["items"]
        if "links" in item
        for link in item["links"]["links"]
    ]
    tabs = [
        tab["href"]
        for block in blocks
        if "linkTabs" in block
        for tab in block["linkTabs"]["tabs"]
    ]
    return partners + tabs


def as_query(href):
    return {
        k: v for k, v in (pair.split("=", 1) for pair in href.lstrip("?").split("&"))
    }


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email in READERS:
        user = User.objects.filter(email=email).first()
        if user is None:
            continue
        seen = set()
        for opening in ({}, FY, {"partner": PARTNER}):
            first = ask(user, opening)
            answers.append(first)
            for href in links(first["body"]):
                query = as_query(href)
                key = tuple(sorted(query.items()))
                if key in seen:
                    continue
                seen.add(key)
                answers.append(ask(user, query))
        for base in (FY, {"partner": PARTNER}):
            for extra in (
                {"work": "visits"},
                {"work": "core"},
                {"work": "clusters"},
                {"activity_type": "school_visit"},
                {"activity_type": "cluster_training", "work": "clusters"},
                {"work": "trainings"},
                {"status": "completed"},
                {"status": "scheduled"},
                {"status": "awaiting_schedule"},
                {"status": "returned"},
                {"status": "verification"},
                {"status": "in_progress"},
                {"period": "quarter", "quarter": "Q1"},
                {"period": "quarter", "quarter": "Q3"},
                {"period": "month", "month": "4"},
                {"period": "month", "month": str(TODAY.month)},
                {"period": "week", "week": "2026-W17"},
                {"period": "week", "week": TODAY.strftime("%G-W%V")},
            ):
                answers.append(ask(user, {**base, **extra}))
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w") as out:
    json.dump(
        {"today": str(TODAY), "rows": rows, "answers": answers},
        out,
        indent=1,
        default=str,
    )
print(f"wrote {len(answers)} answers")
