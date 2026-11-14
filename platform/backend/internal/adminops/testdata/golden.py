"""Write admin_ops_golden.json: the platform-operations registers as the
existing application answers them over records the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/admin_ops_golden.json \\
    python manage.py shell < platform/backend/internal/adminops/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gao", support tickets in every kind of status (one resolvable
alone in its status, two together, one with more than the form's card may
hold around it, an unknown status and category, a ticket with no role or
page), incidents of every severity and an unknown one, with and without a
route or component, a maintenance template and maintenance work of both
kinds, done and of another category; asks the app's feed as Admin and as a
reader who may not open them; writes the rows and the answers to GOLDEN_OUT
and deletes the rows. internal/integration/admin_ops_test.go files the same
rows and compares.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.admin_ops.models import (
    AdminOperationsWorkItem,
    MaintenanceTemplate,
    SupportTicket,
    SystemIncident,
)
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
TABLES = (
    "admin_ops_work_item",
    "admin_support_ticket",
    "admin_system_incident",
    "admin_maintenance_template",
)
# 21:30 UTC is the next day in Nairobi: the registers' times are Nairobi's.
AT = datetime(2026, 11, 10, 21, 30, tzinfo=timezone.utc)


def clear():
    AdminOperationsWorkItem.objects.filter(id__startswith="gao").delete()
    SupportTicket.objects.filter(id__startswith="gao").delete()
    SystemIncident.objects.filter(id__startswith="gao").delete()
    MaintenanceTemplate.objects.filter(id__startswith="gao").delete()


def file_tickets():
    admin = User.objects.get(email="admin@edify.org")
    shapes = [
        ("submitted", "dead_button", "Save button  does nothing", "CCEO", "/planning"),
        ("verification", "slow_page", "Planning page is slow", "", ""),
        ("closed", "other", "Closed one", "Program Lead", "/my-plan"),
        ("fix_ready", "broken_link", "L" * 250, "CCEO", "/schools/" + "x" * 200),
        ("in_progress", "made_up", "Unknown category", "CCEO", "/todos"),
        ("withdrawn", "other", "Unknown status", "CCEO", "/todos"),
        ("triaged", "missing_data", "Missing <school>", "IA", "/schools"),
        ("submitted", "other", "Another submitted", "CCEO", "/calendar"),
    ]
    for i, (status, category, title, role, route) in enumerate(shapes):
        SupportTicket.objects.create(
            id=f"gao{i:03d}",
            reference=f"TCK-9{i:05d}",
            title=title,
            category=category,
            status=status,
            reporter_id=admin.id,
            reporter_role=role,
            route=route,
        )
        SupportTicket.objects.filter(id=f"gao{i:03d}").update(
            created_at=AT - timedelta(hours=5 * i)
        )


def file_incidents():
    shapes = [
        ("critical", "open", "/x", ""),
        ("high", "acknowledged", "", "comp"),
        ("medium", "resolved", "", ""),
        ("low", "mitigated", "/y", "comp"),
        ("weird", "closed", "/z", ""),
        ("high", "reopened", "/r", ""),
    ]
    for i, (severity, status, route, component) in enumerate(shapes):
        SystemIncident.objects.create(
            id=f"gaoi{i:03d}",
            reference=f"INC-9{i:05d}",
            signature=f"gao-signature-{i}",
            title=f"Golden incident {i}",
            severity=severity,
            status=status,
            category="route_defect",
            affected_route=route,
            affected_component=component,
            occurrence_count=1 + i,
            reopened_count=i % 2,
            first_detected_at=AT - timedelta(days=3),
            last_detected_at=AT - timedelta(hours=3 * i),
        )


def file_maintenance():
    MaintenanceTemplate.objects.create(
        id="gaot001",
        name="Golden yearly review",
        category="made_up",
        frequency_days=365,
        estimated_minutes=45,
        next_due_date=date(2027, 3, 1),
    )
    shapes = [
        ("preventive_maintenance", "scheduled", date(2026, 11, 20)),
        ("corrective_maintenance", "in_progress", None),
        ("preventive_maintenance", "done", None),
        ("security", "scheduled", None),
        ("corrective_maintenance", "made_up", date(2026, 12, 1)),
    ]
    for i, (category, status, scheduled) in enumerate(shapes):
        AdminOperationsWorkItem.objects.create(
            id=f"gaow{i:03d}",
            reference=f"OPS-9{i:05d}",
            title=f"Golden work {i}",
            category=category,
            status=status,
            scheduled_date=scheduled,
        )
        AdminOperationsWorkItem.objects.filter(id=f"gaow{i:03d}").update(
            created_at=AT - timedelta(hours=i)
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gao%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


STATUSES = [
    {},
    {"status": "verification"},
    {"status": "fix_ready"},
    {"status": "submitted"},
    {"status": "withdrawn"},
    {"status": "open"},
    {"status": "bogus"},
]
QUESTIONS = {
    "admin@edify.org": {
        "/admin-ops/support": STATUSES,
        "/admin-ops/incidents": STATUSES + [{"status": "reopened"}],
        "/admin-ops/maintenance": [{}],
    },
    "cd@edify.org": {
        "/admin-ops/support": [{}],
        "/admin-ops/incidents": [{}],
        "/admin-ops/maintenance": [{}],
    },
}


def main():
    clear()
    try:
        file_tickets()
        file_incidents()
        file_maintenance()
        rows = dump_rows()
        answers = []
        for email, paths in QUESTIONS.items():
            user = User.objects.get(email=email)
            for path, asked in paths.items():
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
