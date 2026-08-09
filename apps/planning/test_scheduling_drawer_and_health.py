"""The drawer, the availability service, and the guards that keep them honest.

The scheduling drawer used to be one universal form holding every field any
activity might need, with the irrelevant ones hidden by ``x-show``. That is
not a rule, it is a suggestion: a hidden input still submits. A planner who
typed 30 participants for a Training and then switched the purpose to a Visit
posted 30 participants on a visit, and participant counts multiply into cost.

So the drawer is generated from the selected activity's Workflow Profile, the
values it no longer has a field for are cleared, and the backend clears them
again on arrival. These tests hold all three layers.
"""

from __future__ import annotations

import datetime
import json
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.activity_catalogue.availability import (
    CLUSTER,
    SCHOOL,
    available_activity_types,
)
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.activity_catalogue.scheduling_health import scheduling_health
from apps.clusters.models import Cluster
from apps.core.enums import ExecutorType, ParticipantMode, SsaIntervention
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.projects.models import Project
from apps.schools.models import School


def _check(report: dict, key: str) -> dict:
    return next(c for c in report["checks"] if c["key"] == key)


class AvailableActivityTypeServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Avail Region")
        cls.district = District.objects.create(
            name="Avail District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="AVAIL-1",
            name="Avail School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.cluster = Cluster.objects.create(
            name="Avail Cluster",
            region=cls.region,
            district=cls.district,
            status="active",
        )

    def test_school_context_offers_standard_support_first(self):
        rows = available_activity_types(planning_context=SCHOOL, school=self.school)
        self.assertTrue(rows)
        kinds = [row["workflowKind"] for row in rows]
        self.assertIn("school_visit", kinds)
        self.assertIn("in_school_training", kinds)
        # Standard support is the ordinary answer and sorts ahead of the
        # programme's named curriculum titles. Burying "School Visit" under
        # twelve of those is how planners concluded a Project was required.
        self.assertTrue(rows[0]["standardSupport"])

    def test_cluster_context_offers_cluster_work(self):
        rows = available_activity_types(planning_context=CLUSTER, cluster=self.cluster)
        kinds = {row["workflowKind"] for row in rows}
        self.assertIn("cluster_meeting", kinds)
        self.assertIn("cluster_training", kinds)
        self.assertNotIn("school_visit", kinds)

    def test_an_intervention_never_removes_standard_support(self):
        """The heart of the correction.

        Financial Health has no school-level named curriculum response. Under
        the old rule that meant "nothing to schedule here"; now it means the
        standard responses answer it, as they answer any intervention.
        """
        rows = available_activity_types(
            planning_context=SCHOOL,
            school=self.school,
            intervention=SsaIntervention.FINANCIAL_HEALTH,
        )
        kinds = {row["workflowKind"] for row in rows}
        self.assertIn("school_visit", kinds)
        self.assertIn("in_school_training", kinds)

    def test_no_standard_support_item_requires_a_project(self):
        for row in available_activity_types(
            planning_context=SCHOOL, school=self.school
        ):
            if row["standardSupport"]:
                self.assertFalse(
                    row["requiresProject"],
                    f"{row['label']} would block ordinary support on a Project",
                )

    def test_the_profile_states_the_participant_rule_for_each_type(self):
        rows = {
            row["workflowKind"]: row
            for row in available_activity_types(
                planning_context=SCHOOL, school=self.school
            )
        }
        self.assertEqual(rows["school_visit"]["participantMode"], ParticipantMode.NONE)
        self.assertFalse(rows["school_visit"]["requiresParticipants"])
        self.assertTrue(rows["in_school_training"]["requiresParticipants"])


class ScheduleDrawerFieldsTest(TestCase):
    """§8/§10 — what the drawer renders, per Workflow Profile."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Drawer Region")
        cls.district = District.objects.create(
            name="Drawer District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="DRAWER-STD-1",
            name="Drawer Standard School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.user = User.objects.create(
            id="drawer-std-admin",
            email="drawer-std@edify.org",
            name="Drawer Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )

    def _drawer(self) -> str:
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/planning/schedule-modal?school_id={self.school.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_participant_inputs_are_conditional_not_always_present(self):
        """A field inside <template x-if> does not exist in the DOM until its
        condition holds, so it cannot submit a stale value. A field merely
        hidden with x-show does exist, and does submit."""
        html = self._drawer()
        self.assertIn('name="expected_participants"', html)
        for needle in (
            'x-if="showCategories"',
            'x-if="showParticipants && !showCategories"',
        ):
            self.assertIn(needle, html, "participant fields are not profile-gated")
        self.assertNotIn(
            "x-show=\"['training', 'in_school_training',",
            html,
            "the old always-rendered participant field is still in the drawer",
        )

    def test_the_drawer_carries_a_workflow_profile_for_every_purpose(self):
        html = self._drawer()
        self.assertIn("profiles:", html)
        self.assertIn("onPurposeChange()", html)
        self.assertIn("onDeliveryChange(", html)

    def test_switching_purpose_clears_participant_state(self):
        html = self._drawer()
        self.assertIn("this.plannedParticipants = ''", html)
        self.assertIn("this.teacherCount = ''", html)

    def test_switching_delivery_away_from_agency_clears_the_agency(self):
        html = self._drawer()
        self.assertIn("this.selectedAgency = ''", html)

    def test_the_drawer_never_demands_a_project(self):
        html = self._drawer()
        self.assertNotIn("Create a Project", html)
        self.assertNotIn("requires a Project to continue", html)


class ClusterDrawerDeliveryTest(TestCase):
    """§15 — the cluster drawer's "Certified Partner Agency" must mean it.

    It offered that label and submitted ``delivery_type=partner``, which is
    the ASSIGNED-partner workflow: the activity was left waiting for the
    agency to pick a date staff had already picked. One label, two different
    commitments.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="ClusterDrawer Region")
        cls.district = District.objects.create(
            name="ClusterDrawer District", region=cls.region
        )
        cls.cluster = Cluster.objects.create(
            name="ClusterDrawer Cluster",
            region=cls.region,
            district=cls.district,
            status="active",
        )
        for index in range(3):
            School.objects.create(
                school_id=f"CLUSTER-DRAWER-{index}",
                name=f"Cluster Drawer School {index}",
                region=cls.region,
                district=cls.district,
                school_type="client",
                cluster_id=cls.cluster.id,
                cluster_status="clustered",
            )
        cls.literacy = Project.objects.create(
            name="Literacy",
            code="SP-LIT-DRAWER",
            category="intervention_specific",
            status="active",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
        )
        cls.edtech_foundations = Project.objects.create(
            name="EdTech Foundations",
            code="SP-ETF-DRAWER",
            category="intervention_specific",
            status="active",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
        )
        cls.edtech_integration = Project.objects.create(
            name="EdTech Integration",
            code="SP-ETI-DRAWER",
            category="intervention_specific",
            status="active",
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
        )
        cls.paused = Project.objects.create(
            name="Paused Teacher Pedagogy",
            code="SP-TP-DRAWER",
            category="intervention_specific",
            status="paused",
            intervention=SsaIntervention.TEACHING_ENVIRONMENT,
        )
        cls.certified = Partner.objects.create(
            name="Certified Cluster Agency",
            active_status=True,
            is_certified=True,
            coverage_districts=[cls.district.name],
        )
        cls.uncertified = Partner.objects.create(
            name="Uncertified Cluster Partner",
            active_status=True,
            is_certified=False,
        )
        cls.user = User.objects.create(
            id="cluster-drawer-admin",
            email="cluster-drawer@edify.org",
            name="Cluster Drawer Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )

    def _drawer(self) -> str:
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/planning/schedule-modal?cluster_id={self.cluster.id}&action=training",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_it_submits_the_agency_booking_workflow(self):
        html = self._drawer()
        self.assertIn('value="certified_partner_agency"', html)
        self.assertIn('name="executor_type"', html)

    def test_only_certified_agencies_are_offered(self):
        html = self._drawer()
        self.assertIn(self.certified.name, html)
        self.assertNotIn(self.uncertified.name, html)

    def test_training_asks_for_a_created_project_and_invited_school_count(self):
        html = self._drawer()
        self.assertIn('name="participants_per_school"', html)
        self.assertIn('name="schools_invited"', html)
        self.assertIn('max="3"', html)
        self.assertIn('name="project_id"', html)
        self.assertIn("Literacy", html)
        self.assertIn("EdTech Foundations", html)
        self.assertIn("EdTech Integration", html)
        self.assertIn("Paused Teacher Pedagogy", html)
        self.assertIn("Paused", html)
        self.assertIn('name="focus_intervention"', html)
        self.assertNotIn("Activity Goal / Purpose", html)

    def test_cluster_card_drawer_uses_the_same_project_training_contract(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/clusters/planner-drawer?cluster_id={self.cluster.id}"
            "&activity_type=training&fixed_cluster=true",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('name="project_id"', html)
        self.assertIn("EdTech Foundations", html)
        self.assertIn("EdTech Integration", html)
        self.assertIn('name="schools_invited"', html)
        self.assertIn('name="participants_per_school"', html)
        self.assertNotIn("Purpose for Meeting / Training", html)
        self.assertNotIn("Session Goal", html)

    def test_cluster_card_cost_preview_refreshes_for_numeric_input(self):
        html = self._cluster_card_drawer()
        self.assertEqual(
            html.count('hx-trigger="input changed delay:250ms, change"'), 2
        )

    def test_cost_preview_derives_training_total_from_source_fields(self):
        client = Client()
        client.force_login(self.user)
        with patch(
            "apps.frontend.views.cluster_views._get_cost_preview_data",
            return_value={
                "catalogue_version": "test",
                "lines": [],
                "amount": 0,
                "can_schedule": True,
                "blockers": [],
            },
        ) as preview:
            response = client.get(
                "/clusters/cost-preview",
                {
                    "activity_type": "training",
                    "cluster_id": self.cluster.id,
                    # Deliberately stale: Alpine may not have updated this
                    # hidden field when HTMX starts serializing the form.
                    "expected_participants": "60",
                    "participants_per_school": "3",
                    "schools_invited": "12",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200)
        preview.assert_called_once_with("training", 36, self.cluster.id)

    def _cluster_card_drawer(self) -> str:
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/clusters/planner-drawer?cluster_id={self.cluster.id}"
            "&activity_type=training&fixed_cluster=true",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_training_post_cannot_bypass_the_required_project(self):
        client = Client()
        client.force_login(self.user)
        response = client.post(
            "/planning/schedule-action",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "cluster_training",
                "scheduled_date": timezone.localdate() + datetime.timedelta(days=2),
                "participants_per_school": "2",
                "schools_invited": "2",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Select the Project", response.content.decode("utf-8"))

    def test_project_training_post_schedules_with_derived_intervention_and_total(self):
        client = Client()
        client.force_login(self.user)
        scheduled = timezone.localdate() + datetime.timedelta(days=2)
        while scheduled.weekday() == 6:
            scheduled += datetime.timedelta(days=1)
        response = client.post(
            "/planning/schedule-action",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "cluster_training",
                "project_id": self.edtech_foundations.id,
                # A forged intervention must lose to Project configuration.
                "focus_intervention": SsaIntervention.LEADERSHIP,
                "scheduled_date": scheduled.isoformat(),
                "participants_per_school": "2",
                "schools_invited": "2",
                "delivery_type": "staff",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        activity = Activity.objects.get(project_id=self.edtech_foundations.id)
        self.assertEqual(
            activity.focus_intervention, SsaIntervention.LEARNING_ENVIRONMENT
        )
        self.assertEqual(activity.schools_invited, 2)
        self.assertEqual(activity.expected_participants, 4)


class SchedulingHealthTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Health Region")
        cls.district = District.objects.create(
            name="Health District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="HEALTH-1",
            name="Health School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    def test_a_clean_platform_is_green(self):
        report = scheduling_health()
        failing = [c["key"] for c in report["checks"] if c["status"] == "fail"]
        self.assertEqual(failing, [])
        self.assertTrue(report["healthy"])

    def test_it_notices_when_standard_support_loses_its_catalogue_item(self):
        """The early-warning check for the original defect.

        Retiring the standard school-visit item puts the platform straight
        back into "no approved Catalogue Activity costs a school visit".
        """
        ActivityCatalogueItem.objects.filter(
            stable_code="STANDARD_SCHOOL_VISIT"
        ).update(status="retired")
        report = scheduling_health()
        check = _check(report, "scheduling_standard_support_available")
        self.assertEqual(check["status"], "fail")
        self.assertIn("school_visit", check["detail"])

    def test_it_notices_a_visit_carrying_participants(self):
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            status="scheduled",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="STANDARD_SCHOOL_VISIT"
            ),
            expected_participants=25,
        )
        check = _check(scheduling_health(), "scheduling_visit_participant_values")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["actual"], 1)

    def test_it_notices_a_booked_agency_still_asked_to_schedule(self):
        agency = Partner.objects.create(
            name="Health Agency", active_status=True, is_certified=True
        )
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            status="assigned_to_partner",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            delivery_type="partner",
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY,
            assigned_partner_id=agency.id,
        )
        check = _check(scheduling_health(), "scheduling_agency_awaiting_schedule")
        self.assertEqual(check["status"], "fail")

    def test_a_cancelled_booking_is_history_not_a_fault(self):
        agency = Partner.objects.create(
            name="Cancelled Agency", active_status=True, is_certified=True
        )
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            status="cancelled",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            delivery_type="partner",
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY,
            assigned_partner_id=agency.id,
        )
        self.assertTrue(scheduling_health()["healthy"])


class RepairCommandTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Repair Region")
        cls.district = District.objects.create(
            name="Repair District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="REPAIR-1",
            name="Repair School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.visit_item = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT"
        )

    def _stale_visit(self):
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            status="scheduled",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            catalogue_item=self.visit_item,
            expected_participants=30,
            teachers_attended=25,
        )

    def _run(self, *args) -> dict:
        out = StringIO()
        call_command("repair_scheduling_rules", *args, stdout=out)
        return json.loads(out.getvalue())

    def test_dry_run_reports_without_changing_anything(self):
        activity = self._stale_visit()
        report = self._run("--dry-run")
        self.assertEqual(report["repaired"]["visitParticipantsCleared"], 1)
        activity.refresh_from_db()
        self.assertEqual(activity.expected_participants, 30)

    def test_it_clears_stale_visit_participants_and_is_idempotent(self):
        activity = self._stale_visit()
        first = self._run()
        self.assertEqual(first["repaired"]["visitParticipantsCleared"], 1)
        activity.refresh_from_db()
        self.assertIsNone(activity.expected_participants)
        self.assertIsNone(activity.teachers_attended)

        second = self._run()
        self.assertEqual(second["repaired"]["visitParticipantsCleared"], 0)

    def test_an_artificial_looking_project_is_reported_never_unlinked(self):
        """§31 — the correct value here depends on what a person intended.

        Standard support attached to a Project may be the old workaround, or
        may be genuine Project delivery. Unlinking on suspicion would move
        money between programmes on a guess.
        """
        from apps.projects.models import Project

        project = Project.objects.create(
            name="Repair Project", code="REPAIR-P", status="active", category="pilot"
        )
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            status="scheduled",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            catalogue_item=self.visit_item,
            project_id=project.id,
        )
        report = self._run()
        flagged = [
            row["activityId"]
            for row in report["manualReview"]["possibleArtificialProject"]
        ]
        self.assertIn(activity.id, flagged)
        activity.refresh_from_db()
        self.assertEqual(activity.project_id, project.id)

    def test_a_booked_agency_is_not_left_asked_to_schedule(self):
        agency = Partner.objects.create(
            name="Repair Agency", active_status=True, is_certified=True
        )
        activity = Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            status="assigned_to_partner",
            fy="2026",
            quarter="Q1",
            planned_date=timezone.localdate(),
            scheduled_date=timezone.now(),
            delivery_type="partner",
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY,
            assigned_partner_id=agency.id,
            responsible_staff_id="some-staff-id",
        )
        report = self._run()
        self.assertEqual(report["repaired"]["agencyBookingStatusCorrected"], 1)
        self.assertEqual(report["repaired"]["agencyStaffExecutorCleared"], 1)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "partner_scheduled")
        self.assertIsNone(activity.responsible_staff_id)
        self.assertEqual(activity.monitored_by_staff_id, "some-staff-id")


class PartnerMyPlanActionTest(TestCase):
    """§20 — a booked agency prepares, then starts. It never re-schedules."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Action Region")
        cls.district = District.objects.create(
            name="Action District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="ACTION-1",
            name="Action School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    def _activity(self, planned_date):
        return Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            status="partner_scheduled",
            fy="2026",
            quarter="Q1",
            planned_date=planned_date,
            delivery_type="partner",
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY,
        )

    def test_on_the_day_the_action_is_start(self):
        from apps.my_plan.services import compute_next_action

        today = timezone.localdate()
        action = compute_next_action(self._activity(today), today)
        self.assertEqual(action["action"], "start")

    def test_before_the_day_the_action_is_prepare_never_schedule(self):
        from apps.my_plan.services import compute_next_action

        today = timezone.localdate()
        action = compute_next_action(
            self._activity(today + datetime.timedelta(days=5)), today
        )
        self.assertNotEqual(action["action"], "schedule")
        self.assertEqual(action["action"], "prepare")

    def test_the_agency_gets_a_todo_not_just_a_notification(self):
        """§21 — an obligation nothing carries forward is not an obligation.

        A booked agency used to fall through to the generic "View Details"
        next action, which the To-Do service filters out entirely: the
        booking notification was the only thing telling them, and it scrolled
        away. The To-Do query also had no partner branch at all — it scoped
        by staff identifiers, which a partner organisation never has.
        """
        from apps.command_center.todo_service import get_todos

        agency = Partner.objects.create(
            name="Todo Agency", active_status=True, is_certified=True
        )
        agency_user = User.objects.create_user(
            email="todo-agency@partner.test",
            name="Todo Agency Admin",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            password="x",
            is_active=True,
        )
        Partner.objects.filter(id=agency.id).update(user=agency_user)
        activity = self._activity(timezone.localdate() + datetime.timedelta(days=6))
        Activity.objects.filter(id=activity.id).update(
            assigned_partner_id=agency.id, fy=get_operational_fy()
        )

        payload = get_todos(agency_user)
        titles = [row["title"] for row in payload["todos"]]
        self.assertIn("Prepare", titles)
