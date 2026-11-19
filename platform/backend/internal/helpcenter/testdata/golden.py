"""Write the Knowledge Center golden: its reading pages (help_center.views)
as the existing feed reads them, for readers in several roles.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/helpcenter/testdata/golden.py

Only against a database whose name ends in "_test". Beside the canonical
content the database holds, it files (every id starting "gshc") a feature
guide open to two roles only, never reviewed, with two sections, a
walkthrough and a related article, and a glossary term pointing at it; and
maps every route to its article (sync_route_contexts) so the home does not
write on its read. It asks every reading page of each reader (not an
address that names nothing: the oracle cannot read a view's 404), writes the
answers with the rows (`tables`, the route mappings as `route_contexts`)
and deletes all it filed.
internal/integration/help_center_test.go files them again and asks Go.
"""

import json
import os

from django.conf import settings
from django.db import connection

from apps.help_center.models import (
    HelpArticle,
    HelpArticleRoleAccess,
    HelpArticleRouteContext,
    HelpCategory,
    HelpGlossaryTerm,
    HelpWalkthrough,
)
from apps.help_center.services import sync_route_contexts

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

P = "gshc"
READERS = (
    "cceo1@edify.org",
    "ia@edify.org",
    "admin@edify.org",
    "pl1@edify.org",
    "accountant@edify.org",
    "hr@edify.org",
    "partner@edify.org",
)
TABLES = (
    "help_center_helparticle",
    "help_center_helparticleroleaccess",
    "help_center_helparticle_related_articles",
    "help_center_helpwalkthrough",
    "help_center_helpglossaryterm",
)
PAGES = [
    "/help",
    "/help/getting-started",
    "/help/articles/getting-started",
    "/help/articles/role-admin",
    "/help/articles/feature-gshc-guide",
    "/help/features/gshc-guide",
    "/help/features/feature-planning",
    "/help/workflows/evidence-upload",
    "/help/roles/cceo",
    "/help/roles/program-lead",
    "/help/roles/country_program_lead",
    "/help/categories/getting-started",
    "/help/categories/features",
    "/help/categories/glossary",
    "/help/troubleshooting",
    "/help/release-notes",
]
SEARCHED = {
    "/help/glossary": [
        {},
        {"q": "salesforce"},
        {"q": "Gshc"},
        {"q": "50%"},
        {"q": "zzzz"},
    ],
    "/help/search": [
        {},
        {"q": "planning"},
        {"q": "  SF   ID "},
        {"q": "ssa"},
        {"q": "zzzz"},
    ],
}


def clear(route_ids=()):
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM help_center_helparticleroutecontext WHERE id = ANY(%s)",
            [list(route_ids)],
        )
        cursor.execute(
            "DELETE FROM help_center_helpglossaryterm WHERE id LIKE %s", [P + "%"]
        )
        cursor.execute(
            "DELETE FROM help_center_helparticle_related_articles"
            " WHERE from_helparticle_id LIKE %s",
            [P + "%"],
        )
        for table in (
            "help_center_helpwalkthrough",
            "help_center_helparticleroleaccess",
            "help_center_helparticle",
        ):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_rows():
    guide = HelpArticle.objects.create(
        id=f"{P}a1",
        category=HelpCategory.objects.get(slug="features"),
        title="Golden test guide",
        slug="feature-gshc-guide",
        summary="A guide the golden files, open to two roles.",
        content=[
            {"heading": "What it is", "body": "A short guide.", "items": []},
            {"heading": "Steps", "body": "", "items": ["Open it", "Read it"]},
        ],
        search_document="Golden test guide. A short guide for planning. Open it, read it.",
        feature="gshc",
        workflow="",
        keywords=["golden", "Planning help"],
        source_paths=[],
        state="published",
        version=2,
        reviewer_name="",
        estimated_reading_minutes=3,
    )
    for n, role in enumerate(("Accountant", "CCEO")):
        HelpArticleRoleAccess.objects.create(id=f"{P}r{n}", article=guide, role=role)
    guide.related_articles.add(HelpArticle.objects.get(slug="getting-started"))
    HelpWalkthrough.objects.create(
        id=f"{P}w1",
        title="Find the guide",
        slug="gshc-walkthrough",
        article=guide,
        route_pattern="help",
        steps=["Open Help", "Choose Features"],
    )
    HelpGlossaryTerm.objects.create(
        id=f"{P}g1",
        term="Gshc term",
        slug="gshc-term",
        definition="A term for the golden test at 50% strength.",
        used_in="",
        article=guide,
    )


def table_rows(table, column="id"):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE {column}::text LIKE %s ORDER BY 1',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


def ask(paths, queries):
    os.environ["WEB_PATH"] = ",".join(paths)
    os.environ["WEB_QUERIES"] = json.dumps(queries, sort_keys=True)
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        return json.load(fh)


out_path = os.environ["GOLDEN_OUT"]
os.environ["WEB_READERS"] = ",".join(READERS)
before = set(HelpArticleRouteContext.objects.values_list("id", flat=True))
created = []
clear()
try:
    file_rows()
    sync_route_contexts()
    created = sorted(
        set(HelpArticleRouteContext.objects.values_list("id", flat=True)) - before
    )
    tables = {table: table_rows(table) for table in TABLES}
    tables["help_center_helparticle_related_articles"] = table_rows(
        "help_center_helparticle_related_articles", "from_helparticle_id"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM help_center_helparticleroutecontext t"
            " WHERE id = ANY(%s) ORDER BY id",
            [created],
        )
        routes = [json.loads(r[0]) for r in cursor.fetchall()]
    golden = ask(PAGES, [{}])
    for path, queries in SEARCHED.items():
        golden["answers"] += ask([path], queries)["answers"]
    golden["tables"] = tables
    golden["route_contexts"] = routes
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(golden, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"{len(golden['answers'])} answers, {len(routes)} route mappings")
finally:
    clear(created)
