"""Write partners_golden.json: Partner Activities (/partners) as the existing
application answers it over partner work the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/partners_golden.json \\
    python manage.py shell < platform/backend/internal/partnerworkspace/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpw", two organisations (one with contacts, regions, several
interventions and catalogue activities; a Loan Partner with one region and
one intervention; a third deleted) and their work this year: visits ahead,
overdue, completed, undated, dated only by time (late in the evening, so
Kampala's day is the next), a cluster session, last year's and a cancelled
one; hand-overs undated, dated the same day as a visit (one row, not two),
overdue, released and for a cluster; and a visit for the Partner Admin's own
organisation. It asks the app's feed as HR (every filter), the Business
Transformation Officer, the Project Coordinator, the two MFI logins, both
partner logins, and two staff who are sent on to Partner Oversight; writes the
rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/partners_test.go files the same rows and compares.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.mobile_feed.views import read_page
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/partners"
#: Children first.
TABLES = ("partner_assignment", "activity", "partner")
DEMO_PARTNER = "cmw9p8dd5006j6eekheld"


def clear():
    PartnerAssignment.objects.filter(id__startswith="gpw").delete()
    Activity.all_objects.filter(id__startswith="gpw").delete()
    Partner.all_objects.filter(id__startswith="gpw").delete()


def file_rows():
    today = dj_timezone.localdate()
    fy = get_operational_fy()
    schools = list(
        School.objects.filter(deleted_at__isnull=True)
        .exclude(school_id="")
        .order_by("id")[:7]
    )
    cluster = Cluster.objects.filter(deleted_at__isnull=True).order_by("id").first()
    one = Partner.objects.create(
        id="gpwp1",
        name="Golden Partner One",
        region_names=["Central Region", "Eastern Region"],
        contact_person="Jane Golden",
        phone="0700 111 222",
        ssa_intervention="leadership",
        ssa_interventions=["leadership", "group:any", "made_up_focus"],
        activity_codes=["gpw-code-1", "gpw-code-2"],
    )
    lender = Partner.objects.create(
        id="gpwp2",
        name="Golden Lender",
        partner_role="loan",
        region_name="Northern Region",
        ssa_intervention="financial_health",
        activity_codes=["gpw-code-3"],
    )
    Partner.objects.create(id="gpwp3", name="Golden Gone", deleted_at=dj_timezone.now())

    def visit(key, partner, school=None, **fields):
        defaults = dict(
            id=f"gpwa{key}",
            fy=fy,
            status="scheduled",
            delivery_type="partner",
            activity_type="school_visit",
            assigned_partner_id=partner.id,
            school=school,
        )
        defaults.update(fields)
        return Activity.objects.create(**defaults)

    late = dj_timezone.make_aware(
        datetime.combine(today + timedelta(days=2), time(22, 30)),
        dj_timezone.get_fixed_timezone(0),
    )
    visit(
        1,
        one,
        schools[0],
        planned_date=today + timedelta(days=5),
        focus_intervention="leadership",
        est_cost_cents=150000,
    )
    visit(2, one, schools[1], planned_date=today - timedelta(days=3), cost_missing=True)
    visit(
        3,
        one,
        schools[2],
        planned_date=today - timedelta(days=10),
        status="completed",
        est_cost_cents=2500000,
        purpose_type="ssa_support",
    )
    visit(4, one, schools[3], status="planned")
    visit(5, one, schools[4], scheduled_date=late, est_cost_cents=99999)
    visit(
        6,
        one,
        None,
        cluster=cluster,
        activity_type="cluster_training",
        planned_date=today + timedelta(days=1),
        est_cost_cents=500,
    )
    visit(
        7,
        one,
        schools[5],
        fy=str(int(fy) - 1),
        planned_date=today - timedelta(days=200),
    )
    visit(
        8, one, schools[5], status="cancelled", planned_date=today + timedelta(days=3)
    )
    visit(
        9,
        lender,
        schools[6],
        planned_date=today + timedelta(days=20),
        focus_intervention="made_up",
        est_cost_cents=1000000,
    )
    visit(
        10,
        Partner.objects.get(id=DEMO_PARTNER),
        schools[6],
        planned_date=today + timedelta(days=7),
        est_cost_cents=42000,
    )

    def handover(key, partner, school=None, **fields):
        defaults = dict(
            id=f"gpws{key}", partner=partner, school=school, status="pending_scheduling"
        )
        defaults.update(fields)
        return PartnerAssignment.objects.create(**defaults)

    handover(
        1,
        one,
        schools[5],
        expected_activity_type="school_visit",
        focus_intervention="financial_health",
    )
    handover(
        2,
        one,
        schools[0],
        status="partner_scheduled",
        expected_activity_type="school_visit",
        scheduled_date=today + timedelta(days=5),
    )
    handover(
        3,
        one,
        schools[1],
        status="assigned",
        scheduled_date=today - timedelta(days=4),
        purpose_of_visit="social_visit",
    )
    handover(4, one, schools[2], status="returned_to_staff")
    handover(5, one, None, cluster=cluster, expected_activity_type="cluster_meeting")
    handover(
        6,
        lender,
        schools[3],
        scheduled_date=today + timedelta(days=9),
        expected_activity_type="in_school_training",
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpw%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def questions():
    fy = get_operational_fy()
    central = (
        School.objects.filter(id__startswith="cmw")
        .values_list("region_id", flat=True)
        .first()
    )
    return {
        "hr@edify.org": [
            {},
            {"status": "scheduled"},
            {"status": "yet_to_schedule"},
            {"status": "overdue"},
            {"status": "bogus"},
            {"partner": "gpwp1"},
            {"partner": "nobody"},
            {"fy": str(int(fy) - 1)},
            {"fy": "1999"},
            {"region": central or ""},
        ],
        "business-transformation@edify.org": [{}],
        "coordinator@edify.org": [{}],
        "mfi-admin@edify.org": [{}],
        "mfi-officer@edify.org": [{}],
        "partner-admin@edify.org": [{}, {"partner": "gpwp1"}],
        "partner@edify.org": [{}],
        "cd@edify.org": [{"fy": fy, "partner": "gpwp1", "status": "overdue"}],
        "cceo1@edify.org": [{}],
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in questions().items():
            user = User.objects.get(email=email)
            for query in asked:
                status, body = read_page(user, PATH, query)
                answers.append(
                    {
                        "email": email,
                        "path": PATH,
                        "query": query,
                        "status": status,
                        "body": body,
                    }
                )
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
