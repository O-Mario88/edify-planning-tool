"""The Planning and Execution Monitors follow people (owner, 2026-09-29).

"On the Planning Monitoring summaries, PL plans for maximum of 280 and CCEO
560 ... fetch the right data based on what people have planned. Accuracy is
everything ... Design a similar Country execution and completion
Monitoring ... give PLs access ... so they can follow up with their team
members ... add the column for schools assigned to partner and activities
scheduled by partners."

Also the plan export (the Training Name and SSA intervention of every
training, a School ID on every school row) and the SSA intervention every
training carries from its course.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
)
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.execution_monitor import execution_monitor
from apps.planning.planning_monitor import planning_monitor
from apps.schools.models import School

FY = "2027"
DAY = date(2026, 11, 3)
TODAY = date(2027, 2, 1)


def _user(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    profile = StaffProfile.objects.create(user=user)
    return user, profile


class PeopleFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="People Region")
        cls.district = District.objects.create(
            name="People District", region=cls.region
        )
        cls.lead_user, cls.lead = _user(
            "lead@people.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.other_lead_user, cls.other_lead = _user(
            "other@people.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        # Cara owns every school; Dan owns none and plans at hers.
        cls.cara_user, cls.cara = _user("cara@people.test", EdifyRole.CCEO)
        cls.dan_user, cls.dan = _user("dan@people.test", EdifyRole.CCEO)
        cls.eve_user, cls.eve = _user("eve@people.test", EdifyRole.CCEO)
        for officer in (cls.cara, cls.dan):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.lead
            )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.eve, supervisor=cls.other_lead
        )
        cls.cd_user, _ = _user("cd@people.test", EdifyRole.COUNTRY_DIRECTOR)
        cls.cluster = Cluster.objects.create(
            name="People Cluster", region=cls.region, district=cls.district
        )
        cls.client_school = cls._school("PPL-1", "client")
        cls.core = cls._school("PPL-C", "core")

    @classmethod
    def _school(cls, code, school_type):
        return School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            school_type=school_type,
            account_owner_id=cls.cara.id,
            account_owner_status="matched",
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
        )

    @classmethod
    def _work(cls, person, activity_type, *, school=None, status="scheduled", **extra):
        return Activity.objects.create(
            school=school if school is not None else cls.client_school,
            activity_type=activity_type,
            status=status,
            delivery_type=extra.pop("delivery_type", "staff"),
            fy=FY,
            planned_date=extra.pop("planned_date", DAY),
            responsible_staff_id=person.id,
            **extra,
        )

    @staticmethod
    def _row(rows, profile):
        return next(row for row in rows if row.key == profile.id)


class ThePlanningMonitorFollowsPeople(PeopleFixture):
    def _people(self, user=None):
        monitor = planning_monitor(user or self.cd_user, fy=FY)
        return [o for lead in monitor["leads"] for o in lead.officers], monitor

    def test_a_lead_plans_280_and_a_cceo_560(self):
        people, _ = self._people()
        self.assertEqual(self._row(people, self.lead).visits_target, 280)
        self.assertEqual(self._row(people, self.cara).visits_target, 560)
        self.assertEqual(self._row(people, self.lead).role_label, "Programme Lead")

    def test_a_cceo_with_no_school_is_still_followed_with_their_plan(self):
        self._work(self.dan, "school_visit")
        self._work(self.dan, "training_follow_up_visit")
        # SSA Support he schedules himself is one of his 560 (owner,
        # 2026-10-03, reversing the day before for staff).
        self._work(self.dan, "ssa_activity")
        people, _ = self._people()
        dan = self._row(people, self.dan)
        self.assertEqual((dan.school_count, dan.staff_visits), (0, 3))

    def test_visits_count_what_team_plan_lists(self):
        # A visit returned for correction is still planned; a cancelled visit
        # and a partner's delivery are not the officer's. SSA Support the
        # officer schedules counts (owner, 2026-10-03).
        self._work(self.cara, "school_visit")
        self._work(self.cara, "ssa_activity")
        self._work(self.cara, "school_visit_ssa_collection")
        self._work(self.cara, "school_visit", status="returned_by_pl")
        self._work(self.cara, "school_visit", status="cancelled")
        self._work(self.cara, "school_visit", delivery_type="partner")
        self._work(self.cara, "core_visit", school=self.core)
        cara = self._row(self._people()[0], self.cara)
        self.assertEqual((cara.core_visits, cara.client_visits), (1, 4))

    def test_the_lead_total_carries_the_lead_s_own_target(self):
        _, monitor = self._people()
        team = next(lead for lead in monitor["leads"] if lead.key == self.lead.id)
        self.assertEqual(team.visits_target, 280 + 560 + 560)
        self.assertEqual(monitor["totals"].visits_target, 2 * 280 + 3 * 560)

    def test_a_programme_lead_reads_their_own_team(self):
        people, _ = self._people(self.lead_user)
        self.assertEqual(
            {p.key for p in people}, {self.lead.id, self.cara.id, self.dan.id}
        )

    def test_partner_schools_and_partner_activities_per_person(self):
        partner = Partner.objects.create(name="People Partner")
        self._work(
            self.cara,
            "school_visit",
            delivery_type="partner",
            monitored_by_staff_id=self.cara.id,
            status="completed",
        )
        PartnerAssignment.objects.create(
            school=self.core,
            partner=partner,
            assigning_staff_id=self.cara.id,
            status=PartnerAssignment.UNSCHEDULED_STATUSES[0],
        )
        PartnerAssignment.objects.create(
            school=self.core,
            partner=partner,
            assigning_staff_id=self.cara.id,
            status="returned_to_staff",
        )
        people, monitor = self._people()
        cara = self._row(people, self.cara)
        self.assertEqual(cara.partner_assigned_schools, 2)
        self.assertEqual(
            (cara.partner_scheduled, cara.partner_delivered, cara.partner_awaiting),
            (1, 1, 1),
        )
        self.assertEqual(monitor["totals"].partner_scheduled, 1)


class TheExecutionMonitor(PeopleFixture):
    def _people(self, **kwargs):
        monitor = execution_monitor(self.cd_user, fy=FY, today=TODAY, **kwargs)
        return [p for team in monitor["teams"] for p in team.people], monitor

    def test_delivered_complete_overdue_and_verified(self):
        done = self._work(
            self.cara,
            "school_visit",
            status="completed",
            salesforce_activity_id="SVE-1",
        )
        EvidenceRecord.objects.create(
            activity=done, kind="visit_form", uri="f.pdf", uploaded_by=self.cara_user.id
        )
        self._work(self.cara, "school_visit", status="completed")  # nothing in
        self._work(self.cara, "school_visit")  # due, not delivered
        self._work(self.cara, "school_visit", planned_date=TODAY)  # due today
        self._work(self.cara, "school_visit", planned_date=TODAY + timedelta(days=9))
        self._work(self.cara, "school_visit", status="ia_verified")
        self._work(self.cara, "school_visit", status="awaiting_ia_verification")
        self._work(self.cara, "school_visit", status="returned_by_ia")
        cara = self._row(self._people()[0], self.cara)
        self.assertEqual((cara.planned, cara.due, cara.delivered), (8, 7, 4))
        self.assertEqual(cara.visits_delivered, 4)
        self.assertEqual(cara.complete, 1)
        self.assertEqual((cara.missing_salesforce, cara.missing_evidence), (3, 3))
        # The day itself is not late, and returned work is its own list.
        self.assertEqual((cara.overdue, cara.returned), (1, 1))
        self.assertEqual((cara.verified, cara.awaiting_ia), (1, 1))
        self.assertEqual(cara.target_progress, 1)

    def test_the_list_behind_a_count(self):
        late = self._work(self.cara, "school_visit")
        self._work(self.dan, "school_visit")
        _, monitor = self._people(list_key="overdue", person_id=self.cara.id)
        self.assertEqual([row.id for row in monitor["rows"]], [late.id])
        self.assertEqual(monitor["rows"][0].school_code, "PPL-1")

    def test_partner_work_is_counted_for_its_monitor(self):
        self._work(
            self.dan,
            "school_visit",
            delivery_type="partner",
            monitored_by_staff_id=self.cara.id,
            status="completed",
        )
        people, _ = self._people()
        cara, dan = self._row(people, self.cara), self._row(people, self.dan)
        self.assertEqual((cara.partner_scheduled, cara.partner_delivered), (1, 1))
        self.assertEqual((dan.partner_scheduled, dan.planned), (0, 0))

    def test_a_team_total_is_the_sum_of_its_people(self):
        self._work(self.cara, "school_visit", status="completed")
        self._work(self.dan, "school_visit")
        _, monitor = self._people()
        team = next(t for t in monitor["teams"] if t.key == self.lead.id)
        self.assertEqual((team.planned, team.delivered, team.overdue), (2, 1, 1))
        self.assertEqual(team.visits_target, 280 + 2 * 560)


class ThePlanningMonitorPage(PeopleFixture):
    """Its own page, under the Dashboard in the sidebar (owner, 2026-09-29:
    "move the on its own page and add it to the side bar and place it below
    the Dashboard. Do the same for PL")."""

    #: What the Programme Lead's dashboard section sends with its requests
    #: (the monitor moved onto their dashboard, owner 2026-09-29).
    EMBED = {"HTTP_HX_REQUEST": "true", "HTTP_X_EDIFY_EMBED": "dashboard"}

    def test_both_tabs_for_the_cd_and_the_lead(self):
        for user, headers in ((self.cd_user, {}), (self.lead_user, self.EMBED)):
            self.client.force_login(user)
            for view, marker in (
                ("planning", "data-planning-monitor"),
                ("execution", "data-execution-monitor"),
            ):
                with self.subTest(role=user.active_role, view=view):
                    response = self.client.get(
                        f"/planning-monitor/?view={view}", **headers
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, marker)
                    self.assertContains(response, "Execution &amp; Completion")

    def test_the_dashboard_section_gets_the_tabs_and_no_history_entry(self):
        self.client.force_login(self.lead_user)
        response = self.client.get(
            f"/planning-monitor/?view=execution&fy={FY}", **self.EMBED
        )
        self.assertEqual(response["HX-Push-Url"], "false")
        body = response.content.decode()
        self.assertNotIn("<html", body)
        # The tabs travel with the workspace, the shown one marked, and keep
        # the dashboard's year.
        self.assertIn(f'hx-get="/planning-monitor/?view=planning&amp;fy={FY}"', body)
        self.assertRegex(
            body,
            r'aria-current="page"\s+hx-get="/planning-monitor/\?view=execution&amp;fy=',
        )

    def test_the_dashboard_section_does_not_ask_the_year_again(self):
        """Owner, 2026-10-02: "make sure the PLs dont have repeated filters. I
        see FY filters ...". The dashboard has one year, on its title line;
        the monitor it carries reads that year and offers no second one."""
        self.client.force_login(self.lead_user)
        for view in ("planning", "execution"):
            with self.subTest(view=view):
                body = self.client.get(
                    f"/planning-monitor/?view={view}&fy={FY}", **self.EMBED
                ).content.decode()
                self.assertNotIn('<select name="fy"', body)
                self.assertNotIn("Planning year", body)
                self.assertNotIn("Delivery year", body)
                # Its other filters still send the year they are read on.
                self.assertIn(f'<input type="hidden" name="fy" value="{FY}">', body)
        # On a page of its own the monitor keeps its year.
        self.client.force_login(self.cd_user)
        page = self.client.get("/planning-monitor/").content.decode()
        self.assertIn('<select name="fy"', page)

    def test_the_dashboard_s_year_is_the_monitor_s_year(self):
        self.client.force_login(self.lead_user)
        dashboard = self.client.get("/dashboard?fy=2026&view=week").content.decode()
        self.assertIn('hx-get="/planning-monitor/?fy=2026"', dashboard)
        self.assertEqual(dashboard.count('name="fy"'), 1)
        # A link to the monitor that names a year opens the dashboard on it.
        response = self.client.get("/planning-monitor/?view=execution&fy=2026")
        self.assertEqual(
            response["Location"],
            "/dashboard?fy=2026&pm=view%3Dexecution%26fy%3D2026#planning-monitor",
        )

    def test_a_lead_reads_their_own_team(self):
        self.client.force_login(self.lead_user)
        body = self.client.get("/planning-monitor/", **self.EMBED).content.decode()
        # Each person heads their row: "<name> <role>".
        self.assertIn(">Cara <span", body)
        self.assertNotIn(">Eve <span", body)

    def test_a_lead_opening_the_page_lands_on_their_dashboard(self):
        self.client.force_login(self.lead_user)
        response = self.client.get("/planning-monitor/?view=execution&list=overdue")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            "/dashboard?pm=view%3Dexecution%26list%3Doverdue#planning-monitor",
        )
        dashboard = self.client.get(response["Location"].split("#")[0])
        self.assertContains(
            dashboard,
            'hx-get="/planning-monitor/?view=execution&amp;list=overdue&amp;fy=',
        )
        # An htmx request is moved, not swapped.
        moved = self.client.get("/planning-monitor/", HTTP_HX_REQUEST="true")
        self.assertEqual(moved["HX-Redirect"], "/dashboard#planning-monitor")

    def test_a_cceo_has_no_page(self):
        self.client.force_login(self.cara_user)
        self.assertNotEqual(self.client.get("/planning-monitor/").status_code, 200)

    def test_the_sidebar_lists_it_right_under_the_dashboard(self):
        self.client.force_login(self.cd_user)
        body = self.client.get("/planning-monitor/").content.decode()
        dashboard = body.index('href="/country-planning-oversight/"')
        monitor = body.index('href="/planning-monitor/"')
        self.assertLess(dashboard, monitor)
        between = body[dashboard:monitor]
        self.assertNotIn('href="/planning"', between)

    def test_the_leads_sidebar_does_not_list_it(self):
        # It is on their dashboard (owner, 2026-09-29).
        self.client.force_login(self.lead_user)
        body = self.client.get("/dashboard").content.decode()
        self.assertIn('id="planning-monitor"', body)
        self.assertNotIn('href="/planning-monitor/"', body)

    def test_old_monitor_links_open_the_page(self):
        self.client.force_login(self.cd_user)
        for old, view in (
            ("/country-planning-oversight/?view=monitor&fy=2027", "planning"),
            ("/team-planning-oversight/?view=monitor&fy=2027", "planning"),
            ("/team-planning-oversight/?view=execution", "execution"),
        ):
            with self.subTest(old=old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/planning-monitor/?", response["Location"])
                self.assertIn(f"view={view}", response["Location"])


class IaReadsTheMonitorsOnPlanningOversight(PeopleFixture):
    """Owner, 2026-09-30: "on IA can you move the planning monitor and
    Execution & Completion tabs back to Planning oversight page"."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, _ = _user("ia@people.test", EdifyRole.IMPACT_ASSESSMENT)

    def setUp(self):
        self.client.force_login(self.ia_user)

    def test_the_tabs_sit_beside_the_team_plan(self):
        response = self.client.get("/team-planning-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(t["key"], t["label"]) for t in response.context["lens_tabs"]],
            [
                ("planning", "Team Plan"),
                ("monitor", "Planning Monitor"),
                ("execution", "Execution & Completion"),
                ("portfolio", "Country Portfolio"),
                ("coverage", "Schools & Coverage"),
                ("targets", "Target Performance"),
            ],
        )
        body = response.content.decode()
        self.assertIn('href="/team-planning-oversight/?view=monitor"', body)
        self.assertIn('href="/team-planning-oversight/?view=execution"', body)
        # The page of its own is gone from their sidebar.
        self.assertNotIn('href="/planning-monitor/"', body)

    def test_each_tab_opens_its_monitor_in_place(self):
        for view, marker in (
            ("monitor", "data-planning-monitor"),
            ("execution", "data-execution-monitor"),
        ):
            with self.subTest(view=view):
                response = self.client.get(f"/team-planning-oversight/?view={view}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, marker)
                self.assertRegex(
                    response.content.decode(),
                    rf'href="/team-planning-oversight/\?view={view}"\s+'
                    r'data-edify-tab\s+aria-current="page"',
                )
                # The country's people, under every Lead.
                self.assertContains(response, ">Cara <span")
                self.assertContains(response, ">Eve <span")
                # A filter change swaps the workspace and stays on the page.
                swap = self.client.get(
                    f"/team-planning-oversight/?view={view}", HTTP_HX_REQUEST="true"
                )
                self.assertNotContains(swap, "<html")
                self.assertContains(swap, marker)
                self.assertContains(swap, 'hx-get="/team-planning-oversight/"')

    def test_old_links_open_the_tab_here(self):
        for old, destination in (
            ("/planning-monitor/", "/team-planning-oversight/?view=monitor"),
            (
                "/planning-monitor/?view=planning&gap=no_visit",
                "/team-planning-oversight/?view=monitor&gap=no_visit",
            ),
            (
                "/planning-monitor/?view=execution&list=overdue",
                "/team-planning-oversight/?view=execution&list=overdue",
            ),
            (
                "/country-planning-oversight/?view=monitor&fy=2027",
                "/team-planning-oversight/?view=monitor&fy=2027",
            ),
        ):
            with self.subTest(old=old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], destination)

    def test_the_country_director_keeps_the_page_of_its_own(self):
        self.client.force_login(self.cd_user)
        keys = [
            t["key"]
            for t in self.client.get("/team-planning-oversight/").context["lens_tabs"]
        ]
        self.assertNotIn("monitor", keys)
        self.assertNotIn("execution", keys)
        response = self.client.get("/team-planning-oversight/?view=execution")
        self.assertEqual(response["Location"], "/planning-monitor/?view=execution")


class TrainingsCarryTheirIntervention(PeopleFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.course = ActivityCatalogueItem.objects.create(
            stable_code="PPL-DISCIPLESHIP",
            source_name="Discipleship Dynamics",
            display_name="Discipleship Dynamics",
            activity_type="training",
            status="active",
            costing_profile="IN_SCHOOL_TRAINING",
            evidence_profile="TRAINING_ATTENDANCE",
            salesforce_record_type="TRAINING",
            is_training_course=True,
        )
        ActivityInterventionMapping.objects.create(
            catalogue_item=cls.course,
            intervention="exposure_to_word_of_god",
            mapping_mode="fixed",
        )

    def test_a_training_saved_without_one_takes_its_course_s(self):
        training = self._work(
            self.cara, "in_school_training", training_course=self.course
        )
        training.refresh_from_db()
        self.assertEqual(training.focus_intervention, "exposure_to_word_of_god")
        self.assertEqual(training.purpose_intervention, "exposure_to_word_of_god")

    def test_the_planner_s_choice_is_kept(self):
        training = self._work(
            self.cara,
            "in_school_training",
            training_course=self.course,
            focus_intervention="leadership",
        )
        training.refresh_from_db()
        self.assertEqual(training.focus_intervention, "leadership")

    def test_the_export_carries_the_training_name_intervention_and_school_ids(self):
        session = Activity.objects.create(
            cluster=self.cluster,
            activity_type="cluster_training",
            status="scheduled",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.cara.id,
            catalogue_item=self.course,
            activity_name_snapshot="Discipleship Dynamics",
        )
        for school in (self.client_school, self.core):
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True
            )
        self.client.force_login(self.cd_user)
        response = self.client.get(f"/country-planning-oversight/export?fy={FY}")
        rows = list(
            csv.DictReader(b"".join(response.streaming_content).decode().splitlines())
        )
        trainings = [row for row in rows if row["Table"] == "Training"]
        self.assertEqual({row["School ID"] for row in trainings}, {"PPL-1", "PPL-C"})
        for row in trainings:
            self.assertEqual(row["Training name"], "Discipleship Dynamics")
            self.assertEqual(row["SSA intervention"], "Exposure to the Word of God")
