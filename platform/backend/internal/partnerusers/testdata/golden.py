"""Write partner_users_golden.json: the Partner Admin's Users page as the
existing application answers it over a team the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/partner_users_golden.json \\
    python manage.py shell < platform/backend/internal/partnerusers/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpu", a team for the Partner Admin's organisation: enough members
to page, staff and volunteers, with and without a title, phone and email,
logins active, invited, deactivated and deleted, a member who has left, and
the schools they look after (held by the organisation, and one it does not
hold); asks the app's feed as the Partner Admin, the partner's own login
(whose team is empty), Admin and Impact Assessment (who lead no team) and a
Country Director (who may not open the page); writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/partner_users_test.go files the same rows and compares.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page
from apps.partners.models import (
    Partner,
    PartnerAssignment,
    PartnerMember,
    PartnerSchoolMember,
)
from apps.schools.models import School

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/partner/users"
#: Children first.
TABLES = ("partner_school_member", "partner_member", "user")


def clear():
    PartnerSchoolMember.objects.filter(id__startswith="gpu").delete()
    PartnerMember.objects.filter(id__startswith="gpu").delete()
    User.all_objects.filter(id__startswith="gpu").delete()


def file_rows():
    lead = User.objects.get(email="partner-admin@edify.org")
    partner = Partner.objects.get(user=lead)
    held = list(
        School.objects.filter(
            id__in=PartnerAssignment.objects.filter(
                partner=partner, school__isnull=False
            )
            .exclude(status__in=PartnerAssignment.RELEASED_STATUSES)
            .values("school_id")
        ).order_by("id")[:5]
    )
    not_held = (
        School.objects.exclude(id__in=[s.id for s in held])
        .exclude(
            id__in=PartnerAssignment.objects.filter(partner=partner).values("school_id")
        )
        .order_by("id")
        .first()
    )
    now = dj_timezone.now()
    states = [
        ("active", True, None),
        ("pending_invited", False, None),
        ("disabled", False, None),
        ("active", True, now),
    ]
    members = []
    for i in range(56):
        user = None
        if i % 5 < 4 and i < 20:
            status, is_active, deleted = states[i % 4]
            user = User.objects.create(
                id=f"gpuu{i:03d}",
                email=f"gpu{i:03d}@example.org",
                name=f"Login {i}",
                roles=["PartnerFieldOfficer"],
                active_role="PartnerFieldOfficer",
                is_active=is_active,
                status=status,
                deleted_at=deleted,
            )
        members.append(
            PartnerMember.objects.create(
                id=f"gpum{i:03d}",
                partner=partner,
                name=f"Golden Member {i:02d}" + (" <b>x</b>" if i == 2 else ""),
                role="volunteer" if i % 3 == 0 else "staff",
                title=["", "Trainer", "Coordinator"][i % 3],
                phone="" if i % 2 else f"0700 {i:03d}",
                email="" if i % 4 == 1 else f"member{i}@example.org",
                active=i != 7,
                user=user,
            )
        )
    links = [(0, held[0]), (0, held[1]), (0, held[2]), (1, held[3])]
    if not_held is not None:
        links.append((1, not_held))
    links.append((7, held[4]))
    for k, (m, school) in enumerate(links):
        PartnerSchoolMember.objects.create(
            id=f"gpus{k:03d}",
            partner=partner,
            member=members[m],
            school=school,
            assigned_by_user_id=lead.id,
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpu%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "partner-admin@edify.org": [
        {},
        {"roster_page": "2"},
        {"roster_page": "9"},
        {"roster_page": "x"},
    ],
    "partner@edify.org": [{}],
    "admin@edify.org": [{}],
    "ia@edify.org": [{}],
    "cd@edify.org": [{}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for query in asked:
                status, body = read_page(user, PATH, query)
                answers.append(
                    {
                        "email": email,
                        "path": PATH,
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
