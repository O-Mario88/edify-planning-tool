"""Write the Policy Agreement Center golden: /policy-agreement
(documents.views.agreement_center_view, pages/documents/agreement_center.html)
as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/uploadcenter/testdata/agreement_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpag": for the CCEO, answers to Safeguarding (agreed) and the
Apostles' Creed (disagreed, reviewed outside the viewer), two policies of
its own pending (one with a reason, a download, a required comment, a due
date and part of its reading done; one that monitors no reading), a pending
answer to a draft (not shown) and an agreed one; for the Program Lead,
agreements to both onboarding commitments only; for Impact Assessment, an
agreement to Safeguarding alone (the center would assign the Creed). It
asks the page of them and of the Admin (who has answered nothing), writes
the answers with the rows (`tables`) and deletes the rows.
internal/integration/policy_restricted_test.go files them again and asks Go.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.documents.models import (
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentVersion,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("agreement_golden.py runs only against a _test database")

User = get_user_model()
P = "gpag"
PAGE = "/policy-agreement"
READERS = ("cceo1@edify.org", "pl1@edify.org", "ia@edify.org", "admin@edify.org")
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
    pl = User.objects.get(email="pl1@edify.org")
    ia = User.objects.get(email="ia@edify.org")
    n = 0

    def answer(document, version, user, state, **extra):
        nonlocal n
        n += 1
        DocumentAcknowledgement.objects.create(
            id=f"{P}a{n:02d}",
            document=document,
            version=version,
            user_id=user.id,
            state=state,
            choice={"agreed": "agree", "disagreed": "disagree"}.get(state, ""),
            **extra,
        )

    responded = timezone.now() - timedelta(days=3)
    for slug, cceo_state, offline in (
        ("edify-safeguarding-policy", "agreed", False),
        ("edify-apostles-creed", "disagreed", True),
    ):
        document = DocumentAsset.objects.get(slug=slug)
        version = document.current_version
        answer(
            document,
            version,
            cceo,
            cceo_state,
            responded_at=responded,
            offline_attestation=offline,
            active_reading_seconds=40,
        )
        answer(document, version, pl, "agreed", responded_at=responded)
        if slug == "edify-safeguarding-policy":
            answer(document, version, ia, "agreed", responded_at=responded)

    specs = [
        # status, reason, download, comment required, minutes, effective, due, active, sessions, state
        (
            "published",
            "Every officer handles school records.",
            True,
            True,
            5,
            date(2026, 1, 15),
            date(2026, 12, 1),
            120,
            1,
            "pending",
        ),
        ("effective", "", False, False, 0, None, None, 0, 2, "pending"),
        ("draft", "", False, False, 3, None, None, 0, 0, "pending"),
        ("published", "", False, False, 2, None, None, 200, 3, "agreed"),
    ]
    for i, (
        status,
        reason,
        download,
        comment,
        minutes,
        effective,
        due,
        active,
        sessions,
        state,
    ) in enumerate(specs):
        document = DocumentAsset.objects.create(
            id=f"{P}d{i}",
            slug=f"golden-agreement-{i}",
            title=f"Golden Agreement {i}",
            description=f"What policy {i} asks of every officer.",
            document_type="policy",
            category="HR",
            status=status,
            acknowledgement_required=True,
            agreement_required=True,
            agreement_statement=f"I have read and agree to Golden Agreement {i}.",
            acknowledgement_reason=reason,
            download_allowed=download,
            comment_required=comment,
            required_reading_minutes=minutes,
        )
        version = DocumentVersion.objects.create(
            id=f"{P}v{i}",
            document=document,
            version_number=i + 1,
            uri=f"/files/agreement-{i}",
            original_filename=f"agreement-{i}.pdf",
            effective_date=effective,
        )
        DocumentAsset.objects.filter(id=document.id).update(current_version=version)
        answer(
            document,
            version,
            cceo,
            state,
            due_date=due,
            active_reading_seconds=active,
            session_count=sessions,
            responded_at=responded if state == "agreed" else None,
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
