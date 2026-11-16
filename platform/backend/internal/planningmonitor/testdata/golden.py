"""Write golden.json: a Programme Lead's Planning Monitor over schools their
officers hold, as the existing service figures it and as the dashboard's
feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/planningmonitor/testdata/golden.py

Only against a database whose name ends in "_test". The seed's officers hold
no school, so the monitor reads every figure as nothing. It files, every id
starting "gpm": schools an officer holds of every monitored type (Core,
Client, Core Trained) and one Champion, one outside any cluster, one held by
a second officer; staff visits (one Core school past its two, one delivered
and approved), a Partner's dated visit, a school booked by staff and a
Partner, a hand-over the Partner has not dated, an in-school training, a
group training a school is invited to, a confirmed SSA, and a school in an
open project. It writes every figure of the monitor (each person, each team,
the total, the readiness and the ledger) and the lead's dashboard as the
feed reads it, then deletes the rows. Dates sit around the day it was
written, so the comparison holds within half an hour.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.mobile_feed.views import read_page
from apps.partners.models import Partner, PartnerAssignment
from apps.planning import readiness
from apps.planning.planning_monitor import OfficerMonitor, planning_monitor
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
P = "gpm"
FY = "2027"
TODAY = dj_timezone.localdate()
LEAD = "pl1@edify.org"
TABLES = (
    "school",
    # Written by the school's own save (a signal), and so part of the world
    # the existing page reads.
    "school_cluster_assignment",
    "staff_school_assignment",
    "project",
    "activity",
    "cluster_activity_attendance",
    "partner_assignment",
    "ssa_record",
    "project_school_assignment",
)
#: Every figure of a person's year the monitor's tables and checks read.
FIGURES = sorted(
    name
    for name, attr in vars(OfficerMonitor).items()
    if isinstance(attr, property)
    and name not in ("gap_cells", "list_scope", "readiness")
    and not name.startswith("_")
) + [
    "key",
    "name",
    "role",
    "visits_target",
    "planned_core",
    "planned_client",
    "planned_done",
    "partner_assigned_schools",
    "partner_scheduled",
    "partner_delivered",
    "partner_awaiting",
    "project_ceiling",
    "project_added",
]


#: How each table's golden rows are found: by id, or (an attendance row is
#: numbered by the database) by the session it belongs to.
KEY = {
    "cluster_activity_attendance": "activity_id",
    "school_cluster_assignment": "school_id",
}


#: Rows a school's save writes that the monitor never reads: cleared with
#: the schools, not filed in the comparison.
SIDE_EFFECTS = ("data_quality_issue", "school_cluster_membership")


def clear():
    with connection.cursor() as cursor:
        for table in SIDE_EFFECTS:
            cursor.execute(f'DELETE FROM "{table}" WHERE school_id LIKE %s', [P + "%"])
        for table in reversed(TABLES):
            column = KEY.get(table, "id")
            cursor.execute(f'DELETE FROM "{table}" WHERE {column} LIKE %s', [P + "%"])


def file_rows():
    paul = StaffProfile.objects.get(user__email="cceo@edify.org")
    deo = StaffProfile.objects.get(user__email="cceo4@edify.org")
    cluster = Cluster.objects.filter(status="active").first()
    partner = Partner.objects.filter(deleted_at__isnull=True).first()

    def school(key, kind, holder=paul, clustered=True):
        return School.objects.create(
            id=P + key,
            school_id=f"GPM-{key}",
            name=f"Golden monitor school {key}",
            school_type=kind,
            district_id=cluster.district_id,
            region_id=cluster.region_id,
            cluster_id=cluster.id if clustered else None,
            account_owner_id=holder.id,
        )

    s1 = school("S1", "core")
    s2 = school("S2", "core")
    s3 = school("S3", "core")
    s4 = school("S4", "client")
    s5 = school("S5", "client")
    s6 = school("S6", "client")
    school("S7", "core_trained")
    school("S8", "champion")
    school("S9", "core", clustered=False)
    s10 = school("S10", "client", holder=deo)
    # A school in the lead's scope that nobody holds: the monitor's
    # Unassigned row, under a team of its own.
    unheld = School.objects.create(
        id=P + "S11",
        school_id="GPM-S11",
        name="Golden monitor school S11",
        school_type="client",
        district_id=cluster.district_id,
        region_id=cluster.region_id,
    )
    StaffSchoolAssignment.objects.create(id=P + "Z1", staff=paul, school_id=unheld.id)

    def activity(key, at, kind="school_visit", status="scheduled", days=5, **extra):
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status=status,
            delivery_type=extra.pop("delivery", "staff"),
            responsible_staff_id=extra.pop("owner", paul.id),
            planned_date=TODAY + timedelta(days=days),
            fy=FY,
            school=at,
            **extra,
        )

    # Staff visits: two at one Core school, three at another (past its two).
    activity("A1", s1)
    activity("A2", s1, days=6)
    activity("A3", s2)
    activity("A4", s2, days=7)
    activity("A5", s2, days=8)
    # A Client school booked by staff and dated by a Partner.
    activity("A6", s4)
    activity(
        "A7",
        s4,
        status="partner_scheduled",
        delivery="partner",
        owner=None,
        monitored_by_staff_id=paul.id,
        assigned_partner_id=partner.id,
        partner_date_set_by="partner",
    )
    # A Partner's dated visit at a Core school, and one delivered at a
    # Client school by staff and approved.
    activity(
        "A8",
        s1,
        status="partner_scheduled",
        delivery="partner",
        owner=None,
        monitored_by_staff_id=paul.id,
        assigned_partner_id=partner.id,
        partner_date_set_by="partner",
    )
    activity(
        "A9", s6, status="ia_verified", days=-10, salesforce_activity_id="SVE-GPM9"
    )
    # An in-school training at a Client school, and a visit by the second
    # officer at their own school.
    activity("A10", s6, kind="in_school_training", days=9)
    activity("A11", s10, owner=deo.id)
    # A group training the third Core school is invited to.
    Activity.objects.create(
        id=P + "G1",
        activity_type="cluster_training",
        status="scheduled",
        delivery_type="staff",
        responsible_staff_id=paul.id,
        planned_date=TODAY + timedelta(days=12),
        fy=FY,
        cluster=cluster,
    )
    ClusterActivityAttendance.objects.create(
        activity_id=P + "G1", school=s3, invited=True
    )
    # A hand-over the Partner has not dated. bulk_create skips the post_save
    # bookkeeping: its audit row is sealed into the hash chain the moment it
    # is written and outlives clear(), and the gateway hands a log reader on
    # over a hand-over it cannot read the school of.
    PartnerAssignment.objects.bulk_create(
        [
            PartnerAssignment(
                id=P + "H1",
                partner=partner,
                school=s5,
                status="assigned",
                assigning_staff_id=paul.id,
                monitoring_staff_id=paul.id,
            )
        ]
    )
    SsaRecord.objects.create(
        id=P + "R1",
        school=s4,
        date_of_ssa=dj_timezone.now() - timedelta(days=20),
        fy=FY,
        quarter="Q1",
        uploaded_by=paul.user_id,
        verification_status="confirmed",
        average_score=6.5,
    )
    project = Project.objects.create(
        id=P + "J1", name="Golden monitor project", category="general", status="active"
    )
    ProjectSchoolAssignment.objects.create(
        id=P + "J2", project=project, school=s6, assigned_staff_id=paul.id
    )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            column = KEY.get(table, "id")
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE {column} LIKE %s ORDER BY id',
                [P + "%"],
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def figures(row):
    """Every figure the row gives: a team sums its people's counts, and has
    no text figure (a role, a tone) of its own to give."""
    out = {}
    for name in FIGURES:
        try:
            out[name] = getattr(row, name)
        except (AttributeError, TypeError):
            continue
    return out


def school_figures(school):
    return {
        name: value for name, value in vars(school).items() if not name.startswith("_")
    } | {
        "state": readiness.school_state(school),
        "duplicate": readiness.is_duplicate(school),
        "core_missing_partner_half": readiness.core_missing_partner_half(school),
    }


def monitor_of(reader):
    monitor = planning_monitor(reader, fy=FY)
    total = readiness.for_monitor(monitor)
    return {
        "leads": [
            {
                "key": lead.key,
                "name": lead.name,
                "figures": figures(lead),
                "readiness": lead.readiness.as_dict(),
                "officers": [
                    {
                        "figures": figures(officer),
                        "readiness": officer.readiness.as_dict(),
                        "schools": [school_figures(s) for s in officer.schools],
                        "outreach": [
                            school_figures(s) for s in officer.outreach_schools
                        ],
                    }
                    for officer in lead.officers
                ],
            }
            for lead in monitor["leads"]
        ],
        "total": total.as_dict(),
        "ledger": readiness.ledger(monitor, FY, whole_country=False),
    }


clear()
try:
    file_rows()
    rows = dump_rows()
    reader = User.objects.get(email=LEAD)
    with transaction.atomic():
        monitor = monitor_of(reader)
        status, body = read_page(reader, "/dashboard", {})
        transaction.set_rollback(True)
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {
            "written": dj_timezone.now().isoformat(),
            "rows": rows,
            "monitor": monitor,
            "answers": [
                {
                    "email": LEAD,
                    "path": "/dashboard",
                    "query": {},
                    "status": status,
                    "body": body,
                }
            ],
        },
        out,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print("wrote the monitor and the dashboard")
