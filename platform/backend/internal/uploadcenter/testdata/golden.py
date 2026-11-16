"""Write golden.json: the Upload Center (/uploads) as the existing feed reads
it, over uploads the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/uploadcenter/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gup", documents in each state (a draft, one under review, one
approved, one returned, a published policy everyone must sign with an
overdue signature, an archived one), training resources aimed at one role,
at the Country Director by slug, at one person, from a future day and at
nobody, a policy with a title too long for its cell and an audience too long
for its, and school and SSA import batches (staged, imported, with School
IDs to resolve). Each sits a minute apart before the file is written. It
asks the page of every reader it opens for and of readers it refuses, with
each tab, a type, a status, a search and pages; writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/upload_center_test.go files the same rows and
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

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/uploads"
NOW = dj_timezone.now()
TABLES = (
    "ssa_import_row",
    "ssa_import_batch",
    "school_import_batch",
    "document_acknowledgement",
    "document_audience_rule",
    "document_version",
    "document_asset",
)


def clear():
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE document_asset SET current_version_id = NULL WHERE id LIKE 'gup%%'"
        )
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gup%%'")


def insert(cursor, table, row, at):
    """File one row through its model, so the model's defaults apply, then
    stamp its times."""
    from django.apps import apps

    model = next(m for m in apps.get_models() if m._meta.db_table == table)
    model.objects.create(**row)
    cursor.execute(
        f'UPDATE "{table}" SET created_at = %s, updated_at = %s WHERE id = %s',
        [at, at, row["id"]],
    )


def file_rows():
    with connection.cursor() as cursor:

        def user(email):
            return User.objects.get(email=email).id

        hr, ia, cd, cceo = (
            user("hr@edify.org"),
            user("ia@edify.org"),
            user("cd@edify.org"),
            user("cceo@edify.org"),
        )
        n = {"doc": 0}

        def at(minutes):
            return NOW - timedelta(minutes=minutes)

        def document(
            title, doc_type, status, author, rules, *, mandatory=False, acks=()
        ):
            n["doc"] += 1
            key = f"{n['doc']:02d}"
            did, vid = f"gupD{key}", f"gupV{key}"
            when = at(10 + n["doc"])
            insert(
                cursor,
                "document_asset",
                {
                    "id": did,
                    "title": title,
                    "slug": f"gup-{key}",
                    "document_type": doc_type,
                    "status": status,
                    "created_by": author,
                    "acknowledgement_required": mandatory,
                },
                when,
            )
            insert(
                cursor,
                "document_version",
                {
                    "id": vid,
                    "document_id": did,
                    "version_number": 2 if mandatory else 1,
                    "uri": f"documents/{did}.pdf",
                    "original_filename": f"{did}.pdf",
                    "mime_type": "application/pdf",
                    "file_extension": "pdf",
                    "preview_status": "ready" if mandatory else "not_required",
                },
                when,
            )
            cursor.execute(
                "UPDATE document_asset SET current_version_id = %s WHERE id = %s",
                [vid, did],
            )
            for i, rule in enumerate(rules):
                insert(
                    cursor,
                    "document_audience_rule",
                    {"id": f"gupR{key}{i}", "document_id": did, **rule},
                    when,
                )
            for i, (who, state, due) in enumerate(acks):
                insert(
                    cursor,
                    "document_acknowledgement",
                    {
                        "id": f"gupK{key}{i}",
                        "document_id": did,
                        "version_id": vid,
                        "user_id": who,
                        "state": state,
                        "due_date": due,
                    },
                    when,
                )

        today = dj_timezone.localdate()
        document("Field Safety Draft", "policy", "draft", hr, [{"role": "CCEO"}])
        document("Leave Policy Review", "policy", "under_review", hr, [{}])
        document("Finance Manual", "manual", "approved", hr, [{"role": "Accountant"}])
        document("Conduct Policy", "policy", "returned", hr, [{}])
        document(
            "Data Protection Policy",
            "policy",
            "published",
            hr,
            [{"role": "CCEO", "country": "Uganda"}, {"role": "PL"}],
            mandatory=True,
            acks=(
                (cceo, "agreed", today),
                (cd, "pending", today - timedelta(days=3)),
                (ia, "pending", today + timedelta(days=3)),
            ),
        )
        document("Old Travel Policy", "policy", "archived", hr, [{}])
        document(
            "A very long policy title that runs well past the sixty characters a cell shows",
            "policy",
            "effective",
            hr,
            [
                {"role": "CCEO", "country": "Uganda"},
                {"role": "Program Lead"},
                {"role": "HumanResources"},
            ],
        )
        document(
            "SSA Coaching Manual",
            "training_manual",
            "published",
            ia,
            [{"role": "ImpactAssessment"}],
        )
        document(
            "Directors Briefing Deck",
            "training_presentation",
            "published",
            ia,
            [{"role": "CD"}],
        )
        document(
            "Personal Guide", "training_manual", "effective", ia, [{"user_id": hr}]
        )
        document(
            "Next Term Deck",
            "training_presentation",
            "published",
            ia,
            [{"role": "HumanResources", "effective_from": today + timedelta(days=5)}],
        )
        document("Unaimed Manual", "training_manual", "published", ia, [])
        document("Training Draft", "training_presentation", "draft", ia, [{}])

        admin = user("admin@edify.org")
        for key, table, name, by, status, total, minutes in (
            (
                "gupS1",
                "school_import_batch",
                "schools-north.csv",
                admin,
                "staged",
                40,
                3,
            ),
            (
                "gupS2",
                "school_import_batch",
                "schools-east.xlsx",
                "gone-user",
                "imported",
                12,
                4,
            ),
            ("gupA1", "ssa_import_batch", "ssa-term1.csv", ia, "staged", 9, 2),
            ("gupA2", "ssa_import_batch", "ssa-term2.csv", ia, "imported", 5, 5),
        ):
            insert(
                cursor,
                table,
                {
                    "id": key,
                    "file_name": name,
                    "uploaded_by": by,
                    "status": status,
                    "total_rows": total,
                },
                at(minutes),
            )
        for i, status in enumerate(("unmatched", "unmatched", "ready")):
            insert(
                cursor,
                "ssa_import_row",
                {
                    "id": f"gupW{i}",
                    "batch_id": "gupA1",
                    "row_number": i + 1,
                    "status": status,
                },
                at(2),
            )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gup%%' ORDER BY id"
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
    asked = [
        {},
        {"tab": "imports"},
        {"tab": "documents"},
        {"tab": "training"},
        {"tab": "mine"},
        {"tab": "bogus"},
        {"type": "policy"},
        {"type": "training_manual"},
        {"status": "draft"},
        {"status": "review"},
        {"status": "staged"},
        {"q": "policy"},
        {"q": "Edify"},
        {"q": "zzz"},
        {"page": "2"},
        {"page": "x"},
    ]
    readers = {
        "admin@edify.org": asked,
        "ia@edify.org": asked,
        "hr@edify.org": asked,
        "cd@edify.org": [{}, {"tab": "training"}, {"tab": "mine"}],
        "rvp@edify.org": [{}],
        "cceo@edify.org": [{}],
        "pl1@edify.org": [{}],
        "accountant@edify.org": [{}],
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
            "today": dj_timezone.localdate().isoformat(),
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
