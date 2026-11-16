"""Write golden.json: User Management (/admin-panel/users) as the existing feed
reads it, over the development seed.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/adminusers/testdata/golden.py

Only against a database whose name ends in "_test". It files nothing: it asks
the page of the Admin on each table page, with a search, each role and status
filter, and of the readers it refuses.
internal/integration/admin_users_test.go compares Go's answers with these.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/admin-panel/users"


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


admin = User.objects.get(email="admin@edify.org")
answers = []
for query in (
    {},
    {"page": "2"},
    {"page": "3"},
    {"page": "99"},
    {"q": "cceo1"},
    {"q": "program lead"},
    {"q": "nobody matches this"},
    {"role": "CCEO"},
    {"role": "Program Lead", "status": "active"},
    {"status": "inactive"},
    {"role": "PartnerAdmin"},
):
    answers.append(ask(admin, query))
for email in ("cd@edify.org", "ia@edify.org", "cceo1@edify.org", "pl1@edify.org"):
    answers.append(ask(User.objects.get(email=email), {}))

with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"rows": {}, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
