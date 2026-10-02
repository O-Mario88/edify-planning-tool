"""A cluster assigned to a partner to facilitate (owner, 2026-10-02).

"Assigning a cluster to the partner ONLY means they facilitate the cluster
activity NOT assigned to them to do school visit … once the staff has assigned
the cluster to the partner, the rest of the logistics will be calculated when
a meeting or training is planned. And it should go to the partner as clusters
they will facilitate … staff handles meals, and everything. partner is only
paid facilitation fee."

So the assignment is a standing choice on the cluster, with no date, no cost
and no school handed over; each training or meeting staff then plan for the
cluster names the partner as its facilitator, stays the officer's work, and
pays the partner its facilitation fee and nothing else.
"""

from __future__ import annotations

import tempfile

from django.test import override_settings
from freezegun import freeze_time
from rest_framework.test import APITestCase

from apps.accounts.models import StaffSchoolAssignment
from apps.activities import services as activity_services
from apps.activities.facilitation import (
    FEE_LINE_TYPE,
    partner_planned_total,
    takes_facilitator,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.clusters.facilitation import (
    assign_facilitator,
    facilitated_clusters,
    facilitator_of,
)
from apps.clusters.models import Cluster
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.core.tests.test_partner_and_cluster_flows import (
    PartnerAndClusterFlowTest as _flow,
)
from apps.partners.models import Partner, PartnerAssignment


@override_settings(EVIDENCE_STORAGE_DIR=tempfile.mkdtemp(prefix="edify-cluster-fac-"))
@freeze_time("2026-06-24")
class ClusterFacilitationTest(APITestCase):
    # The cluster-flow fixture (see FacilitatedTrainingTest): the method is
    # borrowed, never setUp, so no second freeze is left running.
    _build_flow_fixture = _flow._build_fixture
    _user = _flow._user
    _school = _flow._school
    _ssa = _flow._ssa
    _as = _flow._as
    _get = _flow._get
    _post = _flow._post

    def setUp(self):
        self._build_flow_fixture()
        self.partner_user = self._user(
            "cluster-fac@flow.test", EdifyRole.PARTNER_FIELD_OFFICER.value
        )
        self.partner = Partner.objects.create(
            name="Cluster Facilitating Org",
            user=self.partner_user,
            active_status=True,
            contract_status="active",
            source="local_test_upload",
        )
        self.school = self._school("FLOW-CFAC-1")
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.school.id
        )
        self._ssa(self.school)
        self._as(self.cceo)
        created = self._post(
            "/api/clusters/from-school",
            {
                "schoolId": self.school.school_id,
                "name": "Facilitated Cluster",
                "clusterType": "mixed",
            },
            201,
        )
        self._post(
            "/api/clusters/assign",
            {"schoolId": self.school.school_id, "clusterId": created["id"]},
            200,
        )
        self.cluster = Cluster.objects.get(id=created["id"])

    # -- helpers -------------------------------------------------------------

    def _assign(self, partner=None) -> Cluster:
        with self.captureOnCommitCallbacks(execute=True):
            self.cluster = assign_facilitator(
                self.cluster, (partner or self.partner).id, self.cceo
            )
        return self.cluster

    def _meeting(self, **extra) -> Activity:
        with self.captureOnCommitCallbacks(execute=True):
            scheduled = self._post(
                "/api/activities/schedule-cluster-activity",
                {
                    "activityType": "cluster_meeting",
                    "catalogueItemId": "STANDARD_CLUSTER_MEETING",
                    "clusterId": self.cluster.id,
                    "scheduledDate": "2026-07-21T09:00:00+03:00",
                    "plannedMonth": 7,
                    "expectedParticipants": 10,
                    "focusIntervention": "enrolment",
                    **extra,
                },
                201,
            )
        return Activity.objects.get(id=scheduled["id"])

    def _training(self, **extra) -> Activity:
        with self.captureOnCommitCallbacks(execute=True):
            scheduled = self._post(
                "/api/planning/schedule-cluster-training",
                {
                    "clusterId": self.cluster.id,
                    "catalogueItemId": "GOVERNMENT_STATUTORY_REQUIREMENTS",
                    "scheduledDate": "2026-07-20T09:00:00+03:00",
                    "plannedMonth": 7,
                    "expectedParticipants": 12,
                    "focusIntervention": "government_requirement",
                    **extra,
                },
                201,
            )
        return Activity.objects.get(id=scheduled["id"])

    def _lines(self, activity):
        return list(
            ActivityScheduleCostLine.objects.filter(activity=activity).order_by(
                "line_item_type"
            )
        )

    def _assert_partner_is_paid_the_fee_alone(self, activity) -> None:
        lines = self._lines(activity)
        partner_lines = [line for line in lines if line.partner_id]
        staff_lines = [line for line in lines if not line.partner_id]
        self.assertEqual(
            [(line.line_item_type, line.partner_id) for line in partner_lines],
            [(FEE_LINE_TYPE, self.partner.id)],
            "the partner is paid the facilitation fee and nothing else",
        )
        self.assertTrue(
            staff_lines,
            "the meals, the venue and the officer's day stay staff money",
        )
        self.assertNotIn(FEE_LINE_TYPE, [line.line_item_type for line in staff_lines])
        self.assertEqual(partner_planned_total(activity), partner_lines[0].amount)

    # -- the assignment itself ----------------------------------------------

    def test_assigning_a_cluster_records_its_facilitator_and_nothing_else(self):
        self._assign()

        self.cluster.refresh_from_db()
        self.assertEqual(self.cluster.facilitating_partner_id, self.partner.id)
        self.assertEqual(facilitator_of(self.cluster), self.partner)
        self.assertIsNotNone(self.cluster.facilitator_assigned_at)
        # No date, no cost, no school handed over.
        self.assertFalse(PartnerAssignment.objects.exists())
        self.assertFalse(Activity.objects.filter(cluster=self.cluster).exists())

    def test_the_schools_of_a_facilitated_cluster_are_not_the_partners(self):
        from apps.core.scoping import resolve_user_scope

        self._assign()

        scope = resolve_user_scope(self.partner_user)
        self.assertNotIn(self.school.id, list(scope.school_ids or []))

    def test_only_staff_who_may_assign_to_a_partner_choose_the_facilitator(self):
        with self.assertRaises(Forbidden):
            assign_facilitator(self.cluster, self.partner.id, self.partner_user)

    def test_a_cluster_returns_to_staff(self):
        self._assign()

        self.cluster = assign_facilitator(self.cluster, "", self.cceo)

        self.assertIsNone(self.cluster.facilitating_partner_id)
        self.assertIsNone(facilitator_of(self.cluster))

    # -- what is planned afterwards -------------------------------------------

    def test_a_cluster_meeting_takes_a_facilitator(self):
        self.assertTrue(takes_facilitator("cluster_meeting"))

    def test_a_meeting_planned_for_the_cluster_is_the_partners_to_facilitate(self):
        self._assign()

        meeting = self._meeting()

        self.assertEqual(meeting.facilitating_partner_id, self.partner.id)
        # Still the officer's work: staff run it and complete it.
        self.assertEqual(meeting.delivery_type, "staff")
        self.assertIsNone(meeting.assigned_partner_id)
        self.assertTrue(meeting.responsible_staff_id)
        self.assertEqual(meeting.status, "scheduled")
        self.assertFalse(PartnerAssignment.objects.exists())
        self._assert_partner_is_paid_the_fee_alone(meeting)

    def test_a_training_planned_for_the_cluster_is_the_partners_to_facilitate(self):
        self._assign()

        training = self._training()

        self.assertEqual(training.facilitating_partner_id, self.partner.id)
        self.assertEqual(training.delivery_type, "staff")
        self._assert_partner_is_paid_the_fee_alone(training)

    def test_a_planner_may_still_choose_staff_for_one_session(self):
        self._assign()

        meeting = self._meeting(facilitatingPartnerId="")

        self.assertIsNone(meeting.facilitating_partner_id)
        self.assertNotIn(
            FEE_LINE_TYPE, [line.line_item_type for line in self._lines(meeting)]
        )

    def test_a_meeting_staff_run_themselves_has_no_facilitation_fee(self):
        meeting = self._meeting()

        self.assertIsNone(meeting.facilitating_partner_id)
        self.assertNotIn(
            FEE_LINE_TYPE, [line.line_item_type for line in self._lines(meeting)]
        )
        self.assertFalse(any(line.partner_id for line in self._lines(meeting)))

    def test_sessions_already_planned_keep_the_facilitator_they_have(self):
        before = self._meeting()

        self._assign()

        before.refresh_from_db()
        self.assertIsNone(before.facilitating_partner_id)

    def test_a_planned_meeting_can_be_given_a_facilitator_afterwards(self):
        meeting = self._meeting()

        with self.captureOnCommitCallbacks(execute=True):
            activity_services.set_facilitator(meeting.id, self.partner.id, self.cceo)

        meeting.refresh_from_db()
        self.assertEqual(meeting.facilitating_partner_id, self.partner.id)
        self._assert_partner_is_paid_the_fee_alone(meeting)

    def test_a_facilitated_meetings_fee_is_not_reported_as_a_wrong_cost(self):
        from apps.system_health.services import cluster_meeting_lines_off_recipe

        self._assign()
        facilitated = self._meeting()
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(
                activity=facilitated, line_item_type=FEE_LINE_TYPE
            ).exists()
        )

        reported = cluster_meeting_lines_off_recipe().filter(activity=facilitated)

        self.assertFalse(
            reported.filter(cost_setting_key="group_training_facilitation_fee").exists()
        )

    def test_the_fee_is_invoiced_as_a_meeting_facilitation_fee(self):
        from apps.fund_requests.partner_invoices import _category_of

        self._assign()

        self.assertEqual(_category_of(self._meeting()), "Meeting Facilitation Fee")
        self.assertEqual(_category_of(self._training()), "Training Facilitation Fee")

    # -- Edit: the schools a session invites ----------------------------------

    def _second_member(self):
        second = self._school("FLOW-CFAC-2")
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=second.id)
        self._as(self.cceo)
        self._post(
            "/api/clusters/assign",
            {"schoolId": second.school_id, "clusterId": self.cluster.id},
            200,
        )
        return second

    def _meals(self, activity) -> int:
        return int(
            ActivityScheduleCostLine.objects.get(
                activity=activity, line_item_type="participant_meals"
            ).amount
        )

    def test_adding_a_school_from_edit_re_prices_the_session(self):
        """The drawer's composition: two leaders from each invited school."""
        from apps.activities import editing

        second = self._second_member()
        meeting = self._meeting(
            expectedParticipants=None,
            leadersPerSchool=2,
            # As the drawer posts them: the ticked schools and their count.
            invitedSchoolIds=[self.school.id],
            schoolsInvited="1",
        )
        self.assertEqual(meeting.expected_participants, 2)
        one_school = self._meals(meeting)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                meeting.id,
                {"invitedSchoolIds": [self.school.id, second.id]},
                self.cceo,
            )

        meeting.refresh_from_db()
        self.assertEqual(meeting.expected_participants, 4)
        self.assertEqual(self._meals(meeting), 2 * one_school)

    def test_a_session_planned_with_a_total_keeps_it_when_schools_change(self):
        """No composition per school to multiply: the head count it was
        planned with is not written over as zero."""
        from apps.activities import editing

        second = self._second_member()
        meeting = self._meeting()
        self.assertEqual(meeting.expected_participants, 10)
        before = self._meals(meeting)

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                meeting.id,
                {"invitedSchoolIds": [self.school.id, second.id]},
                self.cceo,
            )

        meeting.refresh_from_db()
        self.assertEqual(meeting.expected_participants, 10)
        self.assertEqual(self._meals(meeting), before)

    # -- the partner's side ----------------------------------------------------

    def test_the_partner_sees_the_clusters_it_facilitates(self):
        self._assign()
        self._meeting()

        rows = facilitated_clusters(self.partner_user)

        self.assertEqual([row.name for row in rows], ["Facilitated Cluster"])
        self.assertEqual(rows[0].schools, 1)
        self.assertEqual(rows[0].sessions_planned, 1)
        self.assertEqual(rows[0].next_session.isoformat(), "2026-07-21")
        self.assertEqual(facilitated_clusters(self.cceo), [])

    def test_the_partners_plan_lists_the_cluster_and_the_fee(self):
        self._assign()
        meeting = self._meeting()
        fee = ActivityScheduleCostLine.objects.get(
            activity=meeting, line_item_type=FEE_LINE_TYPE
        )

        self.client.credentials()
        self.client.force_login(self.partner_user)
        response = self.client.get("/my-plan")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Clusters You Facilitate", html)
        self.assertIn(f'data-facilitated-cluster="{self.cluster.id}"', html)
        self.assertIn(f'data-facilitation="{meeting.id}"', html)
        self.assertIn(f"UGX {int(fee.amount):,}", html)

    # -- the screens ------------------------------------------------------------

    def test_the_drawer_says_what_the_assignment_hands_over(self):
        self.client.credentials()
        self.client.force_login(self.cceo)

        response = self.client.get(f"/clusters/{self.cluster.id}/facilitator-drawer")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'hx-post="/clusters/{self.cluster.id}/facilitator"', html)
        self.assertIn("paid the facilitation fee only", html)
        self.assertIn("schools are not assigned to the partner", html)
        self.assertIn(self.partner.name, html)

    def test_the_drawer_saves_the_facilitator(self):
        self.client.credentials()
        self.client.force_login(self.cceo)

        response = self.client.post(
            f"/clusters/{self.cluster.id}/facilitator",
            {"facilitating_partner_id": self.partner.id},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.cluster.refresh_from_db()
        self.assertEqual(self.cluster.facilitating_partner_id, self.partner.id)

    def test_a_partner_cannot_open_or_save_the_drawer(self):
        self.client.credentials()
        self.client.force_login(self.partner_user)

        opened = self.client.get(f"/clusters/{self.cluster.id}/facilitator-drawer")
        saved = self.client.post(
            f"/clusters/{self.cluster.id}/facilitator",
            {"facilitating_partner_id": self.partner.id},
            format="multipart",
        )

        self.assertIn(opened.status_code, (302, 403))
        self.assertIn(saved.status_code, (302, 403))
        self.cluster.refresh_from_db()
        self.assertIsNone(self.cluster.facilitating_partner_id)

    def test_the_old_cluster_assign_link_opens_the_facilitator_drawer(self):
        self.client.credentials()
        self.client.force_login(self.cceo)

        response = self.client.get(
            "/planning/assign-partner-modal", {"cluster_id": self.cluster.id}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'hx-post="/clusters/{self.cluster.id}/facilitator"',
            response.content.decode(),
        )

    def test_a_cluster_is_no_longer_handed_over_as_partner_work(self):
        """The old cluster hand-over wrote a PartnerAssignment the partner
        dated into work it ran itself and was paid for in full."""
        self.client.credentials()
        self.client.force_login(self.cceo)

        response = self.client.post(
            "/planning/assign-partner-action",
            {
                "cluster_id": self.cluster.id,
                "partner_id": self.partner.id,
                "catalogue_item_id": "STANDARD_CLUSTER_MEETING",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Partner to Facilitate", response.content)
        self.assertFalse(PartnerAssignment.objects.exists())

    def test_the_schedule_drawer_names_the_clusters_partner(self):
        self._assign()
        self.client.credentials()
        self.client.force_login(self.cceo)

        response = self.client.get(
            "/planning/schedule-modal",
            {"cluster_id": self.cluster.id, "action": "meeting"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'<option value="{self.partner.id}" selected>', html)
        self.assertIn("data-cluster-facilitator-note", html)
        # The delivery choice that booked an agency to run the meeting is gone.
        self.assertNotIn('id="delivery_type"', html)
