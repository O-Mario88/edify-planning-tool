"""Programme Rollout, the Programme Lead's page (owner, 2026-09-13).

The role description asks a Programme Lead to coordinate the rollout of
training programmes, school self-assessments and spiritual transformation
interventions. These tests hold the page to that: the figures per
intervention, course and officer; each school's SSA state; the spiritual pair
against the previous cycle and the schools that need a response; who may read
which team; and a cost that does not grow with the team.

One fixture, written out so every expected number can be checked by hand:

    Team of Pat Lead: Alice (A1, A2 in cluster K; A3 in cluster L),
                      Ben (B1, B2), and Pat's own school OWN1.
    Quinn Lead's team: Cara (C1) — never on Pat's page.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
)
from apps.analytics import programme_rollout_service as rollout
from apps.cce_leadership.models import EngagementKind, RegionalEngagement
from apps.clusters.models import Cluster
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.enums import ActivityStatus
from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment, PartnerEngagement
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

TODAY = timezone.localdate()
FY = get_operational_fy(TODAY)
PREV = str(int(FY) - 1)
CB = "christlike_behaviour"
WOG = "exposure_to_word_of_god"
LSHIP = "leadership"
OTHER_SCORES = (
    "financial_health",
    "leadership",
    "government_requirement",
    "learning_environment",
    "teaching_environment",
    "enrolment",
)


def _person(uid, name, role):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


def _course(code, name, *, category="", intervention=None, catalogue_type="training"):
    item, _created = ActivityCatalogueItem.objects.get_or_create(
        stable_code=code,
        defaults={
            "source_name": name,
            "display_name": name,
            "activity_type": catalogue_type,
            "delivery_method": "cluster_training",
            "workflow_kind": "cluster_training",
            "status": "active",
            "is_training_course": bool(category),
            "training_category": category,
            "salesforce_record_type": "TRAINING",
            "evidence_profile": "TRAINING",
            "costing_profile": "CLUSTER_TRAINING",
        },
    )
    if intervention:
        ActivityInterventionMapping.objects.get_or_create(
            catalogue_item=item,
            intervention=intervention,
            mapping_mode="fixed",
            defaults={"is_primary": True, "active": True},
        )
    return item


def _at(day):
    return datetime.combine(day, time(9), tzinfo=dt_timezone.utc)


class RolloutFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Rollout Region", country="Uganda")
        cls.district = District.objects.create(
            name="Rollout District", region=cls.region, district_type="primary"
        )
        cls.cluster_k = Cluster.objects.create(
            name="Cluster K",
            district=cls.district,
            region=cls.region,
            status="active",
            responsible_staff_id="",
        )
        cls.cluster_l = Cluster.objects.create(
            name="Cluster L",
            district=cls.district,
            region=cls.region,
            status="active",
            responsible_staff_id="",
        )

        cls.pl, cls.pl_sp = _person("roll-pl", "Pat Lead", "Program Lead")
        cls.alice, cls.alice_sp = _person("roll-alice", "Alice Officer", "CCEO")
        cls.ben, cls.ben_sp = _person("roll-ben", "Ben Officer", "CCEO")
        cls.other_pl, cls.other_pl_sp = _person(
            "roll-quinn", "Quinn Lead", "Program Lead"
        )
        cls.cara, cls.cara_sp = _person("roll-cara", "Cara Officer", "CCEO")
        for supervisor, supervisee in (
            (cls.pl_sp, cls.alice_sp),
            (cls.pl_sp, cls.ben_sp),
            (cls.other_pl_sp, cls.cara_sp),
        ):
            StaffSupervisorAssignment.objects.create(
                supervisor=supervisor, supervisee=supervisee
            )
        cls.admin, _ = _person("roll-admin", "Rollout Admin", "Admin")

        def school(ref, owner, cluster=None):
            record = School.objects.create(
                school_id=ref,
                name=f"School {ref}",
                region=cls.region,
                district=cls.district,
            )
            if cluster is not None:
                # School.save() clears cluster_id on insert; set it directly.
                School.objects.filter(pk=record.pk).update(cluster_id=cluster.id)
                record.refresh_from_db()
            StaffSchoolAssignment.objects.create(staff=owner, school_id=record.id)
            return record

        cls.a1 = school("RO-A1", cls.alice_sp, cls.cluster_k)
        cls.a2 = school("RO-A2", cls.alice_sp, cls.cluster_k)
        cls.a3 = school("RO-A3", cls.alice_sp, cls.cluster_l)
        cls.b1 = school("RO-B1", cls.ben_sp)
        cls.b2 = school("RO-B2", cls.ben_sp)
        cls.own1 = school("RO-OWN1", cls.pl_sp)
        cls.c1 = school("RO-C1", cls.cara_sp)

        cls.partner = Partner.objects.create(name="Rollout Partner")
        cls.course_ct = _course(
            "ROLL_BIBLICAL",
            "Rollout Biblical Integration",
            category=rollout.CHRISTIAN_TRANSFORMATION,
            intervention=WOG,
        )
        cls.course_lead = _course(
            "ROLL_LEADERSHIP",
            "Rollout Leadership",
            category="Education",
            intervention=LSHIP,
        )
        cls.cc_sel = _course(rollout.CC_SEL_CODE, "CC-SEL", intervention=CB)
        cls.camp = _course(
            "ROLL_CAMP",
            "Rollout Youth Camp",
            intervention=CB,
            catalogue_type=rollout.CAMP_CATALOGUE_TYPE,
        )

        def activity(**fields):
            day = fields.pop("day", TODAY - timedelta(days=10))
            defaults = {
                "fy": FY,
                "quarter": "Q4",
                "delivery_type": "staff",
                "planned_date": day,
                "scheduled_date": _at(day),
            }
            return Activity.objects.create(**{**defaults, **fields})

        cls.t1 = activity(
            activity_type="in_school_training",
            school=cls.a1,
            responsible_staff_id=cls.alice_sp.id,
            status="ia_verified",
            focus_intervention=CB,
            training_course=cls.course_ct,
            teachers_attended=10,
            leaders_attended=2,
            day=TODAY - timedelta(days=20),
        )
        # Keyed by the officer's User id: attribution honours both id forms.
        cls.t2 = activity(
            activity_type="cluster_training",
            cluster=cls.cluster_k,
            responsible_staff_id=cls.alice.id,
            status="ia_verified",
            focus_intervention=WOG,
            catalogue_item=cls.course_ct,
            teachers_attended=5,
            leaders_attended=1,
            day=TODAY - timedelta(days=15),
        )
        for member in (cls.a1, cls.a2):
            ClusterActivityAttendance.objects.create(
                activity=cls.t2, school=member, invited=True, attended=True
            )
        cls.t3 = activity(
            activity_type="training",
            school=cls.b1,
            delivery_type="partner",
            assigned_partner_id=cls.partner.id,
            monitored_by_staff_id=cls.ben_sp.id,
            status="closed",
            focus_intervention=LSHIP,
            catalogue_item=cls.course_lead,
            teachers_attended=7,
            leaders_attended=0,
        )
        cls.t4 = activity(
            activity_type="training",
            school=cls.b1,
            responsible_staff_id=cls.ben_sp.id,
            status="scheduled",
            focus_intervention=CB,
            catalogue_item=cls.course_ct,
            day=TODAY + timedelta(days=5),
        )
        cls.t5 = activity(
            activity_type="in_school_training",
            school=cls.a1,
            responsible_staff_id=cls.alice_sp.id,
            status="awaiting_ia_verification",
            focus_intervention=CB,
            day=TODAY - timedelta(days=3),
        )
        cls.t6 = activity(
            activity_type="training",
            school=cls.c1,
            responsible_staff_id=cls.cara_sp.id,
            status="ia_verified",
            focus_intervention=CB,
            catalogue_item=cls.course_ct,
            teachers_attended=40,
        )
        cls.t7 = activity(
            activity_type="training",
            school=cls.a1,
            responsible_staff_id=cls.alice_sp.id,
            status="cancelled",
            focus_intervention=CB,
        )
        cls.t8 = activity(
            activity_type="in_school_training",
            school=cls.a2,
            delivery_type="partner",
            assigned_partner_id=cls.partner.id,
            monitored_by_staff_id=cls.alice_sp.id,
            status="closed",
            focus_intervention=CB,
            catalogue_item=cls.cc_sel,
            teachers_attended=4,
            leaders_attended=1,
        )
        cls.t9 = activity(
            activity_type="training",
            responsible_staff_id=cls.pl_sp.id,
            status="ia_verified",
            catalogue_item=cls.camp,
            day=TODAY - timedelta(days=30),
        )

        # SSA collection: a cluster review at L, a visit at B1, a partner
        # hand-over at B2.
        activity(
            activity_type="cluster_meeting_ssa_review",
            cluster=cls.cluster_l,
            responsible_staff_id=cls.alice_sp.id,
            status="scheduled",
            day=TODAY + timedelta(days=40),
        )
        activity(
            activity_type="school_visit_ssa_collection",
            school=cls.b1,
            responsible_staff_id=cls.ben_sp.id,
            status="scheduled",
            day=TODAY + timedelta(days=40),
        )
        PartnerAssignment.objects.create(
            school=cls.b2,
            partner=cls.partner,
            assigning_staff_id=cls.ben_sp.id,
            status=PartnerAssignment.STATUS_ASSIGNED,
            expected_activity_type="school_visit_ssa_collection",
        )

        def ssa(school, fy, status, scores):
            record = SsaRecord.objects.create(
                school=school,
                date_of_ssa=_at(TODAY - timedelta(days=60)),
                fy=fy,
                quarter="Q2",
                average_score=round(sum(scores.values()) / len(scores), 2),
                verification_status=status,
                uploaded_by="roll-ia",
            )
            for intervention, value in scores.items():
                SsaScore.objects.create(
                    ssa_record=record, intervention=intervention, score=value
                )
            return record

        def scores(cb, wog, rest=9.0, **overrides):
            values = {CB: cb, WOG: wog, **dict.fromkeys(OTHER_SCORES, rest)}
            values.update(overrides)
            return values

        ssa(cls.a1, FY, "confirmed", scores(3.0, 4.0, leadership=8.0))
        ssa(cls.a2, FY, "pending", scores(1.0, 1.0))
        ssa(cls.b1, PREV, "confirmed", scores(9.0, 1.0, rest=8.0))
        ssa(
            cls.own1,
            PREV,
            "confirmed",
            scores(
                9.0,
                2.0,
                rest=8.0,
                financial_health=5.0,
                leadership=6.0,
                government_requirement=7.0,
            ),
        )
        ssa(cls.c1, FY, "confirmed", scores(1.0, 9.0))

        lead = User.objects.create(
            id="roll-rpl",
            email="roll-rpl@edify.org",
            name="Regional Lead",
            roles=["RegionalProgramLead"],
            active_role="RegionalProgramLead",
            is_active=True,
        )
        cls.rpl = lead

        def observation(activity, *, biblical, recommendation, shared=True, **extra):
            return RegionalEngagement.objects.create(
                author_id=lead.id,
                kind=EngagementKind.TRAINING_OBSERVATION,
                held_on=TODAY,
                fy=FY,
                subject=f"Observed {activity.id}",
                activity=activity,
                program_lead_ids=extra.pop("leads", [cls.pl_sp.id]),
                rating_biblical_integration=biblical,
                rating_need_alignment=3,
                rating_facilitation=3,
                rating_participation=3,
                rating_application=3,
                recommendation=recommendation,
                feedback="Model the practice first.",
                feedback_shared_at=timezone.now() if shared else None,
                **extra,
            )

        cls.o1 = observation(cls.t3, biblical=2, recommendation="strengthen")
        cls.o2 = observation(
            cls.t2,
            biblical=4,
            recommendation="continue",
            acknowledged_at=timezone.now(),
        )
        observation(cls.t1, biblical=1, recommendation="replace", shared=False)
        observation(
            cls.t6, biblical=1, recommendation="replace", leads=[cls.other_pl_sp.id]
        )
        PartnerEngagement.objects.create(
            author_id=cls.pl.id,
            author_role="Program Lead",
            partner=cls.partner,
            kind="quality_follow_up",
            held_on=TODAY,
            fy=FY,
            subject="Followed up the observation",
            source_engagement=cls.o1,
        )


# ── Scope ────────────────────────────────────────────────────────────────────
class ScopeTest(RolloutFixture):
    def test_the_lead_reads_their_officers_and_their_own_portfolio(self):
        scope = rollout.resolve_rollout_scope(self.pl)
        self.assertEqual(
            [m.name for m in scope.officers], ["Alice Officer", "Ben Officer"]
        )
        self.assertEqual(scope.lead.school_ids, {self.own1.id})
        self.assertEqual(
            scope.school_ids,
            {self.a1.id, self.a2.id, self.a3.id, self.b1.id, self.b2.id, self.own1.id},
        )
        self.assertNotIn(self.c1.id, scope.school_ids)

    def test_a_lead_passed_by_a_programme_lead_is_ignored(self):
        scope = rollout.resolve_rollout_scope(self.pl, lead=self.other_pl_sp.id)
        self.assertEqual(scope.lead_staff_id, self.pl_sp.id)
        self.assertFalse(scope.support_view)

    def test_admin_reads_one_chosen_lead_and_lands_on_a_lead_with_a_team(self):
        chosen = rollout.resolve_rollout_scope(self.admin, lead=self.other_pl_sp.id)
        self.assertTrue(chosen.support_view)
        self.assertEqual([m.name for m in chosen.officers], ["Cara Officer"])
        default = rollout.resolve_rollout_scope(self.admin)
        self.assertEqual(default.lead_staff_id, self.pl_sp.id)
        self.assertEqual(
            [name for _id, name in default.leads], ["Pat Lead", "Quinn Lead"]
        )

    def test_every_other_role_is_refused_by_the_service_too(self):
        for user in (self.alice, self.rpl):
            with self.subTest(role=user.active_role), self.assertRaises(Forbidden):
                rollout.resolve_rollout_scope(user)
        with self.assertRaises(Forbidden):
            rollout.get_rollout(self.alice, view="ssa")

    def test_activity_statuses_are_counted_in_exactly_one_group(self):
        groups = [
            rollout.NOT_PLANNED_STATUSES,
            rollout.LIVE_STATUSES,
            rollout.IN_REVIEW_STATUSES,
            COMPLETED_WORK_STATUSES,
        ]
        flat = [status for group in groups for status in group]
        self.assertEqual(len(flat), len(set(flat)))
        self.assertEqual(set(flat), set(ActivityStatus.values))


# ── Trainings ────────────────────────────────────────────────────────────────
class TrainingsTest(RolloutFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        scope = rollout.resolve_rollout_scope(cls.pl)
        cls.data = rollout.trainings_rollout(cls.pl, scope, FY, TODAY)

    def _row(self, rows, **match):
        return next(r for r in rows if all(r[k] == v for k, v in match.items()))

    def test_team_totals_exclude_other_teams_and_withdrawn_work(self):
        summary = self.data["summary"]
        self.assertEqual(summary["planned"], 7)
        self.assertEqual(summary["delivered"], 5)
        self.assertEqual(summary["in_review"], 1)
        self.assertEqual(summary["to_deliver"], 1)
        self.assertEqual(summary["teachers"], 26)
        self.assertEqual(summary["leaders"], 4)
        self.assertEqual((summary["by_staff"], summary["by_partner"]), (3, 2))
        self.assertEqual((summary["schools_trained"], summary["portfolio"]), (3, 6))

    def test_all_eight_interventions_with_the_spiritual_pair_first(self):
        codes = [r["code"] for r in self.data["interventions"]]
        self.assertEqual(codes[:2], [CB, WOG])
        self.assertEqual(len(codes), 9, "eight interventions and the unnamed row")
        self.assertEqual(self.data["interventions"][0]["abbr"], "CB")
        self.assertEqual(self.data["interventions"][1]["abbr"], "WOG")
        cb = self._row(self.data["interventions"], code=CB)
        self.assertEqual(
            (cb["planned"], cb["delivered"], cb["in_review"], cb["schools_reached"]),
            (4, 2, 1, 2),
        )
        self.assertEqual((cb["by_staff"], cb["by_partner"]), (1, 1))
        wog = self._row(self.data["interventions"], code=WOG)
        self.assertEqual(
            (wog["delivered"], wog["schools_reached"]),
            (1, 2),
            "a cluster training reaches the schools whose attendance was confirmed",
        )
        unnamed = self._row(self.data["interventions"], code="")
        self.assertEqual(unnamed["planned"], 1)
        enrolment = self._row(self.data["interventions"], code="enrolment")
        self.assertEqual(enrolment["planned"], 0)

    def test_courses_list_the_catalogue_with_their_observations(self):
        biblical = self._row(self.data["courses"], id=self.course_ct.id)
        self.assertEqual((biblical["planned"], biblical["delivered"]), (3, 2))
        self.assertEqual(biblical["abbr"], "WOG")
        self.assertEqual((biblical["observed"], biblical["rating"]), (1, 3.2))
        leadership = self._row(self.data["courses"], id=self.course_lead.id)
        self.assertEqual(
            (leadership["rating"], leadership["open_recommendations"]), (2.8, 1)
        )
        self.assertEqual(self.data["courses"][-1]["id"], "", "no course named, last")
        self.assertEqual(self.data["courses"][-1]["planned"], 3)

    def test_officers_are_credited_by_owner_monitor_or_school(self):
        alice = self._row(self.data["officers"], staff_id=self.alice_sp.id)
        self.assertEqual(
            (alice["planned"], alice["delivered"], alice["in_review"]), (4, 3, 1)
        )
        self.assertEqual((alice["schools_trained"], alice["portfolio"]), (2, 3))
        self.assertEqual(alice["by_partner"], 1, "the partner work Alice monitors")
        ben = self._row(self.data["officers"], staff_id=self.ben_sp.id)
        self.assertEqual((ben["planned"], ben["delivered"]), (2, 1))
        self.assertEqual(ben["next_training"], TODAY + timedelta(days=5))
        own = self._row(self.data["officers"], staff_id=self.pl_sp.id)
        self.assertEqual(own["name"], "Your own portfolio")
        self.assertEqual((own["delivered"], own["schools_trained"]), (1, 0))
        self.assertEqual(
            own["oversight_url"], f"/team-planning-oversight/?owner=mine&fy={FY}"
        )

    def test_the_next_thirty_days_names_the_training_and_who_delivers_it(self):
        self.assertEqual([r["id"] for r in self.data["upcoming"]], [self.t4.id])
        row = self.data["upcoming"][0]
        self.assertEqual(row["training"], "Rollout Biblical Integration")
        self.assertEqual(row["delivered_by"], "Ben Officer")
        self.assertEqual(row["url"], f"/activities/{self.t4.id}")

    def test_only_observations_shared_with_the_lead_count(self):
        summary = self.data["summary"]
        self.assertEqual(summary["observed"], 2)
        self.assertEqual(summary["open_recommendations"], 1)
        self.assertEqual(summary["biblical"], 3.0)
        by = self.data["observations_by_deliverer"]
        self.assertEqual(by[0]["name"], "Your officers")
        partner = self._row(by, name="Rollout Partner")
        self.assertEqual((partner["rating"], partner["open_recommendations"]), (2.8, 1))
        [recommendation] = self.data["recommendations"]
        self.assertEqual(recommendation["id"], self.o1.id)
        self.assertEqual(recommendation["state"], "Awaiting your answer")
        self.assertTrue(recommendation["follow_up"].startswith("Partner engagement"))


# ── School self-assessments ──────────────────────────────────────────────────
class SsaTest(RolloutFixture):
    def test_has_an_ssa_this_fy_is_a_confirmed_record_for_the_year(self):
        found = rollout.schools_with_confirmed_ssa(
            [self.a1.id, self.a2.id, self.own1.id, self.b1.id], FY
        )
        self.assertEqual(found, {self.a1.id})
        self.assertEqual(
            rollout.schools_with_confirmed_ssa([self.own1.id], PREV), {self.own1.id}
        )

    def test_each_school_takes_the_first_state_it_qualifies_for(self):
        scope = rollout.resolve_rollout_scope(self.pl)
        states = {sid: s["state"] for sid, s in rollout.ssa_states(scope, FY).items()}
        self.assertEqual(
            states,
            {
                self.a1.id: rollout.SSA_CONFIRMED,
                self.a2.id: rollout.SSA_AWAITING,
                self.a3.id: rollout.SSA_SCHEDULED,
                self.b1.id: rollout.SSA_SCHEDULED,
                self.b2.id: rollout.SSA_SCHEDULED,
                self.own1.id: rollout.SSA_NOT_PLANNED,
            },
        )

    def test_rollout_per_officer_per_cluster_and_the_heatmap(self):
        data = rollout.ssa_rollout(rollout.resolve_rollout_scope(self.pl), FY)
        self.assertEqual(
            {
                k: data["summary"][k]
                for k in (
                    "portfolio",
                    "confirmed",
                    "awaiting",
                    "scheduled",
                    "not_planned",
                )
            },
            {
                "portfolio": 6,
                "confirmed": 1,
                "awaiting": 1,
                "scheduled": 3,
                "not_planned": 1,
            },
        )
        by_officer = {r["staff_id"]: r for r in data["officers"]}
        self.assertEqual(
            (
                by_officer[self.alice_sp.id]["confirmed"],
                by_officer[self.alice_sp.id]["scheduled"],
            ),
            (1, 1),
        )
        self.assertEqual(by_officer[self.ben_sp.id]["scheduled"], 2)
        self.assertEqual(by_officer[self.pl_sp.id]["not_planned"], 1)
        by_cluster = {r["cluster"]: r for r in data["clusters"]}
        self.assertEqual(
            (
                by_cluster[self.cluster_k.id]["portfolio"],
                by_cluster[self.cluster_k.id]["coverage"],
            ),
            (2, 50),
        )
        self.assertEqual(by_cluster[rollout.NO_CLUSTER]["portfolio"], 3)
        self.assertIn("Cluster K", [row["name"] for row in data["matrix"]["rows"]])
        self.assertEqual([h["code"] for h in data["matrix_headers"]][:2], ["CB", "WOG"])

    def test_school_lists_follow_the_team_and_refuse_anyone_else(self):
        team = rollout.school_list(self.pl, kind="ssa_not_planned", fy=FY)
        self.assertEqual([r["school_id"] for r in team["rows"]], [self.own1.id])
        awaiting = rollout.school_list(
            self.pl, kind="ssa_awaiting", fy=FY, cluster=self.cluster_k.id
        )
        self.assertEqual([r["school_id"] for r in awaiting["rows"]], [self.a2.id])
        untrained = rollout.school_list(
            self.pl, kind="not_trained", fy=FY, member=self.alice_sp.id
        )
        self.assertEqual([r["school_id"] for r in untrained["rows"]], [self.a3.id])
        with self.assertRaises(NotFoundError):
            rollout.school_list(
                self.pl, kind="ssa_not_planned", fy=FY, member=self.cara_sp.id
            )
        with self.assertRaises(NotFoundError):
            rollout.school_list(self.pl, kind="not_trained", cluster="elsewhere")


# ── Spiritual transformation ─────────────────────────────────────────────────
class SpiritualTest(RolloutFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.data = rollout.spiritual_rollout(
            cls.pl, rollout.resolve_rollout_scope(cls.pl), FY, TODAY
        )

    def test_team_averages_against_the_previous_cycle(self):
        scores = {s["code"]: s for s in self.data["scores"]}
        self.assertEqual((scores[CB]["score"], scores[CB]["delta"]), (3.0, -6.0))
        self.assertEqual((scores[WOG]["score"], scores[WOG]["delta"]), (4.0, 2.5))
        self.assertEqual(
            (self.data["summary"]["latest_fy"], self.data["summary"]["prev_fy"]),
            (FY, PREV),
        )
        alice = next(
            o for o in self.data["officers"] if o["staff_id"] == self.alice_sp.id
        )
        alice_cb = next(s for s in alice["scores"] if s["code"] == CB)
        self.assertEqual((alice_cb["score"], alice_cb["delta"]), (3.0, None))

    def test_weak_schools_show_whether_a_response_is_planned(self):
        rows = self.data["weak_schools"]
        self.assertEqual(
            [r["school_id"] for r in rows], [self.b1.id, self.own1.id, self.a1.id]
        )
        b1, own1, a1 = rows
        self.assertEqual((b1["state"], a1["state"]), ("No plan", "Planned"))
        self.assertEqual(
            b1["plan_url"], "", "a supervised school is its officer's to plan"
        )
        self.assertIn(f"school_id={self.own1.id}", own1["plan_url"])
        self.assertIn(f"focus_intervention={WOG}", own1["plan_url"])
        self.assertEqual(self.data["summary"]["weak_without_plan"], 2)

    def test_spiritual_programmes_by_family_and_deliverer(self):
        programmes = {r["id"]: r for r in self.data["programmes"]}
        self.assertEqual(
            (
                programmes[self.course_ct.id]["delivered"],
                programmes[self.course_ct.id]["to_deliver"],
            ),
            (2, 1),
        )
        self.assertEqual(programmes[self.cc_sel.id]["by_partner"], 1)
        self.assertEqual(programmes[self.camp.id]["family"], "Camps")
        self.assertEqual(self.data["summary"]["programmes_delivered"], 4)
        deliverers = {r["name"]: r for r in self.data["deliverers"]}
        self.assertEqual(deliverers["Alice Officer"]["christian_transformation"], 2)
        self.assertEqual(deliverers["Rollout Partner"]["cc_sel"], 1)
        self.assertEqual(deliverers["Your own portfolio"]["camp"], 1)
        self.assertEqual(deliverers["Ben Officer"]["to_deliver"], 1)
        self.assertEqual(self.data["deliverers"][-1]["kind"], "Training partner")

    def test_biblical_integration_ratings_from_shared_observations(self):
        summary = self.data["summary"]
        self.assertEqual((summary["observed"], summary["biblical"]), (2, 3.0))
        self.assertEqual(
            (summary["spiritual_observed"], summary["spiritual_biblical"]), (1, 4.0)
        )


# ── Pages ────────────────────────────────────────────────────────────────────
class PagesTest(RolloutFixture):
    def test_the_lead_opens_every_tab_with_registered_tiles(self):
        self.client.force_login(self.pl)
        for view, marker in (
            ("trainings", "data-rollout-interventions"),
            ("ssa", "data-rollout-ssa-clusters"),
            ("spiritual", "data-rollout-weak-schools"),
        ):
            with self.subTest(view=view):
                response = self.client.get(f"/programme-rollout?view={view}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, marker)
                self.assertContains(response, f'data-rollout-view="{view}"')
                self.assertNotContains(response, "Access Denied")
                tiles = response.context["metrics"]
                self.assertTrue(tiles)
                self.assertTrue(
                    all(t["metric_key"].startswith("programme_rollout_") for t in tiles)
                )
        default = self.client.get("/programme-rollout")
        self.assertEqual(default.context["view"], "trainings")

    def test_a_tab_click_returns_only_the_shell(self):
        self.client.force_login(self.pl)
        response = self.client.get(
            "/programme-rollout?view=ssa",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="programme-rollout-view-shell",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, 'id="rollout-filter-view"')
        self.assertContains(response, "data-rollout-ssa-officers")

    def test_the_year_filter_reaches_the_figures(self):
        self.client.force_login(self.pl)
        page = self.client.get(f"/programme-rollout?fy={PREV}")
        self.assertContains(page, 'name="fy"')
        self.assertEqual(page.context["fy"], PREV)
        self.assertEqual(page.context["rollout"]["summary"]["planned"], 0)
        current = self.client.get(f"/programme-rollout?fy={FY}")
        self.assertEqual(current.context["rollout"]["summary"]["planned"], 7)
        junk = self.client.get("/programme-rollout?fy=1999&view=nonsense")
        self.assertEqual((junk.context["fy"], junk.context["view"]), (FY, "trainings"))

    def test_who_opens_the_page(self):
        for user in (self.pl, self.admin):
            with self.subTest(role=user.active_role):
                self.client.force_login(user)
                response = self.client.get("/programme-rollout?view=ssa")
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Access Denied")
        _cd, _ = _person("roll-cd", "Rollout Director", "CountryDirector")
        _hr, _ = _person("roll-hr", "Rollout HR", "HumanResources")
        _ia, _ = _person("roll-ia-user", "Rollout IA", "ImpactAssessment")
        for user in (self.alice, self.rpl, _cd, _hr, _ia):
            for url in (
                "/programme-rollout",
                f"/programme-rollout/schools?kind=ssa_not_planned&member={self.alice_sp.id}",
            ):
                with self.subTest(role=user.active_role, url=url):
                    self.client.force_login(user)
                    response = self.client.get(url)
                    self.assertTrue(
                        response.status_code in (302, 403)
                        or b"Access Denied" in response.content,
                        response.status_code,
                    )
                    self.assertNotContains(
                        response,
                        "data-rollout-school-list",
                        status_code=response.status_code,
                    )

    def test_admin_chooses_the_lead_and_is_told_whose_team_it_is(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/programme-rollout?lead={self.other_pl_sp.id}")
        self.assertContains(response, "Quinn Lead&#x27;s team")
        self.assertContains(response, 'name="lead"')
        self.assertEqual(
            [r["name"] for r in response.context["rollout"]["officers"]],
            ["Cara Officer"],
        )
        drawer = self.client.get(
            f"/programme-rollout/schools?kind=ssa_confirmed&fy={FY}&lead={self.other_pl_sp.id}"
        )
        self.assertContains(drawer, "School RO-C1")

    def test_the_lead_cannot_choose_another_team(self):
        self.client.force_login(self.pl)
        response = self.client.get(f"/programme-rollout?lead={self.other_pl_sp.id}")
        self.assertNotContains(response, 'name="lead"')
        self.assertEqual(
            [r["name"] for r in response.context["rollout"]["officers"]][:2],
            ["Alice Officer", "Ben Officer"],
        )

    def test_the_school_list_drawer_lists_and_refuses(self):
        self.client.force_login(self.pl)
        listed = self.client.get(
            f"/programme-rollout/schools?kind=ssa_scheduled&member={self.ben_sp.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(listed, "data-rollout-school-list")
        self.assertContains(listed, "School RO-B1")
        self.assertContains(listed, "School RO-B2")
        self.assertContains(listed, "Handed to Rollout Partner")
        refused = self.client.get(
            f"/programme-rollout/schools?kind=ssa_scheduled&member={self.cara_sp.id}"
        )
        self.assertContains(refused, "data-rollout-refusal")
        self.assertContains(refused, "not on this team")
        self.assertNotContains(refused, "School RO-C1")
        unknown = self.client.get("/programme-rollout/schools?kind=everything")
        self.assertContains(unknown, "Choose which schools to list.")

    def test_the_payload_is_cached_per_view_year_and_day(self):
        with patch(
            "apps.core.cache_utils.cached_role_dashboard",
            side_effect=lambda kind, user, parts, build: build(),
        ) as cached:
            rollout.get_rollout(self.pl, view="spiritual", fy=PREV)
        kind, user, parts, _build = cached.call_args.args
        self.assertEqual((kind, user), ("programme_rollout", self.pl))
        self.assertEqual(parts, ("spiritual", PREV, "", TODAY.isoformat()))


# ── Cost ─────────────────────────────────────────────────────────────────────
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "programme-rollout-query-budget",
        }
    }
)
class QueryBudgetTest(RolloutFixture):
    """A view costs the same number of queries for two officers as for six.

    Measured against a cache this process owns: dev tests share a real Redis
    (apps/command_center/test_todo_query_budget.py). The payload cache is off
    in tests, so each measurement builds the page."""

    #: The page, the shell and the sidebar for the busiest tab, measured at
    #: well under this; a ceiling, never a target.
    REQUEST_CEILING = 90

    def _cost(self, view):
        with CaptureQueriesContext(connection) as ctx:
            rollout.build_rollout(self.pl, view=view, fy=FY, today=TODAY)
        return len(ctx)

    def _grow_the_team(self, count):
        for index in range(count):
            user, profile = _person(f"roll-extra-{index}", f"Extra {index}", "CCEO")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.pl_sp, supervisee=profile
            )
            school = School.objects.create(
                school_id=f"RO-X{index}",
                name=f"School RO-X{index}",
                region=self.region,
                district=self.district,
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
            Activity.objects.create(
                activity_type="training",
                school=school,
                fy=FY,
                quarter="Q4",
                delivery_type="staff",
                responsible_staff_id=profile.id,
                status="ia_verified",
                focus_intervention=CB,
                catalogue_item=self.course_ct,
                planned_date=TODAY - timedelta(days=5),
                scheduled_date=_at(TODAY - timedelta(days=5)),
                teachers_attended=3,
            )
            record = SsaRecord.objects.create(
                school=school,
                date_of_ssa=_at(TODAY - timedelta(days=30)),
                fy=FY,
                quarter="Q2",
                average_score=5.0,
                verification_status="confirmed",
                uploaded_by="roll-ia",
            )
            for intervention in (CB, WOG, *OTHER_SCORES):
                SsaScore.objects.create(
                    ssa_record=record,
                    intervention=intervention,
                    score=2.0 if intervention == CB else 7.0,
                )

    def test_no_view_costs_more_for_a_bigger_team(self):
        # The profile id is cached on the user instance after its first read;
        # read it once so both measurements start from the same state.
        self.assertTrue(self.pl.staff_profile_id)
        before = {view: self._cost(view) for view in rollout.VIEWS}
        self._grow_the_team(4)
        self.assertEqual(
            len(rollout.resolve_rollout_scope(self.pl).officers),
            6,
            "the fixture really grew the team",
        )
        after = {view: self._cost(view) for view in rollout.VIEWS}
        self.assertEqual(before, after)
        for view, cost in after.items():
            with self.subTest(view=view):
                self.assertLessEqual(cost, 30, f"{view} costs {cost} queries")

    def test_the_request_stays_under_a_ceiling(self):
        self.client.force_login(self.pl)
        for view in rollout.VIEWS:
            self.client.get(f"/programme-rollout?view={view}")  # warm
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get(f"/programme-rollout?view={view}")
            with self.subTest(view=view):
                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(len(ctx), self.REQUEST_CEILING)
