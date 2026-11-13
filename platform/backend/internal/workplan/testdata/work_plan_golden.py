"""What the existing feed shows of the Work Plan for synthetic people, for
internal/workplan's page_golden_test.go.

Run from the repository root against a Go integration TEST database, never
the development one (it writes records there, every id starting "g19"):

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_a19_test MODE=make \\
        OUT=/tmp/work_plan.json python manage.py shell < .../work_plan_golden.py
    (run the Go test with EDIFY_WORKPLAN_GOLDEN=/tmp/work_plan.json and
     EDIFY_WORKPLAN_DB=postgresql://localhost:5432/edify_gorn_a19_test)
    DATABASE_URL=postgresql://localhost:5432/edify_gorn_a19_test MODE=remove \\
        python manage.py shell < .../work_plan_golden.py

MODE=make files synthetic people in every role the page serves, a team,
partners, projects (one no SSA measures), schools and clusters (one of each
soft-deleted), activities of every type and status over the year and either
side of it (dated, scheduled only, undated, several days long, on a public
holiday, a recorded holiday, a recorded Eid and approved leave), in-school
pairs, an online training, non-school work, cost lines in and out of the
period, weekly requests and advances in every state, SSA verdicts, and the
year's approval envelopes; then asks the feed itself
(apps.mobile_feed.views.read_page, unmodified) for /work-plan as each
person, for many queries, and writes each answer. MODE=remove deletes every
record it filed.
"""

import json
import os
import random
from datetime import date, datetime, time, timedelta, timezone as tz

from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffGeographyAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.clusters.models import Cluster
from apps.fund_requests.models import (
    AdvanceRequest,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District
from apps.mobile_feed.views import read_page
from apps.monthly_work_plan.models import CountryAnnualBudget
from apps.partners.models import Partner
from apps.projects.models import Project
from apps.schools.models import School

if not connection.settings_dict["NAME"].endswith("_test"):
    raise SystemExit("work_plan_golden.py writes records: a test database only")

P = "g19"


def remove():
    with transaction.atomic():
        AdvanceRequest.objects.filter(id__startswith=P).delete()
        WeeklyFundRequestLine.objects.filter(id__startswith=P).delete()
        WeeklyFundRequest.objects.filter(id__startswith=P).delete()
        ActivityScheduleCostLine.objects.filter(id__startswith=P).delete()
        Activity.all_objects.filter(id__startswith=P).update(paired_school_visit=None)
        Activity.all_objects.filter(id__startswith=P).delete()
        CountryAnnualBudget.objects.filter(id__startswith=P).delete()
        Leave.objects.filter(id__startswith=P).delete()
        PublicHoliday.objects.filter(id__startswith=P).delete()
        CalendarBlock.objects.filter(id__startswith=P).delete()
        StaffGeographyAssignment.objects.filter(id__startswith=P).delete()
        StaffSupervisorAssignment.objects.filter(id__startswith=P).delete()
        School.all_objects.filter(id__startswith=P).delete()
        Cluster.all_objects.filter(id__startswith=P).delete()
        Project.all_objects.filter(id__startswith=P).delete()
        Partner.all_objects.filter(id__startswith=P).delete()
        StaffProfile.all_objects.filter(id__startswith=P).delete()
        User.objects.filter(id__startswith=P).delete()
    print("removed")


TYPES = (
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "donor_visit",
    "core_visit",
    "training",
    "in_school_training",
    "cluster_training",
    "cluster_meeting",
    "ssa_activity",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_activity",
    "project_activity",
    "programme_event",
    "field_event",
)
STATUSES = (
    "planned",
    "scheduled",
    "scheduled",
    "rescheduled",
    "partner_scheduled",
    "assigned_to_partner",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "salesforce_id_required",
    "submitted_to_pl",
    "returned_by_pl",
    "returned",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
    "closed",
    "cancelled",
    "rejected",
    "deferred",
    "not_planned",
    "awaiting_owner_approval",
)
WFR_STATUSES = (
    "pending_responsible_confirmation",
    "submitted_to_pl",
    "submitted_to_cd",
    "returned_by_cd",
    "disbursed",
    "some_new_state",
)
ADVANCE_STATUSES = (
    "pending_responsible_confirmation",
    "disbursed",
    "accountability_pending",
    "accountability_pl_pending",
    "reimbursement_pl_pending",
    "reimbursement_submitted",
    "reimbursement_disbursed",
    "cleared",
)
QUERIES = [
    {},
    {"view": "quarter"},
    {"view": "fy"},
    {"view": "quarter", "period": "Q2"},
    {"period": "12"},
    {"period": "3"},
    {"period": "2"},
    {"fy": "2026", "view": "fy"},
    {"fy": "2028", "view": "fy"},
    {"fy": "2025"},
    {"flag": "cost_missing"},
    {"flag": "pending_approval", "view": "fy"},
    {"flag": "at_risk", "view": "fy"},
    {"view": "fy", "executor": "partner"},
    {"view": "fy", "status": "cancelled"},
    {"view": "fy", "status": "completed"},
    {"view": "fy", "status": "in_progress"},
    {"view": "fy", "activity_type": "in_school_training"},
    {"view": "fy", "activity_type": "programme_event"},
    {"wp_page": "2"},
    {"wp_page": "3"},
    {"view": "fy", "wp_page": "2"},
    {"view": "fy", "wp_page": "99"},
    {"scope": "own"},
    {"scope": "own", "view": "fy"},
]


def make(out_path):
    rnd = random.Random(19)  # nosec B311
    seq = iter(range(1, 1000000))

    def nid(kind):
        return f"{P}{kind}{next(seq):06d}"

    now = timezone.now()
    today = timezone.localdate()
    kampala = District.objects.get(name="Kampala")
    north = (
        District.objects.exclude(region_id=kampala.region_id).order_by("name").first()
    )

    def person(name, roles, active, profile=True):
        user = User.objects.create(
            id=nid("u"),
            email=f"{nid('e')}@g19.test",
            name=name,
            roles=roles,
            active_role=active,
        )
        sp = StaffProfile.objects.create(id=nid("p"), user=user) if profile else None
        return user, sp

    officer, officer_sp = person("G19 Officer", ["CCEO"], "CCEO")
    peer, peer_sp = person("G19 Officer", ["CCEO"], "CCEO")
    lead, lead_sp = person("G19 Lead", ["Program Lead"], "Program Lead")
    cd, cd_sp = person("G19 Director", ["CountryDirector"], "CountryDirector")
    admin, _ = person("G19 Admin", ["Admin"], "Admin", profile=False)
    rvp, rvp_sp = person("G19 RVP", ["RegionalVicePresident"], "RegionalVicePresident")
    accountant, _ = person("G19 Accountant", ["Accountant"], "Accountant")
    hr, _ = person("G19 HR", ["HumanResources"], "HumanResources")
    pc, pc_sp = person("G19 Coordinator", ["ProjectCoordinator"], "ProjectCoordinator")
    ia, _ = person("G19 IA", ["ImpactAssessment"], "ImpactAssessment")
    bare, _ = person("  G19   Bare  ", ["CCEO"], "CCEO", profile=False)
    nameless, _ = person("", ["CCEO"], "CCEO", profile=False)
    StaffGeographyAssignment.objects.create(
        id=nid("g"), staff=rvp_sp, region_id=kampala.region_id
    )
    for supervisee in (officer_sp, peer_sp):
        StaffSupervisorAssignment.objects.create(
            id=nid("w"), supervisor=lead_sp, supervisee=supervisee
        )

    partner = Partner.objects.create(id=nid("r"), name="G19 Partner")
    gone_partner = Partner.objects.create(id=nid("r"), name="G19 Gone Partner")
    gone_partner.delete()
    project = Project.objects.create(
        id=nid("j"),
        name="G19 Project",
        category="general",
        manager_staff_id=pc_sp.id,
        intervention="leadership",
        target_interventions=["leadership"],
    )
    alumni = Project.objects.create(
        id=nid("j"),
        name="G19 Alumni",
        category="general",
        manager_staff_id=pc_sp.id,
        intervention="general",
        target_interventions=["general"],
    )

    region = kampala.region
    cluster = Cluster.objects.create(
        id=nid("c"), name="G19 Cluster", region=region, district=kampala
    )
    gone_cluster = Cluster.objects.create(
        id=nid("c"), name="G19 Gone Cluster", region=region, district=north
    )
    schools = []
    for i, (code, district, home) in enumerate(
        (
            ("G19001", kampala, cluster),
            ("G19 /2", north, gone_cluster),
            ("", kampala, cluster),
            (" G19004 ", None, None),
        )
    ):
        schools.append(
            School.objects.create(
                id=nid("s"),
                school_id=code,
                name=f"G19  School {i}",
                school_type="client",
                district=district,
                region=district.region if district else None,
                cluster_id=home.id if home else None,
                cluster_status="clustered",
                operational_status="active",
                current_fy_ssa_status=("done", "pending", "not_started", "done")[i],
            )
        )
    gone_cluster.delete()

    # The year's approval envelopes, one per year either side.
    for fy_, status, note in (
        ("2025", "approved_by_rvp", ""),
        ("2026", "submitted_to_rvp", ""),
        ("2028", "returned_by_rvp", "[Go parity check] fix the  costs"),
    ):
        CountryAnnualBudget.objects.create(
            id=nid("b"),
            fy=fy_,
            country_id="Uganda",
            status=status,
            rvp_review_note=note,
        )

    # Days off: a recorded holiday, a block, a recorded Eid a day after the
    # expected one, and the officer's approved leave (and a pending one).
    PublicHoliday.objects.create(id=nid("h"), name="G19 Day", date=date(2027, 1, 12))
    PublicHoliday.objects.create(
        id=nid("h"), name="Idd el Fitri", date=date(2027, 3, 10)
    )
    CalendarBlock.objects.create(
        id=nid("k"),
        title="G19 Block",
        block_type="PUBLIC_HOLIDAY",
        start_date=date(2027, 2, 2),
        end_date=date(2027, 2, 3),
        country="Uganda",
        is_active=True,
    )
    Leave.objects.create(
        id=nid("l"),
        staff=officer_sp,
        type="annual",
        start_date="2026-12-01",
        end_date="2026-12-03",
        days=3,
        status="approved",
    )
    Leave.objects.create(
        id=nid("l"),
        staff=peer_sp,
        type="annual",
        start_date="2026-11-20",
        end_date="2026-11-21",
        days=2,
        status="pending",
    )

    owners = [
        officer_sp.id,
        officer.id,
        peer_sp.id,
        peer.id,
        lead_sp.id,
        cd_sp.id,
        bare.id,
        nameless.id,
        "g19nobody",
    ]
    special_days = [
        today,
        today + timedelta(days=1),
        today - timedelta(days=1),
        date(2026, 12, 25),
        date(2026, 12, 2),
        date(2027, 1, 12),
        date(2027, 2, 2),
        date(2027, 3, 9),
        date(2027, 3, 10),
        date(2026, 10, 9),
        date(2027, 9, 30),
        date(2026, 10, 1),
    ]
    acts = []

    def activity(**fields):
        defaults = dict(
            id=nid("a"),
            fy="2027",
            quarter="Q1",
            status="scheduled",
            delivery_type="staff",
            activity_type="school_visit",
        )
        defaults.update(fields)
        a = Activity(**defaults)
        acts.append(a)
        return a

    for n in range(260):
        t = rnd.choice(TYPES)
        status = rnd.choice(STATUSES)
        school = (
            rnd.choice(schools + [None])
            if t not in ("programme_event", "field_event")
            else None
        )
        cl = (
            rnd.choice((cluster, None))
            if school is None
            else rnd.choice((None, None, cluster))
        )
        roll = rnd.random()
        planned = scheduled = None
        end = None
        month = None
        if roll < 0.55:
            planned = rnd.choice(
                special_days + [today + timedelta(days=rnd.randint(-120, 300))]
            )
            if rnd.random() < 0.15:
                end = planned + timedelta(days=rnd.choice((0, 1, 3, 9, 40)))
        elif roll < 0.75:
            scheduled = datetime.combine(
                today + timedelta(days=rnd.randint(-40, 200)),
                time(rnd.choice((6, 21, 22)), 0),
                tzinfo=tz.utc,
            )
        else:
            month = rnd.choice((None, 11, 5, 9, 0))
        partner_work = rnd.random() < 0.25
        responsible = (
            rnd.choice(owners + [None])
            if not partner_work
            else rnd.choice((None, officer_sp.id))
        )
        pairing = None
        activity(
            fy=rnd.choice(("2027",) * 8 + ("2026", "2028")),
            activity_type=t,
            status=status,
            delivery_type="partner" if partner_work else "staff",
            assigned_partner_id=rnd.choice((partner.id, gone_partner.id, None))
            if partner_work
            else None,
            monitored_by_staff_id=rnd.choice((officer_sp.id, lead_sp.id, peer.id, None))
            if partner_work
            else None,
            responsible_staff_id=responsible,
            school=school,
            cluster=cl,
            event_district=rnd.choice((kampala, north, None))
            if school is None and cl is None
            else None,
            project_id=rnd.choice((None, None, project.id, alumni.id)),
            planning_source=rnd.choice(("", "", "manual_work_plan"))
            if school is None
            else "",
            planned_date=planned,
            end_date=end,
            scheduled_date=scheduled,
            month=month,
            activity_name_snapshot=rnd.choice(("", "G19 Boot Camp", "G19  Conference")),
            catalogue_item_id=rnd.choice((None, "cmw9p6bjm00hrheeihgnv")),
            cost_missing=rnd.random() < 0.2,
            programme_delivery_mode=rnd.choice((None, "", "online", "group", "visit")),
            programme_activity_type=rnd.choice((None, "", "conference", "camp")),
            delivery_method_snapshot=rnd.choice(("", "in_person", "online_live")),
            purpose_type=rnd.choice(
                (
                    None,
                    "",
                    "follow_up",
                    "ssa_support",
                    "in_school_training_delivery_visit",
                    "made_up",
                )
            ),
            focus_intervention=rnd.choice((None, "", "leadership", "financial_health")),
            source_score=rnd.choice((None, 5.05, 6.15, 7, 4.25)),
            ssa_alignment=rnd.choice(
                ("", "", "aligned", "deviated", "no_ssa", "weird")
            ),
            ssa_deviation_reason=rnd.choice(("", "[Go parity check] the  head asked")),
            evidence_status=rnd.choice(("none", "uploaded", "accepted")),
            payment_status=rnd.choice(("none", "pending_ia", "paid")),
            ia_verification_status=rnd.choice(("", "pending", "confirmed")),
            salesforce_activity_id=rnd.choice((None, "", f"SVE-G19{n:04d}")),
            teachers_attended=rnd.choice((None, 0, 3)),
            leaders_attended=rnd.choice((None, 2)),
            paired_school_visit_id=pairing,
        )
    # Enough of the officer's own work in this month for a third page.
    for n in range(110):
        activity(
            responsible_staff_id=officer_sp.id,
            school=schools[n % 3],
            planned_date=date(today.year, today.month, 1) + timedelta(days=n % 28),
            status=("scheduled", "planned", "rescheduled", "completed")[n % 4],
            activity_type=("school_visit", "coaching_visit", "cluster_meeting")[n % 3],
            cluster=cluster if n % 3 == 2 else None,
        )
    # In-school pairs: priced visit / free training; priced training / free
    # visit; a pair whose visit was called off; an online training.
    visit = activity(
        responsible_staff_id=officer_sp.id,
        school=schools[0],
        planned_date=today + timedelta(days=5),
    )
    activity(
        responsible_staff_id=officer_sp.id,
        school=schools[0],
        planned_date=today + timedelta(days=5),
        activity_type="in_school_training",
        paired_school_visit_id=visit.id,
    )
    bare_visit = activity(
        responsible_staff_id=officer_sp.id,
        school=schools[1],
        planned_date=today + timedelta(days=6),
    )
    priced_training = activity(
        responsible_staff_id=officer_sp.id,
        school=schools[1],
        planned_date=today + timedelta(days=6),
        activity_type="in_school_training",
        paired_school_visit_id=bare_visit.id,
    )
    gone_visit = activity(
        responsible_staff_id=officer_sp.id,
        school=schools[2],
        planned_date=today + timedelta(days=7),
        status="cancelled",
    )
    activity(
        responsible_staff_id=officer_sp.id,
        school=schools[2],
        planned_date=today + timedelta(days=7),
        activity_type="in_school_training",
        paired_school_visit_id=gone_visit.id,
    )
    activity(
        responsible_staff_id=officer_sp.id,
        cluster=cluster,
        planned_date=today + timedelta(days=8),
        activity_type="training",
        programme_delivery_mode="online",
    )
    Activity.objects.bulk_create(acts)
    # Pairs randomly made among the first activities.
    trainings = [a for a in acts[:260] if a.activity_type == "in_school_training"]
    visits = [a for a in acts[:260] if a.activity_type == "school_visit"]
    for a in trainings[: len(trainings) // 2]:
        Activity.objects.filter(id=a.id).update(
            paired_school_visit_id=rnd.choice(visits).id
        )

    lines = []
    for a in acts:
        if a.id == bare_visit.id:
            continue
        if a.id in (visit.id, priced_training.id) or rnd.random() < 0.45:
            for k in range(rnd.choice((1, 1, 2, 3))):
                planned_line = None
                month_line = None
                fiscal = None
                r = rnd.random()
                if r < 0.3:
                    planned_line = (a.planned_date or today) + timedelta(
                        days=rnd.choice((0, 0, 20, 45, -30))
                    )
                elif r < 0.6:
                    month_line = rnd.choice((11, 12, 1, 5, 0))
                    fiscal = rnd.choice((None, "", "2027", "2026", 2027))
                lines.append(
                    ActivityScheduleCostLine(
                        id=nid("x"),
                        activity=a,
                        cost_setting_key=f"g19_{k}",
                        label=rnd.choice(("Transport", "Lunch", "G19  Fuel")),
                        unit_cost=1,
                        quantity=1,
                        amount=rnd.choice((0, 12000, 62000, 333333, 1500000)),
                        planned_date=planned_line,
                        month=month_line,
                        fiscal_year=str(fiscal) if fiscal is not None else None,
                    )
                )
    ActivityScheduleCostLine.objects.bulk_create(lines)
    for w, line in enumerate(lines):
        if rnd.random() < 0.35:
            week = today + timedelta(weeks=w)
            request = WeeklyFundRequest.objects.create(
                id=nid("q"),
                fy="2027",
                week_start_date=week,
                week_end_date=week + timedelta(days=6),
                responsible_user=officer.id,
                status=rnd.choice(WFR_STATUSES),
            )
            WeeklyFundRequestLine.objects.create(
                id=nid("y"),
                weekly_fund_request=request,
                activity_budget_line=line,
                line_item_type="lunch",
                description="G19",
                unit_cost=1,
                total_cost=1,
            )
        if rnd.random() < 0.3:
            AdvanceRequest.objects.create(
                id=nid("v"),
                activity=line.activity,
                budget_line=line,
                responsible_user_id=officer.id,
                fy="2027",
                quarter="Q1",
                amount=1,
                status=rnd.choice(ADVANCE_STATUSES),
                accountability_netsuite_id=rnd.choice((None, None, f"NS-G19{w}")),
                reimbursement_receipt_confirmed_at=rnd.choice((None, now)),
            )

    people = [officer, peer, lead, cd, admin, rvp, accountant, hr, pc, ia, bare]
    answers = []
    for user in people:
        user = User.objects.get(id=user.id)
        asked = list(QUERIES)
        first_status, first_body = read_page(user, "/work-plan", {})
        for block in first_body.get("blocks", []):
            for f in (block.get("filters") or {}).get("filters", []):
                if f["name"] in ("responsible", "project"):
                    asked += [
                        {f["name"]: o["value"], "view": "fy"} for o in f["options"][1:4]
                    ]
        for query in asked:
            # In key order, as the gateway hands the feed its query.
            query = dict(sorted(query.items()))
            status, body = read_page(user, "/work-plan", query)
            answers.append(
                {"user": user.id, "query": query, "status": status, "body": body}
            )
    with open(out_path, "w") as out:
        json.dump(
            {"now": now.isoformat(), "answers": answers},
            out,
            ensure_ascii=False,
            default=str,
        )
    print(f"wrote {len(answers)} answers")


mode = os.environ.get("MODE", "make")
if mode == "remove":
    remove()
else:
    make(os.environ["OUT"])
