"""Write the Schedule form's golden: /planning/schedule
(planning_views.schedule_activity_form_view, pages/planning/schedule.html)
as the existing feed reads it, for each choice the form takes.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/fieldpages/testdata/schedule_golden.py

Only against a database whose name ends in "_test". It files nothing. It
asks each reader the bare form; a training and a meeting, each with a
cluster the first officer plans in and one they do not; an action that is
none of the three; and a visit for a school with no
confirmed SSA, one with one (by id and by School ID), and one nobody holds.
A school with a confirmed SSA carries the SSA's recommended focus areas,
which Go hands on: those answers are written as handed on (302), with no
body. The scope-profiles test compares the rest.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.core.scoping import (
    cluster_queryset,
    direct_portfolio_schools,
    resolve_user_scope,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("schedule_golden.py runs only against a _test database")

User = get_user_model()
PAGE = "/planning/schedule"
READERS = (
    "cceo1@edify.org",
    "pl1@edify.org",
    "admin@edify.org",
    "coordinator@edify.org",
    "cd@edify.org",
    "partner@edify.org",
)


def queries() -> list[dict]:
    from apps.clusters.models import Cluster
    from apps.schools.models import School

    admin = User.objects.get(email="admin@edify.org")
    officer = User.objects.get(email="cceo1@edify.org")
    portfolio = direct_portfolio_schools(resolve_user_scope(admin))
    confirmed = portfolio.filter(
        ssa_records__deleted_at__isnull=True,
        ssa_records__verification_status="confirmed",
    )
    plain = portfolio.exclude(id__in=confirmed.values("id")).first()
    with_ssa = confirmed.first()
    own = cluster_queryset(resolve_user_scope(officer), direct_only=True).first()
    other = (
        Cluster.objects.filter(deleted_at__isnull=True)
        .exclude(id=getattr(own, "id", ""))
        .first()
    )
    unheld = School.objects.exclude(id__in=portfolio.values("id")).first()
    out = [
        {},
        {"action": "training"},
        {"action": "meeting"},
        # An empty action (Django: a meeting) is not asked: the gateway drops
        # empty query values, so it reaches Go as no action at all.
        {"action": "workshop"},
        {"action": "visit"},
    ]
    for cluster in (own, other):
        if cluster:
            out += [
                {"action": "training", "cluster": cluster.id},
                {"action": "meeting", "cluster": cluster.id},
                {"cluster": cluster.id},
            ]
    for school in (plain, with_ssa, unheld):
        if school:
            out.append({"school": school.id})
            if school.school_id:
                out.append({"school": school.school_id})
    return out


def handed_on(email: str, query: dict) -> bool:
    """Whether the form names a chosen school with a confirmed SSA."""
    from django.db.models import Q

    key = query.get("school")
    if not key or query.get("action", "visit") != "visit":
        return False
    user = User.objects.get(email=email)
    school = (
        direct_portfolio_schools(resolve_user_scope(user))
        .filter(Q(id=key) | Q(school_id=key))
        .first()
    )
    return bool(
        school
        and school.ssa_records.filter(
            deleted_at__isnull=True, verification_status="confirmed"
        ).exists()
    )


asked = queries()
os.environ["WEB_PATH"] = PAGE
os.environ["WEB_READERS"] = ",".join(READERS)
os.environ["WEB_QUERIES"] = json.dumps(asked)
oracle = os.path.join(
    settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
)
with open(oracle, encoding="utf-8") as fh:
    exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102
with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
    out = json.load(fh)
marked = 0
for answer in out["answers"]:
    if answer["status"] == 200 and handed_on(answer["email"], answer["query"]):
        answer["status"] = 302
        answer.pop("body", None)
        marked += 1
with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, sort_keys=True)
print(f"{len(asked)} queries, {marked} handed on")
