"""Write countrymap_golden.json: the Country Map (/country-map/) as the
existing feed reads it, over the development seed.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/countrymap_golden.json \\
    python manage.py shell < platform/backend/internal/oversightportfolio/testdata/countrymap_golden.py

Only against a database whose name ends in "_test". It files nothing: it asks
the page of the Country Director on each filter (a Programme Lead, a
district, each planning state, another year) and on the officer table's
second page, and of every reader the page opens for and refuses.
internal/integration/country_map_test.go compares Go's answers with these.
"""

import json
import os
from urllib.parse import parse_qsl, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("countrymap_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/country-map/"


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


def second_page(body):
    """The officer table's own page parameter, from its pager's "2"."""
    for block in body.get("blocks", []):
        for item in block.get("panel", {}).get("items", []):
            for link in item.get("links", {}).get("links", []):
                if link.get("text") == "2":
                    return dict(parse_qsl(urlsplit(link["href"]).query))
    return None


with connection.cursor() as cursor:
    cursor.execute(
        'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
        "WHERE u.email = 'pl1@edify.org'"
    )
    lead = cursor.fetchone()
    cursor.execute(
        "SELECT id FROM district WHERE sub_region_id IS NOT NULL ORDER BY name LIMIT 1"
    )
    district = cursor.fetchone()

director = User.objects.get(email="cd@edify.org")
answers = [ask(director, {})]
pager = second_page(answers[0]["body"])
director_asks = [
    {"planned": "unplanned"},
    {"planned": "planned"},
    {"fy": "2026"},
]
if lead:
    director_asks.append({"program_lead": lead[0]})
if district:
    director_asks.append({"district": district[0]})
if pager:
    director_asks.append(pager)
for query in director_asks:
    answers.append(ask(director, query))
for email in (
    "admin@edify.org",
    "ia@edify.org",
    "rvp@edify.org",
    "pl1@edify.org",
    "cceo1@edify.org",
    "accountant@edify.org",
    "partner@edify.org",
):
    reader = User.objects.filter(email=email).first()
    if reader:
        answers.append(ask(reader, {}))

with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"rows": {}, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
