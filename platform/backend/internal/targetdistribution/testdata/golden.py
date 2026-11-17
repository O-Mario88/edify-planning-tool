"""Write golden.json: Uganda Target Distribution (/target-distribution) as the
existing feed reads it, for every reader the page opens to and one it does
not, over years with no master.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/targetdistribution/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gtd": a draft cycle for the year after the seed's (so the page
opens on it), an archived cycle the year after that holding a country
priority (a master, which Go hands on), and a staged priority import for a
year without a cycle (which Go hands on to a reader who may import). It asks
the page with no year, each of those years and the seed's own, writes the
rows and the answers to GOLDEN_OUT and deletes the rows.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.hr.models import (
    PriorityImportBatch,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/target-distribution"
P = "gtd"
SEED = StrategicPriorityCycle.objects.order_by("-financial_year").first()
BASE = int(SEED.financial_year) if SEED else int(dj_timezone.localdate().year) + 1
DRAFT, MASTER, STAGED = str(BASE + 1), str(BASE + 2), str(BASE - 1)
#: Children first.
TABLES = (
    "hr_strategic_priority",
    "hr_priority_import_batch",
    "hr_strategic_priority_cycle",
)
READERS = ["ia@edify.org", "cd@edify.org", "admin@edify.org", "cceo@edify.org"]


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows():
    StrategicPriorityCycle.objects.bulk_create(
        [
            StrategicPriorityCycle(
                id=P + "C1", financial_year=DRAFT, title="Draft cycle", status="draft"
            ),
            StrategicPriorityCycle(
                id=P + "C2",
                financial_year=MASTER,
                title="Archived cycle",
                status="archived",
            ),
        ]
    )
    StrategicPriority.objects.bulk_create(
        [
            StrategicPriority(
                id=P + "S1",
                fy=MASTER,
                level="country",
                country_id="Uganda",
                cycle_id=P + "C2",
                title="A country priority",
                sequence=1,
            )
        ]
    )
    PriorityImportBatch.objects.bulk_create(
        [
            PriorityImportBatch(
                id=P + "B1",
                fy=STAGED,
                country_id="Uganda",
                original_file_name="priorities.csv",
                file_sha256="0" * 64,
                uploaded_by=User.objects.get(email="ia@edify.org").id,
            )
        ]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gtd%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUERIES = [{}, {"fy": DRAFT}, {"fy": STAGED}, {"fy": str(BASE)}, {"fy": MASTER}]

clear()
try:
    file_rows()
    rows = dump_rows()
    answers = []
    for email in READERS:
        reader = User.objects.get(email=email)
        for query in QUERIES:
            at = dj_timezone.now().isoformat()
            with transaction.atomic():
                status, body = read_page(reader, PATH, query)
                transaction.set_rollback(True)
            answers.append(
                {
                    "email": email,
                    "path": PATH,
                    "query": query,
                    "at": at,
                    "status": status,
                    "body": body,
                    # A master, or staged imports for a reader who may see them.
                    "hand_on": status == 200
                    and (
                        query.get("fy") == MASTER
                        or (
                            query.get("fy") == STAGED
                            and email in ("ia@edify.org", "admin@edify.org")
                        )
                    ),
                }
            )
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        out,
        default=str,
    )
print(f"wrote {len(answers)} answers")
