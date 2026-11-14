"""What the existing feed shows of My Plan's Trainings and Group Trainings
tables (the cluster invited-school expansion), for internal/myplan's
plan_tables_golden_test.go (the same test reads this file's answers).

Run from the repository root against an agent's copy of the TEST database,
never the development one (it writes records there, every id starting
"g57"):

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_aNN_test MODE=make \\
        OUT=/tmp/trainings.json python manage.py shell < .../trainings_golden.py
    (run the Go test with EDIFY_MYPLAN_TABLES_GOLDEN=/tmp/trainings.json)
    DATABASE_URL=postgresql://localhost:5432/edify_gorn_aNN_test MODE=remove \\
        python manage.py shell < .../trainings_golden.py

MODE=make files synthetic people, clusters, schools of every type and
standing, trainings of every kind at a cluster, a school or nowhere, the
invitations and attendance of the sessions (named, recorded with nobody
invited, never recorded), head counts and meal snapshots, from a seeded
random source, then asks the feed itself (apps.mobile_feed.views.read_page,
unmodified) for /my-plan as each person, for many queries, and writes each
answer. MODE=remove deletes every record it filed.
"""

import json
import os
import random
import re
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget.models import ActivityCostSnapshot
from apps.clusters.models import Cluster
from apps.geography.models import District
from apps.mobile_feed.views import read_page
from apps.schools.models import School

# An agent's own copy of the test database (edify_gorn_aNN_test).
if not re.fullmatch(r"edify_gorn(_a\d+)?_test", connection.settings_dict["NAME"]):
    raise SystemExit("trainings_golden.py writes records: the test database only")

P = "g57"


def remove():
    with transaction.atomic():
        ClusterActivityAttendance.objects.filter(activity__id__startswith=P).delete()
        ActivityCostSnapshot.objects.filter(id__startswith=P).delete()
        Activity.all_objects.filter(id__startswith=P).delete()
        School.all_objects.filter(id__startswith=P).delete()
        Cluster.all_objects.filter(id__startswith=P).delete()
        StaffProfile.all_objects.filter(id__startswith=P).delete()
        User.objects.filter(id__startswith=P).delete()
        District.objects.filter(id__startswith=P).delete()
    print("removed")


TYPES = (
    "cluster_training",
    "cluster_training",
    "cluster_training",
    "in_school_training",
    "school_improvement_training",
    "training",
)
STATUSES = (
    "completed",
    "closed",
    "ia_verified",
    "in_progress",
    "scheduled",
    "scheduled",
    "planned",
    "rescheduled",
    "cancelled",
    "deferred",
    "awaiting_owner_approval",
    "submitted_to_pl",
    "returned_by_pl",
)
QUERIES = [
    {},
    {"fy": "2026"},
    {"period": "quarter"},
    {"period": "month"},
    {"period": "week"},
    {"q": "G57 School 2"},
    {"q": "G57 Cluster 1"},
    {"activity_type": "cluster_training"},
    {"activity_type": "in_school_training"},
    {"activity_type": "school_improvement_training"},
    {"activity_type": "training"},
    {"activity_type": "cluster_training", "status": "completed"},
    {"activity_type": "cluster_training", "status": "scheduled"},
    {"activity_type": "cluster_training", "period": "month"},
] + [
    {"status": s}
    for s in (
        "completed",
        "closed",
        "in_progress",
        "cancelled",
        "deferred",
        "scheduled",
        "upcoming",
        "under_way",
        "overdue",
        "submitted",
        "returned_for_correction",
    )
]


def make(out_path):
    rnd = random.Random(57)  # nosec B311
    seq = iter(range(1, 100000))

    def nid(kind):
        return f"{P}{kind}{next(seq):06d}"

    today = timezone.localdate()
    fy = "2027"
    kampala = District.objects.get(name="Kampala")
    region = kampala.region
    home = District.objects.create(
        id=nid("d"), name="G57 Home", region=region, district_type="primary"
    )
    away = District.objects.create(
        id=nid("d"), name="G57 Away", region=region, district_type="secondary"
    )

    def person(name, roles, active, district=None):
        user = User.objects.create(
            id=nid("u"),
            email=f"{nid('e')}@g57.test",
            name=name,
            roles=roles,
            active_role=active,
        )
        sp = StaffProfile.objects.create(
            id=nid("p"),
            user=user,
            primary_district_id=district.id if district else None,
        )
        return user, sp

    officer, officer_sp = person("G57 Officer", ["CCEO"], "CCEO", home)
    lead, lead_sp = person("G57 Lead", ["Program Lead"], "Program Lead", away)
    staff, staff_sp = person("G57 Staff", ["ImpactAssessment"], "ImpactAssessment")
    people = [officer, lead, staff]
    owner_ids = {
        officer.id: [officer_sp.id, officer.id],
        lead.id: [lead_sp.id],
        staff.id: [staff_sp.id],
    }

    # Cluster 3 holds a Core School: a session reaching it is still the
    # existing application's (Core School Trainings).
    clusters = [
        Cluster.objects.create(
            id=nid("c"), name=f"G57 Cluster {i}", region=region, district=d
        )
        for i, d in enumerate((home, away, kampala, home))
    ]
    kinds = (
        "client",
        "client",
        "champion",
        "core_trained",
        "core_graduate",
        "client",
        "",
        "client",
    )
    schools = []
    for c, cluster in enumerate(clusters[:3]):
        for i, kind in enumerate(kinds):
            n = c * 10 + i
            schools.append(
                School.objects.create(
                    id=nid("s"),
                    school_id="" if n == 5 else f"G57{n:03d}",
                    name=f"G57 School {n}" if i != 7 else f"G57 School {c * 10}",
                    school_type=kind,
                    district=(kampala, home, away, None)[i % 4],
                    cluster_id=cluster.id,
                    cluster_status=("clustered", "clustered", "unclustered")[i % 3],
                    operational_status=("active", "", "reopened", "closed")[i % 4],
                    current_fy_ssa_status="done",
                )
            )
    # A cluster where nobody is confirmed: every member is reached.
    for i in range(2):
        schools.append(
            School.objects.create(
                id=nid("s"),
                school_id=f"G57U{i}",
                name=f"G57 Loose {i}",
                school_type="client",
                district=home,
                cluster_id=clusters[1].id,
                cluster_status="unclustered",
                operational_status="closed",
            )
        )
    gone = School.objects.create(
        id=nid("s"),
        school_id="G57GONE",
        name="G57 Gone",
        school_type="client",
        district=home,
        cluster_id=clusters[0].id,
        cluster_status="clustered",
        operational_status="active",
    )
    School.all_objects.filter(id=gone.id).update(deleted_at=timezone.now())
    School.objects.create(
        id=nid("s"),
        school_id="G57CORE",
        name="G57 Core",
        school_type="core",
        district=home,
        cluster_id=clusters[3].id,
        cluster_status="clustered",
        operational_status="active",
    )
    live = [s for s in schools]
    courses = list(ActivityCatalogueItem.objects.values_list("id", flat=True)[:8])

    days = (0, 3, 9, -2, -5, -40, None, 10, 2)
    acts = []
    for n in range(150):
        person_ = people[n % 3]
        t = rnd.choice(TYPES)
        school = cluster = None
        if t == "cluster_training":
            # Mostly the three clusters without a Core School.
            cluster = rnd.choice(clusters[:3] * 6 + [clusters[3]])
        elif t != "training" or rnd.random() < 0.5:
            school = rnd.choice(live)
        d = rnd.choice(days)
        planned = today + timedelta(days=d) if d is not None else None
        acts.append(
            Activity(
                id=nid("a"),
                activity_type=t,
                fy=fy if rnd.random() < 0.85 else "2026",
                quarter=rnd.choice(("Q1", "Q2")),
                status=rnd.choice(STATUSES),
                delivery_type=rnd.choice(("staff", "staff", "staff", "in-school")),
                school=school,
                cluster=cluster,
                event_district=rnd.choice((home, None)) if school is None else None,
                responsible_staff_id=rnd.choice(owner_ids[person_.id]),
                planned_date=planned,
                salesforce_activity_id=rnd.choice((None, "", f"TS-G57{n:04d}")),
                activity_purpose_text=rnd.choice(("", "", "[Go parity check] topic")),
                activity_name_snapshot=rnd.choice(("", "", "G57 Named session")),
                focus_intervention=rnd.choice((None, "", "leadership")),
                teachers_attended=rnd.choice((None, None, 0, 4)),
                leaders_attended=rnd.choice((None, 2)),
                expected_participants=rnd.choice((None, 0, 9, 25)),
                participants_per_school=rnd.choice((None, None, 0, 3)),
                teachers_per_school=rnd.choice((None, None, 5)),
                programme_delivery_mode=rnd.choice(("", "", "in_person", "online")),
                catalogue_item_id=rnd.choice(courses + [None, None])
                if courses
                else None,
                evidence_status=rnd.choice(("none", "uploaded", "accepted")),
                payment_status="none",
                ia_verification_status=rnd.choice(("", "pending", "confirmed")),
                actual_delivery_date=today + timedelta(days=rnd.choice((-6, 1)))
                if rnd.random() < 0.3
                else None,
            )
        )
    Activity.objects.bulk_create(acts)

    def meals(amount, unit, qty):
        return {
            "key": "group_training_meals",
            "qty": qty,
            "unit": unit,
            "label": "Meals",
            "amount": amount,
            "missing": False,
        }

    sessions = [a for a in acts if a.cluster_id]
    for i, a in enumerate(sessions):
        if rnd.random() < 0.5:
            ActivityCostSnapshot.objects.create(
                id=nid("z"),
                activity_id=a.id,
                sequence=1,
                is_current=True,
                operational_cost=1,
                operational_breakdown=rnd.choice(
                    ([meals(48000, 8000, 6)], [meals(0, 7000, 0)], [])
                ),
                missing_configuration=[],
                calculated_at=timezone.now(),
            )
        members = [s for s in live if s.cluster_id == a.cluster_id]
        if i % 3 == 0 or not members:
            continue  # planned before invitations were recorded by name
        if i % 3 == 2:
            # Recorded, nobody invited or attending: the session itself.
            for s in members[:2]:
                ClusterActivityAttendance.objects.create(activity_id=a.id, school=s)
            continue
        guests = rnd.sample(live, 2)
        for s in {s.id: s for s in rnd.sample(members, 3) + guests}.values():
            ClusterActivityAttendance.objects.create(
                activity_id=a.id,
                school=s,
                invited=rnd.random() < 0.7,
                attended=rnd.random() < 0.4,
                teachers=rnd.choice((None, 3, 0)),
                leaders=rnd.choice((None, 1)),
                other=rnd.choice((None, 0)),
                is_guest=s.cluster_id != a.cluster_id,
            )

    answers = []
    asked = QUERIES + [
        {"status": q["status"], "fy": "2026"} for q in QUERIES if "status" in q
    ]
    for user in people:
        user = User.objects.get(id=user.id)
        for query in asked:
            # In key order, as the gateway hands a query on.
            status, body = read_page(user, "/my-plan", dict(sorted(query.items())))
            answers.append(
                {"user": user.id, "query": query, "status": status, "body": body}
            )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"now": timezone.now().isoformat(), "answers": answers},
            f,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(out_path, len(answers))


if os.environ.get("MODE") == "remove":
    remove()
else:
    remove()
    make(os.environ["OUT"])
