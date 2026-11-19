"""Write the Performance Conversation golden: /performance-conversation
(hr_views.performance_conversation_view, pages/hr/performance_conversation.html)
as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/perfconversation/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpcv", four officers reviewed by Programme Lead 1 (each signs in
with the seed password): one with an agreement of reflective priorities (a
Country Director its functional manager), one whose priorities wait on the
Lead's agreement, one with a measured priority (whose live figures Go hands
on) and one with no agreement; asks the conversation of each officer, of the
Lead about each, of HR, the Country Director, Admin and readers it refuses,
in the open window and again with the year's window shut (restored after),
writes the answers with the rows (`tables`) and deletes the rows.
internal/integration/perf_conversation_test.go files them again and asks Go.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.core.fy import get_operational_fy
from apps.hr.models import (
    PerformanceCycle,
    PerformancePriority,
    PerformanceReview,
    ValueCommitment,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
P = "gpcv"
PAGE = "/performance-conversation"
#: Children first; each row is found by the column named.
TABLES = (
    ("hr_value_commitment", "review_id"),
    ("hr_performance_priority", "review_id"),
    ("hr_performance_review", "id"),
    ("staff_supervisor_assignment", "id"),
    ("staff_profile", "id"),
    # The officers' sign-ins, when Go's comparison signed them in.
    ("refresh_token", "user_id"),
    ("login_event", "user_id"),
    ("user", "id"),
)


def clear():
    with connection.cursor() as cursor:
        for table, column in TABLES:
            cursor.execute(
                f'DELETE FROM "{table}" WHERE {column} LIKE %s',  # noqa: S608  # nosec B608
                [P + "%"],
            )


def file_rows():
    fy = get_operational_fy()
    password = User.objects.get(email="cceo1@edify.org").password
    lead = StaffProfile.objects.get(user__email="pl1@edify.org")
    director = User.objects.get(email="cd@edify.org")
    profiles = []
    for i in range(1, 5):
        user = User.objects.create(
            id=f"{P}u{i}",
            email=f"{P}{i}@edify.org",
            name=f"Gpcv Officer {i}",
            password=password,
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        profile = StaffProfile.objects.create(
            id=f"{P}p{i}",
            user=user,
            title="Field Officer" if i % 2 else "",
            department="Programmes",
            country="Uganda",
            onboarding_state="active",
        )
        StaffSupervisorAssignment.objects.create(
            id=f"{P}s{i}", supervisee=profile, supervisor=lead
        )
        profiles.append(profile)
    stages = ["priorities_draft", "priorities_manager_review", "priorities_draft"]
    for i, stage in enumerate(stages, start=1):
        review = PerformanceReview.objects.create(
            id=f"{P}r{i}",
            staff=profiles[i - 1],
            period=f"FY{fy}",
            fy=fy,
            review_type="annual_priorities",
            stage=stage,
            due_date=timezone.localdate(),
            functional_manager=director if i == 1 else None,
        )
        for n in range(1, 4 if i != 3 else 3):
            PerformancePriority.objects.create(
                id=f"{P}q{i}{n}",
                review=review,
                sequence=n,
                outcome_statement=f"Outcome {i}.{n}: schools lead their own improvement",
                strategic_alignment="Strategic pillar 2"
                if n % 2
                else (None if i == 2 else ""),
                weight=[40, 35, 25][n - 1],
                metric_key="direct_visits" if i == 3 and n == 1 else None,
                target_number=12 if i == 3 and n == 1 else None,
                employee_reflection="Visited every cluster" if n == 1 else None,
                employee_rating={1: "meets", 3: "far_exceeds"}.get(n),
                manager_assessment="Good progress\nkeep going" if n == 2 else None,
                manager_rating="exceeds" if n == 2 else None,
                agreed_action="Pair with a mentor" if n == 2 else None,
                functional_manager_rating="meets" if n == 3 else None,
                is_mandatory=n == 3,
            )
        for k, (kind, name) in enumerate(
            [("value", "Christ like Service"), ("spiritual", "Prayer life")]
            if i == 1
            else [("value", "Best Idea Wins")]
        ):
            ValueCommitment.objects.create(
                id=f"{P}v{i}{k}",
                review=review,
                kind=kind,
                value_name=name,
                agreed_behaviour="Serve every school first" if k == 0 else None,
                employee_reflection="I pray with the cluster" if k == 0 else None,
                manager_evidence="Seen at every cluster meeting" if k == 0 else None,
            )


def table_rows(table, column):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE {column} LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


def ask(readers_queries):
    """The oracle's answers for each (reader, query)."""
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    out_path = os.environ["GOLDEN_OUT"]
    answers = []
    for email, queries in readers_queries:
        os.environ["WEB_PATH"] = PAGE
        os.environ["WEB_READERS"] = email
        os.environ["WEB_QUERIES"] = json.dumps(queries)
        with open(oracle, encoding="utf-8") as fh:
            exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
        with open(out_path, encoding="utf-8") as fh:
            answers += json.load(fh)["answers"]
    return answers


OPEN = [
    (f"{P}1@edify.org", [{}]),
    (f"{P}2@edify.org", [{}]),
    (f"{P}3@edify.org", [{}]),
    (f"{P}4@edify.org", [{}]),
    (
        "pl1@edify.org",
        [
            {},
            {"staff": f"{P}p1"},
            {"staff": f"{P}p2"},
            {"staff": f"{P}p3"},
            {"staff": f"{P}p4"},
        ],
    ),
    ("hr@edify.org", [{}, {"staff": f"{P}p1"}, {"staff": "nobody"}]),
    ("cd@edify.org", [{"staff": f"{P}p1"}, {"staff": f"{P}p2"}]),
    ("admin@edify.org", [{"staff": f"{P}p2"}]),
    ("cceo1@edify.org", [{}, {"staff": f"{P}p1"}]),
    ("partner@edify.org", [{}]),
]
LOCKED = [
    (f"{P}1@edify.org", [{}]),
    (f"{P}3@edify.org", [{}]),
    ("pl1@edify.org", [{"staff": f"{P}p2"}]),
    ("hr@edify.org", [{"staff": f"{P}p1"}]),
]
#: The answers Go hands on in the open window: a measured priority's live
#: figures.
HANDED_ON = {(f"{P}3@edify.org", ""), ("pl1@edify.org", f"{P}p3")}

clear()
cycle = PerformanceCycle.objects.get(fy=get_operational_fy())
window = cycle.active_window
try:
    file_rows()
    tables = {
        table: table_rows(table, column)
        for table, column in TABLES
        if column != "user_id"
    }
    written = timezone.now().isoformat()
    opened = ask(OPEN)
    PerformanceCycle.objects.filter(id=cycle.id).update(active_window="none")
    locked = ask(LOCKED)
finally:
    PerformanceCycle.objects.filter(id=cycle.id).update(active_window=window)
    clear()
for a in opened:
    if (a["email"], a["query"].get("staff", "")) in HANDED_ON:
        a["handed_on"] = True
with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
    json.dump(
        {
            "written": written,
            "window": window,
            "tables": tables,
            "open": opened,
            "locked": locked,
        },
        fh,
        indent=1,
        sort_keys=True,
        ensure_ascii=False,
    )
print(f"{len(opened)} open and {len(locked)} locked answers")
