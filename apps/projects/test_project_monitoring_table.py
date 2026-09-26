"""Project Monitoring's school table, and the Project Coordinator's decisions.

Owner, 2026-09-24:

  "On Project Monitoring, users don't have access to the table with the list
  of schools they have added to the project. build the table similar to the
  one of partner oversight ... Schools assigned to project cannot be withdrawn
  by the staff but the project coordinator can withdraw from they partner they
  assigned to and reassign to another partner. Users want to see the schools
  they have assigned to the project so make sure the tables for each of the
  project they have assigned schools to is available to them. They have read
  only access, Only Project coordinator can edit paln and do everything."
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.partners.models import Partner, PartnerAssignment
from apps.projects import monitoring
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.projects.test_project_monitoring_schools import _Fixture

COLUMNS = [
    "School ID",
    "School Name",
    "Staff Name",
    "Training",
    "Purpose of Assignment",
    "SSA Intervention",
    "Status",
    "Activity date",
    "Actions",
]

WITHDRAW = {
    "reason_category": "capacity",
    "partner_facing_reason": "The partner cannot staff this term's visits.",
}


class _TableFixture(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_partner = Partner.objects.create(
            name="PMS Second Partner", active_status=True
        )
        cls.handed_over = PartnerAssignment.objects.get(school=cls.handed.school)
        cls.handed_back = PartnerAssignment.objects.get(school=cls.returned.school)

    def page(self, user, **query):
        self.client.force_login(user)
        response = self.client.get("/projects/monitoring", {"fy": self.fy, **query})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class TheNineColumnsTest(_TableFixture):
    def test_every_reader_gets_the_owners_columns_in_order(self):
        for user in (self.lead_user, self.ia_user, self.coord_user):
            with self.subTest(role=user.active_role):
                body = self.page(user)
                start = body.index("data-project-schools")
                table = body[start : body.index("</table>", start)]
                headers = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', table)
                self.assertEqual(headers, COLUMNS)


class EachSchoolSaysWhereItStandsTest(_TableFixture):
    def test_the_status_and_date_of_every_school(self):
        _result, rows = self.rows_for(self.lead_user)
        soon = min(self.today + timedelta(days=4), date(int(self.fy), 9, 30))
        expected = {
            "Unplanned Primary": (monitoring.STATUS_AWAITING_COORDINATOR, None),
            "Coordinated Primary": (monitoring.STATUS_SCHEDULED, soon),
            "Handed Primary": (monitoring.STATUS_AWAITING_PARTNER, None),
            "Partnered Primary": (monitoring.STATUS_SCHEDULED, soon),
            "Delivered Primary": (
                monitoring.STATUS_AWAITING_VERIFICATION,
                self.today - timedelta(days=2),
            ),
            "Verified Primary": (
                monitoring.STATUS_COMPLETED,
                self.today - timedelta(days=20),
            ),
            "Returned Primary": (monitoring.STATUS_PARTNER_RETURNED, None),
        }
        for name, (status, day) in expected.items():
            with self.subTest(school=name):
                self.assertEqual(rows[name].status_key, status)
                self.assertEqual(rows[name].activity_date, day)

    def test_an_unplanned_school_waits_on_the_project_coordinator(self):
        body = self.page(self.lead_user)

        self.assertIn("Awaiting Project Coordinator Action", body)
        self.assertIn("Awaiting Partner Schedule", body)
        self.assertIn("Awaiting scheduling", body)

    def test_the_partner_scheduling_turns_the_row_to_scheduled(self):
        """The handed-over school reads Scheduled, on the partner's day, once
        the partner dates the handover."""
        day = min(self.today + timedelta(days=3), date(int(self.fy), 9, 30))
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.handed.school,
            project_id=self.project.id,
            fy=self.fy,
            planned_date=day,
            status="partner_scheduled",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
        )
        PartnerAssignment.objects.filter(id=self.handed_over.id).update(
            status="partner_scheduled", scheduled_activity=activity
        )

        _result, rows = self.rows_for(self.lead_user)

        row = rows["Handed Primary"]
        self.assertEqual(row.status_key, monitoring.STATUS_SCHEDULED)
        self.assertEqual(row.status_label, "Scheduled")
        self.assertEqual(row.activity_date, day)


class TheWordsComeFromTheRecordsTest(_TableFixture):
    def test_a_school_with_no_work_reads_what_it_was_added_for(self):
        ProjectSchoolAssignment.objects.filter(id=self.unplanned.id).update(
            participation_type="Training", support_area="leadership"
        )

        _result, rows = self.rows_for(self.lead_user)

        row = rows["Unplanned Primary"]
        self.assertEqual(row.purpose_label, "Training")
        self.assertEqual(row.intervention_label, "Leadership")
        self.assertEqual(row.training_name, "")

    def test_a_training_names_its_course(self):
        course = ActivityCatalogueItem.objects.create(
            stable_code="PMT-COURSE",
            source_name="Classroom Management",
            display_name="Classroom Management",
            activity_type="in_school_training",
            delivery_method="in_school_training",
            workflow_kind="in_school_training",
            status="active",
            is_training_course=True,
            costing_profile="IN_SCHOOL_TRAINING",
            evidence_profile="TRAINING_ATTENDANCE",
            salesforce_record_type="TRAINING",
        )
        Activity.objects.filter(
            school=self.partnered.school, project_id=self.project.id
        ).update(training_course=course, focus_intervention="teaching_environment")

        _result, rows = self.rows_for(self.lead_user)

        row = rows["Partnered Primary"]
        self.assertEqual(row.training_name, "Classroom Management")
        self.assertEqual(row.purpose_label, "In-school Training")
        self.assertEqual(row.intervention_label, "Teacher's Environment")

    def test_a_handover_names_its_purpose_and_the_school_who_added_it(self):
        PartnerAssignment.objects.filter(id=self.handed_over.id).update(
            purpose_of_visit="ssa_support", focus_intervention=None
        )

        _result, rows = self.rows_for(self.lead_user)

        row = rows["Handed Primary"]
        self.assertEqual(row.purpose_label, "SSA Support")
        self.assertEqual(row.intervention_label, "Data Gathering")
        self.assertEqual(row.added_by, "PMS Lead")


class TheViewDrawerKeepsTheLensTest(_TableFixture):
    def open(self, user, enrolment):
        self.client.force_login(user)
        return self.client.get(
            "/projects/monitoring/school", {"enrolment": enrolment.id, "fy": self.fy}
        )

    def test_the_officer_who_added_the_school_reads_its_work(self):
        response = self.open(self.lead_user, self.partnered)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partnered Primary")
        self.assertContains(response, "Project work at this school")
        self.assertContains(response, "Read only")
        self.assertNotContains(response, "/projects/monitoring/withdraw")

    def test_another_officers_school_resolves_to_nothing(self):
        response = self.open(self.other_lead_user, self.partnered)

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Partnered Primary", status_code=404)

    def test_the_coordinator_gets_the_decisions_on_each_piece_of_work(self):
        response = self.open(self.coord_user, self.handed)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f"/projects/monitoring/withdraw?handover={self.handed_over.id}"
        )


class OnlyTheCoordinatorDecidesTest(_TableFixture):
    def test_the_coordinator_sees_withdraw_and_resolve(self):
        body = self.page(self.coord_user)

        self.assertIn(
            f"/projects/monitoring/withdraw?handover={self.handed_over.id}", body
        )
        self.assertIn(
            f"/projects/monitoring/resolve?handover={self.handed_back.id}", body
        )
        # Both are items on the row's Actions menu (owner, 2026-09-26);
        # withdrawing takes the work from its partner, so it reads as such.
        self.assertIn(
            'class="row-menu__item row-menu__item--danger" role="menuitem" '
            f'hx-get="/projects/monitoring/withdraw?handover={self.handed_over.id}"',
            body,
        )
        self.assertIn(
            'class="row-menu__item" role="menuitem" '
            f'hx-get="/projects/monitoring/resolve?handover={self.handed_back.id}"',
            body,
        )

    def test_everyone_else_is_offered_no_decision(self):
        for user in (self.lead_user, self.ia_user):
            with self.subTest(role=user.active_role):
                body = self.page(user)
                self.assertNotIn("/projects/monitoring/withdraw", body)
                self.assertNotIn("/projects/monitoring/resolve", body)
                self.assertIn("Read only", body)

    def test_the_coordinator_withdraws_and_reassigns_to_another_partner(self):
        self.client.force_login(self.coord_user)
        drawer = self.client.get(
            "/projects/monitoring/withdraw", {"handover": self.handed_over.id}
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "/projects/monitoring/withdraw/submit")
        self.assertContains(drawer, "Return to Project Planning")

        response = self.client.post(
            "/projects/monitoring/withdraw/submit",
            {
                **WITHDRAW,
                "assignment_id": self.handed_over.id,
                "disposition": "reassign_partner",
                "replacement_partner_id": self.other_partner.id,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response["HX-Refresh"], "true")
        self.handed_over.refresh_from_db()
        self.assertEqual(self.handed_over.status, "returned_to_staff")
        replacement = PartnerAssignment.objects.get(
            replaces_assignment=self.handed_over
        )
        self.assertEqual(replacement.partner_id, self.other_partner.id)
        self.assertEqual(replacement.project_id, self.project.id)
        self.assertEqual(replacement.school_id, self.handed.school_id)
        # The school now waits on the new partner's date.
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(
            rows["Handed Primary"].status_key, monitoring.STATUS_AWAITING_PARTNER
        )

    def test_a_withdrawal_back_to_planning_is_not_a_partner_return(self):
        """The coordinator took the work back: the school waits on them again,
        and no second decision is offered on work already decided."""
        from apps.partners import withdrawal_service

        withdrawal_service.withdraw(
            self.handed_over.id,
            {**WITHDRAW, "disposition": "return_to_planning"},
            self.coord_user,
        )

        _result, rows = self.rows_for(self.coord_user)
        row = rows["Handed Primary"]
        self.assertEqual(row.status_key, monitoring.STATUS_AWAITING_COORDINATOR)
        self.assertEqual(row.resolve_url, "")
        self.client.force_login(self.coord_user)
        drawer = self.client.get(
            "/projects/monitoring/resolve", {"handover": self.handed_over.id}
        )
        self.assertEqual(drawer.status_code, 404)

    def test_staff_cannot_use_the_coordinators_routes(self):
        for user in (self.lead_user, self.ia_user, self.stranger_user):
            with self.subTest(role=user.email):
                self.client.force_login(user)
                drawer = self.client.get(
                    "/projects/monitoring/withdraw", {"handover": self.handed_over.id}
                )
                self.assertEqual(drawer.status_code, 404)
                submit = self.client.post(
                    "/projects/monitoring/withdraw/submit",
                    {
                        **WITHDRAW,
                        "assignment_id": self.handed_over.id,
                        "disposition": "return_to_planning",
                    },
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(submit.status_code, 403)
        self.handed_over.refresh_from_db()
        self.assertEqual(self.handed_over.status, "assigned")

    def test_the_coordinator_resolves_a_return_by_reassigning_it(self):
        self.client.force_login(self.coord_user)
        drawer = self.client.get(
            "/projects/monitoring/resolve", {"handover": self.handed_back.id}
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "/projects/monitoring/resolve/submit")

        response = self.client.post(
            "/projects/monitoring/resolve/submit",
            {
                "assignment_id": self.handed_back.id,
                "resolution": "reassigned",
                "partner_id": self.other_partner.id,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.handed_back.refresh_from_db()
        self.assertEqual(self.handed_back.resolution, "reassigned")
        replacement = PartnerAssignment.objects.get(
            replaces_assignment=self.handed_back
        )
        self.assertEqual(replacement.project_id, self.project.id)

    def test_a_paused_project_takes_no_replacement_partner(self):
        Project.objects.filter(id=self.project.id).update(status="paused")
        self.client.force_login(self.coord_user)

        response = self.client.post(
            "/projects/monitoring/withdraw/submit",
            {
                **WITHDRAW,
                "assignment_id": self.handed_over.id,
                "disposition": "reassign_partner",
                "replacement_partner_id": self.other_partner.id,
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "paused", status_code=400)
        self.handed_over.refresh_from_db()
        self.assertEqual(self.handed_over.status, "assigned")
        self.assertFalse(
            PartnerAssignment.objects.filter(
                replaces_assignment=self.handed_over
            ).exists()
        )


class StaffCannotWithdrawASchoolFromTheProjectTest(_TableFixture):
    def url(self, enrolment):
        return (
            f"/api/special-projects/{self.project.id}/schools/"
            f"{enrolment.school.school_id}"
        )

    def test_the_officer_who_added_it_cannot_remove_it(self):
        self.client.force_login(self.lead_user)

        response = self.client.delete(self.url(self.unplanned))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(id=self.unplanned.id).exists()
        )

    def test_another_projects_coordinator_cannot_remove_it(self):
        self.client.force_login(self.stranger_user)

        response = self.client.delete(self.url(self.unplanned))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(id=self.unplanned.id).exists()
        )

    def test_the_projects_coordinator_removes_it_and_the_history_stays(self):
        from apps.projects.models import ProjectSchoolEnrollmentHistory

        self.client.force_login(self.coord_user)

        response = self.client.delete(self.url(self.unplanned))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(id=self.unplanned.id).exists()
        )
        self.assertTrue(
            ProjectSchoolEnrollmentHistory.objects.filter(
                project=self.project, school=self.unplanned.school
            ).exists()
        )


class TheCoordinatorsDoorsCostNoQueryPerRowTest(_TableFixture):
    def test_more_partner_work_costs_no_more_queries(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                monitoring.project_monitoring(self.coord_user, fy=self.fy)
            return len(queries)

        before = count()
        for n in range(5):
            enrolment = self._enrol(f"PMT-X{n}", f"Extra Partnered {n}")
            PartnerAssignment.objects.create(
                school=enrolment.school,
                partner=self.partner,
                project=self.project,
                assigning_staff_id=self.coord.id,
                expected_activity_type="school_visit",
                status="assigned",
            )
            self._work(
                enrolment.school,
                "school_visit",
                self.today + timedelta(days=1),
                None,
                status="partner_scheduled",
                partner=self.other_partner,
            )
        self.assertEqual(count(), before)


class OnlyTheCoordinatorLinksPartnersTest(_TableFixture):
    """The project's partner links are part of its plan: only its coordinator
    changes them (owner, 2026-09-24). Both routes used to take any caller."""

    def link(self, user):
        self.client.force_login(user)
        return self.client.post(
            f"/api/special-projects/{self.project.id}/partners",
            {"partnerId": self.other_partner.id},
            content_type="application/json",
        )

    def unlink(self, user):
        self.client.force_login(user)
        return self.client.delete(
            f"/api/special-projects/{self.project.id}/partners/{self.partner.id}"
        )

    def linked(self, partner):
        from apps.projects.models import ProjectPartnerAssignment

        return ProjectPartnerAssignment.objects.filter(
            project=self.project, partner=partner
        ).exists()

    def test_staff_and_another_coordinator_cannot_link_or_unlink(self):
        from apps.projects.models import ProjectPartnerAssignment

        ProjectPartnerAssignment.objects.create(
            project=self.project, partner=self.partner
        )
        for user in (self.lead_user, self.ia_user, self.stranger_user):
            with self.subTest(role=user.email):
                self.assertEqual(self.link(user).status_code, 403)
                self.assertEqual(self.unlink(user).status_code, 403)
        self.assertFalse(self.linked(self.other_partner))
        self.assertTrue(self.linked(self.partner))

    def test_the_projects_coordinator_links_and_unlinks(self):
        from apps.projects.models import ProjectPartnerAssignment

        ProjectPartnerAssignment.objects.create(
            project=self.project, partner=self.partner
        )

        self.assertEqual(self.link(self.coord_user).status_code, 201)
        self.assertEqual(self.unlink(self.coord_user).status_code, 200)

        self.assertTrue(self.linked(self.other_partner))
        self.assertFalse(self.linked(self.partner))
