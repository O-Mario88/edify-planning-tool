"""Project Monitoring, school by school.

Owner, 2026-09-24: "Project Monitoring should show you a list of all the
schools you have assigned to a project grouped by project, and track if the
schools have been assigned to a partner and the partner has scheduled them, or
scheduled/planned for by project coordinator. The staff except Project
coordinator have read only access. But they should monitor if the school has
been planned for, execution has taken place, improvement against their focus
ssa interventions."
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.projects import monitoring
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

FOCUS = "learning_environment"
SUPPORTING = "leadership"


def _user(uid, role, name):
    user = User.objects.create_user(
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        id=f"{uid}-sp", user=user, title=role, country="Uganda"
    )
    return user, profile


class _Fixture(TestCase):
    """One coordinated project, schools at every stage the page tracks."""

    @classmethod
    def setUpTestData(cls):
        cls.today = date.today()
        cls.fy = get_operational_fy(cls.today)
        cls.region = Region.objects.create(name="PMS Region")
        cls.district = District.objects.create(name="PMS District", region=cls.region)

        cls.lead_user, cls.lead = _user("pms-pl", "Program Lead", "PMS Lead")
        cls.other_lead_user, _ = _user("pms-pl2", "Program Lead", "PMS Other Lead")
        cls.ia_user, _ = _user("pms-ia", "ImpactAssessment", "PMS IA")
        cls.coord_user, cls.coord = _user(
            "pms-coord", "ProjectCoordinator", "PMS Coordinator"
        )
        cls.stranger_user, cls.stranger = _user(
            "pms-coord2", "ProjectCoordinator", "PMS Other Coordinator"
        )

        cls.project = Project.objects.create(
            name="PMS Learning Project",
            code="SP-PMS",
            category="pilot",
            status="active",
            intervention=FOCUS,
            target_interventions=[FOCUS, SUPPORTING],
            manager_staff_id=cls.coord.id,
        )
        cls.partner = Partner.objects.create(name="PMS Partner", active_status=True)

        cls.unplanned = cls._enrol("PMS-1", "Unplanned Primary")
        cls.coordinated = cls._enrol("PMS-2", "Coordinated Primary")
        cls.handed = cls._enrol("PMS-3", "Handed Primary")
        cls.partnered = cls._enrol("PMS-4", "Partnered Primary")
        cls.delivered = cls._enrol("PMS-5", "Delivered Primary")
        cls.verified = cls._enrol("PMS-6", "Verified Primary")
        cls.returned = cls._enrol("PMS-7", "Returned Primary")
        # Somebody else's enrolment in the same project.
        cls.theirs = cls._enrol("PMS-8", "Theirs Primary", by=cls.other_lead_user)

        soon = min(cls.today + timedelta(days=4), date(int(cls.fy), 9, 30))
        cls._work(cls.coordinated.school, "school_visit", soon, cls.coord.id)
        PartnerAssignment.objects.create(
            school=cls.handed.school,
            partner=cls.partner,
            project=cls.project,
            assigning_staff_id=cls.coord.id,
            monitoring_staff_id=cls.coord.id,
            expected_activity_type="school_visit",
            status="assigned",
        )
        cls._work(
            cls.partnered.school,
            "in_school_training",
            soon,
            None,
            status="partner_scheduled",
            partner=cls.partner,
        )
        cls._work(
            cls.delivered.school,
            "school_visit",
            cls.today - timedelta(days=2),
            cls.coord.id,
            status="submitted_to_pl",
        )
        cls._work(
            cls.verified.school,
            "school_visit",
            cls.today - timedelta(days=20),
            cls.coord.id,
            status="ia_verified",
        )
        PartnerAssignment.objects.create(
            school=cls.returned.school,
            partner=cls.partner,
            project=cls.project,
            assigning_staff_id=cls.coord.id,
            monitoring_staff_id=cls.coord.id,
            expected_activity_type="school_visit",
            status="returned_to_staff",
        )

        # The verified school entered at 4.0 on the focus intervention and
        # was confirmed at 6.0 since; the engine classified it Improved.
        cls._ssa(cls.verified.school, cls.today - timedelta(days=200), 4.0, 5.0)
        cls._ssa(cls.verified.school, cls.today - timedelta(days=1), 6.0, 5.5)
        ProjectSchoolAssignment.objects.filter(id=cls.verified.id).update(
            baseline_score=4.0,
            follow_up_score=6.0,
            impact_classification="improved",
            start_date=cls.today - timedelta(days=100),
        )
        # The delivered school has a baseline but no verified delivery yet.
        cls._ssa(cls.delivered.school, cls.today - timedelta(days=200), 3.0, 4.0)
        ProjectSchoolAssignment.objects.filter(id=cls.delivered.id).update(
            baseline_score=3.0, start_date=cls.today - timedelta(days=100)
        )

    @classmethod
    def _enrol(cls, code, name, *, by=None):
        school = School.objects.create(
            school_id=code,
            name=name,
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        return ProjectSchoolAssignment.objects.create(
            project=cls.project,
            school=school,
            assigned_by=(by or cls.lead_user).id,
        )

    @classmethod
    def _work(cls, school, kind, when, owner, *, status="scheduled", partner=None):
        return Activity.objects.create(
            activity_type=kind,
            school=school,
            project_id=cls.project.id,
            fy=get_operational_fy(when),
            planned_date=when,
            planned_month=when.month,
            status=status,
            responsible_staff_id=owner,
            delivery_type="partner" if partner else "staff",
            assigned_partner_id=partner.id if partner else None,
        )

    @classmethod
    def _ssa(cls, school, on, focus, supporting):
        record = SsaRecord.objects.create(
            school=school,
            fy=get_operational_fy(on),
            quarter="Q1",
            average_score=focus,
            verification_status="confirmed",
            date_of_ssa=timezone.make_aware(datetime.combine(on, time(9))),
            uploaded_by="t",
        )
        SsaScore.objects.create(ssa_record=record, intervention=FOCUS, score=focus)
        SsaScore.objects.create(
            ssa_record=record, intervention=SUPPORTING, score=supporting
        )

    def rows_for(self, user, **kwargs):
        result = monitoring.project_monitoring(user, fy=self.fy, **kwargs)
        project = next(row for row in result.rows if row.id == self.project.id)
        return result, {row.school_name: row for row in project.school_rows}


class EachSchoolSaysWhoHasTheWorkTest(_Fixture):
    def test_the_stage_of_every_school(self):
        _result, rows = self.rows_for(self.lead_user)
        expected = {
            "Unplanned Primary": monitoring.PLAN_NOT_PLANNED,
            "Coordinated Primary": monitoring.PLAN_STAFF_PLANNED,
            "Handed Primary": monitoring.PLAN_PARTNER_AWAITING,
            "Partnered Primary": monitoring.PLAN_PARTNER_SCHEDULED,
            "Returned Primary": monitoring.PLAN_PARTNER_RETURNED,
        }
        for name, stage in expected.items():
            with self.subTest(school=name):
                self.assertEqual(rows[name].plan_stage, stage)

    def test_the_partner_and_the_coordinator_are_named(self):
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(rows["Handed Primary"].partner_name, "PMS Partner")
        self.assertEqual(rows["Partnered Primary"].partner_name, "PMS Partner")
        coordinated = rows["Coordinated Primary"]
        self.assertEqual(coordinated.planned_by, "PMS Coordinator")
        self.assertEqual(coordinated.plan_label, "Coordinator planned")
        self.assertIsNotNone(coordinated.next_date)

    def test_whether_the_work_happened(self):
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(rows["Unplanned Primary"].execution, monitoring.EXEC_NONE)
        self.assertEqual(
            rows["Coordinated Primary"].execution, monitoring.EXEC_SCHEDULED
        )
        self.assertEqual(rows["Delivered Primary"].execution, monitoring.EXEC_DELIVERED)
        self.assertEqual(rows["Verified Primary"].execution, monitoring.EXEC_VERIFIED)
        self.assertEqual(rows["Verified Primary"].verified, 1)

    def test_next_year_s_date_is_planned_not_unplanned(self):
        """September plans land in October, the next fiscal year."""
        october = date(int(self.fy), 10, 8)
        self._work(self.unplanned.school, "school_visit", october, self.coord.id)
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(
            rows["Unplanned Primary"].plan_stage, monitoring.PLAN_STAFF_PLANNED
        )

    def test_released_work_is_not_a_plan(self):
        self._work(
            self.unplanned.school,
            "school_visit",
            self.today + timedelta(days=1),
            self.coord.id,
            status="cancelled",
        )
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(
            rows["Unplanned Primary"].plan_stage, monitoring.PLAN_NOT_PLANNED
        )


class FocusInterventionsTest(_Fixture):
    def test_the_engine_s_verdict_and_the_readings_beside_it(self):
        _result, rows = self.rows_for(self.lead_user)
        verified = rows["Verified Primary"]
        self.assertEqual(verified.impact_label, "Improved")
        focus = {reading.code: reading for reading in verified.focus}
        self.assertEqual([r.code for r in verified.focus], [FOCUS, SUPPORTING])
        self.assertEqual((focus[FOCUS].baseline, focus[FOCUS].latest), (4.0, 6.0))
        self.assertEqual(focus[FOCUS].change, 2.0)
        self.assertEqual(focus[SUPPORTING].change, 0.5)

    def test_a_missing_follow_up_is_never_no_change(self):
        _result, rows = self.rows_for(self.lead_user)
        self.assertEqual(rows["Delivered Primary"].impact_label, "Awaiting delivery")
        self.assertEqual(rows["Unplanned Primary"].impact_label, "No baseline")


class WhoSeesWhichSchoolsTest(_Fixture):
    def test_a_lead_sees_only_the_schools_they_added(self):
        _result, rows = self.rows_for(self.lead_user)
        self.assertNotIn("Theirs Primary", rows)
        self.assertEqual(len(rows), 7)

    def test_the_other_lead_sees_only_theirs(self):
        _result, rows = self.rows_for(self.other_lead_user)
        self.assertEqual(list(rows), ["Theirs Primary"])

    def test_ia_and_the_coordinator_read_the_project_whole(self):
        for user in (self.ia_user, self.coord_user):
            with self.subTest(role=user.active_role):
                result, rows = self.rows_for(user)
                self.assertTrue(result.whole_project)
                self.assertIn("Theirs Primary", rows)
                self.assertEqual(len(rows), 8)

    def test_a_coordinator_sees_only_the_projects_they_run(self):
        result = monitoring.project_monitoring(self.stranger_user, fy=self.fy)
        self.assertEqual(result.rows, [])

    def test_the_stage_filter_narrows_rows_not_the_project(self):
        result, rows = self.rows_for(
            self.lead_user, stage=monitoring.PLAN_PARTNER_AWAITING
        )
        self.assertEqual(list(rows), ["Handed Primary"])
        project = result.rows[0]
        self.assertEqual(project.schools_awaiting_partner, 1)
        self.assertEqual(project.schools_planned, 5)
        self.assertEqual(project.my_schools, 7)


class OnlyTheCoordinatorActsTest(_Fixture):
    def test_the_coordinator_gets_schedule_and_partner_controls(self):
        self.client.force_login(self.coord_user)
        response = self.client.get("/projects/monitoring", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(
            f"/planning/schedule-modal?school_id={self.unplanned.school.id}"
            f"&amp;project_id={self.project.id}",
            html,
        )
        # The project-stamped handover door, not the generic support drawer.
        self.assertIn(
            f"/projects/planning/bulk-partner?assignments={self.unplanned.id}", html
        )
        self.assertNotIn("/planning/assign-partner-modal", html)
        self.assertNotIn("Read only. Scheduling", html)

    def test_the_coordinator_s_controls_open_their_drawers(self):
        _result, rows = self.rows_for(self.coord_user)
        row = rows["Unplanned Primary"]
        self.client.force_login(self.coord_user)
        for url in (row.schedule_url, row.partner_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_everyone_else_reads(self):
        for user in (self.lead_user, self.ia_user):
            with self.subTest(role=user.active_role):
                self.client.force_login(user)
                response = self.client.get("/projects/monitoring", {"fy": self.fy})
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn('data-project-school="', html)
                self.assertNotIn("/planning/schedule-modal", html)
                self.assertNotIn("assign-partner-modal", html)
                self.assertNotIn("/projects/planning/bulk-partner", html)
                self.assertIn("Read only", html)

    def test_a_paused_project_offers_the_coordinator_no_new_work(self):
        Project.objects.filter(id=self.project.id).update(status="paused")
        _result, rows = self.rows_for(self.coord_user)
        self.assertTrue(all(not row.schedule_url for row in rows.values()))

    def test_the_page_shows_each_school_s_stage(self):
        self.client.force_login(self.lead_user)
        response = self.client.get(
            "/projects/monitoring",
            {"fy": self.fy, "stage": monitoring.PLAN_PARTNER_AWAITING},
        )
        self.assertContains(response, "Awaiting partner")
        self.assertContains(response, 'data-plan-stage="partner_awaiting"')
        self.assertNotContains(response, 'data-plan-stage="not_planned"')


class TheQueryCostIsFixedTest(_Fixture):
    def test_more_schools_cost_no_more_queries(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                monitoring.project_monitoring(self.ia_user, fy=self.fy)
            return len(queries)

        before = count()
        for n in range(6):
            enrolment = self._enrol(f"PMS-X{n}", f"Extra {n}")
            self._work(
                enrolment.school,
                "school_visit",
                self.today + timedelta(days=1),
                self.coord.id,
            )
        self.assertEqual(count(), before)
