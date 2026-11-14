"""Write policy_compliance_golden.json: Policy and Manual Compliance as the
existing application answers it over acknowledgements the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/policy_compliance_golden.json \\
    python manage.py shell < platform/backend/internal/policycompliance/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpl", two readable policies (one timing its readers, one not), a
draft one whose answers the page leaves out, and acknowledgements in every
state by enough people to page, read fully, partly, not at all and outside
the viewer, some overdue and some without a role on file; asks the app's
feed as every reader who opens the page and two who may not; writes the rows
and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/policy_compliance_test.go files the same rows and
compares. No policy comment is filed: a reader with comments waiting is
passed on to the existing application.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.core.exceptions import Forbidden
from apps.documents.models import (
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentVersion,
)
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/policy-compliance"
#: Children first.
TABLES = ("document_acknowledgement", "document_version", "document_asset")


def clear():
    # One transaction: a document and its current version name each other.
    with transaction.atomic(), connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gpl%%'")  # noqa: S608  # nosec B608


def file_rows():
    today = dj_timezone.localdate()
    now = dj_timezone.now()
    people = list(User.objects.filter(deleted_at__isnull=True).order_by("id"))
    documents = []
    for i, (status, minutes) in enumerate(
        [("published", 2), ("effective", 0), ("draft", 5)]
    ):
        document = DocumentAsset.objects.create(
            id=f"gplp{i}",
            slug=f"golden-compliance-{i}",
            title=["Golden Code of Conduct", "Golden Leave Manual", "Golden Draft"][i],
            document_type="policy",
            category="HR",
            status=status,
            acknowledgement_required=True,
            required_reading_minutes=minutes,
        )
        version = DocumentVersion.objects.create(
            id=f"gplv{i}",
            document=document,
            version_number=[3, 1, 2][i],
            uri=f"/files/golden-{i}",
            original_filename=f"golden-{i}.pdf",
        )
        DocumentAsset.objects.filter(id=document.id).update(current_version=version)
        documents.append((document, version))
    states = ["pending", "agreed", "disagreed", "pending", "superseded", "agreed"]
    k = 0
    for d, (document, version) in enumerate(documents):
        for n, person in enumerate(people[: [70, 20, 5][d]]):
            DocumentAcknowledgement.objects.create(
                id=f"gpla{k:04d}",
                document=document,
                version=version,
                user_id=person.id,
                state=states[(n + d) % 6],
                role_at_acknowledgement=""
                if n % 7 == 3
                else (person.active_role or ""),
                active_reading_seconds=[0, 45, 120, 4000, 30, 200][n % 6],
                offline_attestation=n % 11 == 5,
                due_date=None
                if n % 4 == 0
                else today + timedelta(days=[-3, 0, 4][n % 3]),
            )
            DocumentAcknowledgement.objects.filter(id=f"gpla{k:04d}").update(
                created_at=now - timedelta(hours=k)
            )
            k += 1


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gpl%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "hr@edify.org": [
        {},
        {"rows_page": "2"},
        {"state": "agreed"},
        {"state": "pending"},
        {"document": "gplp1"},
        {"role": "CCEO"},
        {"state": "bogus"},
    ],
    "cd@edify.org": [{}, {"state": "disagreed"}],
    "pl1@edify.org": [{}],
    "rvp@edify.org": [{}, {"rows_page": "2"}],
    "admin@edify.org": [{}],
    "ia@edify.org": [{}],
    "cceo1@edify.org": [{}],
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
                try:
                    status, body = read_page(user, PATH, query)
                except Forbidden as exc:
                    # _scope_user_ids refuses a role it has no scope for;
                    # the feed's API answers that refusal with a 403.
                    status, body = 403, {"detail": str(exc)}
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
