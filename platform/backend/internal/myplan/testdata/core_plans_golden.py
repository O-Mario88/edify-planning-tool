"""What the existing code lists on Core School Oversight's two tabs of
planned work, for internal/myplan's coreplans_golden_test.go.

Run from the repository root against the TEST database, never the
development one (it writes records there, every id starting "g7"):

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test MODE=make \\
        OUT=/tmp/core_plans.json python manage.py shell < .../core_plans_golden.py
    (run the Go test)
    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test MODE=remove \\
        python manage.py shell < .../core_plans_golden.py

MODE=make files synthetic schools, clusters, people, activities, cost lines,
weekly requests, cost snapshots and rates, Core packages, invitations, SSA
records, evidence and visit days from a seeded random source, then asks
apps.my_plan.table_export.core_school_plans itself, unmodified, for several
sets of schools and years, and writes each sheet as the page shows it
(table_export.shown). MODE=remove deletes every record it filed.
"""

import json
import re
import os
import random
from datetime import datetime, time, timedelta, timezone as tz
from types import SimpleNamespace

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ClusterActivityAttendance,
)
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget.models import ActivityCostSnapshot, CostCatalogue, CostSetting
from apps.clusters.models import Cluster
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.daily_visit_batches.models import DailyVisitBatch
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import WeeklyFundRequest, WeeklyFundRequestLine
from apps.geography.models import District
from apps.my_plan import table_export
from apps.partners.models import Partner
from apps.schools.models import School
from apps.ssa.models import SsaRecord

# The shared test database, or an agent's own copy of it (edify_gorn_aNN_test).
if not re.fullmatch(r"edify_gorn(_a\d+)?_test", connection.settings_dict["NAME"]):
    raise SystemExit("core_plans_golden.py writes records: the test database only")

P = "g7"
DONE = (
    "completed",
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "closed",
    "accountant_confirmed",
)
MODELS = (
    EvidenceRecord,
    WeeklyFundRequestLine,
    WeeklyFundRequest,
    ActivityScheduleCostLine,
    ActivityCostSnapshot,
    CoreActivitySlot,
    CorePlan,
    SsaRecord,
)


def remove():
    with transaction.atomic():
        for model in MODELS:
            model.objects.filter(id__startswith=P).delete()
        ClusterActivityAttendance.objects.filter(activity__id__startswith=P).delete()
        Activity.all_objects.filter(id__startswith=P).update(
            paired_school_visit=None, daily_visit_batch=None
        )
        Activity.all_objects.filter(id__startswith=P).delete()
        DailyVisitBatch.objects.filter(id__startswith=P).delete()
        CostSetting.objects.filter(id__startswith=P).delete()
        CostCatalogue.objects.filter(id__startswith=P).delete()
        School.all_objects.filter(id__startswith=P).delete()
        Cluster.all_objects.filter(id__startswith=P).delete()
        StaffSupervisorAssignment.objects.filter(id__startswith=P).delete()
        StaffProfile.all_objects.filter(id__startswith=P).delete()
        User.objects.filter(id__startswith=P).delete()
        District.objects.filter(id__startswith=P).delete()
    print("removed")


def make(out_path):
    rnd = random.Random(7)  # nosec B311
    seq = iter(range(1, 100000))

    def nid(kind):
        return f"{P}{kind}{next(seq):06d}"

    today = timezone.localdate()
    fy = "2027"
    kampala = District.objects.get(name="Kampala")
    region = kampala.region
    home = District.objects.create(
        id=nid("d"), name="G7 Home", region=region, district_type="primary"
    )
    away = District.objects.create(
        id=nid("d"), name="G7 Away", region=region, district_type="secondary"
    )
    odd = District.objects.create(id=nid("d"), name="G7 Odd", region=region)
    districts = [kampala, home, away, odd, None]

    # People: a field officer with a home district, one without, a
    # head-office account with no profile, an officer a lead supervises.
    def person(name, roles, active, district=None, profile=True):
        user = User.objects.create(
            id=nid("u"),
            email=f"{nid('e')}@g7.test",
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

    field_user, field_sp = person("G7 Field", ["CCEO"], "CCEO", home)
    loose_user, loose_sp = person("G7 Loose", [], "CCEO")
    hq_user, _ = person(
        "G7 Office", ["ImpactAssessment"], "ImpactAssessment", profile=False
    )
    led_user, led_sp = person("G7 Led", ["Accountant"], "Accountant")
    blank_user, blank_sp = person("", ["CCEO"], "CCEO")
    lead_sp = StaffProfile.objects.filter(
        user__roles__contains=["Program Lead"]
    ).first()
    StaffSupervisorAssignment.objects.create(
        id=nid("l"), supervisee=led_sp, supervisor=lead_sp
    )
    seeded = list(
        StaffProfile.objects.filter(user__roles__contains=["CCEO"]).exclude(
            id__startswith=P
        )[:3]
    )
    owners = [
        field_sp.id,
        field_user.id,
        loose_sp.id,
        hq_user.id,
        led_sp.id,
        blank_sp.id,
        seeded[0].id,
        seeded[1].user_id,
        "nobody",
        None,
    ]
    partners = list(Partner.objects.values_list("id", flat=True)[:2]) + ["g7gone"]

    clusters = [
        Cluster.objects.create(
            id=nid("c"), name=f"G7 Cluster {i}", region=region, district=d
        )
        for i, d in enumerate((home, away, kampala))
    ]
    schools = []
    for i in range(16):
        kind = (
            "core"
            if i < 11
            else ("champion", "client", "core_trained", "core_graduate", "core")[i - 11]
        )
        code = "" if i == 15 else f"G7{i:03d}"
        schools.append(
            School.objects.create(
                id=nid("s"),
                school_id=code,
                name=f"G7 School {i % 9}",
                school_type=kind,
                district=districts[i % 5],
                cluster_id=clusters[i % 3].id if i % 4 else None,
                cluster_status="clustered" if i % 3 else "invited",
                operational_status=("active", "", "reopened", "closed")[i % 4],
            )
        )
    core = [s for s in schools if s.school_type == "core"]

    courses = list(
        ActivityCatalogueItem.objects.values_list("id", "is_training_course")[:6]
    )
    catalogue = CostCatalogue.objects.create(
        id=nid("k"), country="G7 Test", fy=fy, version=7007, is_active=False
    )
    for key, minimum, unit in (
        ("primary_transport_per_day", 45000, 50000),
        ("lunch_per_day", 10000, 12000),
        ("group_training_meals", 7000, 8000),
        ("cluster_meetings_trainings_meals", None, 6000),
        ("accommodation_per_night", 0, 0),
        ("partner_visit_lump_sum", 30000, 40000),
    ):
        CostSetting.objects.create(
            id=nid("r"),
            catalogue=catalogue,
            key=key,
            label=key,
            unit_cost=unit,
            approved_minimum=minimum,
            unit="day",
        )

    batches = [
        DailyVisitBatch.objects.create(
            id=nid("b"),
            responsible_user=u,
            visit_date=today + timedelta(days=d),
            district_type="primary",
        )
        for u, d in (
            (field_user.id, 3),
            (loose_user.id, 4),
            (hq_user.id, 5),
            (field_user.id, 6),
        )
    ]

    types = (
        "core_visit",
        "school_visit",
        "school_visit_ssa_collection",
        "follow_up_visit",
        "in_school_training",
        "cluster_training",
        "cluster_meeting",
        "ssa_activity",
        "partner_activity",
        "training",
        "programme_event",
    )
    statuses = (
        "scheduled",
        "planned",
        "rescheduled",
        "completed",
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "closed",
        "returned_by_pl",
        "returned",
        "in_progress",
        "partner_scheduled",
        "assigned_to_partner",
        "cancelled",
        "accountant_confirmed",
    )
    days = (0, 3, 4, 5, 6, 7, 8, 10, -5, -40, None, None)
    acts = []
    for n in range(170):
        t = rnd.choice(types)
        place = rnd.random()
        school = cluster = None
        if t in ("cluster_training", "cluster_meeting", "training") and place < 0.7:
            cluster = rnd.choice(clusters)
        elif t != "programme_event":
            school = rnd.choice(core if place < 0.8 else schools)
            if rnd.random() < 0.15:
                cluster = rnd.choice(clusters)
        d = rnd.choice(days)
        planned = today + timedelta(days=d) if d is not None else None
        scheduled = None
        if planned is None and rnd.random() < 0.6:
            sday = today + timedelta(days=rnd.choice((2, -3, 9)))
            scheduled = datetime.combine(
                sday - timedelta(days=1), time(21, 0), tzinfo=tz.utc
            )
        status = rnd.choice(statuses)
        partner = rnd.random() < 0.25
        if partner and status in DONE and school is not core[0]:
            # A partner's completed work is complete by its uploaded form,
            # which the gateway may not read: Go leaves a sheet holding it
            # to the existing code, so only the first Core school holds it.
            status = "partner_scheduled"
        started = None
        if rnd.random() < 0.4:
            started = datetime.combine(
                today + timedelta(days=rnd.choice((-9, -1, 2, 12))),
                time(rnd.choice((5, 22)), 30),
                tzinfo=tz.utc,
            )
        course = rnd.choice(courses + [(None, False)])
        acts.append(
            Activity(
                id=nid("a"),
                activity_type=t,
                fy=fy if rnd.random() < 0.9 else "2026",
                quarter="Q1",
                status=status,
                delivery_type="partner" if partner else "staff",
                assigned_partner_id=rnd.choice(partners)
                if partner or rnd.random() < 0.1
                else None,
                school=school,
                cluster=cluster,
                responsible_staff_id=rnd.choice(owners),
                planned_date=planned,
                scheduled_date=scheduled,
                salesforce_activity_id=rnd.choice(
                    (None, "", f" SVE-G7{n:04d} ", f"TS-G7{n:04d}")
                ),
                reschedule_count=rnd.choice((0, 0, 1)),
                purpose_type=rnd.choice(
                    (
                        None,
                        "",
                        "ssa_support",
                        "follow_up",
                        "in_school_training",
                        "nonsense",
                    )
                ),
                activity_purpose_text=rnd.choice(("", "", "[Go parity check] purpose")),
                focus_intervention=rnd.choice(
                    (None, "", "financial_health", "leadership", "made_up")
                ),
                teachers_attended=rnd.choice((None, 0, 4)),
                leaders_attended=rnd.choice((None, 2)),
                other_participants=rnd.choice((None, 1)),
                expected_participants=rnd.choice((None, 0, 9, 30)),
                participants_per_school=rnd.choice((None, 0, 3)),
                teachers_per_school=rnd.choice((None, 5)),
                training_course_id=course[0] if rnd.random() < 0.5 else None,
                catalogue_item_id=course[0] if rnd.random() < 0.5 else None,
                programme_delivery_mode=rnd.choice(("", "in_person", "online")),
                planning_source="manual_work_plan" if t == "programme_event" else "",
                cost_missing=rnd.random() < 0.15,
                ia_verification_status=rnd.choice(
                    ("", "pending", "confirmed", "returned")
                ),
                ssa_collection_expected=rnd.random() < 0.2,
                daily_visit_batch=rnd.choice(batches) if rnd.random() < 0.15 else None,
                actual_delivery_date=today + timedelta(days=rnd.choice((-6, 1)))
                if rnd.random() < 0.3
                else None,
                execution_started_at=started,
                submitted_to_ia_at=started + timedelta(days=rnd.choice((0, 3)))
                if started and rnd.random() < 0.5
                else None,
                pl_reviewed_at=started + timedelta(days=1)
                if started and rnd.random() < 0.3
                else None,
                planned_date_before_completion=today
                + timedelta(days=rnd.choice((-2, 9)))
                if rnd.random() < 0.15
                else None,
            )
        )
    by_type = {}
    for a in acts:
        by_type.setdefault(a.activity_type, []).append(a)
    free = list(by_type.get("school_visit", []))
    rnd.shuffle(free)
    for a in by_type.get("in_school_training", [])[1:]:
        if free and rnd.random() < 0.7:
            a.paired_school_visit_id = free.pop().id
    Activity.objects.bulk_create(acts)
    # A pair's visit outside the chosen work: another year's.
    outside = Activity.objects.create(
        id=nid("a"),
        activity_type="school_visit",
        fy="2025",
        quarter="Q1",
        status="scheduled",
        delivery_type="staff",
        school=core[0],
    )
    ActivityScheduleCostLine.objects.create(
        id=nid("x"),
        activity=outside,
        cost_setting_key="lunch_per_day",
        label="Lunch",
        unit_cost=1,
        amount=1,
    )
    for a in by_type.get("in_school_training", [])[:1]:
        Activity.objects.filter(id=a.id).update(paired_school_visit=outside)

    requests = [
        WeeklyFundRequest.objects.create(
            id=nid("w"),
            fy=fy,
            week_start_date=today + timedelta(weeks=i),
            week_end_date=today + timedelta(weeks=i),
            responsible_user=field_user.id,
            status=s,
        )
        for i, s in enumerate(
            (
                "pending_responsible_confirmation",
                "submitted_to_pl",
                "submitted_to_cd",
                "returned_by_pl",
                "returned_by_accountant",
                "confirmed_for_advance",
                "disbursed",
                "draft",
            )
        )
    ]
    for a in acts:
        for key in ("lunch_per_day", "primary_transport_per_day")[
            : rnd.choice((0, 0, 1, 2))
        ]:
            line = ActivityScheduleCostLine.objects.create(
                id=nid("x"),
                activity_id=a.id,
                cost_setting_key=key,
                label="Lunch",
                unit_cost=1000,
                amount=1000,
            )
            for request in rnd.sample(requests, rnd.choice((0, 1, 1, 2))):
                WeeklyFundRequestLine.objects.create(
                    id=nid("y"),
                    weekly_fund_request=request,
                    activity_budget_line=line,
                    line_item_type="lunch",
                    description="g7",
                    unit_cost=1,
                    total_cost=1,
                )

    def component(key, amount, unit, **extra):
        return {
            "key": key,
            "qty": extra.pop("qty", 1),
            "unit": unit,
            "label": extra.pop("label", key),
            "amount": amount,
            "missing": False,
            **extra,
        }

    shapes = (
        [
            component("primary_transport_per_day", 50000, 50000),
            component("lunch_per_day", 12000, 12000),
        ],
        [
            component(
                "primary_transport_per_day",
                25000,
                25000,
                label="Transport (shared, 2 schools)",
            )
        ],
        [
            component(
                "primary_transport_per_day",
                16667,
                16667,
                dailyAllocation={"count": 3, "index": 1},
            )
        ],
        [component("transport_per_day", 9000, 9000)],
        [component("client_partner_visit", 40000, 40000)],
        [component("accommodation_per_night", 0, 0)],
        [component("cluster_meetings_trainings_meals", 6000, 6000)],
        [
            component("group_training_meals", 48000, 8000, qty=6),
            component("lunch_per_day", 12000, 12000),
        ],
        [component("group_training_meals", 8000, 8000, qty=0)],
        [component("lunch_per_day", 12000, 12000, missing=True)],
        [
            component("lunch_per_day", 3333, 12000, label="Lunch"),
            component("primary_transport_per_day", 1, 3, qty=3),
        ],
        [],
    )
    for a in acts:
        if rnd.random() < 0.75:
            shape = rnd.choice(shapes)
            ActivityCostSnapshot.objects.create(
                id=nid("z"),
                activity_id=a.id,
                sequence=1,
                is_current=True,
                operational_rate_card=catalogue if rnd.random() < 0.9 else None,
                operational_cost=rnd.choice((0, 0, 5000)) if not shape else 1,
                operational_breakdown=shape,
                missing_configuration=["rate"] if rnd.random() < 0.1 else [],
                calculated_at=timezone.now(),
            )

    plans = {}
    for s in core:
        if not s.school_id:
            continue
        for year in (fy, "2026"):
            plans[(s.school_id, year)] = CorePlan.objects.create(
                id=nid("q"), school_id=s.school_id, fy=year
            )
    slot_status = (
        "completed",
        "Completed ",
        "scheduled",
        "ia_verified",
        "closed",
        "pending",
    )
    # Each piece of school work fills one slot at most, as booking does: an
    # activity in two slots would be read in whatever order the table
    # holds them, by the existing code as by Go.
    booked = set()
    for (code, year), plan in plans.items():
        mine = [
            a
            for a in acts
            if a.school_id
            and a.school.school_id == code
            and a.school.school_type == "core"
        ]
        for kind in ("visit", "training", "assessment"):
            for n in range(1, 5 if kind != "assessment" else 2):
                pick = rnd.choice(mine + [None, None]) if mine else None
                if pick is not None and (pick.id in booked or year != fy):
                    pick = None
                if pick is not None:
                    booked.add(pick.id)
                CoreActivitySlot.objects.create(
                    id=nid("t"),
                    core_plan=plan,
                    school_id=code,
                    activity_type=kind,
                    sequence_number=n,
                    status=rnd.choice(slot_status),
                    activity_id=pick.id if pick and year == fy else None,
                )
    sessions = [a for a in acts if a.cluster_id and not a.school_id]
    for i, a in enumerate(sessions):
        if i % 4 == 0:
            continue  # planned before invitations were recorded by name
        for s in rnd.sample(schools, 5):
            ClusterActivityAttendance.objects.create(
                activity_id=a.id,
                school=s,
                invited=rnd.random() < 0.7,
                attended=rnd.random() < 0.3,
                teachers=rnd.choice((None, 3)),
                leaders=rnd.choice((None, 1)),
                other=rnd.choice((None, 0)),
            )
            if (
                s.school_type == "core"
                and s.school_id
                and (s.school_id, fy) in plans
                and rnd.random() < 0.6
            ):
                CoreActivitySlot.objects.create(
                    id=nid("t"),
                    core_plan=plans[(s.school_id, fy)],
                    school_id=s.school_id,
                    activity_type="training",
                    sequence_number=rnd.choice((1, 2, 3)),
                    status="scheduled",
                    activity_id=a.id,
                )
    for s in core[:6]:
        SsaRecord.objects.create(
            id=nid("h"),
            school=s,
            date_of_ssa=today,
            fy=rnd.choice((fy, "2026")),
            quarter="Q1",
            uploaded_by="g7",
            verification_status=rnd.choice(("pending", "confirmed", "returned")),
        )
    for a in acts:
        if a.delivery_type == "partner" and rnd.random() < 0.6:
            EvidenceRecord.objects.create(
                id=nid("f"),
                activity_id=a.id,
                kind=rnd.choice(("visit_form", "attendance_form", "photo")),
                uri="g7://evidence",
                uploaded_by="g7",
                quarantined=rnd.random() < 0.2,
            )

    # One partner visit at the first Core school is done: its sheets are
    # the existing code's.
    done = (
        Activity.objects.filter(id__startswith=P, school=core[0], fy=fy)
        .exclude(status="cancelled")
        .first()
    )
    Activity.objects.filter(id=done.id).update(
        delivery_type="partner", status="completed"
    )

    def asked(chosen):
        return [SimpleNamespace(id=s.id, code=s.school_id or "") for s in chosen]

    cases = []
    user = User.objects.get(id=field_user.id)
    asks = [
        ("every school", schools, fy),
        ("the Core schools", core, fy),
        ("the first five", core[:5], fy),
        ("every school but the first", schools[1:], fy),
        ("the Core schools but the first, the year before", core[1:], "2026"),
        ("no school", [], fy),
        ("the year before", schools, "2026"),
    ]
    asks += [
        (f"{s.name} ({s.school_id or 'no ID'}) in {year}", [s], year)
        for s in schools
        for year in (fy, "2026")
    ]
    for label, chosen, year in asks:
        visits, trainings = table_export.core_school_plans(user, asked(chosen), year)
        cases.append(
            {
                "label": label,
                "fy": year,
                "schools": [[s.id, s.school_id or ""] for s in chosen],
                "visits": {
                    "title": visits["title"],
                    "headers": visits["headers"],
                    "rows": table_export.shown(visits),
                },
                "trainings": {
                    "title": trainings["title"],
                    "headers": trainings["headers"],
                    "rows": table_export.shown(trainings),
                },
            }
        )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"now": timezone.now().isoformat(), "cases": cases},
            f,
            ensure_ascii=False,
            indent=1,
        )
    print(
        out_path,
        [
            (c["label"], len(c["visits"]["rows"]), len(c["trainings"]["rows"]))
            for c in cases
        ],
    )


if os.environ.get("MODE") == "remove":
    remove()
else:
    remove()
    make(os.environ["OUT"])
