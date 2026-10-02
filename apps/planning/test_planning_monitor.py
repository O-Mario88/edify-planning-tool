"""The Planning Monitor (owner, 2026-09-28).

"Every CCEO is supposed to plan 560 visits that includes the 2 visits from
each core school and client school ... the remaining ... will be client visit,
core trained. The rest of the remaining number should be assigned to the
partner. CD and IA needs to track ... total number of schools and how many
unique school visits have been planned ... how many schools have been planned
for training (through cluster group training and Cluster Meetings) ... all
school not clustered, not planned for (Visits, training and both) ... how many
schools are assigned to projects."
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
    User,
)
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.planning_monitor import (
    CCEO_VISITS_TARGET,
    DEFAULT_VISITS_TARGET,
    PL_VISITS_TARGET,
    planning_monitor,
)
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School

FY = "2027"
DAY = date(2026, 11, 3)


def _user(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=user.name)


class MonitorFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Monitor Region")
        cls.district = District.objects.create(
            name="Monitor District", region=cls.region
        )
        cls.pl_user, cls.pl = _user("lead@monitor.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        cls.anna_user, cls.anna = _user("anna@monitor.test", EdifyRole.CCEO)
        cls.ben_user, cls.ben = _user("ben@monitor.test", EdifyRole.CCEO)
        for officer in (cls.anna, cls.ben):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.pl
            )
        cls.cd_user, _ = _user("cd@monitor.test", EdifyRole.COUNTRY_DIRECTOR)
        cls.ia_user, _ = _user("ia@monitor.test", EdifyRole.IMPACT_ASSESSMENT)

        cls.cluster = Cluster.objects.create(
            name="Monitor Cluster",
            region=cls.region,
            district=cls.district,
            responsible_staff_id=cls.anna.id,
        )
        # Anna: two Core schools, three client-rule schools (one Core
        # Trained), one of them not clustered. A Champion is not counted.
        cls.core_a = cls._school("MON-C1", "core", cls.anna)
        cls.core_b = cls._school("MON-C2", "core", cls.anna)
        cls.client_a = cls._school("MON-1", "client", cls.anna)
        cls.trained = cls._school("MON-2", "core_trained", cls.anna)
        cls.loose = cls._school("MON-3", "client", cls.anna, clustered=False)
        cls._school("MON-CH", "champion", cls.anna)
        # Ben: one client school, nothing planned.
        cls.ben_school = cls._school("MON-B1", "client", cls.ben)

        # Anna's plan: two core visits (one delivered), one client visit, a
        # donor visit at the Core Trained school, and a partner visit.
        cls._visit(cls.core_a, "core_visit", status="submitted_to_pl")
        cls._visit(cls.core_b, "core_visit")
        cls._visit(cls.client_a, "school_visit")
        cls._visit(cls.trained, "donor_visit")
        cls._visit(cls.loose, "school_visit", delivery="partner")
        # A cancelled visit is no plan.
        cls._visit(cls.client_a, "follow_up_visit", status="cancelled")
        # A group training invites two schools; a cluster meeting one.
        training = cls._session("cluster_training")
        meeting = cls._session("cluster_meeting")
        for school in (cls.core_a, cls.client_a):
            ClusterActivityAttendance.objects.create(
                activity=training, school=school, invited=True
            )
        ClusterActivityAttendance.objects.create(
            activity=meeting, school=cls.trained, invited=True
        )
        # A handover the partner has not dated yet.
        partner = Partner.objects.create(name="Monitor Partner")
        PartnerAssignment.objects.create(
            school=cls.trained,
            partner=partner,
            status=PartnerAssignment.UNSCHEDULED_STATUSES[0],
        )
        project = Project.objects.create(name="Monitor Project", status="active")
        ProjectSchoolAssignment.objects.create(project=project, school=cls.client_a)

    @classmethod
    def _school(cls, code, school_type, owner, *, clustered=True):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            school_type=school_type,
            account_owner_id=owner.id,
            account_owner_status="matched",
            cluster_id=cls.cluster.id if clustered else None,
            cluster_status="clustered" if clustered else "unclustered",
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    @classmethod
    def _visit(cls, school, activity_type, *, status="scheduled", delivery="staff"):
        return Activity.objects.create(
            school=school,
            activity_type=activity_type,
            status=status,
            delivery_type=delivery,
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=cls.anna.id,
        )

    @classmethod
    def _session(cls, activity_type):
        return Activity.objects.create(
            cluster=cls.cluster,
            activity_type=activity_type,
            status="scheduled",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=cls.anna.id,
        )

    def _officer(self, monitor, profile):
        return next(
            officer
            for lead in monitor["leads"]
            for officer in lead.officers
            if officer.key == profile.id
        )


class TheYearAgainstItsTarget(MonitorFixture):
    def test_the_target_splits_into_core_and_client_visits(self):
        anna = self._officer(planning_monitor(self.cd_user, fy=FY), self.anna)
        self.assertEqual(anna.visits_target, DEFAULT_VISITS_TARGET)
        self.assertEqual((anna.core_schools, anna.client_schools), (2, 3))
        self.assertEqual(anna.core_visit_target, 4)
        self.assertEqual(anna.client_visit_target, DEFAULT_VISITS_TARGET - 4)

    def test_staff_visits_are_counted_by_kind_and_delivery(self):
        anna = self._officer(planning_monitor(self.cd_user, fy=FY), self.anna)
        self.assertEqual(anna.core_visits, 2)
        # The client visit. Not the donor visit (owner, 2026-10-01: the visits
        # that count are SSA Support, In-school Training and Follow up), not
        # the cancelled one, not the partner's.
        self.assertEqual(anna.client_visits, 1)
        self.assertEqual(anna.visits_done, 1)

    def test_the_role_sets_the_target_not_a_saved_profile(self):
        # Owner, 2026-09-29: "PL plans for maximum of 280 and CCEO 560". A
        # StaffTargetProfile feeds Target Performance, not this monitor.
        StaffTargetProfile.objects.create(staff=self.anna, fy=FY, visits_target=300)
        monitor = planning_monitor(self.cd_user, fy=FY)
        anna = self._officer(monitor, self.anna)
        lead = self._officer(monitor, self.pl)
        self.assertEqual(anna.visits_target, CCEO_VISITS_TARGET)
        self.assertEqual(anna.client_visit_target, CCEO_VISITS_TARGET - 4)
        self.assertEqual((lead.visits_target, lead.role_label), (280, "Programme Lead"))

    def test_client_schools_with_partner_work(self):
        anna = self._officer(planning_monitor(self.cd_user, fy=FY), self.anna)
        # 560 − 4 core visits reach every one of her 3 client-rule schools.
        self.assertEqual(anna.partner_needed, 0)
        # The partner visit, and the handover not yet dated.
        self.assertEqual(anna.partner_schools, 2)


class VisitsCountForThePlanner(MonitorFixture):
    """A visit is counted for the officer who planned it, at any school, as
    My Plan counts it (owner, 2026-09-28)."""

    def test_a_visit_at_a_colleague_s_school_is_the_planner_s(self):
        Activity.objects.create(
            school=self.ben_school,
            activity_type="school_visit",
            status="scheduled",
            delivery_type="staff",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.anna.id,
        )
        monitor = planning_monitor(self.cd_user, fy=FY)
        anna = self._officer(monitor, self.anna)
        ben = self._officer(monitor, self.ben)
        self.assertEqual((anna.core_visits, anna.client_visits), (2, 2))
        self.assertEqual(ben.staff_visits, 0)
        # The school is still visited, whoever planned it.
        self.assertEqual(ben.schools_with_visit, 1)


class CoverageAndGaps(MonitorFixture):
    def test_unique_schools_training_and_gaps(self):
        anna = self._officer(planning_monitor(self.cd_user, fy=FY), self.anna)
        self.assertEqual(anna.school_count, 5)  # the Champion is not counted
        # The Core Trained school has a donor visit and a handover the
        # partner has not dated: neither is a visit planned.
        self.assertEqual(anna.schools_with_visit, 4)
        self.assertEqual(anna.schools_group_training, 2)
        self.assertEqual(anna.schools_meeting, 1)
        self.assertEqual(anna.schools_with_training, 3)
        self.assertEqual(anna.not_clustered, 1)
        self.assertEqual((anna.no_visit, anna.no_training, anna.no_both), (1, 2, 0))
        self.assertEqual(anna.in_projects, 1)

    def test_an_officer_with_nothing_planned_reads_every_gap(self):
        ben = self._officer(planning_monitor(self.cd_user, fy=FY), self.ben)
        self.assertEqual((ben.no_visit, ben.no_training, ben.no_both), (1, 1, 1))

    def test_the_lead_total_is_the_sum_of_the_officers(self):
        monitor = planning_monitor(self.cd_user, fy=FY)
        lead = next(lead for lead in monitor["leads"] if lead.key == self.pl.id)
        self.assertEqual(lead.school_count, 6)
        # The Lead's own 280 and each CCEO's 560.
        self.assertEqual(lead.visits_target, PL_VISITS_TARGET + 2 * CCEO_VISITS_TARGET)
        self.assertEqual(lead.officer_count, 3)
        self.assertEqual(lead.no_both, 1)

    def test_the_drill_down_lists_the_schools_behind_a_count(self):
        monitor = planning_monitor(self.cd_user, fy=FY, gap="no_training")
        self.assertEqual(
            {s.code for s in monitor["gap_schools"]}, {"MON-C2", "MON-3", "MON-B1"}
        )
        only_anna = planning_monitor(
            self.cd_user, fy=FY, gap="no_training", officer_id=self.anna.id
        )
        self.assertEqual(
            {s.code for s in only_anna["gap_schools"]}, {"MON-C2", "MON-3"}
        )

    def test_another_year_is_a_year_with_nothing_planned(self):
        anna = self._officer(planning_monitor(self.cd_user, fy="2026"), self.anna)
        self.assertEqual((anna.staff_visits, anna.schools_with_training), (0, 0))


class TheLensIsTheirs(MonitorFixture):
    def test_the_country_director_and_ia_read_it(self):
        # IA reads it as a Planning Oversight tab (owner, 2026-09-30).
        for user, path, view in (
            (self.cd_user, "/planning-monitor/", "planning"),
            (self.ia_user, "/team-planning-oversight/", "monitor"),
        ):
            with self.subTest(role=user.active_role):
                self.client.force_login(user)
                response = self.client.get(path, {"view": view, "fy": FY})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-planning-monitor")
                self.assertContains(response, "School MON-B1", count=0)
                gap = self.client.get(path, {"view": view, "fy": FY, "gap": "no_both"})
                self.assertContains(gap, "School MON-B1")

    def test_a_programme_lead_reads_their_team(self):
        # On their dashboard (owner, 2026-09-29): the section's requests
        # carry X-Edify-Embed.
        self.client.force_login(self.pl_user)
        response = self.client.get(
            "/planning-monitor/",
            {"fy": FY},
            HTTP_HX_REQUEST="true",
            HTTP_X_EDIFY_EMBED="dashboard",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-planning-monitor")
        self.assertEqual(response.context["monitor_totals"].school_count, 6)

    def test_a_cceo_has_no_monitor(self):
        self.client.force_login(self.anna_user)
        response = self.client.get("/planning-monitor/", {"fy": FY})
        self.assertNotIn("data-planning-monitor", response.content.decode())


class OneRulebookWithCountryOversight(MonitorFixture):
    """Owner, 2026-10-01: the monitor and Country Planning Oversight count by
    one rulebook, so the Country Director reads one figure for one plan."""

    def test_the_monitor_and_the_dashboard_agree(self):
        from apps.planning.country_oversight import service as svc

        monitor = planning_monitor(self.cd_user, fy=FY)["totals"]
        country = svc.snapshot_for(self.cd_user, svc.Filters(fy=FY)).tree.country
        self.assertEqual(monitor.visits_target, country.target)
        self.assertEqual(monitor.staff_visits, country.p_visits)
        self.assertEqual(monitor.partner_scheduled, country.pp_work)
        self.assertEqual(
            monitor.partner_scheduled + monitor.partner_awaiting, country.pa_work
        )
        self.assertEqual(monitor.partner_assigned_schools, country.pa_schools)
        self.assertEqual(monitor.no_visit, country.no_visit)

    def test_partner_work_is_scheduled_only_once_the_partner_dates_it(self):
        Activity.objects.create(
            school=self.ben_school,
            activity_type="school_visit",
            status="assigned_to_partner",
            delivery_type="partner",
            fy=FY,
            monitored_by_staff_id=self.ben.id,
        )
        ben = self._officer(planning_monitor(self.cd_user, fy=FY), self.ben)
        self.assertEqual((ben.partner_scheduled, ben.partner_awaiting), (0, 1))
        self.assertEqual(ben.partner_assigned_schools, 1)
        self.assertEqual(ben.no_visit, 1)

    def test_a_core_graduate_school_is_followed_like_a_client_school(self):
        self._school("MON-G1", "core_graduate", self.ben)
        ben = self._officer(planning_monitor(self.cd_user, fy=FY), self.ben)
        self.assertEqual((ben.school_count, ben.client_schools), (2, 2))

    def test_a_lead_using_another_role_is_still_followed_with_their_team(self):
        self.pl_user.roles = [
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.ADMIN.value,
        ]
        self.pl_user.active_role = EdifyRole.ADMIN.value
        self.pl_user.save()
        monitor = planning_monitor(self.cd_user, fy=FY)
        lead = next(lead for lead in monitor["leads"] if lead.key == self.pl.id)
        self.assertEqual(lead.officer_count, 3)
        self.assertEqual(lead.visits_target, PL_VISITS_TARGET + 2 * CCEO_VISITS_TARGET)
