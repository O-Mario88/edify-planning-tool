"""Partner Monitoring's Schools assigned table, and whose project work it is.

Owner, 2026-09-24:

  "On partner oversight, the table for assigned schools can you make sure the
  table has the following columns; School ID, School Name, Staff Name,
  Training, Purpose of Assignment, SSA Intervention, Status, Activity date,
  Actions. When the partner schedules, the status should changed to Scheduled
  and the activity date is the scheduled date."

  "Schools assigned to project cannot be withdrawn by the staff but the
  project coordinator can withdraw from the partner they assigned to and
  reassign to another partner."

Every value the table shows is read from the handover and the activity the
Partner's scheduling created; nothing here is a label the page invents.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.exceptions import Forbidden
from apps.partners import withdrawal_service
from apps.partners.services import resolve_returned_assignment
from apps.planning import partner_oversight_service as svc
from apps.planning.fy_policy import planning_horizon
from apps.planning.test_partner_oversight import PartnerOversightFixture
from apps.projects.models import Project

COLUMNS = [
    "School ID",
    "School Name",
    "Staff Name",
    "Training",
    "Purpose of Assignment",
    "SSA Intervention",
    # Every planned activities table's two completion columns, before Status
    # (owner, 2026-09-26).
    "Salesforce ID",
    "Evidence",
    "Status",
    "Activity date",
    "Actions",
]

WITHDRAWAL = {
    "reason_category": "capacity",
    "partner_facing_reason": "The partner cannot staff this term's visits.",
    "disposition": "return_to_planning",
}


class _Fixture(PartnerOversightFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.course = ActivityCatalogueItem.objects.create(
            stable_code="COLS-PHONICS",
            source_name="Phonics Foundations",
            display_name="Phonics Foundations",
            activity_type="in_school_training",
            delivery_method="in_school_training",
            workflow_kind="in_school_training",
            status="active",
            is_training_course=True,
            costing_profile="IN_SCHOOL_TRAINING",
            evidence_profile="TRAINING_ATTENDANCE",
            salesforce_record_type="TRAINING",
        )

    def page(self, user=None, query=""):
        self.client.force_login(user or self.pl_user)
        response = self.client.get(f"/partner-oversight/{query}")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def school_table(self, body):
        start = body.index("data-partner-school-columns")
        return body[start : body.index("</table>", start)]

    def row(self, body, assignment):
        """The table row for one handover, up to its details row."""
        table = self.school_table(body)
        start = table.index(f'data-assignment="{assignment.id}"')
        return table[start : table.index('<tr id="partner-row-details-', start)]

    def details(self, body, assignment):
        """The row's details disclosure."""
        start = body.index(f'<tr id="partner-row-details-a-{assignment.id}"')
        return body[start : body.index("</tr>", start)]

    #: What the fixture's assign() fixes, set here after it creates the row.
    _FIXED = ("expected_activity_type", "focus_intervention")

    def handover(self, **fields):
        """A handover as the Assign to partner drawer writes one."""
        fixed = {name: fields.pop(name) for name in self._FIXED if name in fields}
        assignment = self.assign(**fields)
        if fixed:
            for name, value in fixed.items():
                setattr(assignment, name, value)
            assignment.save(update_fields=[*fixed, "updated_at"])
        return assignment

    def training(self, **fields):
        return self.handover(
            purpose_of_visit="in_school_training",
            expected_activity_type="in_school_training",
            training_course=self.course,
            **fields,
        )


class TheNineColumnsTest(_Fixture):
    def test_the_schools_table_reads_the_owners_columns_in_order(self):
        self.assign()

        table = self.school_table(self.page())

        headers = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', table)
        self.assertEqual(headers, COLUMNS)

    def test_the_cluster_and_activity_tables_keep_their_columns(self):
        self.assign()

        body = self.page()

        self.assertEqual(body.count("data-partner-monitoring-table"), 3)
        self.assertEqual(body.count("data-partner-school-columns"), 1)
        self.assertIn("Activity / purpose", body)

    def test_every_value_on_the_row_comes_from_the_handover(self):
        handover = self.training()

        row = self.row(self.page(), handover)

        for expected in (
            "s1",  # the operational School ID, not the primary key
            "School A",
            "James",  # the staff member managing the school
            "Phonics Foundations",
            "In-school Training",
            "Financial Health",
        ):
            with self.subTest(value=expected):
                self.assertIn(expected, row)


class ScheduledOnThePartnersDateTest(_Fixture):
    def test_before_the_partner_schedules_it_awaits_them_with_no_date(self):
        handover = self.training(scheduled_date=date.today() + timedelta(days=9))

        row = self.row(self.page(), handover)

        self.assertIn(">Awaiting Schedule<", row)
        self.assertIn("Awaiting scheduling", row)
        # The schedule-by date is a deadline, not the activity date.
        item = svc.build_item_by_assignment(handover.id)
        self.assertIsNone(item.activity_date)
        self.assertEqual(item.status_label, "Awaiting Schedule")

    def test_once_the_partner_schedules_it_reads_scheduled_on_their_date(self):
        handover = self.training()
        chosen = date.today() + timedelta(days=6)
        self.schedule(handover, when=chosen)

        row = self.row(self.page(), handover)

        self.assertIn(">Scheduled<", row)
        self.assertIn(f"{chosen.day} {chosen:%b %Y}", row)
        self.assertNotIn("Awaiting scheduling", row)
        item = svc.build_item_by_assignment(handover.id)
        self.assertEqual(item.activity_date, chosen)
        self.assertEqual(item.status_tone, "warning")

    def test_an_activity_dated_only_by_its_timestamp_still_shows_its_day(self):
        """Older rows carry scheduled_date alone; My Plan reads that day."""
        handover = self.assign()
        activity = self.schedule(handover)
        moment = timezone.make_aware(
            datetime.combine(date.today() + timedelta(days=3), time(10))
        )
        Activity.objects.filter(id=activity.id).update(
            planned_date=None, scheduled_date=moment
        )

        item = svc.build_item_by_assignment(handover.id)

        self.assertEqual(item.activity_date, timezone.localtime(moment).date())

    def test_work_the_partner_dates_into_next_year_stays_on_the_page(self):
        """September handover, October visit: next fiscal year's work. Read
        for the page year alone it disappeared the moment it was scheduled."""
        handover = self.assign()
        october = date(int(self.fy), 10, 8)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=str(int(self.fy) + 1),
            quarter="Q1",
            planned_date=october,
            planned_month=october.month,
            status="partner_scheduled",
            delivery_type="partner",
            assigned_partner_id=handover.partner_id,
            monitored_by_staff_id=handover.monitoring_staff_id,
        )
        handover.status = "partner_scheduled"
        handover.scheduled_activity = activity
        handover.save()

        horizon = planning_horizon(self.fy)
        items = svc.build_items(self.pl_user, fy=self.fy, fys=horizon)
        row = self.row(self.page(), handover)

        self.assertIn(str(int(self.fy) + 1), horizon)
        self.assertEqual([i.partner_assignment_id for i in items], [handover.id])
        self.assertIn(">Scheduled<", row)
        self.assertIn(f"8 Oct {october.year}", row)

    def test_the_export_holds_the_rows_the_page_shows(self):
        handover = self.assign()
        october = date(int(self.fy), 10, 8)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=str(int(self.fy) + 1),
            quarter="Q1",
            planned_date=october,
            status="partner_scheduled",
            delivery_type="partner",
            assigned_partner_id=handover.partner_id,
        )
        handover.status = "partner_scheduled"
        handover.scheduled_activity = activity
        handover.save()
        self.client.force_login(self.pl_user)

        response = self.client.get(f"/partner-oversight/export?fy={self.fy}")
        content = b"".join(response.streaming_content).decode()

        self.assertIn(october.isoformat(), content)


class TheWordsComeFromTheRecordsTest(_Fixture):
    def test_a_training_follow_up_names_the_training_it_follows(self):
        delivered = Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=30),
            status="ia_verified",
            training_course=self.course,
            focus_intervention="learning_environment",
        )
        handover = self.handover(
            purpose_of_visit="training_follow_up",
            expected_activity_type="training_follow_up_visit",
            source_activity=delivered,
            focus_intervention="learning_environment",
        )

        item = svc.build_item_by_assignment(handover.id)

        self.assertEqual(item.training_name, "Phonics Foundations")
        self.assertEqual(item.purpose_label, "Training Follow Up")
        self.assertEqual(item.intervention_label, "Learning Environment")

    def test_ssa_support_reads_data_gathering_and_names_no_training(self):
        handover = self.handover(
            purpose_of_visit="ssa_support",
            expected_activity_type="school_visit_ssa_collection",
            focus_intervention=None,
        )

        item = svc.build_item_by_assignment(handover.id)

        self.assertEqual(item.training_name, "")
        self.assertEqual(item.purpose_label, "SSA Support")
        self.assertEqual(item.intervention_label, svc.DATA_GATHERING_LABEL)

    def test_a_legacy_handover_with_no_purpose_reads_its_activity_type(self):
        handover = self.assign()

        item = svc.build_item_by_assignment(handover.id)

        self.assertEqual(item.purpose_label, "School Visit")


class ProjectWorkIsTheCoordinatorsTest(_Fixture):
    """Staff follow project work on Partner Monitoring and decide none of it."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import StaffProfile, User

        cls.coordinator_user = User.objects.create(
            email="pc@p.test",
            name="Pat Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            is_active=True,
        )
        cls.coordinator = StaffProfile.objects.create(
            user=cls.coordinator_user, title="Project Coordinator"
        )
        cls.project = Project.objects.create(
            name="Reading Recovery Project",
            code="SP-RR",
            category="pilot",
            status="active",
            manager_staff_id=cls.coordinator.id,
        )

    def test_the_row_names_the_project_and_offers_staff_no_withdrawal(self):
        handover = self.assign(project=self.project)
        plain = self.assign(school=self.rival_school, cceo=self.cceo)

        body = self.page()

        self.assertIn("Reading Recovery Project", self.details(body, handover))
        self.assertIn("Project Coordinator", self.details(body, handover))
        self.assertNotIn(
            f"/partner-oversight/withdraw?assignment_id={handover.id}", body
        )
        # Work outside a project keeps its control.
        self.assertIn(f"/partner-oversight/withdraw?assignment_id={plain.id}", body)

    def test_a_returned_project_handover_offers_staff_no_resolve(self):
        handover = self.assign(
            project=self.project,
            status="returned_to_staff",
            return_reason_category="capacity",
            return_reason="No facilitator this term.",
        )

        row = self.row(self.page(), handover)

        self.assertIn("Returned to Staff", row)
        self.assertNotIn("Resolve Exception", row)

    def test_the_withdrawal_service_refuses_staff(self):
        handover = self.assign(project=self.project)

        for user in (self.pl_user, self.cceo_user):
            with self.subTest(role=user.active_role):
                with self.assertRaises(Forbidden) as caught:
                    withdrawal_service.withdraw(handover.id, WITHDRAWAL, user)
                self.assertIn("Project Coordinator", str(caught.exception))
        handover.refresh_from_db()
        self.assertEqual(handover.status, "assigned")

    def test_a_cceo_cannot_ask_their_lead_to_withdraw_it_either(self):
        handover = self.assign(project=self.project)
        self.schedule(handover)

        with self.assertRaises(Forbidden):
            withdrawal_service.request_withdrawal(
                handover.id, WITHDRAWAL, self.cceo_user
            )

    def test_the_coordinator_withdraws_it(self):
        handover = self.assign(project=self.project)

        withdrawal = withdrawal_service.withdraw(
            handover.id, WITHDRAWAL, self.coordinator_user
        )

        handover.refresh_from_db()
        self.assertEqual(handover.status, "returned_to_staff")
        self.assertEqual(withdrawal.requested_by_role, "ProjectCoordinator")

    def test_the_drawer_says_whose_decision_it_is(self):
        handover = self.assign(project=self.project)
        self.client.force_login(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/withdraw?assignment_id={handover.id}"
        ).content.decode()

        self.assertIn("Only its Project Coordinator", body)
        self.assertNotIn("/partner-oversight/withdraw/submit", body)

    def test_resolving_a_returned_project_handover_is_refused_to_staff(self):
        handover = self.assign(
            project=self.project,
            status="returned_to_staff",
            return_reason="No facilitator this term.",
        )

        with self.assertRaises(Forbidden):
            resolve_returned_assignment(
                handover.id, {"resolution": "support_closed"}, self.pl_user
            )
        handover.refresh_from_db()
        self.assertIsNone(handover.resolved_at)

    def test_a_closing_school_still_stops_its_project_work(self):
        """Closing a school is not a project decision: the partner stops."""
        from apps.schools import lifecycle_service
        from apps.schools.lifecycle_models import ClosureReason, ClosureType

        from apps.schools.models import School

        # The CCEO closes a school they own (lifecycle_service.assert_may_close).
        School.objects.filter(id=self.school.id).update(account_owner_id=self.cceo.id)
        handover = self.assign(project=self.project)

        lifecycle_service.close_school(
            self.school.id,
            {
                "closure_type": ClosureType.PERMANENT,
                "reason_category": ClosureReason.FINANCIAL,
                "reason": "The owner confirmed the school stopped operating.",
                "effective_date": date.today(),
            },
            self.cceo_user,
        )

        handover.refresh_from_db()
        self.assertEqual(handover.status, "returned_to_staff")
        self.assertTrue(handover.withdrawals.exists())
