"""Write my_pd_golden.json: My Professional Development (/my-professional-
development) as the existing feed reads it, and what that read writes, over
courses the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/my_pd_golden.json \\
    python manage.py shell < platform/backend/internal/mypd/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gmpd" and every date counted from today: for one CCEO this year a
course whose enrolment is confirmed and whose start has passed (the read
moves it on, and closes its "starts soon" reminder), one returned by the
supervisor, a draft, a closed course and a rejected one, an allocation and
two messages from HR; last year a course whose end has passed (the read ends
it), one marked complete with its proof on file and one whose certificate was
uploaded weeks ago. For a second CCEO this year a funded and a self-funded
course confirmed in BambooHR, an accountability without its expense id and
one awaiting HR sign-off; last year a request with HR and a course starting in
three days, and a course that ends today and one that starts today. A third
CCEO holds nothing, so the read makes their allocation.

Each page is asked inside a transaction that is rolled back, so every
question meets the same rows; what the read wrote (course statuses, closed
reminders, allocations made) is recorded beside the answer. The rows, the
answers and the writes go to GOLDEN_OUT and the rows are deleted.
internal/integration/my_pd_test.go files the same rows and compares both.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page
from apps.messaging.models import Message, MessageThread
from apps.notifications.models import Notification
from apps.professional_development.models import (
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentCertificate,
    ProfessionalDevelopmentRequest,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/my-professional-development"
#: Children first.
TABLES = (
    "pd_certificate",
    "notification",
    "message",
    "messaging_messagethread",
    "pd_request",
    "pd_allocation",
)
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()


def day(n):
    return TODAY + timedelta(days=n)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gmpd%%'")  # noqa: S608  # nosec B608
        # The allocations the reads made for the readers (none survive a
        # rolled-back read, but an earlier failed run may have left one).
        cursor.execute(
            "DELETE FROM pd_allocation WHERE staff_id IN "
            '(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email IN ('cceo1@edify.org', 'cceo2@edify.org', 'cceo3@edify.org'))"
        )


def profile(email):
    return User.objects.get(email=email).staff_profile


def file_rows():
    one, two = profile("cceo1@edify.org"), profile("cceo2@edify.org")
    hr = User.objects.get(email="hr@edify.org")
    n = 0

    def course(sp, fy, status, ago, **kw):
        nonlocal n
        n += 1
        rid = f"gmpdr{n:02d}"
        fields = {
            "id": rid,
            "fy": fy,
            "staff_id": sp.id,
            "staff_name": sp.user.name,
            "course_name": f"Golden course {n:02d}",
            "course_category": "Leadership",
            "course_type": "online",
            "institution": f"Golden Institute {n:02d}",
            "start_date": day(-30),
            "end_date": day(30),
            "funding_type": "fully_funded",
            "currency": "USD",
            "requested_amount_cents": 25000,
            "total_cost_cents": 25000,
            "course_fee_cents": 25000,
            "status": status,
            **kw,
        }
        ProfessionalDevelopmentRequest.objects.create(**fields)
        # created_at / updated_at as the scenario needs them.
        ProfessionalDevelopmentRequest.objects.filter(id=rid).update(
            created_at=NOW - timedelta(days=ago),
            updated_at=NOW - timedelta(days=ago),
        )
        return rid

    # cceo1, this year.
    started = course(
        one,
        "2027",
        "enrollment_confirmed",
        40,
        start_date=day(-2),
        enrollment_confirmed_at=NOW - timedelta(days=5),
        submitted_at=NOW - timedelta(days=40),
    )
    course(
        one,
        "2027",
        "returned_by_supervisor",
        20,
        submitted_at=NOW - timedelta(days=21),
        supervisor_reviewed_at=NOW - timedelta(days=20),
    )
    course(
        one, "2027", "draft", 10, funding_type="self_funded", requested_amount_cents=0
    )
    course(
        one,
        "2027",
        "completed_closed",
        90,
        start_date=day(-120),
        end_date=day(-60),
        accounted_amount=20000,
        signed_off_at=NOW - timedelta(days=50),
    )
    course(one, "2027", "rejected", 70, course_type="in_person")
    # cceo1, last year.
    ending = course(
        one, "2026", "in_progress", 200, start_date=day(-60), end_date=day(-1)
    )
    marked = course(
        one,
        "2026",
        "marked_complete",
        150,
        start_date=day(-100),
        end_date=day(-40),
        marked_complete_at=NOW - timedelta(days=20),
        course_type="hybrid",
    )
    course(
        one,
        "2026",
        "certificate_uploaded",
        400,
        start_date=day(-100),
        end_date=day(-50),
    )
    # cceo2, this year.
    course(
        two, "2027", "bamboohr_confirmed", 50, start_date=day(-90), end_date=day(-30)
    )
    course(
        two,
        "2027",
        "bamboohr_confirmed",
        55,
        start_date=day(-90),
        end_date=day(-30),
        funding_type="self_funded",
        requested_amount_cents=0,
    )
    course(
        two,
        "2027",
        "accountability_submitted",
        60,
        accounted_amount=24000,
        accountability_submitted_at=NOW - timedelta(days=8),
    )
    course(two, "2027", "awaiting_hr_signoff", 65, accounted_amount=25000)
    # cceo2, last year.
    course(
        two,
        "2026",
        "submitted_to_hr",
        15,
        submitted_at=NOW - timedelta(days=15),
        supervisor_reviewed_at=NOW - timedelta(days=12),
    )
    course(two, "2026", "enrollment_confirmed", 25, start_date=day(3), end_date=day(40))
    # The day's edges: a course that ends today and one that starts today.
    course(two, "2026", "in_progress", 30, start_date=day(-20), end_date=day(0))
    course(two, "2026", "enrollment_confirmed", 35, start_date=day(0), end_date=day(20))

    ProfessionalDevelopmentAllocation.objects.create(
        id="gmpda1",
        staff_id=one.id,
        fy="2027",
        annual_allocation=200000,
        currency="USD",
    )
    ProfessionalDevelopmentAllocation.objects.create(
        id="gmpda2", staff_id=two.id, fy="2027", annual_allocation=10000, currency="UGX"
    )
    ProfessionalDevelopmentCertificate.objects.create(
        id="gmpdc1",
        request_id=marked,
        uri="pd/gmpd/cert.pdf",
        original_name="certificate.pdf",
        file_size=1200,
        uploaded_by=one.user_id,
        status="uploaded",
        document_type="certificate",
    )
    thread = MessageThread.objects.create(
        id="gmpdt1", subject="Golden course", category="professional_development"
    ).id
    for m, (sender, status) in enumerate(
        ((hr.id, "unread"), ("system", "read")), start=1
    ):
        Message.objects.create(
            thread_id=thread,
            id=f"gmpdm{m}",
            recipient_id=one.user_id,
            sender_id=sender,
            category="professional_development",
            body=f"Golden note {m} about your course",
            status=status,
            context_id=started,
        )
    # The reminders the clock closes: "starts soon" on the started course,
    # "in progress" on the one that has ended.
    for k, (rid, event) in enumerate(
        ((started, "pd_course_starting"), (ending, "pd_course_in_progress")), start=1
    ):
        Notification.objects.create(
            id=f"gmpdn{k}",
            recipient_id=one.user_id,
            title="Golden reminder",
            body="Golden reminder",
            source_event_type=event,
            context_type="pd_request",
            context_id=rid,
            action_required=True,
            status="unread",
            category="professional_development",
        )


def dump(table, where):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE {where} ORDER BY id'
        )  # noqa: S608  # nosec B608
        return [json.loads(r[0]) for r in cursor.fetchall()]


def dump_rows():
    return {table: dump(table, "id LIKE 'gmpd%%'") for table in TABLES}


def writes(email):
    """What the read left: each course's status, each reminder's state, and
    the reader's allocations."""
    sp = profile(email)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, status FROM pd_request WHERE id LIKE 'gmpd%%' ORDER BY id"
        )
        courses = dict(cursor.fetchall())
        cursor.execute(
            "SELECT id, status, action_required, resolved_at IS NOT NULL FROM notification "
            "WHERE id LIKE 'gmpd%%' ORDER BY id"
        )
        reminders = {r[0]: list(r[1:]) for r in cursor.fetchall()}
        cursor.execute(
            "SELECT fy, country, currency, annual_allocation, status, set_by FROM pd_allocation "
            "WHERE staff_id = %s ORDER BY fy",
            [sp.id],
        )
        allocations = [list(r) for r in cursor.fetchall()]
    return {"courses": courses, "reminders": reminders, "allocations": allocations}


QUESTIONS = {
    "cceo1@edify.org": [{}, {"fy": "2026"}, {"fy": "2025"}, {"fy": "1999"}],
    "cceo2@edify.org": [{}, {"fy": "2026"}],
    "cceo3@edify.org": [{}],
    "hr@edify.org": [{}],
    "pl1@edify.org": [{}],
}

clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email, asked in QUESTIONS.items():
        user = User.objects.get(email=email)
        for query in asked:
            with transaction.atomic():
                status, body = read_page(user, PATH, query)
                wrote = writes(email)
                transaction.set_rollback(True)
            answers.append(
                {
                    "email": email,
                    "path": PATH,
                    "query": query,
                    "status": status,
                    "body": body,
                    "writes": wrote,
                }
            )
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"today": TODAY.isoformat(), "rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
