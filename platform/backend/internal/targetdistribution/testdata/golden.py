"""Write golden.json: Uganda Target Distribution (/target-distribution) as the
existing feed reads it, for every reader the page opens to and one it does
not.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/targetdistribution/testdata/golden.py

Only against a database whose name ends in "_test". Everything below happens
in one transaction that is rolled back, so nothing it files outlives it. It
files: a draft cycle for the year after the seed's; an archived cycle the
year after that holding one country priority with no milestones; a staged
priority import for a year without a cycle (which Go hands on to a reader who
may import); and two years with the Uganda master imported by the canonical
seeding (apps.hr.uganda_master_seeding) — one left in draft for the Country
Director's confirmation, the other confirmed and published by the Country
Director and distributed by IA through the page's own action: one milestone
distributed and approved, one balanced and awaiting approval, one part
allocated. The published year also holds planned and completed visits that
match a milestone's rule, for the plan's progress.

It asks the page with no year and for each of those years and the seed's own,
writes the rows the page reads (found as the rows the transaction added) and
the answers to GOLDEN_OUT.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone as dj_timezone

from apps.activities.models import Activity
from apps.hr.models import (
    MilestoneActivityRule,
    PriorityImportBatch,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
)
from apps.hr.target_distribution import (
    confirm_milestone,
    country_distribution_workspace,
    program_lead_teams,
    publish_uganda_master,
)
from apps.hr.uganda_master_seeding import seed_uganda_master
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/target-distribution"
P = "gtd"
SEED = StrategicPriorityCycle.objects.order_by("-financial_year").first()
BASE = int(SEED.financial_year) if SEED else int(dj_timezone.localdate().year) + 1
DRAFT, MASTER, STAGED = str(BASE + 1), str(BASE + 2), str(BASE - 1)
#: The Uganda master in draft, and the one published and distributed.
DRAFT_MASTER, PUBLISHED = str(BASE + 3), str(BASE + 4)
#: The tables the page reads that the transaction adds rows to, parents
#: first; the activities are the plan's.
TABLES = (
    "hr_strategic_priority_cycle",
    "hr_milestone_metric_definition",
    "hr_strategic_priority",
    "hr_priority_milestone",
    "hr_milestone_target_component",
    "hr_milestone_activity_rule",
    "hr_milestone_allocation",
    "hr_milestone_period_target",
    "hr_priority_import_batch",
    "activity",
)
READERS = ["ia@edify.org", "cd@edify.org", "admin@edify.org", "cceo@edify.org"]
IMPORTERS = ("ia@edify.org", "admin@edify.org")


def ids():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'SELECT id::text FROM "{table}"')  # noqa: S608  # nosec B608
            out[table] = {r[0] for r in cursor.fetchall()}
    return out


def file_empty_years():
    StrategicPriorityCycle.objects.bulk_create(
        [
            StrategicPriorityCycle(
                id=P + "C1", financial_year=DRAFT, title="Draft cycle", status="draft"
            ),
            StrategicPriorityCycle(
                id=P + "C2",
                financial_year=MASTER,
                title="Archived cycle",
                status="archived",
            ),
        ]
    )
    StrategicPriority.objects.bulk_create(
        [
            StrategicPriority(
                id=P + "S1",
                fy=MASTER,
                level="country",
                country_id="Uganda",
                cycle_id=P + "C2",
                title="A country priority",
                sequence=1,
            )
        ]
    )
    PriorityImportBatch.objects.bulk_create(
        [
            PriorityImportBatch(
                id=P + "B1",
                fy=STAGED,
                country_id="Uganda",
                original_file_name="priorities.csv",
                file_sha256="0" * 64,
                uploaded_by=User.objects.get(email="ia@edify.org").id,
            )
        ]
    )


def file_masters():
    for fy, cid in ((DRAFT_MASTER, P + "C3"), (PUBLISHED, P + "C4")):
        StrategicPriorityCycle.objects.create(
            id=cid, financial_year=fy, title=f"Golden FY{fy}", status="draft"
        )
        seed_uganda_master(fy=fy, actor_id="golden")
    director = User.objects.get(email="cd@edify.org")
    director.active_role = "CountryDirector"
    for milestone in PriorityMilestone.objects.filter(
        priority__fy=PUBLISHED, needs_confirmation=True
    ):
        data = (
            {}
            if milestone.target_value is not None
            else {"allocationMethod": "non_scoreable"}
        )
        confirm_milestone(milestone, data=data, principal=director)
    publish_uganda_master(PUBLISHED, principal=director)

    leads = [team["staff"].id for team in program_lead_teams()]
    client = Client()
    client.force_login(User.objects.get(email="ia@edify.org"))
    field = [
        row["milestone"]
        for group in country_distribution_workspace(PUBLISHED)["groups"]
        for row in group["milestones"]
        if row["milestone"].allocation_method == "field_cascade"
        and row["milestone"].measurement_type == "count"
    ]

    def split(total):
        shares = [total // len(leads)] * len(leads)
        shares[0] += total - sum(shares)
        return shares

    def post(action, milestone, shares):
        data = {"action": action, "fy": PUBLISHED, "milestone": milestone.id}
        for lead, share in zip(leads, shares):
            data[f"target__{lead}"] = str(share)
        response = client.post("/target-distribution/action", data)
        if response.status_code != 302:
            raise SystemExit(f"{action} answered {response.status_code}")

    post(
        "save_and_approve_team_distribution",
        field[0],
        split(int(field[0].target_value)),
    )
    post("save_team_allocations", field[1], split(int(field[1].target_value)))
    post(
        "save_team_allocations",
        field[2],
        [int(field[2].target_value) // (2 * len(leads))] + [0] * (len(leads) - 1),
    )

    # The plan: visits matching the first distributed milestone's rule.
    rule = MilestoneActivityRule.objects.filter(milestone=field[0], active=True).first()
    officer = User.objects.get(email="cceo@edify.org").staff_profile
    start = date(int(PUBLISHED) - 1, 10, 1)
    schools = list(
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(school=None)
        .values_list("school_id", flat=True)
        .distinct()[:3]
    )
    for n, (status, school) in enumerate(
        [
            ("scheduled", schools[0]),
            ("completed", schools[1]),
            ("scheduled", schools[2]),
        ],
        start=1,
    ):
        Activity.objects.create(
            id=f"{P}A{n}",
            activity_type="school_visit",
            status=status,
            delivery_type=rule.required_executor_type or "staff",
            responsible_staff_id=officer.id,
            planned_date=start + timedelta(days=10 * n),
            fy=PUBLISHED,
            school_id=school,
            catalogue_item_id=rule.catalogue_item_id,
            project_id=rule.project_id,
            focus_intervention=rule.target_intervention or None,
        )


def dump_rows(before):
    """The rows the transaction added, in the order they are stored: the
    activity rules carry no order of their own, so the page lists a
    milestone's activities in the order its database returns them, and the
    Go test files the rows back in this order to store them alike."""
    after = ids()
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            added = sorted(after[table] - before[table])
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id::text = ANY(%s) ORDER BY ctid',  # noqa: S608  # nosec B608
                [added],
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUERIES = [
    {},
    {"fy": DRAFT},
    {"fy": STAGED},
    {"fy": str(BASE)},
    {"fy": MASTER},
    {"fy": DRAFT_MASTER},
    {"fy": PUBLISHED},
    {"fy": PUBLISHED, "page": "2"},
    {"fy": DRAFT_MASTER, "page": "2"},
]
#: The master table's own views, asked by IA alone: each tab, the filters
#: and their chips, a search, a filter nothing matches.
FILTERED = [
    {"fy": PUBLISHED, "tab": "field_cascade"},
    {"fy": PUBLISHED, "tab": "non_scoreable"},
    {"fy": PUBLISHED, "tab": "specialist"},
    {"fy": PUBLISHED, "status": "balance_open"},
    {"fy": PUBLISHED, "priority": "PROGRAM_QUALITY", "portfolio": "core"},
    {"fy": PUBLISHED, "portfolio": "client"},
    {"fy": PUBLISHED, "q": "school visits"},
    {"fy": PUBLISHED, "status": "needs_confirmation"},
    {"fy": DRAFT_MASTER, "status": "needs_confirmation"},
]

with transaction.atomic():
    before = ids()
    file_empty_years()
    file_masters()
    rows = dump_rows(before)
    answers = []
    asked = [(email, query) for email in READERS for query in QUERIES] + [
        ("ia@edify.org", query) for query in FILTERED
    ]
    for email, query in asked:
        reader = User.objects.get(email=email)
        at = dj_timezone.now().isoformat()
        with transaction.atomic():
            status, body = read_page(reader, PATH, query)
            transaction.set_rollback(True)
        answers.append(
            {
                "email": email,
                "path": PATH,
                "query": query,
                "at": at,
                "status": status,
                "body": body,
                # Staged imports, for a reader who may see them.
                "hand_on": status == 200
                and query.get("fy") == STAGED
                and email in IMPORTERS,
            }
        )
    transaction.set_rollback(True)

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        out,
        default=str,
    )
print(
    f"wrote {len(answers)} answers, "
    + ", ".join(f"{t} {len(r)}" for t, r in rows.items())
)
