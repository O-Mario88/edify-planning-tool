"""Write golden.json: the HR Professional Development Dashboard
(/cpd-learning) as the existing feed reads it, over courses the development
seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/cpdlearning/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gcp", courses for ten officers in each part of the course's life
(not started, starting within the week, in progress, ended without a
certificate, waiting on accountability, awaiting sign-off, signed off, a
returned one, a draft, last year's, one in another country, one paid by the
officer, a fourth in progress with its certificate in early), their
allocations and the CCEO role's default, and certificates.
No request waits at the supervisor stage (Go hands the page on then). It
asks the page of the readers it serves with each filter, and of a reader it
refuses; writes the rows and the answers to GOLDEN_OUT and deletes the
rows. internal/integration/cpd_learning_test.go files the same rows and
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
from apps.professional_development.models import (
    PDRoleAllocation,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentCertificate,
    ProfessionalDevelopmentRequest,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/cpd-learning"
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()
TABLES = ("pd_certificate", "pd_request", "pd_allocation", "pd_role_allocation")


def day(n):
    return TODAY + timedelta(days=n)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gcp%%'")


def profile(email):
    return User.objects.get(email=email).staff_profile


def file_rows():
    n = {"r": 0}

    def course(email, status, ago, **kw):
        n["r"] += 1
        sp = profile(email)
        rid = f"gcpr{n['r']:02d}"
        fields = {
            "id": rid,
            "fy": "2027",
            "staff_id": sp.id,
            "staff_name": sp.user.name,
            "position": "CCEO",
            "country": "Uganda",
            "supervisor_name": "Program Lead 1",
            "course_name": f"Golden course {n['r']:02d}",
            "course_category": "Leadership",
            "course_type": "online",
            "institution": "Golden Institute",
            "start_date": day(-30),
            "end_date": day(30),
            "funding_type": "fully_funded",
            "currency": "USD",
            "requested_amount_cents": 20000 + 1000 * n["r"],
            "total_cost_cents": 20000,
            "course_fee_cents": 20000,
            "status": status,
            **kw,
        }
        ProfessionalDevelopmentRequest.objects.create(**fields)
        ProfessionalDevelopmentRequest.objects.filter(id=rid).update(
            created_at=NOW - timedelta(days=ago + 1),
            updated_at=NOW - timedelta(days=ago),
        )
        return rid

    course(
        "cceo1@edify.org", "submitted_to_hr", 2, start_date=day(10), end_date=day(40)
    )
    course(
        "cceo2@edify.org",
        "enrollment_confirmed",
        3,
        start_date=day(3),
        end_date=day(20),
        certification_expected=True,
    )
    course("cceo3@edify.org", "in_progress", 4, start_date=day(-5), end_date=day(9))
    course(
        "cceo4@edify.org",
        "ended",
        5,
        start_date=day(-40),
        end_date=day(-10),
        certification_expected=True,
    )
    course(
        "cceo5@edify.org",
        "bamboohr_confirmed",
        20,
        start_date=day(-60),
        end_date=day(-30),
        accounted_amount=15000,
    )
    signoff = course(
        "cceo6@edify.org",
        "awaiting_hr_signoff",
        6,
        start_date=day(-50),
        end_date=day(-20),
        marked_complete_at=NOW - timedelta(days=8),
        accounted_amount=20000,
        accountability_submitted_at=NOW - timedelta(days=7),
        accountability_reviewed_at=NOW - timedelta(days=6),
    )
    closed = course(
        "cceo7@edify.org",
        "completed_closed",
        9,
        start_date=day(-90),
        end_date=day(-60),
        bamboohr_uploaded=True,
        accounted_amount=18000,
    )
    course("cceo8@edify.org", "returned_by_hr", 1)
    course("cceo9@edify.org", "draft", 1)
    course("cceo10@edify.org", "in_progress", 2, fy="2026")
    course(
        "cceo1@edify.org",
        "in_progress",
        3,
        country="Kenya",
        course_name="Kenya course",
    )
    course(
        "cceo2@edify.org",
        "marked_complete",
        4,
        funding_type="self_funded",
        start_date=day(-20),
        end_date=day(-1),
    )
    uploaded = course(
        "cceo11@edify.org",
        "in_progress",
        7,
        start_date=day(-3),
        end_date=day(12),
        certification_expected=True,
    )

    for i, (email, cents) in enumerate(
        (
            ("cceo1@edify.org", 50000),
            ("cceo3@edify.org", 40000),
            ("cceo7@edify.org", 30000),
        )
    ):
        ProfessionalDevelopmentAllocation.objects.create(
            id=f"gcpa{i}",
            staff_id=profile(email).id,
            fy="2027",
            country="Uganda",
            currency="USD",
            annual_allocation=cents,
        )
    PDRoleAllocation.objects.create(
        id="gcpo1",
        role="CCEO",
        fy="2027",
        country="Uganda",
        currency="USD",
        annual_allocation_cents=25000,
    )
    hr = User.objects.get(email="hr@edify.org")
    for i, rid in enumerate((closed, signoff, uploaded)):
        ProfessionalDevelopmentCertificate.objects.create(
            id=f"gcpc{i}",
            request_id=rid,
            uri=f"pd/{rid}.pdf",
            original_name=f"{rid}.pdf",
            file_size=1000,
            uploaded_by=hr.id,
            status="uploaded",
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gcp%%' ORDER BY id"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def ask(reader, query):
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
    }


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    hr_asks = [
        {},
        {"fy": "2026"},
        {"country": "Uganda"},
        {"country": "Kenya"},
        {"role": "CCEO"},
        {"status": "not_started"},
        {"status": "in_progress"},
        {"status": "pending_certificate"},
        {"status": "completed"},
        {"status": "signed_off"},
        {"status": "inactive"},
        {"reminder": "due"},
        {"reminder": "overdue"},
        {"q": "kenya"},
        {"fund_status": "not_applied"},
        {"page": "2"},
    ]
    readers = {
        "hr@edify.org": hr_asks,
        "admin@edify.org": [{}, {"country": "Kenya"}],
        "cd@edify.org": [{}, {"country": "Kenya"}],
        "rvp@edify.org": [{}],
        "ia@edify.org": [{}],
        "cceo@edify.org": [{}],
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
            "today": TODAY.isoformat(),
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
