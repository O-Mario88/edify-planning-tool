"""Write hr_register_golden.json: the HR registers as the existing
application answers them for people the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/hr_register_golden.json \\
    python manage.py shell < platform/backend/internal/hrregister/testdata/golden.py

Only against a database whose name ends in "_test". It files a set of
accounts and People records there, every id starting "ghr" (enough to page
the register; departments, titles and none; pending, suspended and exited;
two lines to one person, a top role with no line, another country, a deleted
record and a deleted account), asks the app's feed (apps.mobile_feed.views.
read_page, the views, the templates and the reader unmodified) a set of
questions as three accounts, writes the rows and the answers to GOLDEN_OUT
and deletes the rows. internal/integration/hr_register_test.go files the same
rows, asks Go the same questions and compares each answer as a whole message.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.hr.models import (
    Application,
    Candidate,
    OffboardingPlan,
    OnboardingPlan,
    OnboardingTask,
    SafetyIncident,
    StaffRecognition,
    Vacancy,
)
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
#: Deleted children first.
TABLES = (
    "hr_application",
    "hr_candidate",
    "hr_vacancy",
    "hr_onboarding_task",
    "hr_onboarding_plan",
    "hr_offboarding",
    "hr_safety_incident",
    "hr_staff_recognition",
    "staff_supervisor_assignment",
    "staff_profile",
    "user",
)
PATHS = (
    "/org-structure",
    "/recognition",
    "/health-safety",
    "/onboarding",
    "/offboarding",
    "/candidate-pipeline",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'ghr%%'")  # noqa: S608  # nosec B608


def file_rows():
    now = dj_timezone.now()
    profiles = []
    for i in range(62):
        user = User.objects.create(
            id=f"ghru{i:03d}",
            email=f"ghr{i:03d}@example.org",
            name=f"Golden Person {i % 50:02d}",
            roles=["CCEO"],
            active_role=["CCEO", "Program Lead", "CountryDirector"][i % 3],
            is_active=True,
            status="active",
            deleted_at=now if i == 61 else None,
        )
        profiles.append(
            StaffProfile.objects.create(
                id=f"ghrp{i:03d}",
                user=user,
                title=["", "Field Officer", None][i % 3],
                department=["Programmes", "", None, "Finance"][i % 4],
                country="Kenya" if i == 60 else "Uganda",
                onboarding_state=["active", "active", "pending", "suspended", "exited"][
                    i % 5
                ],
                deleted_at=now if i == 59 else None,
            )
        )
    for i in range(1, 40):
        StaffSupervisorAssignment.objects.create(
            id=f"ghrs{i:03d}", supervisee=profiles[i], supervisor=profiles[i % 5]
        )
    StaffSupervisorAssignment.objects.create(
        id="ghrs999", supervisee=profiles[1], supervisor=profiles[7]
    )
    today = dj_timezone.localdate()
    long = (
        "Stayed late every night of the term to finish the cluster's training plan, "
        * 2
    )
    categories = ["values", "excellence", "teamwork", "innovation", "above_and_beyond"]
    for i in range(12):
        StaffRecognition.objects.create(
            id=f"ghrr{i:03d}",
            staff=profiles[i % 7],
            country="Kenya" if i == 11 else "Uganda",
            category=categories[i % 5],
            citation=long if i % 3 == 0 else f"Recognised for work {i}",
            awarded_on=today
            - timedelta(days=[1, 30, 90, 91, 92, 200, 2, 31, 89, 93, 0, 150][i]),
        )
    file_lifecycle(profiles, today)
    file_candidates()
    kinds = ["injury", "road_traffic", "near_miss", "hazard", "security", "illness"]
    for i in range(10):
        SafetyIncident.objects.create(
            id=f"ghri{i:03d}",
            country="Kenya" if i == 9 else "Uganda",
            affected_staff=profiles[i] if i % 3 else None,
            incident_date=today
            - timedelta(days=[3, 100, 364, 365, 366, 500, 4, 101, 363, 0][i]),
            location=f"Site {i}",
            category=kinds[i % 6],
            severity=["low", "medium", "high", "critical"][i % 4],
            description="What happened.",
            days_lost=i,
            status=["reported", "investigating", "action", "closed"][i % 4],
        )


def file_lifecycle(profiles, today):
    statuses = [
        "not_started",
        "in_progress",
        "supervisor_review",
        "ready_for_activation",
        "closed",
    ]
    for i in range(10):
        plan = OnboardingPlan.objects.create(
            id=f"ghro{i:03d}",
            staff=profiles[10 + i],
            status=statuses[i % 5],
            start_date=None if i == 3 else today - timedelta(days=40 - i),
            target_completion_date=None
            if i == 4
            else today + timedelta(days=[-5, -1, 0, 1, 9][i % 5]),
        )
        OnboardingPlan.objects.filter(id=plan.id).update(
            created_at=dj_timezone.now() - timedelta(hours=i)
        )
        for k in range(i % 4):
            OnboardingTask.objects.create(
                id=f"ghrt{i:03d}{k}",
                plan=plan,
                name=f"Task {k}",
                is_completed=k % 2 == 0,
            )
    reasons = ["resignation", "", "retirement", "dismissal", "end_of_contract"]
    for i in range(10):
        OffboardingPlan.objects.create(
            id=f"ghrx{i:03d}",
            staff=profiles[20 + i],
            status=["Initiated", "Portfolio Reassigned", "Closed"][i % 3],
            last_working_day=None if i == 5 else today + timedelta(days=i * 7 - 30),
            handover_owner=profiles[i] if i % 2 else None,
            exit_reason=reasons[i % 5],
        )


def file_candidates():
    vacancies = [
        Vacancy.objects.create(
            id=f"ghrv{i}",
            country=["Uganda", "Uganda", "Kenya"][i],
            department="Programmes",
            role=["Field Officer", "Accountant", "Driver"][i],
        )
        for i in range(3)
    ]
    stages = [
        "applied",
        "screening",
        "interview",
        "assessment",
        "reference_check",
        "offer",
        "accepted",
        "hired",
        "rejected",
        "withdrawn",
    ]
    for i in range(12):
        candidate = Candidate.objects.create(
            id=f"ghrc{i:03d}",
            name=f"Golden Candidate {i:02d}",
            email=f"candidate{i:02d}@example.org",
        )
        application = Application.objects.create(
            id=f"ghra{i:03d}",
            vacancy=vacancies[i % 3],
            candidate=candidate,
            stage=stages[i % 10],
        )
        Application.objects.filter(id=application.id).update(
            updated_at=dj_timezone.now() - timedelta(hours=7 * i + 1)
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'ghr%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "admin@edify.org": [
        {},
        {"page": "2"},
        {"page": "3"},
        {"page": "9"},
        {"q": "golden"},
        {"q": "golden", "page": "2"},
        {"q": "golden person 0"},
        {"q": "finance"},
        {"q": "kenya"},
    ],
    "hr@edify.org": [
        {},
        {"page": "2"},
        {"q": "field officer"},
        {"q": "golden person 01"},
        {"q": "near_miss"},
        {"q": "site 1"},
        {"q": "values"},
        {"q": "nothing at all"},
        {"q": "closed"},
        {"q": "resignation"},
        {"q": "golden person 03"},
        {"q": "candidate07@example"},
        {"q": "accountant"},
        {"q": "reference"},
    ],
    "ia@edify.org": [{}, {"page": "2"}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for path in PATHS:
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
    out = {
        "today": dj_timezone.localdate().isoformat(),
        "rows": rows,
        "answers": answers,
    }
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1, default=str)
    print(f"{len(answers)} answers written")


main()
