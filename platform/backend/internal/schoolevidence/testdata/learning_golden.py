"""Write the School Evidence Learning results golden: /ia/school-evidence/
(ia_school_evidence_views.school_evidence_page, its Learning tab) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/schoolevidence/testdata/learning_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gsev", class results in three schools Impact Assessment reads:
confirmed pairs across last year and this (compared by score, by
proficiency, withheld for too few learners, one year only, not comparable),
pending results recorded by Impact Assessment and by someone else (the
second the officer may verify), a returned one with its reason, subjects in
mixed case, and enough this year to page the register; asks the tab of the
readers who open it under its filters, writes the answers with the rows
(`tables`) and deletes the rows.
internal/integration/school_evidence_test.go files them again and asks Go.
"""

import json
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.core.fy import get_operational_fy
from apps.impact.evidence_services import evidence_schools
from apps.impact.models import LearningAssessmentResult

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("learning_golden.py runs only against a _test database")

User = get_user_model()
P = "gsev"
PAGE = "/ia/school-evidence/"
READERS = ("ia@edify.org", "admin@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("impact_learning_result",)


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM impact_learning_result WHERE id LIKE %s", [P + "%"])


def file_rows():
    ia = User.objects.get(email="ia@edify.org")
    cceo = User.objects.get(email="cceo1@edify.org")
    schools = list(evidence_schools(ia).order_by("name")[:3])
    fy = get_operational_fy()
    prev = str(int(fy) - 1)
    today = timezone.localdate()
    n = 0

    def result(
        school,
        year,
        status,
        *,
        grade="P5",
        subject="Mathematics",
        assessment="onetest",
        learners=20,
        mean=None,
        maximum=None,
        proficient=None,
        recorder=cceo,
        reason="",
        days=0,
    ):
        nonlocal n
        LearningAssessmentResult.objects.create(
            id=f"{P}{n:03d}",
            school=school,
            country="Uganda",
            fy=year,
            assessment_type=assessment,
            assessed_on=today - timedelta(days=days),
            grade_level=grade,
            subject=subject,
            learners_tested=learners,
            mean_score=mean,
            max_score=maximum,
            learners_proficient=proficient,
            recorded_by_user_id=recorder.id,
            verification_status=status,
            return_reason=reason,
        )
        n += 1

    a, b, c = schools
    # Compared by score: P5 Mathematics in school a.
    result(
        a, prev, "confirmed", mean=Decimal("45.50"), maximum=Decimal("100"), days=400
    )
    result(a, fy, "confirmed", mean=Decimal("52.25"), maximum=Decimal("100"), days=3)
    # Compared by proficiency (no maximum): P6 English in school a.
    result(a, prev, "confirmed", grade="P6", subject="English", proficient=8, days=380)
    result(
        a,
        fy,
        "confirmed",
        grade="P6",
        subject=" english ",
        proficient=6,
        learners=25,
        days=4,
    )
    # Withheld: too few learners in school b.
    result(
        b,
        prev,
        "confirmed",
        learners=6,
        mean=Decimal("30"),
        maximum=Decimal("50"),
        days=390,
    )
    result(
        b,
        fy,
        "confirmed",
        learners=12,
        mean=Decimal("35"),
        maximum=Decimal("50"),
        days=5,
    )
    # One year only: school c this year.
    result(
        c,
        fy,
        "confirmed",
        grade="P7",
        subject="Science",
        mean=Decimal("61"),
        maximum=Decimal("80"),
        days=6,
    )
    # Not comparable: a score before, a proficiency after, school c P4.
    result(
        c,
        prev,
        "confirmed",
        grade="P4",
        subject="Literacy",
        mean=Decimal("40"),
        maximum=Decimal("80"),
        days=370,
    )
    result(c, fy, "confirmed", grade="P4", subject="Literacy", proficient=11, days=7)
    # Pending: by Impact Assessment (not theirs to verify) and by someone else.
    result(
        a,
        fy,
        "pending",
        grade="P3",
        subject="Numeracy",
        recorder=ia,
        proficient=4,
        days=1,
    )
    result(b, fy, "pending", grade="P3", subject="Numeracy", proficient=9, days=2)
    # Returned with its reason.
    result(
        c,
        fy,
        "returned",
        grade="P2",
        reason="The class size does not match the register",
        days=8,
    )
    # Enough this year to page the register.
    for k in range(45):
        result(
            schools[k % 3],
            fy,
            "confirmed",
            grade=f"P{1 + k % 7}",
            subject="Reading",
            mean=Decimal(str(50 + k)),
            maximum=Decimal("100"),
            days=10 + k,
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    fy = get_operational_fy()
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            {},
            {"register_page": "2"},
            {"status": "pending"},
            {"status": "returned"},
            {"subject": "Mathematics"},
            {"register_page": "9", "subject": "Reading"},
            {"fy": str(int(fy) - 1)},
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
