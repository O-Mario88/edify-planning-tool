"""What the existing application's page shows, read as the app's feed reads
pages, for a page the feed does not open (a web-only page).

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    WEB_PATH=/districts/<id>,/districts/<other> WEB_READERS=cd@edify.org,pl1@edify.org \\
    WEB_QUERIES='[{}, {"fy": "2026"}]' GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/webpages/testdata/web_page.py

It runs the page's own view, unmodified, for each reader, exactly as the
feed runs one of its pages (apps.mobile_feed.views._run_page, which also
asks can_open_url), and reads the HTML with the feed's own reader
(page_body), following the parts the page loads after it opens as the feed
does (read_page's `later`). Nothing is written: each answer runs in a transaction rolled
back.
"""

import json
import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import Resolver404, resolve
from django.utils import timezone

from apps.mobile_feed.views import (
    LATER_PARTS,
    NATIVE_PAGES,
    _page_params,
    _run_page,
    page_body,
)


def later_for(user):
    """read_page's `later`: a part the page loads after it opens, run through
    the page's own view."""
    from urllib.parse import parse_qsl, urlparse

    from django.http import Http404

    def later(part_path, headers):
        url = urlparse(part_path)
        try:
            part = _run_page(
                user,
                url.path,
                _page_params(dict(parse_qsl(url.query))),
                LATER_PARTS | NATIVE_PAGES,
                headers,
            )
        except Http404:
            return None
        if part is None or part.status_code != 200:
            return None
        return part.content.decode()

    return later


paths = os.environ["WEB_PATH"].split(",")
queries = json.loads(os.environ.get("WEB_QUERIES") or "[{}]")
answers = []
for path, email, query in (
    (path, email, query)
    for path in paths
    for email in os.environ["WEB_READERS"].split(",")
    for query in queries
):
    try:
        name = frozenset({resolve(path).url_name})
    except Resolver404:
        answers.append({"email": email, "path": path, "query": query, "status": 404})
        continue
    user = get_user_model().objects.filter(email=email.strip()).first()
    if user is None:
        continue
    with transaction.atomic():
        response = _run_page(user, path, query, name)
        body = None
        if response is not None and response.status_code == 200:
            # The parts the page loads after it opens are read as the feed
            # reads them (read_page's own `later`), in the same rolled-back
            # transaction.
            body = page_body(response.content.decode(), path, later_for(user))
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
