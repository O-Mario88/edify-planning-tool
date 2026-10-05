"""A project no SSA intervention measures: Alumni (owner, 2026-10-02).

"Alumni is not an intervention so it can be assigned to any school but it
should not restrict another project from being assigned to that school. for
example if a school A has edtech foundation, Alumni can still be assigned to
that school because it is not measured via ssa."

A project whose stated target is General alone is that kind of project. Its
activities are offered at every school it enrols, and its work is outside the
school's SSA-measured allowance: it is not the client school's support visit,
takes no side of a Core package, and waits beside the school's other support
with the same partner. The limit on how many partners hold one school stays.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.activities.services import _assert_schedule_entitlement
from apps.activity_catalogue.services import (
    recommend_activities,
    resolve_item_for_workflow_kind,
)
from apps.core.exceptions import BadRequest, ConflictError
from apps.core.fy import get_operational_fy
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.core_schools.package_split import (
    PARTNER,
    STAFF,
    TRAINING,
    VISIT,
    package_split,
)
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.visit_gate import visit_gate
from apps.projects.models import (
    GENERAL_INTERVENTION,
    Project,
    is_outside_ssa,
    projects_outside_ssa,
)
from apps.projects.services import create_project
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(name="Alumni Region")
        cls.district = District.objects.create(
            name="Alumni District", region=cls.region
        )
        cls.client_school = cls._school("ALU-1", "Alumni Client", "client")
        cls.core_school = cls._school("ALU-2", "Alumni Core", "core")
        cls.champion = cls._school("ALU-3", "Alumni Champion", "champion")
        cls.plan = CorePlan.objects.create(
            id=cplan_id("ALU-2", fy=cls.fy),
            school_id="ALU-2",
            fy=cls.fy,
            status="Active",
        )
        create_package_slots(cls.plan, "ALU-2", ["leadership"])
        cls.partner = Partner.objects.create(name="Alumni Partner", active_status=True)
        cls.coordinator = User.objects.create(
            id="alu-pc",
            email="alu-pc@edify.org",
            name="Alumni Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
            status="active",
        )
        StaffProfile.objects.create(
            id="alu-pc-staff",
            user=cls.coordinator,
            staff_number="PC-ALU",
            country="Uganda",
        )
        cls.visit_item = resolve_item_for_workflow_kind("school_visit")
        cls.alumni = cls._project("Alumni", [GENERAL_INTERVENTION])
        cls.edtech = cls._project("EdTech", ["learning_environment"])

    @classmethod
    def _school(cls, code, name, school_type):
        return School.objects.create(
            school_id=code,
            name=name,
            region=cls.region,
            district=cls.district,
            school_type=school_type,
        )

    @classmethod
    def _project(cls, name, targets):
        created = create_project(
            {
                "name": name,
                "category": "intervention_specific",
                "targetInterventions": targets,
                "catalogueItemIds": [cls.visit_item.id],
            },
            cls.coordinator,
        )
        project = Project.objects.get(id=created["id"])
        project.status = "active"
        project.save(update_fields=["status"])
        return project

    def _activity(self, school, activity_type="training_follow_up_visit", **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return Activity.objects.create(
                activity_type=activity_type,
                school=school,
                fy=self.fy,
                quarter="Q1",
                planned_date=date.today() + timedelta(days=3),
                status="scheduled",
                **fields,
            )


class WhichProjectsAreOutsideTheSsaTest(_Fixture):
    def test_general_alone_is_outside(self):
        self.assertFalse(self.alumni.measured_by_ssa)
        self.assertTrue(is_outside_ssa(self.alumni))
        self.assertTrue(is_outside_ssa(self.alumni.id))
        self.assertEqual(projects_outside_ssa(), frozenset({self.alumni.id}))

    def test_an_ssa_target_is_measured_with_or_without_general(self):
        self.assertTrue(self.edtech.measured_by_ssa)
        both = self._project("Both", [GENERAL_INTERVENTION, "leadership"])
        self.assertTrue(both.measured_by_ssa)

    def test_a_project_that_states_no_target_is_measured(self):
        """Saying nothing is not saying General: an older row keeps the rules
        it always had."""
        silent = Project.objects.create(name="Silent", category="pilot")
        self.assertTrue(silent.measured_by_ssa)
        self.assertFalse(is_outside_ssa(silent))

    def test_no_project_is_not_outside(self):
        self.assertFalse(is_outside_ssa(None))
        self.assertFalse(is_outside_ssa(""))


class OfferedAtAnAssessedSchoolTest(_Fixture):
    def test_its_activities_are_offered_whatever_the_ssa_says(self):
        """The school has a confirmed SSA; the project's list is still its
        own, not the school's ranked needs."""
        SsaRecord.objects.create(
            school=self.client_school,
            fy=self.fy,
            date_of_ssa=date.today(),
            verification_status="confirmed",
        )
        for executor_type in ("staff", "partner"):
            with self.subTest(executor_type=executor_type):
                result = recommend_activities(
                    school=self.client_school,
                    project=self.alumni,
                    executor_type=executor_type,
                    limit=100,
                )
                offered = {
                    row["catalogueItemId"]
                    for row in [*result["primary"], *result["otherEligible"]]
                }
                self.assertIn(self.visit_item.id, offered)
                self.assertEqual(
                    result["priority"]["classification"], "Not measured by the SSA"
                )


class TheSsaLendsItNoFocusTest(_Fixture):
    """An Alumni activity targets no SSA intervention. A school's weakest
    score used to be written onto it as its focus, and a plan with none was
    judged as one that forgot to name it."""

    def setUp(self):
        from apps.ssa.plan_alignment import SchoolNeed

        self.need = SchoolNeed(None, [], ["leadership"])
        self.plan = dict(
            activity_type="school_visit",
            mapping_modes={"any_ssa_intervention"},
            school=self.client_school,
            school_need_=self.need,
        )

    def test_the_schools_weakest_intervention_is_not_its_focus(self):
        from apps.ssa.plan_alignment import default_focus

        self.assertEqual(default_focus(**self.plan), "leadership")
        self.assertIsNone(default_focus(**self.plan, outside_ssa=True))

    def test_it_is_not_judged_for_naming_none(self):
        from apps.core.enums import SsaAlignment
        from apps.ssa.plan_alignment import assess, plan_nature

        self.assertEqual(
            plan_nature("school_visit", outside_ssa=True), "not_applicable"
        )
        judged = assess(focus=None, **self.plan)
        outside = assess(focus=None, outside_ssa=True, **self.plan)
        self.assertEqual(judged.alignment, SsaAlignment.NO_SSA)
        self.assertEqual(outside.alignment, SsaAlignment.NOT_APPLICABLE)

    def test_a_visit_that_collects_the_ssa_still_collects_it(self):
        from apps.ssa.plan_alignment import plan_nature

        self.assertEqual(
            plan_nature("school_visit", collects_ssa=True, outside_ssa=True),
            "collection",
        )

    def test_lists_read_it_as_general(self):
        from apps.projects.models import intervention_or_general

        self.assertEqual(intervention_or_general("", self.alumni.id), "general")
        self.assertEqual(intervention_or_general(None, self.alumni), "general")
        self.assertEqual(intervention_or_general("", self.edtech.id), "")
        self.assertEqual(intervention_or_general("", None), "")
        self.assertEqual(
            intervention_or_general("leadership", self.alumni.id), "leadership"
        )

    def test_a_plan_knows_its_project(self):
        from apps.ssa.plan_alignment import _outside_ssa

        alumni = self._activity(self.client_school, project_id=self.alumni.id)
        edtech = self._activity(self.client_school, project_id=self.edtech.id)
        plain = self._activity(self.client_school)
        self.assertTrue(_outside_ssa(alumni))
        self.assertFalse(_outside_ssa(edtech))
        self.assertFalse(_outside_ssa(plain))


class ClientSchoolSupportVisitTest(_Fixture):
    def _check(self, project=None):
        _assert_schedule_entitlement(
            "training_follow_up_visit",
            self.client_school,
            self.fy,
            {"deliveryType": "staff", "projectId": getattr(project, "id", None)},
        )

    def test_alumni_does_not_use_the_years_support_visit(self):
        self._activity(self.client_school, project_id=self.alumni.id)
        gate = visit_gate(self.client_school, self.fy)
        self.assertEqual(gate.staff_visits, 0)
        self.assertTrue(gate.staff_can_schedule)
        self._check(self.edtech)  # not refused

    def test_alumni_is_not_refused_once_the_visit_is_used(self):
        self._activity(self.client_school, project_id=self.edtech.id)
        with self.assertRaises(BadRequest):
            self._check(self.edtech)
        with self.assertRaises(BadRequest):
            self._check()
        self._check(self.alumni)

    def test_a_champion_school_takes_alumni_work(self):
        with self.assertRaises(BadRequest):
            _assert_schedule_entitlement(
                "training_follow_up_visit", self.champion, self.fy, {}
            )
        _assert_schedule_entitlement(
            "training_follow_up_visit",
            self.champion,
            self.fy,
            {"projectId": self.alumni.id},
        )


class CorePackageTest(_Fixture):
    def test_alumni_takes_no_side_and_no_slot(self):
        visit = self._activity(self.core_school, project_id=self.alumni.id)
        training = self._activity(
            self.core_school, "in_school_training", project_id=self.alumni.id
        )
        partner_visit = self._activity(
            self.core_school,
            project_id=self.alumni.id,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
        )
        split = package_split(self.core_school, self.fy)
        self.assertEqual(
            (
                split.used(VISIT, STAFF),
                split.used(TRAINING, STAFF),
                split.used(VISIT, PARTNER),
            ),
            (0, 0, 0),
        )
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                activity_id__in=[visit.id, training.id, partner_visit.id]
            ).exists()
        )

    def test_another_projects_work_still_counts(self):
        self._activity(self.core_school, project_id=self.edtech.id)
        self.assertEqual(package_split(self.core_school, self.fy).used(VISIT, STAFF), 1)

    def test_alumni_is_not_refused_by_a_full_side(self):
        for _ in range(2):
            self._activity(self.core_school, project_id=self.edtech.id)
        with self.assertRaises(BadRequest):
            _assert_schedule_entitlement(
                "training_follow_up_visit",
                self.core_school,
                self.fy,
                {"projectId": self.edtech.id},
            )
        _assert_schedule_entitlement(
            "training_follow_up_visit",
            self.core_school,
            self.fy,
            {"projectId": self.alumni.id},
        )

    def test_an_alumni_hand_over_is_not_the_partners_half(self):
        for number in (1, 2):
            PartnerAssignment.objects.create(
                school=self.core_school,
                partner=self.partner,
                status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
                support_type="Visit",
                visit_number=str(number),
            )
        fields = dict(
            school=self.core_school,
            partner=self.partner,
            expected_activity_type="training_follow_up_visit",
            purpose_of_visit="training_follow_up",
        )
        # The half, held with its switch on: every project's hand-over goes
        # past it for now (owner, 2026-10-05; apps.partners.handover_policy),
        # and Alumni's does whichever way the switch is.
        with mock.patch(
            "apps.partners.handover_policy.PROJECT_HANDOVERS_KEEP_SCHOOL_RULES", True
        ):
            with self.assertRaises(BadRequest):
                partner_services.create_assignment(project=self.edtech, **fields)
            handover = partner_services.create_assignment(project=self.alumni, **fields)
        self.assertTrue(handover.outside_ssa)
        self.assertEqual(
            package_split(self.core_school, self.fy).used(VISIT, PARTNER), 2
        )


class SamePartnerTest(_Fixture):
    def _hand(self, project):
        return partner_services.create_assignment(
            school=self.client_school,
            partner=self.partner,
            project=project,
            expected_activity_type="training_follow_up_visit",
            purpose_of_visit="training_follow_up",
        )

    def test_alumni_waits_beside_the_schools_other_support(self):
        first = self._hand(self.edtech)
        alumni = self._hand(self.alumni)
        self.assertFalse(first.outside_ssa)
        self.assertTrue(alumni.outside_ssa)

    def test_the_order_does_not_matter(self):
        self._hand(self.alumni)
        self._hand(self.edtech)
        self.assertEqual(
            PartnerAssignment.objects.filter(school=self.client_school).count(), 2
        )

    def test_alumni_is_still_handed_to_a_partner_once(self):
        self._hand(self.alumni)
        with self.assertRaises(ConflictError):
            self._hand(self.alumni)

    def test_two_measured_projects_still_wait_their_turn(self):
        self._hand(self.edtech)
        other = self._project("CC-SEL", ["christlike_behaviour"])
        with self.assertRaises(ConflictError):
            self._hand(other)

    def test_an_alumni_hand_over_does_not_hold_the_school_for_the_gate(self):
        self._hand(self.alumni)
        gate = visit_gate(self.client_school, self.fy)
        self.assertEqual(gate.partner_pending, 0)
        self.assertFalse(
            PartnerAssignment.has_open_assignment(self.client_school, self.partner)
        )
