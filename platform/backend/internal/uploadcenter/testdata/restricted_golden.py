"""Write the policy response golden: /policy-agreement/restricted
(documents.views.restricted_view, pages/documents/restricted.html) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/uploadcenter/testdata/restricted_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gprd", policies a CCEO disagreed with: two that gate the
application and are in force (one with a long description and statement,
one with none, one short with a statement), one that does not gate it and one still a draft (neither
shown); asks the page of the CCEO and of readers who disagreed with
nothing, writes the answers with the rows (`tables`) and deletes the rows.
internal/integration/policy_restricted_test.go files them again and asks Go.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection

from apps.documents.models import (
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentVersion,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("restricted_golden.py runs only against a _test database")

User = get_user_model()
P = "gprd"
PAGE = "/policy-agreement/restricted"
READERS = ("cceo1@edify.org", "pl1@edify.org", "admin@edify.org")
#: Children first.
TABLES = ("document_acknowledgement", "document_version", "document_asset")


def clear():
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE document_asset SET current_version_id = NULL WHERE id LIKE %s",
            [P + "%"],
        )
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_rows():
    cceo = User.objects.get(email="cceo1@edify.org")
    long = (
        "Every officer keeps school records safe and shares them only with the school. "
        * 6
    )
    specs = [
        (
            "published",
            True,
            long,
            "I have read and agree to the Golden Safeguarding Policy.",
            "The deadline is too short",
        ),
        ("effective", True, "", "", ""),
        ("published", False, "Not a gate", "I agree.", "No"),
        ("draft", True, "A draft", "I agree.", "Not yet"),
        (
            "published",
            True,
            "A short policy",
            "I have read and agree to the Golden Leave Policy.",
            "Too many forms",
        ),
    ]
    for i, (status, blocks, description, statement, comment) in enumerate(specs):
        document = DocumentAsset.objects.create(
            id=f"{P}d{i}",
            slug=f"golden-response-policy-{i}",
            title=f"Golden Response Policy {i}",
            description=description,
            document_type="policy",
            category="HR",
            status=status,
            acknowledgement_required=True,
            agreement_required=True,
            agreement_statement=statement,
            blocks_application_access=blocks,
        )
        version = DocumentVersion.objects.create(
            id=f"{P}v{i}",
            document=document,
            version_number=1,
            uri=f"/files/response-{i}",
            original_filename=f"response-{i}.pdf",
        )
        DocumentAsset.objects.filter(id=document.id).update(current_version=version)
        DocumentAcknowledgement.objects.create(
            id=f"{P}a{i}",
            document=document,
            version=version,
            user_id=cceo.id,
            state="disagreed",
            choice="disagree",
            comment=comment,
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
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps([{}])
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
