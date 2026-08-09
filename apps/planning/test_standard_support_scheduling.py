"""Ordinary support must be schedulable without inventing a Project.

The defect these tests pin was not a single bad `if`. It was an absence: the
Activity Catalogue held the programme's 28 named curriculum titles and nothing
else, so there was no catalogue row that costed ``school_visit`` at all, and
five of the eight SSA interventions (Financial Health, Leadership, Enrolment,
Government Requirements, Exposure to the Word of God) were answered ONLY by
cluster-delivered trainings.

The consequences compounded:

  * The drawer derives an activity's costing from the purpose a planner picks.
    With nothing costing ``school_visit`` the derivation returned nothing and
    the drawer refused — "no single approved Catalogue Activity costs this".
  * ``in_school_training`` had the opposite problem: five curriculum titles
    costed it, the resolver correctly refused to guess between them, and the
    refusal read the same to the planner.
  * A school whose weakest intervention was Financial Health had no
    school-level response to offer, so the drawer recommended activities for
    an intervention scoring 8.0/10 while the 2.0/10 one was unschedulable.
  * The only school-level items that did exist for the weak interventions were
    named ``*_PROJECT``, which is how "you need a Project first" became the
    working theory in the field.

So the fix is standard-support catalogue items plus a rule: ordinary field
support is schedulable in its planning context on a target intervention and a
stated rationale alone. It never requires a Special Project and never has to
be the SSA engine's top-ranked pick — while still creating one canonical
Activity that carries its intervention, source SSA and planning-time score.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.services import resolve_item_for_workflow_kind
from apps.clusters.models import Cluster
from apps.core.enums import ExecutorType, ParticipantMode, SsaIntervention
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner
from apps.projects.models import Project
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


def _schedulable_date():
    """The next date the calendar policy will accept (Sundays are blocked)."""
    day = timezone.localdate() + datetime.timedelta(days=3)
    while day.weekday() == 6:
        day += datetime.timedelta(days=1)
    return day


def _at(day):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(9)),
        timezone.get_current_timezone(),
    )


class StandardSupportBase(TestCase):
    """A school whose weakest intervention has no named curriculum response.

    Financial Health is deliberately the weakest here, and deliberately also
    used by a Special Project: scenario §34 exists because a planner in that
    exact situation was told to attach the work to the Project.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Standard Region")
        cls.district = District.objects.create(
            name="Standard District", region=cls.region, district_type="primary"
        )
        cls.sub_county = SubCounty.objects.create(
            name="Standard Sub County", district=cls.district
        )
        cls.cluster = Cluster.objects.create(
            name="Standard Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_type="mixed",
            status="active",
        )
        cls.school = School.objects.create(
            school_id="STD-001",
            name="Standard Support School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=180,
        )
        School.objects.filter(id=cls.school.id).update(
            cluster_id=cls.cluster.id, cluster_status="clustered"
        )
        cls.school.refresh_from_db()
        for index in range(4):
            member = School.objects.create(
                school_id=f"STD-MEM-{index}",
                name=f"Standard Member {index}",
                region=cls.region,
                district=cls.district,
                school_type="client",
            )
            School.objects.filter(id=member.id).update(
                cluster_id=cls.cluster.id, cluster_status="clustered"
            )

        cls.record = SsaRecord.objects.create(
            school=cls.school,
            fy=get_operational_fy(),
            date_of_ssa=timezone.localdate() - datetime.timedelta(days=30),
            verification_status="confirmed",
        )
        for intervention, score in {
            SsaIntervention.FINANCIAL_HEALTH: 2.0,
            SsaIntervention.LEADERSHIP: 3.5,
            SsaIntervention.ENROLMENT: 4.0,
            SsaIntervention.GOVERNMENT_REQUIREMENT: 6.0,
            SsaIntervention.EXPOSURE_TO_WORD_OF_GOD: 7.0,
            SsaIntervention.LEARNING_ENVIRONMENT: 8.0,
            SsaIntervention.TEACHING_ENVIRONMENT: 8.5,
            SsaIntervention.CHRISTLIKE_BEHAVIOUR: 9.0,
        }.items():
            SsaScore.objects.create(
                ssa_record=cls.record, intervention=intervention, score=score
            )

        cls.user = User.objects.create_user(
            email="standard-cceo@edify.org",
            name="Standard CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            user=cls.user, staff_number="ST-STD", country="Uganda"
        )
        StaffSchoolAssignment.objects.create(staff=cls.staff, school_id=cls.school.id)

    def setUp(self):
        # Cost snapshotting is a separate, already-covered chain. These tests
        # are about whether scheduling is PERMITTED and what it records.
        patcher = patch("apps.activities.services._apply_schedule_cost_snapshot")
        self.addCleanup(patcher.stop)
        self.cost_snapshot = patcher.start()

    def schedule(self, **payload):
        from apps.activities.services import create

        base = {
            "scheduledDate": _at(_schedulable_date()).isoformat(),
            "requireCatalogue": True,
        }
        return create({**base, **payload}, self.user)

    def item(self, code: str) -> ActivityCatalogueItem:
        return ActivityCatalogueItem.objects.get(stable_code=code)


class StandardSupportIsSchedulableWithoutAProjectTest(StandardSupportBase):
    def test_every_standard_purpose_resolves_to_exactly_one_costing(self):
        """The refusal a planner actually met, in its most literal form.

        ``resolve_item_for_workflow_kind`` is what turns "In-school Training"
        into the catalogue row that prices it. Returning None here is what the
        drawer surfaces as "no approved Catalogue Activity costs this" — and
        it did so for every standard purpose in the list.
        """
        for kind in (
            "school_visit",
            "in_school_training",
            "cluster_meeting",
            "cluster_training",
            "in_school_coaching_visit",
            "training_follow_up_visit",
            "school_visit_ssa_collection",
            "in_school_support",
            "donor_visit",
            "story_gathering_visit",
            "school_invitation",
            "social_visit",
        ):
            with self.subTest(kind=kind):
                resolved = resolve_item_for_workflow_kind(kind)
                self.assertIsNotNone(
                    resolved,
                    f"nothing costs {kind}, so the drawer cannot schedule it",
                )
                self.assertEqual(resolved.workflow_kind, kind)

    def test_in_school_training_without_a_project(self):
        """§34 — the end-to-end scenario, against the weakest intervention."""
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            activityPurposeText="Rebuild fee collection and bookkeeping practice",
            teachersAttended=8,
            leadersAttended=2,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.project_id)
        self.assertEqual(activity.focus_intervention, SsaIntervention.FINANCIAL_HEALTH)
        self.assertEqual(activity.source_ssa_id, self.record.id)
        self.assertEqual(activity.source_score, 2.0)
        self.assertEqual(activity.source_classification, "Critical")
        self.assertEqual(activity.status, "scheduled")
        self.assertEqual(activity.executor_type, ExecutorType.STAFF)

    def test_school_visit_without_a_project(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            activityPurposeText="Coach the head teacher on delegation",
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.project_id)
        self.assertEqual(activity.focus_intervention, SsaIntervention.LEADERSHIP)

    def test_cluster_meeting_without_a_project(self):
        result = self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item("STANDARD_CLUSTER_MEETING").id,
            focusIntervention=SsaIntervention.ENROLMENT,
            participantsPerSchool=3,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.project_id)
        self.assertEqual(activity.participants_per_school, 3)
        self.assertEqual(activity.cluster_school_count_snapshot, 5)
        self.assertEqual(activity.expected_participants, 15)

    def test_cluster_training_without_a_project(self):
        result = self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item("STANDARD_CLUSTER_TRAINING").id,
            focusIntervention=SsaIntervention.GOVERNMENT_REQUIREMENT,
            participantsPerSchool=2,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.project_id)
        self.assertEqual(activity.expected_participants, 10)

    def test_an_intervention_used_by_a_project_does_not_force_the_project(self):
        """§34.3 — Financial Health is also a Capital Project's concern.

        That is a fact about the Project, not a claim on the intervention. A
        school needing Financial Health support gets it whether or not it is
        in the Project.
        """
        project = Project.objects.create(
            name="Capital Project",
            code="CAPITAL-1",
            status="active",
            category="capital",
            intervention=SsaIntervention.FINANCIAL_HEALTH,
        )
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            teachersAttended=6,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.project_id)
        self.assertNotEqual(activity.project_id, project.id)
        self.assertEqual(activity.planning_source, "school_planning")

    def test_a_project_required_activity_still_refuses_without_one(self):
        """Relaxing the default must not remove the real rule."""
        item = self.item("STANDARD_IN_SCHOOL_TRAINING")
        ActivityCatalogueItem.objects.filter(id=item.id).update(requires_project=True)
        with self.assertRaises(BadRequest) as caught:
            self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=item.id,
                focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
                teachersAttended=6,
            )
        self.assertIn("Special Project", str(caught.exception))

    def test_activity_type_is_still_required(self):
        from apps.activities.services import create

        with self.assertRaises(BadRequest):
            create(
                {
                    "schoolId": self.school.school_id,
                    "scheduledDate": _at(_schedulable_date()).isoformat(),
                    "requireCatalogue": True,
                },
                self.user,
            )


class ParticipantModeTest(StandardSupportBase):
    """§8/§9 — a visit is not scheduled on a participant basis."""

    def test_the_visit_profile_declares_no_participants(self):
        profile = self.item("STANDARD_SCHOOL_VISIT").workflow_profile()
        self.assertEqual(profile["participantMode"], ParticipantMode.NONE)
        self.assertFalse(profile["requiresParticipants"])

    def test_participant_values_posted_on_a_visit_are_not_stored(self):
        """The API-client half of the rule.

        Hiding the field in JavaScript stops an honest planner. It does not
        stop a stale value from a previous drawer selection, and it does not
        stop a crafted request from moving the visit's cost.
        """
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            expectedParticipants=30,
            teachersAttended=25,
            leadersAttended=5,
            participantsPerSchool=4,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.expected_participants)
        self.assertIsNone(activity.teachers_attended)
        self.assertIsNone(activity.leaders_attended)
        self.assertIsNone(activity.participants_per_school)

    def test_visit_cost_never_sees_a_participant_value(self):
        """Whatever the request carried must not reach the costing engine."""
        from apps.activities.services import create

        with patch(
            "apps.budget.costing_service.preview",
            wraps=__import__(
                "apps.budget.costing_service", fromlist=["preview"]
            ).preview,
        ) as spy:
            create(
                {
                    "schoolId": self.school.school_id,
                    "catalogueItemId": self.item("STANDARD_SCHOOL_VISIT").id,
                    "focusIntervention": SsaIntervention.LEADERSHIP,
                    "expectedParticipants": 40,
                    "scheduledDate": _at(_schedulable_date()).isoformat(),
                    "requireCatalogue": True,
                },
                self.user,
            )
        self.assertTrue(spy.call_args_list, "the funded-scheduling gate did not run")
        for call in spy.call_args_list:
            payload = call.args[0]
            self.assertIsNone(payload.get("expectedParticipants"))
            self.assertIsNone(payload.get("teachersAttended"))

    def test_training_totals_are_summed_from_categories_by_the_backend(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            teachersAttended=12,
            leadersAttended=3,
            otherParticipants=2,
            # A disagreeing total from a stale browser preview loses.
            expectedParticipants=99,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.expected_participants, 17)

    def test_a_cluster_total_is_derived_not_accepted(self):
        result = self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item("STANDARD_CLUSTER_TRAINING").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            participantsPerSchool=3,
            expectedParticipants=999,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.expected_participants, 15)

    def test_a_bare_cluster_total_is_kept_rather_than_replaced_by_a_default(self):
        """§11 is a rule about the DRAWER, which has no total field.

        Discarding a total an API client did state looks stricter and costs
        money: `costing._participants_of` substitutes
        DEFAULT_TRAINING_PARTICIPANTS (25) when nothing reaches it, so
        throwing away a stated 15 prices twenty-five people. A number
        somebody stated beats a hardcoded default; a number DERIVED from
        cluster membership beats both, and that is asserted above.
        """
        result = self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item("STANDARD_CLUSTER_MEETING").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            expectedParticipants=12,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.expected_participants, 12)
        self.assertIsNone(activity.participants_per_school)


class CertifiedPartnerAgencyBookingTest(StandardSupportBase):
    """§15B/§17–§24 — staff book the agency; the agency does not re-schedule."""

    def setUp(self):
        super().setUp()
        self.agency = Partner.objects.create(
            name="Certified Agency X",
            active_status=True,
            is_certified=True,
            certification_status="certified",
            coverage_districts=[self.district.name],
        )
        self.plain_partner = Partner.objects.create(
            name="Ordinary Partner",
            active_status=True,
            is_certified=False,
        )

    def book(self, **overrides):
        payload = {
            "schoolId": self.school.school_id,
            "catalogueItemId": self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            "focusIntervention": SsaIntervention.FINANCIAL_HEALTH,
            "executorType": ExecutorType.CERTIFIED_PARTNER_AGENCY,
            "assignedPartnerId": self.agency.id,
            "teachersAttended": 10,
        }
        payload.update(overrides)
        return self.schedule(**payload)

    def test_one_activity_scheduled_immediately_with_the_agency_as_executor(self):
        result = self.book()
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.status, "partner_scheduled")
        self.assertEqual(activity.executor_type, ExecutorType.CERTIFIED_PARTNER_AGENCY)
        self.assertEqual(activity.delivery_type, "partner")
        self.assertEqual(activity.assigned_partner_id, self.agency.id)
        self.assertEqual(Activity.objects.filter(deleted_at__isnull=True).count(), 1)

    def test_the_staff_member_is_the_owner_and_not_the_executor(self):
        """§23 — the same delivery must not be executable work for two people."""
        result = self.book()
        activity = Activity.objects.get(id=result["id"])
        self.assertIsNone(activity.responsible_staff_id)
        self.assertEqual(activity.monitored_by_staff_id, self.staff.id)

    def test_the_booking_lands_in_the_agencys_my_plan(self):
        result = self.book()
        agency_user = User.objects.create_user(
            email="agency-x@partner.test",
            name="Agency X Admin",
            roles=["PartnerAdmin"],
            active_role="PartnerAdmin",
            password="x",
            is_active=True,
        )
        Partner.objects.filter(id=self.agency.id).update(user=agency_user)

        from apps.my_plan.services import get as my_plan

        activity = Activity.objects.get(id=result["id"])
        payload = my_plan(agency_user, {"fy": activity.fy, "period": "fy"})
        ids = {row["id"] for row in payload["items"]}
        self.assertIn(activity.id, ids)

    def test_an_uncertified_partner_cannot_be_booked(self):
        with self.assertRaises(BadRequest) as caught:
            self.book(assignedPartnerId=self.plain_partner.id)
        self.assertIn("not a Certified Partner Agency", str(caught.exception))

    def test_certified_agency_delivery_requires_a_selected_agency(self):
        with self.assertRaises(BadRequest):
            self.book(assignedPartnerId="")

    def test_an_agency_cannot_be_booked_twice_on_one_day(self):
        self.book()
        with self.assertRaises(BadRequest) as caught:
            self.book(schoolId=self.school.school_id, focusIntervention="leadership")
        self.assertIn("already has work booked", str(caught.exception))

    def test_an_activity_not_approved_for_agency_delivery_is_refused(self):
        with self.assertRaises(Exception) as caught:
            self.book(catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id)
        self.assertIn("Certified", str(caught.exception))

    def test_internal_staff_delivery_creates_no_partner_record(self):
        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            teachersAttended=5,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.executor_type, ExecutorType.STAFF)
        self.assertIsNone(activity.assigned_partner_id)
        self.assertEqual(activity.responsible_staff_id, self.staff.id)


class GroupTrainingUnderAProjectTest(StandardSupportBase):
    """Group Training is Project work, invited school by school.

    Two corrections here, and both are about not asking a question the system
    can already answer — or asking one it cannot.

    A Project declares which SSA interventions it exists to move. Asking the
    planner to pick the Project AND restate the intervention is two answers
    to one question; when they disagree, intervention analytics credit the
    work to something the Project is not trying to change.

    Participants, meanwhile, were multiplied by full cluster membership. A
    Literacy training does not reach the secondary and vocational schools in
    a mixed cluster, so that invited, catered and BUDGETED for people who
    were never coming. The planner states how many schools are invited; the
    total is derived from that.
    """

    def setUp(self):
        super().setUp()
        self.literacy = Project.objects.create(
            name="Literacy",
            code="SP-LIT",
            status="active",
            category="intervention_specific",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
        )

    def train(self, **overrides):
        payload = {
            "clusterId": self.cluster.id,
            "catalogueItemId": self.item("STANDARD_CLUSTER_TRAINING").id,
            "participantsPerSchool": 4,
        }
        payload.update(overrides)
        return self.schedule(**payload)

    def test_the_project_populates_the_target_intervention(self):
        result = self.train(projectId=self.literacy.id)
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.project_id, self.literacy.id)
        self.assertEqual(
            activity.focus_intervention, SsaIntervention.LEARNING_ENVIRONMENT
        )
        self.assertEqual(activity.activity_purpose_text, "Literacy")

    def test_cluster_drawer_workflow_requires_a_project(self):
        from apps.clusters.services import ClusterActionPlannerService

        with self.assertRaises(BadRequest) as caught:
            ClusterActionPlannerService.schedule_activity(
                {
                    "activityType": "cluster_training",
                    "clusterId": self.cluster.id,
                    "participantsPerSchool": 2,
                    "schoolsInvited": 3,
                    "scheduledDate": _at(_schedulable_date()).isoformat(),
                },
                self.user,
            )
        self.assertIn("Select the Project", str(caught.exception))

    def test_cluster_drawer_derives_intervention_server_side(self):
        from apps.clusters.services import ClusterActionPlannerService

        result = ClusterActionPlannerService.schedule_activity(
            {
                "activityType": "cluster_training",
                "clusterId": self.cluster.id,
                "projectId": self.literacy.id,
                "focusIntervention": SsaIntervention.LEADERSHIP,
                "participantsPerSchool": 2,
                "schoolsInvited": 3,
                "scheduledDate": _at(_schedulable_date()).isoformat(),
            },
            self.user,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(
            activity.focus_intervention, SsaIntervention.LEARNING_ENVIRONMENT
        )
        self.assertEqual(activity.expected_participants, 6)

    def test_a_stated_intervention_is_never_overridden_by_the_project(self):
        """Derivation fills a gap; it does not overrule a person."""
        result = self.train(
            projectId=self.literacy.id,
            focusIntervention=SsaIntervention.LEADERSHIP,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.focus_intervention, SsaIntervention.LEADERSHIP)

    def test_a_multi_intervention_project_uses_its_primary_and_supporting_targets(self):
        multi = Project.objects.create(
            name="Whole School",
            code="SP-WS",
            status="active",
            category="pilot",
            intervention=SsaIntervention.LEADERSHIP,
            target_interventions=[
                SsaIntervention.LEADERSHIP,
                SsaIntervention.FINANCIAL_HEALTH,
            ],
        )
        result = self.train(projectId=multi.id)
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.focus_intervention, SsaIntervention.LEADERSHIP)
        self.assertEqual(
            activity.secondary_focus_interventions,
            [SsaIntervention.FINANCIAL_HEALTH],
        )

    def test_the_total_is_per_school_times_schools_invited(self):
        """The cluster has 5 schools; only 3 qualify for this session."""
        result = self.train(projectId=self.literacy.id, schoolsInvited=3)
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.participants_per_school, 4)
        self.assertEqual(activity.schools_invited, 3)
        self.assertEqual(activity.cluster_school_count_snapshot, 5)
        self.assertEqual(activity.expected_participants, 12)

    def test_inviting_everyone_stays_the_default(self):
        """Every activity scheduled before this input existed meant this."""
        result = self.train(projectId=self.literacy.id)
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.schools_invited, 5)
        self.assertEqual(activity.expected_participants, 20)

    def test_more_schools_than_the_cluster_holds_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            self.train(projectId=self.literacy.id, schoolsInvited=9)
        self.assertIn("cannot invite 9", str(caught.exception))

    def test_zero_schools_invited_is_refused(self):
        with self.assertRaises(BadRequest):
            self.train(projectId=self.literacy.id, schoolsInvited=0)

    def test_a_fractional_school_count_is_refused_rather_than_rounded(self):
        with self.assertRaises(BadRequest) as caught:
            self.train(projectId=self.literacy.id, schoolsInvited="2.5")
        self.assertIn("whole number", str(caught.exception))

    def test_fewer_invited_schools_cost_less(self):
        """The point of the field: it must reach the budget, not just the record."""
        from apps.budget.costing import cost_for_activity

        rates = {
            "group_training_participant_meal_cost_per_head": 12000,
            "group_training_facilitation_fee": 150000,
            "group_training_venue_cost": 200000,
        }
        everyone = self.train(projectId=self.literacy.id)
        Activity.objects.filter(id=everyone["id"]).delete()
        some = self.train(projectId=self.literacy.id, schoolsInvited=3)
        activity = Activity.objects.get(id=some["id"])

        priced = cost_for_activity(
            {
                "activityType": "cluster_training",
                "expectedParticipants": activity.expected_participants,
            },
            rates,
        )
        # 12 people, not 20: 144,000 of meals rather than 240,000.
        self.assertEqual(priced.amount, 12 * 12000 + 150000 + 200000)

    def test_standard_support_does_not_need_mapping_into_the_project(self):
        """A Literacy project running a cluster training is running a cluster
        training. Requiring someone to first map the generic response into
        all five projects adds a setup step whose only effect is that
        scheduling fails until it is done."""
        from apps.activity_catalogue.models import ActivityProjectMapping

        self.assertFalse(
            ActivityProjectMapping.objects.filter(project=self.literacy).exists()
        )
        result = self.train(projectId=self.literacy.id)
        self.assertIsNotNone(result["id"])
