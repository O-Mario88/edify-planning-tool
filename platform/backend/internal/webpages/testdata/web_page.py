"""What the existing application's page shows, read as the app's feed reads
pages, for a page the feed does not open (a web-only page).

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    WEB_PATH=/districts/<id>,/districts/<other> WEB_READERS=cd@edify.org,pl1@edify.org \\
    WEB_QUERIES='[{}, {"fy": "2026"}]' GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/webpages/testdata/web_page.py

It runs the page's own view, unmodified, for each reader, exactly as the
feed runs one of its pages (apps.mobile_feed.views._run_page, which also
asks can_open_url), and reads the HTML with the feed's own reader
(page_body). Nothing is written: each answer runs in a transaction rolled
back.
"""

import json
import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import resolve
from django.utils import timezone

from apps.mobile_feed.views import _run_page, page_body

paths = os.environ["WEB_PATH"].split(",")
queries = json.loads(os.environ.get("WEB_QUERIES") or "[{}]")
answers = []
for path, email, query in (
    (path, email, query)
    for path in paths
    for email in os.environ["WEB_READERS"].split(",")
    for query in queries
):
    name = frozenset({resolve(path).url_name})
    user = get_user_model().objects.filter(email=email.strip()).first()
    if user is None:
        continue
    with transaction.atomic():
        response = _run_page(user, path, query, name)
        transaction.set_rollback(True)
    if response is None:
        answers.append({"email": email, "path": path, "query": query, "status": 404})
        continue
    if response.status_code != 200:
        answers.append(
            {
                "email": email,
                "path": path,
                "query": query,
                "status": response.status_code,
            }
        )
        continue
    body = page_body(response.content.decode(), path)
    answers.append(
        {"email": email, "path": path, "query": query, "status": 200, "body": body}
    )
with open(os.environ["GOLDEN_OUT"], "w") as out:
    json.dump(
        {"written": timezone.now().isoformat(), "answers": answers},
        out,
        indent=1,
        default=str,
    )
print(f"wrote {len(answers)} answers")
