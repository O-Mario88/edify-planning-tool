"""Write golden.json: Core Schools Planning (/core-schools) as the existing
feed reads it, with its three lazily drawn tabs.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/coreschools/testdata/golden.py

Only against a database whose name ends in "_test". Everything below happens
in one transaction that is rolled back, so nothing it writes outlives it.
The page gives every core school in the reader's scope its package for the
year on each read (CoreSchoolsService.self_heal_plans and
carry_packages_forward) — a write Go does not make, so Go hands such a read
on. This first heals every core school for the operational year and the one
before by those same services, as a first read would, so the page's own
heal finds nothing to do. It then asks the page as the CCEO who holds the
core schools, a CCEO who holds none, the Programme Lead (both lenses), the
Accountant, IA and the Admin, for the operational year and the one before,
the second page, a page size, each filter and a search, and writes the rows
the page reads (the rows the transaction added, in the order they are
stored) and the answers to GOLDEN_OUT.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.core.fy import get_operational_fy
from apps.core_schools.core_planning_services import CoreSchoolsService
from apps.mobile_feed.views import read_page
from apps.schools.lifecycle_service import active_schools

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/core-schools"
FY = get_operational_fy()
EARLIER = str(int(FY) - 1)
#: The tables the heal writes and the page reads, parents first.
TABLES = ("core_plan", "core_school_profile", "core_activity_slot")


def ids():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'SELECT id::text FROM "{table}"')  # noqa: S608  # nosec B608
            out[table] = {r[0] for r in cursor.fetchall()}
    return out


def heal():
    """Every core school's package for both years, as a first read gives it."""
    reader = User.objects.get(email="admin@edify.org")
    schools = active_schools().filter(school_type="core")
    for fy in (FY, EARLIER):
        while CoreSchoolsService.self_heal_plans(schools, fy, reader):
            pass
        while CoreSchoolsService.carry_packages_forward(schools, fy):
            pass


def dump_rows(before):
    after = ids()
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            added = sorted(after[table] - before[table])
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id::text = ANY(%s) ORDER BY ctid',  # noqa: S608  # nosec B608
                [added],
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def options(body, name):
    """The values a filter of the answer offers, past "All"."""
    for block in body.get("blocks", []):
        for f in block.get("filters", {}).get("filters", []):
            if f["name"] == name:
                return [o["value"] for o in f["options"] if o["value"] != "All"]
    return []


def ask(reader, query):
    at = dj_timezone.now().isoformat()
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "at": at,
        "status": status,
        "body": body,
    }


with transaction.atomic():
    before = ids()
    heal()
    rows = dump_rows(before)
    officer = User.objects.get(email="cceo@edify.org")
    first = ask(officer, {})
    answers = [first]
    asked = [
        {"fy": EARLIER},
        {"page": "2"},
        {"page": "3", "per_page": "20"},
        {"per_page": "10"},
        {"ssa_status": "done"},
        {"ssa_status": "not_done"},
        {"partner_assigned": "assigned"},
        {"partner_assigned": "unassigned"},
        {"school_type_filter": "core"},
        {"school_type_filter": "champion"},
        {"q": "primary"},
    ]
    for name in ("district", "staff", "partner"):
        for value in options(first["body"], name)[:1]:
            asked.append({name: value})
    for query in asked:
        answers.append(ask(officer, query))
    for email, queries in (
        ("cceo8@edify.org", [{}]),
        (
            "pl1@edify.org",
            [{}, {"lens": "oversight"}, {"lens": "oversight", "page": "2"}],
        ),
        ("accountant@edify.org", [{}]),
        ("ia@edify.org", [{}]),
        ("admin@edify.org", [{}, {"fy": EARLIER}]),
        ("partner@edify.org", [{}]),
    ):
        reader = User.objects.get(email=email)
        for query in queries:
            answers.append(ask(reader, query))
    transaction.set_rollback(True)

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        out,
        default=str,
    )
print(
    f"wrote {len(answers)} answers, "
    + ", ".join(f"{t} {len(r)}" for t, r in rows.items())
)
