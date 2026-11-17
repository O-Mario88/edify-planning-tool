"""Write golden.json: Uganda Priorities (/priorities/master) as the existing
feed reads it, for every reader the page opens to and one it refuses.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/prioritiesmaster/testdata/golden.py

Only against a database whose name ends in "_test". Everything below happens
in one transaction that is rolled back, so nothing it files outlives it. It
imports the Uganda master by the canonical seeding
(apps.hr.uganda_master_seeding) for two years after the seed's: one left in
draft, the other confirmed and published by the Country Director and
distributed by IA to the Programme Leads through the page's own action (one
milestone approved, one awaiting approval); the first Programme Lead then
distributes the approved team target within the team, keeping a share,
through the team page's own action, and approves the distribution of a
second. The published year also holds planned and completed visits that
match a milestone's rule, for the plan's progress.

It asks the page with no year, for each master year and for the seed's own
year (no master), as every kind of reader (the Programme Lead, a CCEO of the
team and one outside it, the RVP, the Regional Programme Lead, HR, the
Project Coordinator, the roles the page sends to Target Distribution, and the
Accountant it refuses), and writes the rows the page reads (found as the rows
the transaction added, in the order they are stored) and the answers to
GOLDEN_OUT.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import Client
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.hr.models import (
    MilestoneActivityRule,
    MilestoneAllocation,
    PriorityMilestone,
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
PATH = "/priorities/master"
P = "gpm"
SEED = StrategicPriorityCycle.objects.order_by("-financial_year").first()
BASE = int(SEED.financial_year) if SEED else int(dj_timezone.localdate().year) + 1
DRAFT_MASTER, PUBLISHED = str(BASE + 1), str(BASE + 2)
TABLES = (
    "hr_strategic_priority_cycle",
    "hr_milestone_metric_definition",
    "hr_strategic_priority",
    "hr_priority_milestone",
    "hr_milestone_target_component",
    "hr_milestone_activity_rule",
    "hr_milestone_allocation",
    "hr_milestone_period_target",
    "activity",
)


def ids():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'SELECT id::text FROM "{table}"')  # noqa: S608  # nosec B608
            out[table] = {r[0] for r in cursor.fetchall()}
    return out


def post(client, path, data):
    response = client.post(path, data)
    if response.status_code != 302:
        raise SystemExit(f"{data['action']} answered {response.status_code}")


def file_masters():
    """The two masters, the IA distribution, and the first team's own."""
    for fy, cid in ((DRAFT_MASTER, P + "C1"), (PUBLISHED, P + "C2")):
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

    teams = program_lead_teams()
    leads = [team["staff"].id for team in teams]
    ia = Client()
    ia.force_login(User.objects.get(email="ia@edify.org"))
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

    for action, milestone in (
        ("save_and_approve_team_distribution", field[0]),
        ("save_and_approve_team_distribution", field[1]),
        ("save_team_allocations", field[2]),
    ):
        data = {"action": action, "fy": PUBLISHED, "milestone": milestone.id}
        for lead, share in zip(leads, split(int(milestone.target_value))):
            data[f"target__{lead}"] = str(share)
        post(ia, "/target-distribution/action", data)

    # The first Programme Lead keeps a share of two team targets and gives
    # the first member the rest: a draft distribution, then an approved one.
    lead = teams[0]["staff"]
    member = teams[0]["cceo_staff_ids"][0]
    team_client = Client()
    team_client.force_login(lead.user)
    for action, milestone in (
        ("save_member_allocations", field[0]),
        ("save_and_approve_member_distribution", field[1]),
    ):
        team = MilestoneAllocation.objects.get(
            milestone=milestone, team_id=lead.id, allocated_to_type="team"
        )
        kept = int(team.allocated_target) // 5
        post(
            team_client,
            "/target-distribution/team/action",
            {
                "action": action,
                "fy": PUBLISHED,
                "allocation": team.id,
                f"target__{lead.id}": str(kept),
                f"target__{member}": str(int(team.allocated_target) - kept),
            },
        )

    rule = MilestoneActivityRule.objects.filter(milestone=field[0], active=True).first()
    officer = StaffProfile.objects.get(id=member)
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
    return lead.user.email, officer.user.email


def dump_rows(before):
    """The rows the transaction added, in the order they are stored (the
    activity rules carry no order of their own)."""
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


QUERIES = [{}, {"fy": PUBLISHED}, {"fy": DRAFT_MASTER}, {"fy": str(BASE)}]

with transaction.atomic():
    before = ids()
    lead_email, member_email = file_masters()
    rows = dump_rows(before)
    readers = [
        lead_email,
        member_email,
        "cceo8@edify.org",
        "rvp@edify.org",
        "regional-lead@edify.org",
        "hr@edify.org",
        "coordinator@edify.org",
        "ia@edify.org",
        "cd@edify.org",
        "admin@edify.org",
        "accountant@edify.org",
    ]
    answers = []
    for email in readers:
        reader = User.objects.get(email=email)
        for query in QUERIES:
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
