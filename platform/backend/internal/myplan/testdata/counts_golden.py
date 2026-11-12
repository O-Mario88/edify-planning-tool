"""What the existing My Plan counts, for internal/myplan's counts_golden_test.go.

Run from the repository root against the development database:

    ACCOUNTS=cceo@edify.org,admin@edify.org OUT=/tmp/golden.json \\
        python manage.py shell < platform/backend/internal/myplan/testdata/counts_golden.py

For each account and each query it asks apps.my_plan.services.get_frontend_context
itself (the query in the view's shape, without the readiness panel) and writes
what the strip and the breakdown show, the past-due count, whether the tables
list anything, and the account's two ids. It reads only.
"""

import json
import os
import re

from django.contrib.auth import get_user_model

from apps.geography.models import District
from apps.my_plan.services import get_frontend_context

KEYS = (
    "fy",
    "quarter",
    "month",
    "week",
    "fy_prev",
    "quarter_prev",
    "district",
    "staff",
    "activity_type",
    "status",
    "period",
    "q",
)
TABLES = (
    "school_visits",
    "cluster_trainings",
    "group_trainings",
    "cluster_meetings",
    "core_school_visits",
    "core_school_trainings",
    "programme_activities",
)
COUNTED = re.compile(r": ([\d,]+) at Core schools, ([\d,]+) at Client")


def queries(user) -> list[dict]:
    mukono = District.objects.filter(name="Mukono").values_list("id", flat=True).first()
    staff = getattr(user, "staff_profile_id", None) or user.id
    out = [
        {},
        {"period": "week"},
        {"period": "month"},
        {"period": "quarter"},
        {"period": "xyz"},
        {"fy": "2026"},
        {"fy": "2028"},
        {"fy": " 2027 "},
        {"quarter": "Q1"},
        {"quarter": "Q2"},
        {"quarter": "q1"},
        {"month": "10"},
        {"month": "11"},
        {"month": "12"},
        {"month": "1"},
        {"week": "1"},
        {"week": "4"},
        {"period": "week", "week": "4"},
        {"period": "week", "week": "3", "month": "11"},
        {"period": "quarter", "quarter": "Q1"},
        {"period": "quarter", "quarter": "Q2"},
        {"q": "kimenyedde"},
        {"q": "Cluster E"},
        {"q": "mukono"},
        {"q": "parity"},
        {"q": "%"},
        {"q": "_"},
        {"q": "zzz"},
        {"q": " Primary "},
        {"district": mukono or "nope"},
        {"district": "nope"},
        {"staff": staff},
        {"staff": "nope"},
        {"fy": "2027", "fy_prev": "2026", "quarter": "Q2", "month": "1"},
        {"quarter": "Q2", "quarter_prev": "Q1", "month": "2"},
        {"status": "completed", "period": "month", "month": "10"},
    ]
    out += [
        {"status": s}
        for s in (
            "scheduled",
            "upcoming",
            "under_way",
            "overdue",
            "completed",
            "submitted",
            "returned_for_correction",
            "returned",
            "cancelled",
            "closed",
            "xyz",
            "all",
        )
    ]
    out += [
        {"activity_type": t}
        for t in (
            "school_visit",
            "in_school_support",
            "cluster_training",
            "cluster_meeting",
            "core_visit",
            "donor_visit",
        )
    ]
    return out


answers = []
for email in os.environ["ACCOUNTS"].split(","):
    user = get_user_model().objects.get(email=email)
    for asked in queries(user):
        query = {key: asked.get(key) for key in KEYS}
        query["q"] = (asked.get("q") or "").strip()
        context = get_frontend_context(user, query, with_readiness=False)
        strip = context["kpi_strip_items"]
        counted = COUNTED.search(strip[4].get("helper_exact") or "")
        answers.append(
            {
                "email": email,
                "ids": [user.id, getattr(user, "staff_profile_id", None) or ""],
                "query": {k: v for k, v in asked.items() if v is not None},
                "strip": [str(item["display_value"]) for item in strip],
                "core": int(counted.group(1).replace(",", "")) if counted else None,
                "client": int(counted.group(2).replace(",", "")) if counted else None,
                "breakdown": [
                    context["breakdown"][k] for k in ("week", "month", "quarter", "fy")
                ],
                "past_due": context["past_due_count"],
                "listed": any(context[t] for t in TABLES)
                or any(group["rows"] for group in context["programme_school_work"])
                or bool(
                    context["returned_needs_correction"] or context["day_off_work"]
                ),
            }
        )
json.dump(answers, open(os.environ["OUT"], "w"), indent=1)
print(len(answers), "answers")
