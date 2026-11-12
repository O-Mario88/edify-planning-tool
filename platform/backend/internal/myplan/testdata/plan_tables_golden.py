"""What the existing feed shows of My Plan's own tables, for internal/myplan's
plan_tables_golden_test.go.

Run from the repository root against the TEST database, never the
development one (it writes records there, every id starting "g8"):

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test MODE=make \\
        OUT=/tmp/plan_tables.json python manage.py shell < .../plan_tables_golden.py
    (run the Go test)
    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test MODE=remove \\
        python manage.py shell < .../plan_tables_golden.py

MODE=make files synthetic people, districts, clusters, schools, Core plans
and slots, activities of the visit and meeting kinds in every state, cost
lines and work at a cluster, from a seeded random source, then asks the
feed itself (apps.mobile_feed.views.read_page, unmodified) for /my-plan as
each person, for many queries, and writes each answer. MODE=remove deletes
every record it filed.
"""

import json
import os
import random
from datetime import datetime, time, timedelta, timezone as tz

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.clusters.models import Cluster
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.fund_requests.models import AdvanceRequest
from apps.geography.models import District
from apps.mobile_feed.views import read_page
from apps.schools.models import School

if connection.settings_dict["NAME"] != "edify_gorn_test":
    raise SystemExit("plan_tables_golden.py writes records: the test database only")

P = "g8"


def remove():
    with transaction.atomic():
        AdvanceRequest.objects.filter(id__startswith=P).delete()
        ActivityScheduleCostLine.objects.filter(id__startswith=P).delete()
        CoreActivitySlot.objects.filter(id__startswith=P).delete()
        CorePlan.objects.filter(id__startswith=P).delete()
        Activity.all_objects.filter(id__startswith=P).delete()
        School.all_objects.filter(id__startswith=P).delete()
        Cluster.all_objects.filter(id__startswith=P).delete()
        StaffProfile.all_objects.filter(id__startswith=P).delete()
        User.objects.filter(id__startswith=P).delete()
        District.objects.filter(id__startswith=P).delete()
    print("removed")


TYPES = (
    "school_visit",
    "follow_up_visit",
    "core_visit",
    "ssa_activity",
    "donor_visit",
    "cluster_meeting",
    "cluster_meeting",
)
STATUSES = (
    "completed",
    "completed",
    "closed",
    "accountant_confirmed",
    "ia_verified",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "salesforce_id_required",
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
    "scheduled",
    "submitted_to_pl",
    "returned_by_pl",
)
QUERIES = [
    {},
    {"fy": "2026"},
    {"period": "quarter"},
    {"period": "month"},
    {"period": "week"},
    {"q": "G8 School 3"},
    {"activity_type": "cluster_meeting"},
    {"activity_type": "school_visit", "status": "completed"},
] + [
    {"status": s}
    for s in (
        "completed",
        "closed",
        "accountant_confirmed",
        "ia_verified",
        "in_progress",
        "completion_started",
        "evidence_uploaded",
        "salesforce_id_required",
        "cancelled",
        "rejected",
        "deferred",
        "not_planned",
        "awaiting_owner_approval",
        "under_way",
        "overdue",
        "scheduled",
    )
]


def make(out_path):
    rnd = random.Random(8)  # nosec B311
    seq = iter(range(1, 100000))

    def nid(kind):
        return f"{P}{kind}{next(seq):06d}"

    today = timezone.localdate()
    fy = "2027"
    kampala = District.objects.get(name="Kampala")
    region = kampala.region
    home = District.objects.create(
        id=nid("d"), name="G8 Home", region=region, district_type="primary"
    )
    away = District.objects.create(
        id=nid("d"), name="G8 Away", region=region, district_type="secondary"
    )

    def person(name, roles, active, district=None, profile=True):
        user = User.objects.create(
            id=nid("u"),
            email=f"{nid('e')}@g8.test",
            name=name,
            roles=roles,
            active_role=active,
        )
        sp = None
        if profile:
            sp = StaffProfile.objects.create(
                id=nid("p"),
                user=user,
                primary_district_id=district.id if district else None,
            )
        return user, sp

    officer, officer_sp = person("G8 Officer", ["CCEO"], "CCEO", home)
    lead, lead_sp = person("G8 Lead", ["Program Lead"], "Program Lead", away)
    staff, staff_sp = person("G8 Staff", ["ImpactAssessment"], "ImpactAssessment")
    bare, _ = person("", ["Admin"], "Admin", profile=False)
    people = [officer, lead, staff, bare]
    owner_ids = {
        officer.id: [officer_sp.id, officer.id],
        lead.id: [lead_sp.id],
        staff.id: [staff_sp.id],
        bare.id: [bare.id],
    }

    clusters = [
        Cluster.objects.create(
            id=nid("c"), name=f"G8 Cluster {i}", region=region, district=d
        )
        for i, d in enumerate((home, away, kampala))
    ]
    schools = []
    for i, kind in enumerate(
        (
            "core",
            "core",
            "core",
            "client",
            "core_trained",
            "core_graduate",
            "champion",
            "client",
        )
    ):
        schools.append(
            School.objects.create(
                id=nid("s"),
                school_id="" if i == 7 else f"G8{i:03d}",
                name=f"G8 School {i}",
                school_type=kind,
                district=(kampala, home, away, None)[i % 4],
                cluster_id=clusters[i % 3].id,
                cluster_status="clustered",
                operational_status="active",
            )
        )
    # The first Core school's package: slots of no activity, statuses the
    # Status select does not offer. The third's slot holds an activity.
    plan = CorePlan.objects.create(id=nid("q"), school_id=schools[0].school_id, fy=fy)
    for n, status in enumerate(("Planned", "Assigned"), start=1):
        CoreActivitySlot.objects.create(
            id=nid("t"),
            core_plan=plan,
            school_id=schools[0].school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=n,
            status=status,
        )
    slotted_plan = CorePlan.objects.create(
        id=nid("q"), school_id=schools[2].school_id, fy=fy
    )

    days = (0, 3, 9, -2, -5, -40, None)
    acts = []
    for n in range(320):
        person_ = people[n % 4]
        t = rnd.choice(TYPES)
        school = cluster = None
        if t == "cluster_meeting":
            cluster = rnd.choice(clusters + [None]) if n % 9 else None
        else:
            school = rnd.choice(schools)
        d = rnd.choice(days)
        planned = today + timedelta(days=d) if d is not None else None
        scheduled = None
        if planned is None and rnd.random() < 0.6:
            scheduled = datetime.combine(
                today + timedelta(days=rnd.choice((2, -3))), time(21, 0), tzinfo=tz.utc
            )
        started = None
        if rnd.random() < 0.4:
            started = datetime.combine(
                today + timedelta(days=rnd.choice((-9, -1, 2))),
                time(rnd.choice((5, 22)), 30),
                tzinfo=tz.utc,
            )
        acts.append(
            Activity(
                id=nid("a"),
                activity_type=t,
                fy=fy if rnd.random() < 0.85 else "2026",
                quarter=rnd.choice(("Q1", "Q2")),
                status=rnd.choice(STATUSES),
                delivery_type=rnd.choice(("staff", "staff", "staff", "")),
                school=school,
                cluster=cluster,
                event_district=rnd.choice((home, None)) if school is None else None,
                responsible_staff_id=rnd.choice(owner_ids[person_.id]),
                planned_date=planned,
                scheduled_date=scheduled,
                salesforce_activity_id=rnd.choice(
                    (None, "", f" SVE-G8{n:04d} ", f"TS-G8{n:04d}")
                ),
                reschedule_count=rnd.choice((0, 0, 1)),
                purpose_type=rnd.choice((None, "", "follow_up", "ssa_support")),
                activity_purpose_text=rnd.choice(("", "", "[Go parity check] topic")),
                focus_intervention=rnd.choice((None, "", "leadership")),
                meeting_kind=rnd.choice(("", "", "only_meeting", "cluster_leaders"))
                if t == "cluster_meeting"
                else "",
                teachers_attended=rnd.choice((None, 0, 4)),
                leaders_attended=rnd.choice((None, 2)),
                other_participants=rnd.choice((None, 1)),
                expected_participants=rnd.choice((None, 0, 9)),
                evidence_status=rnd.choice(("none", "uploaded", "accepted")),
                payment_status=rnd.choice(("none", "none", "paid")),
                ia_verification_status=rnd.choice(("", "pending", "confirmed")),
                actual_delivery_date=today + timedelta(days=rnd.choice((-6, 1)))
                if rnd.random() < 0.3
                else None,
                execution_started_at=started,
                planned_date_before_completion=today + timedelta(days=-2)
                if rnd.random() < 0.15
                else None,
            )
        )
    Activity.objects.bulk_create(acts)
    for a in acts:
        if rnd.random() < 0.4:
            line = ActivityScheduleCostLine.objects.create(
                id=nid("x"),
                activity=a,
                cost_setting_key="lunch_per_day",
                label="Lunch",
                unit_cost=1,
                amount=1,
            )
            # Advances in states that wait on nobody, and in ones that wait
            # on the Lead or the Accountant (Waiting on Approval).
            if rnd.random() < 0.5:
                AdvanceRequest.objects.create(
                    id=nid("v"),
                    activity=a,
                    budget_line=line,
                    responsible_user_id=officer.id,
                    fy=fy,
                    quarter="Q1",
                    amount=1,
                    status=rnd.choice(
                        (
                            "pending_responsible_confirmation",
                            "pending_responsible_confirmation",
                            "disbursed",
                            "accountability_pending",
                            "reimbursement_submitted",
                        )
                    ),
                )
    slotted = next(a for a in acts if a.school_id == schools[2].id)
    CoreActivitySlot.objects.create(
        id=nid("t"),
        core_plan=slotted_plan,
        school_id=schools[2].school_id,
        intervention="leadership",
        activity_type="visit",
        sequence_number=1,
        status="Planned",
        activity_id=slotted.id,
    )

    answers = []
    asked = (
        QUERIES
        + [{"status": q["status"], "fy": "2026"} for q in QUERIES if "status" in q]
        + [
            {"status": q["status"], "activity_type": "cluster_meeting"}
            for q in QUERIES
            if "status" in q
        ]
    )
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
