"""Write employee_relations_golden.json: Employee Relations as the existing
application answers it over cases the development seed does not hold, and
the audit row each reading appends.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/employee_relations_golden.json \\
    python manage.py shell < platform/backend/internal/hrregister/testdata/employee_relations_golden.py

Only against a database whose name ends in "_test". It files cases, every id
starting "gpe": each type, status and severity; open and closed; in Uganda
and in Kenya; confidential ones owned or investigated by HR and ones they do
not work; with a subject and none; opened on a day and not opened. It asks
the app's feed as HR (with searches by type, status, country and the
subject's name), Admin, Impact Assessment (who may open the register but
sees no case) and a CCEO (who may not), writes the rows, the answers and the
audit row each reading appended (its action, subject, actor, role, success
and payload) to GOLDEN_OUT and deletes the cases. Audit rows stay: the chain
is never cut. internal/integration/employee_relations_test.go files the same
cases, asks Go the same questions and compares the answers and the rows Go
appends.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile
from apps.audit.models import AuditLog
from apps.hr.models import EmployeeRelationsCase
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("employee_relations_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/employee-relations"
TABLES = ("hr_relations_case",)


def clear():
    EmployeeRelationsCase.objects.filter(id__startswith="gpe").delete()


def file_rows():
    hr = User.objects.get(email="hr@edify.org")
    admin = User.objects.get(email="admin@edify.org")
    subjects = list(
        StaffProfile.objects.filter(
            user__email__in=["cceo1@edify.org", "cceo2@edify.org"]
        ).order_by("user__email")
    )
    types = [
        "disciplinary",
        "grievance",
        "dispute",
        "conflict",
        "harassment",
        "conduct",
        "whistleblowing",
        "safeguarding",
    ]
    statuses = [
        "submitted",
        "triage",
        "investigation",
        "findings",
        "action",
        "appeal",
        "resolved",
        "closed",
    ]
    severities = ["low", "medium", "high", "critical"]
    base = datetime(2026, 9, 1, 21, 30, tzinfo=timezone.utc)
    for i in range(18):
        case = EmployeeRelationsCase.objects.create(
            id=f"gpe{i:03d}",
            case_type=types[i % len(types)],
            status=statuses[(i * 3) % len(statuses)],
            severity=severities[i % len(severities)],
            country="Kenya" if i % 5 == 4 else "Uganda",
            subject_staff=subjects[i % 2] if i % 3 else None,
            case_owner=hr if i % 4 == 0 else (admin if i % 4 == 1 else None),
            investigator=hr if i % 6 == 2 else None,
            is_confidential=i % 2 == 0,
            opened_at=None if i % 7 == 3 else base + timedelta(days=i),
            description=f"Golden case {i}",
        )
        # The register lists the latest change first.
        EmployeeRelationsCase.objects.filter(id=case.id).update(
            updated_at=base + timedelta(hours=i * 7 % 19)
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpe%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "hr@edify.org": [
        {},
        {"q": "disciplinary"},
        {"q": "closed"},
        {"q": "kenya"},
        {"q": "cceo"},
        {"q": "nothing-matches"},
    ],
    "admin@edify.org": [{}],
    "ia@edify.org": [{}],
    "cceo1@edify.org": [{}],
}


def newest_seq():
    last = AuditLog.objects.filter(seq__isnull=False).order_by("-seq").first()
    return last.seq if last else 0


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for query in asked:
                before = newest_seq()
                status, body = read_page(user, PATH, query)
                audited = [
                    {
                        "action": a.action,
                        "subject_kind": a.subject_kind,
                        "subject_id": a.subject_id,
                        "actor_id": a.actor_id,
                        "actor_role": a.actor_role,
                        "success": a.success,
                        "payload": a.payload,
                    }
                    for a in AuditLog.objects.filter(
                        seq__gt=before, action="hr.er_accessed"
                    ).order_by("seq")
                ]
                answers.append(
                    {
                        "email": email,
                        "path": PATH,
                        "query": query,
                        "status": status,
                        "body": body,
                        "audited": audited,
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
