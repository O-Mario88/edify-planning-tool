"""Which trainings a school's entitlement counts (owner, 2026-10-06).

"School Improvement Planning training is universal every schools can attend.
for the rest of the trainings, Core gets 4 training and clients get 1
training ontop of School improvement training. therefore schools that are
added to school improvement training can have one more training. Special
project trainings like Technology, cc-sel.... are not restricted. any school
can be assigned to those but it is controlled byt project coordinator"

And, later the same day: "School improvement Planning is actually SSA
training." So the universal training is the catalogue's SSA Training.

Pinned here, each beside the ordinary training it differs from so the test
cannot pass by counting nothing at all:

* the universal training is SSA Training, and only it;
* at a Core school it is on neither half of the package's 2 + 2, takes no
  slot — in-school, with the visit written beside it, or as a group session —
  and is scheduled when the package's trainings are all taken;
* at a client school an in-school delivery of it is not the year's support
  visit, and is scheduled after that visit is used;
* a training under a Special Project is never refused over either rule, a
  project's visit still is, and project work still counts where it did;
* a Champion school still takes no training at all;
* renaming a scheduled training to or from the universal one moves it out of
  or into the package, and into it only where there is room;
* the slots SSA Training held before this rule are given back by the deploy
  repair, and nothing else is.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.test import TestCase

from apps.activities.cluster_attendance import set_invited_schools
from apps.activities.models import Activity
from apps.activities.services import _assert_schedule_entitlement
from apps.activities.training_change import change_training
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core_schools import cluster_credit
from apps.core_schools import test_core_visit_purposes as _core_doors
from apps.core_schools.models import CoreActivitySlot
from apps.core_schools.package_split import PARTNER, STAFF, TRAINING, VISIT
from apps.core_schools.test_package_split import _SplitFixture
from apps.partners.models import PartnerAssignment
from apps.planning import training_entitlement
from apps.planning.visit_gate import COMPANION_VISIT_PURPOSE, visit_gate
from apps.projects.models import Project
from apps.schools.models import School

IMPROVEMENT = "SSA_TRAINING"
LEADERSHIP = "SCHOOL_LEADERSHIP"


def _course(code: str) -> ActivityCatalogueItem:
    return ActivityCatalogueItem.objects.get(stable_code=code)


class _Entitlement(_SplitFixture):
    """A Core school with its package, a client school, and the two trainings."""

    def setUp(self):
        super().setUp()
        self.improvement = _course(IMPROVEMENT)
        self.leadership = _course(LEADERSHIP)
        self.client_school = School.objects.create(
            school_id="ENT-CLIENT",
            name="Entitled Client Primary",
            school_type="client",
            region=self.region,
            district=self.district,
        )
        self.project = Project.objects.create(
            name="Technology",
            category="intervention_specific",
            intervention="teaching_environment",
        )

    def _in_school(self, course, school=None, **fields):
        """An in-school training and the School Visit written beside it, saved
        in one transaction as the scheduling door saves them."""
        school = school or self.school
        with self.captureOnCommitCallbacks(execute=True):
            training = Activity.objects.create(
                activity_type="in_school_training",
                purpose_type="in_school_training",
                training_course=course,
                school=school,
                fy=self.fy,
                quarter="Q1",
                planned_date=date.today() + timedelta(days=3),
                status="scheduled",
                **fields,
            )
            visit = Activity.objects.create(
                activity_type="school_visit",
                purpose_type=COMPANION_VISIT_PURPOSE,
                school=school,
                fy=self.fy,
                quarter="Q1",
                planned_date=date.today() + timedelta(days=3),
                status="scheduled",
                **fields,
            )
            training.paired_school_visit = visit
            training.save(update_fields=["paired_school_visit", "updated_at"])
        return training, visit

    def _slots_of(self, *activities) -> list[str]:
        return sorted(
            f"{slot.activity_type[0].upper()}{slot.sequence_number}"
            for slot in CoreActivitySlot.objects.filter(
                activity_id__in=[a.id for a in activities]
            )
        )

    def _used(self) -> tuple[int, int]:
        split = self._split()
        return split.used(TRAINING, STAFF), split.used(VISIT, STAFF)

    def _entitled(self, activity_type, school, course=None, **data):
        _assert_schedule_entitlement(
            activity_type, school, self.fy, data, training_course=course
        )


class TheUniversalTraining(_Entitlement):
    def test_it_is_ssa_training_and_only_it(self):
        self.assertTrue(self.improvement.universal_training)
        self.assertFalse(self.leadership.universal_training)
        self.assertEqual(
            training_entitlement.universal_course_ids(), {self.improvement.id}
        )
        self.assertEqual(
            list(
                ActivityCatalogueItem.objects.filter(
                    universal_training=True
                ).values_list("stable_code", flat=True)
            ),
            [IMPROVEMENT],
        )

    def test_the_seed_run_on_every_deploy_keeps_it(self):
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        ActivityCatalogueItem.objects.filter(id=self.improvement.id).update(
            universal_training=False
        )

        seed_activity_catalogue(actor_id="reference_data")

        self.improvement.refresh_from_db()
        self.leadership.refresh_from_db()
        self.assertTrue(self.improvement.universal_training)
        self.assertFalse(self.leadership.universal_training)

    def test_only_a_training_is_ever_let_past_the_entitlement(self):
        never = training_entitlement.never_refused

        self.assertTrue(never("in_school_training", course=self.improvement))
        self.assertTrue(never("in_school_training", course=self.improvement.id))
        self.assertTrue(never("in_school_training", project_id=self.project.id))
        self.assertFalse(never("in_school_training", course=self.leadership))
        self.assertFalse(never("in_school_training"))
        # A visit is the school's visit, whatever it belongs to.
        self.assertFalse(never("school_visit", project_id=self.project.id))
        self.assertFalse(never("training_follow_up_visit", course=self.improvement))


class AtACoreSchool(_Entitlement):
    def test_an_ordinary_in_school_training_is_a_training_and_a_visit(self):
        training, visit = self._in_school(self.leadership)

        self.assertEqual(self._used(), (1, 1))
        self.assertEqual(self._slots_of(training, visit), ["T1", "V1"])

    def test_the_universal_training_is_on_neither_half_and_takes_no_slot(self):
        training, visit = self._in_school(self.improvement)

        self.assertEqual(self._used(), (0, 0))
        self.assertEqual(self._slots_of(training, visit), [])
        gate = visit_gate(self.school, self.fy)
        self.assertEqual((gate.staff_trainings, gate.staff_visits), (0, 0))

    def test_it_leaves_the_package_its_four_trainings(self):
        """Core gets four trainings on top of the universal one."""
        self._in_school(self.improvement)
        first, _ = self._in_school(self.leadership)
        second, _ = self._in_school(self.leadership)

        self.assertEqual(self._slots_of(first, second), ["T1", "T2"])
        self.assertEqual(self._split().used(TRAINING, STAFF), 2)
        # The Partner's two are untouched.
        self.assertTrue(self._split().is_open(TRAINING, PARTNER))

    def test_it_is_scheduled_when_staff_s_trainings_are_all_taken(self):
        self._in_school(self.leadership)
        self._in_school(self.leadership)

        with self.assertRaisesMessage(BadRequest, "2 staff core trainings"):
            self._entitled("in_school_training", self.school, self.leadership)
        self._entitled("in_school_training", self.school, self.improvement)

    def test_a_partner_delivering_it_is_not_held_by_the_partner_s_half(self):
        self._partner_activity("in_school_training", training_course=self.leadership)
        self._partner_activity("in_school_training", training_course=self.leadership)
        partner = {"deliveryType": "partner", "assignedPartnerId": self.partner.id}

        with self.assertRaisesMessage(BadRequest, "2 partner core trainings"):
            self._entitled(
                "in_school_training", self.school, self.leadership, **partner
            )
        self._entitled("in_school_training", self.school, self.improvement, **partner)

    def test_a_hand_over_of_it_holds_none_of_the_partner_s_two(self):
        from apps.partners.models import Partner

        def hand_over(partner, course):
            return PartnerAssignment.objects.create(
                school=self.school,
                partner=partner,
                status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
                expected_activity_type="in_school_training",
                purpose_of_visit="in_school_training",
                training_course=course,
            )

        hand_over(self.partner, self.leadership)
        self.assertEqual(self._split().used(TRAINING, PARTNER), 1)

        other = Partner.objects.create(name="Second Split Partner", active_status=True)
        hand_over(other, self.improvement)
        self.assertEqual(self._split().used(TRAINING, PARTNER), 1)

    def test_a_group_session_of_it_takes_no_training_slot(self):
        cluster = Cluster.objects.create(
            name="Entitlement Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )
        School.objects.filter(id=self.school.id).update(
            cluster_id=cluster.id, cluster_status="clustered"
        )

        def session(course):
            made = Activity.objects.create(
                activity_type="cluster_training",
                catalogue_item=course,
                cluster=cluster,
                fy=self.fy,
                quarter="Q1",
                status="scheduled",
                planned_date=date.today() + timedelta(days=10),
            )
            set_invited_schools(made, [self.school.id])
            return made

        universal, ordinary = session(self.improvement), session(self.leadership)

        self.assertFalse(cluster_credit.counts_in_package(universal))
        self.assertTrue(cluster_credit.counts_in_package(ordinary))
        self.assertEqual(self._slots_of(universal), [])
        self.assertEqual(self._slots_of(ordinary), ["T1"])
        self.assertEqual(self._split().used(TRAINING, STAFF), 1)

    def test_a_champion_school_still_takes_no_training(self):
        champion = School.objects.create(
            school_id="ENT-CHAMPION",
            name="Entitled Champion Primary",
            school_type="champion",
            region=self.region,
            district=self.district,
        )

        with self.assertRaisesMessage(BadRequest, "receives no training"):
            self._entitled("in_school_training", champion, self.improvement)
        with self.assertRaisesMessage(BadRequest, "receives no training"):
            self._entitled(
                "in_school_training",
                champion,
                self.leadership,
                projectId=self.project.id,
            )


class AtAClientSchool(_Entitlement):
    def test_an_ordinary_in_school_training_is_the_year_s_support_visit(self):
        self._in_school(self.leadership, school=self.client_school)

        gate = visit_gate(self.client_school, self.fy)
        self.assertEqual(gate.staff_visits, 1)
        self.assertFalse(gate.staff_can_schedule)

    def test_the_universal_training_is_not(self):
        """A school added to the universal training can have one more."""
        self._in_school(self.improvement, school=self.client_school)

        gate = visit_gate(self.client_school, self.fy)
        self.assertEqual(gate.staff_visits, 0)
        self.assertTrue(gate.staff_can_schedule)
        self._entitled("in_school_training", self.client_school, self.leadership)

    def test_and_one_more_is_one_more(self):
        self._in_school(self.improvement, school=self.client_school)
        self._in_school(self.leadership, school=self.client_school)

        with self.assertRaisesMessage(BadRequest, "has had its staff support visit"):
            self._entitled("in_school_training", self.client_school, self.leadership)
        with self.assertRaisesMessage(BadRequest, "has had its staff support visit"):
            self._entitled("training_follow_up_visit", self.client_school)

    def test_it_is_scheduled_after_the_support_visit_is_used(self):
        self._in_school(self.leadership, school=self.client_school)

        self._entitled("in_school_training", self.client_school, self.improvement)

    def test_core_trained_and_core_graduate_schools_take_it_the_same_way(self):
        for school_type in ("core_trained", "core_graduate"):
            with self.subTest(school_type=school_type):
                school = School.objects.create(
                    school_id=f"ENT-{school_type}",
                    name=f"Entitled {school_type}",
                    school_type=school_type,
                    region=self.region,
                    district=self.district,
                )
                self._in_school(self.leadership, school=school)
                self._in_school(self.improvement, school=school)

                self.assertEqual(visit_gate(school, self.fy).staff_visits, 1)
                self._entitled("in_school_training", school, self.improvement)
                with self.assertRaises(BadRequest):
                    self._entitled("in_school_training", school, self.leadership)


class ATrainingUnderASpecialProject(_Entitlement):
    def test_it_is_never_refused_at_a_core_school(self):
        self._in_school(self.leadership)
        self._in_school(self.leadership)

        with self.assertRaises(BadRequest):
            self._entitled("in_school_training", self.school, self.leadership)
        self._entitled(
            "in_school_training",
            self.school,
            self.leadership,
            projectId=self.project.id,
        )

    def test_it_is_never_refused_at_a_client_school(self):
        self._in_school(self.leadership, school=self.client_school)

        with self.assertRaises(BadRequest):
            self._entitled("in_school_training", self.client_school, self.leadership)
        self._entitled(
            "in_school_training",
            self.client_school,
            self.leadership,
            projectId=self.project.id,
        )

    def test_a_project_s_visit_keeps_the_school_s_rule(self):
        self._activity()
        self._activity("follow_up_visit")
        self._in_school(self.leadership, school=self.client_school)

        with self.assertRaisesMessage(BadRequest, "2 staff core visits"):
            self._entitled("school_visit", self.school, projectId=self.project.id)
        with self.assertRaisesMessage(BadRequest, "has had its staff support visit"):
            self._entitled(
                "training_follow_up_visit",
                self.client_school,
                projectId=self.project.id,
            )

    def test_project_work_still_counts_where_it_counted(self):
        """Only the refusal is lifted: a project's training is still one of
        the package's (owner, 2026-09-30), and still the client school's
        support visit."""
        training, visit = self._in_school(self.leadership, project_id=self.project.id)
        self._in_school(
            self.leadership, school=self.client_school, project_id=self.project.id
        )

        self.assertEqual(self._used(), (1, 1))
        self.assertEqual(self._slots_of(training, visit), ["T1", "V1"])
        self.assertEqual(visit_gate(self.client_school, self.fy).staff_visits, 1)


class RenamingAScheduledTraining(_Entitlement):
    """The Edit drawer's Training field (apps.activities.training_change)."""

    def _rename(self, training, course):
        with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
            return change_training(training, course.id, None)

    def test_named_the_universal_training_it_gives_its_slots_back(self):
        training, visit = self._in_school(self.leadership)
        self.assertEqual(self._slots_of(training, visit), ["T1", "V1"])

        self.assertTrue(self._rename(training, self.improvement))

        self.assertEqual(self._slots_of(training, visit), [])
        self.assertEqual(self._used(), (0, 0))
        self.assertEqual(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, status="Planned", activity_id__isnull=True
            ).count(),
            CoreActivitySlot.objects.filter(core_plan=self.plan).count(),
        )

    def test_named_an_ordinary_training_it_takes_its_slots(self):
        training, visit = self._in_school(self.improvement)

        self._rename(training, self.leadership)

        self.assertEqual(self._slots_of(training, visit), ["T1", "V1"])
        self.assertEqual(self._used(), (1, 1))

    def test_it_is_not_named_an_ordinary_training_where_there_is_no_room(self):
        self._in_school(self.leadership)
        self._in_school(self.leadership)
        training, _visit = self._in_school(self.improvement)

        with self.assertRaisesMessage(BadRequest, "2 staff core trainings"):
            self._rename(training, self.leadership)

        training.refresh_from_db()
        self.assertEqual(training.training_course_id, self.improvement.id)

    def test_nor_at_a_client_school_that_has_had_its_support_visit(self):
        self._in_school(self.leadership, school=self.client_school)
        training, _visit = self._in_school(self.improvement, school=self.client_school)

        with self.assertRaisesMessage(BadRequest, "has had its staff support visit"):
            self._rename(training, self.leadership)


class TheRepairGivesBackWhatItHeld(_Entitlement):
    """SSA Training was a training like any other until 2026-10-06, so the
    sessions already planned hold package slots. ``package_year.refile`` (the
    deploy migration core_schools 0011, and the management command) gives
    them back."""

    def _hold(self, kind, sequence, activity):
        """As it was written before the rule: the slot points at the work."""
        CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type=kind, sequence_number=sequence
        ).update(
            activity_id=activity.id,
            status="scheduled",
            owner="staff",
            scheduled_for=activity.planned_date.isoformat(),
        )

    def _before_the_rule(self):
        self.ssa_training, self.ssa_visit = self._in_school(self.improvement)
        self._hold("training", 1, self.ssa_training)
        self._hold("visit", 1, self.ssa_visit)
        self.own_training, self.own_visit = self._in_school(self.leadership)
        self.assertEqual(
            self._slots_of(self.ssa_training, self.ssa_visit), ["T1", "V1"]
        )
        self.assertEqual(
            self._slots_of(self.own_training, self.own_visit), ["T2", "V2"]
        )

    def _refile(self, **kwargs):
        from apps.activities.models import ClusterActivityAttendance
        from apps.core_schools import package_year
        from apps.core_schools.models import CorePlan

        lines = []
        kwargs.setdefault("universal_courses", {self.improvement.id})
        report = package_year.refile(
            CorePlan,
            CoreActivitySlot,
            Activity,
            ClusterActivityAttendance,
            School,
            from_fy=str(self.fy),
            out=lines.append,
            **kwargs,
        )
        return report, lines

    def test_an_in_school_one_and_its_visit_give_their_slots_back(self):
        self._before_the_rule()

        report, lines = self._refile()

        self.assertEqual(self._slots_of(self.ssa_training, self.ssa_visit), [])
        # The school's own training and visit move up into the gap.
        self.assertEqual(
            self._slots_of(self.own_training, self.own_visit), ["T1", "V1"]
        )
        self.assertEqual(
            {entry["activity"] for entry in report["released"]},
            {self.ssa_training.id, self.ssa_visit.id},
        )
        # The visit beside it is not handed a slot again by the next step.
        self.assertEqual(report["companion_credited"], [])
        self.assertTrue(any("a universal training is on top" in line for line in lines))
        self.assertEqual(self._used(), (1, 1))

    def test_a_dry_run_reports_it_and_writes_nothing(self):
        self._before_the_rule()

        report, _lines = self._refile(write=False)

        self.assertEqual(len(report["released"]), 2)
        self.assertEqual(
            self._slots_of(self.ssa_training, self.ssa_visit), ["T1", "V1"]
        )

    def test_running_it_twice_changes_nothing_more(self):
        self._before_the_rule()
        self._refile()

        report, _lines = self._refile()

        self.assertEqual(report["released"], [])
        self.assertEqual(report["moved"], [])
        self.assertEqual(
            self._slots_of(self.own_training, self.own_visit), ["T1", "V1"]
        )

    def test_without_being_told_the_training_it_leaves_everything(self):
        """Migrations 0008 to 0010 run the same code and name no training."""
        self._before_the_rule()

        report, _lines = self._refile(universal_courses=())

        self.assertEqual(report["released"], [])
        self.assertEqual(
            self._slots_of(self.ssa_training, self.ssa_visit), ["T1", "V1"]
        )

    def test_a_group_session_of_it_gives_its_slot_back(self):
        cluster = Cluster.objects.create(
            name="Repair Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )
        School.objects.filter(id=self.school.id).update(
            cluster_id=cluster.id, cluster_status="clustered"
        )

        def session(course, days):
            made = Activity.objects.create(
                activity_type="cluster_training",
                catalogue_item=course,
                cluster=cluster,
                fy=self.fy,
                quarter="Q1",
                status="scheduled",
                delivery_type="staff",
                planned_date=date.today() + timedelta(days=days),
            )
            set_invited_schools(made, [self.school.id])
            return made

        universal = session(self.improvement, 10)
        self._hold("training", 1, universal)
        ordinary = session(self.leadership, 20)
        self.assertEqual(self._slots_of(universal, ordinary), ["T1", "T2"])

        report, lines = self._refile()

        self.assertEqual(self._slots_of(universal), [])
        self.assertEqual(self._slots_of(ordinary), ["T1"])
        self.assertIn(universal.id, {e["activity"] for e in report["released"]})
        self.assertTrue(any("a universal training is on top" in line for line in lines))

    def test_the_deploy_migration_finds_it_by_its_code(self):
        """The column that marks it is filled by the seed after migrate, so
        the migration reads the stable code."""
        import importlib

        from django.apps import apps as live_apps

        migration = importlib.import_module(
            "apps.core_schools.migrations."
            "0011_universal_training_on_top_of_the_package"
        )
        self.assertEqual(
            set(migration.UNIVERSAL_TRAINING_CODES),
            set(
                ActivityCatalogueItem.objects.filter(
                    universal_training=True
                ).values_list("stable_code", flat=True)
            ),
        )
        self._before_the_rule()
        ActivityCatalogueItem.objects.update(universal_training=False)

        migration.forwards(live_apps, None)

        self.assertEqual(self._slots_of(self.ssa_training, self.ssa_visit), [])
        self.assertEqual(
            self._slots_of(self.own_training, self.own_visit), ["T1", "V1"]
        )


class TheCoreSchoolsDoors(_core_doors._CoreFixture):
    """Scheduled from the Core Schools page, the universal training is
    scheduled and the package's slot is left for one of its four."""

    def _schedule(self, course, **fields):
        return self._client(self.cceo).post(
            "/core-schools/schedule-training/action",
            {
                "school_id": self.school.school_id,
                "training_number": "1",
                "scheduled_date": _core_doors._today().isoformat(),
                "catalogue_item_id": course.id,
                "responsible_staff_id": self.cceo_sp.id,
                **fields,
            },
        )

    def test_the_training_drawer_schedules_it_and_takes_no_slot(self):
        course = _course(IMPROVEMENT)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._schedule(course)

        self.assertEqual(response.status_code, 200, response.content[:300])
        training = Activity.objects.get(school=self.school)
        self.assertEqual(training.training_course_id, course.id)
        self.assertEqual(training.focus_intervention, "leadership")
        self.assertFalse(
            CoreActivitySlot.objects.filter(activity_id=training.id).exists()
        )
        self.assertIsNone(self._slot("t", 1).activity_id)
        self.assertIn(
            "on top of the package", response.content.decode() + str(response.headers)
        )

    def test_it_is_scheduled_when_staff_s_two_trainings_are_taken(self):
        leadership = _course(LEADERSHIP)
        for days in (7, 14):
            Activity.objects.create(
                activity_type="in_school_training",
                training_course=leadership,
                school=self.school,
                fy=self.plan.fy,
                status="scheduled",
                planned_date=_core_doors._today() + timedelta(days=days),
                responsible_staff_id=self.cceo_sp.id,
            )

        refused = self._schedule(leadership)
        self.assertEqual(refused.status_code, 400)
        self.assertIn("2 staff core trainings", refused.content.decode())

        scheduled = self._schedule(_course(IMPROVEMENT))
        self.assertEqual(scheduled.status_code, 200, scheduled.content[:300])

    def test_the_visit_drawer_s_in_school_training_does_the_same(self):
        course = _course(IMPROVEMENT)

        with self.captureOnCommitCallbacks(execute=True):
            response = self._post_visit(
                purpose_of_visit="in_school_training", training_course_id=course.id
            )

        self.assertEqual(response.status_code, 200, response.content[:300])
        training = Activity.objects.get(
            school=self.school, activity_type="in_school_training"
        )
        visit = training.paired_school_visit
        self.assertIsNotNone(visit)
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                activity_id__in=[training.id, visit.id]
            ).exists()
        )


class NothingIsReadThroughAFilterThatHidesEverything(TestCase):
    """The filter the counts share leaves every ordinary row in."""

    def test_rows_with_no_training_at_all_pass_it(self):
        visit = Activity.objects.create(
            activity_type="school_visit", fy="2027", status="scheduled"
        )
        training = Activity.objects.create(
            activity_type="in_school_training",
            training_course=_course(LEADERSHIP),
            fy="2027",
            status="scheduled",
        )
        universal = Activity.objects.create(
            activity_type="in_school_training",
            training_course=_course(IMPROVEMENT),
            fy="2027",
            status="scheduled",
        )
        beside = Activity.objects.create(
            activity_type="school_visit",
            purpose_type=COMPANION_VISIT_PURPOSE,
            fy="2027",
            status="scheduled",
        )
        universal.paired_school_visit = beside
        universal.save(update_fields=["paired_school_visit", "updated_at"])

        kept = set(
            Activity.objects.filter(
                id__in=[visit.id, training.id, universal.id, beside.id]
            )
            .filter(training_entitlement.not_universal_q())
            .values_list("id", flat=True)
        )

        self.assertEqual(kept, {visit.id, training.id})
        self.assertTrue(training_entitlement.activity_is_universal(universal))
        self.assertTrue(training_entitlement.activity_is_universal(beside))
        self.assertFalse(training_entitlement.activity_is_universal(training))
        self.assertFalse(training_entitlement.activity_is_universal(visit))
