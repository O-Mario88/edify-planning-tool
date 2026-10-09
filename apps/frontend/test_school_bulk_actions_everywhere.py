"""Bulk Assign, Schedule and Add to project on every list of schools, and the
three on a school's own profile.

Owner, 2026-10-06: "make sure core school page also get the bulk assign,
schedule, bulk add to project just like these other schools. Add the
checkboxes on core school list so that users can select many and assign or
schedule or add to project. Also, add schedule, assign, and add to project
buttons with their functionalities to the school profile, cluster profiles."

What is pinned here:

* the Core school list and its lifecycle tables tick by school code, with a
  Select-all box and the one bar (partials/schools/bulk_bar.html) whose three
  buttons open the Planning page's bulk hand-over, the bulk Schedule and the
  directory's bulk Add to project; the read-only oversight lens has none;
* the bulk Schedule (/planning/bulk-schedule-drawer, /planning/bulk-schedule)
  schedules one activity per ticked school in the planner's own portfolio,
  a visit at a Core School into its package, and names the school the rules
  refuse rather than refusing the selection;
* the bulk Add to project drawer and its save return the planner to the list
  they ticked on, and never to another host;
* a cluster's roster ticks every school for the same three doors;
* the school profile offers Schedule and Assign to Partner beside Add to
  Project, each the door its list row opens — a Core School's own on Core
  Schools — and none on a closed school.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School

SCHEDULE_DRAWER = "/planning/bulk-schedule-drawer"
SCHEDULE = "/planning/bulk-schedule"
PROJECT_DRAWER = "/schools/bulk-assign-project-drawer"
PROJECT_SAVE = "/schools/bulk-assign-project"


def _delivery_day():
    """A weekday a fortnight out, never a Sunday."""
    day = timezone.localdate() + timedelta(days=14)
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day


class _Portfolio(TestCase):
    """A CCEO with a Core school (with its package), a client school, a Core
    Trained school and a Champion school, all in one cluster; a colleague's
    school outside the portfolio; a supervising Programme Lead; a partner
    and an open project."""

    @classmethod
    def setUpTestData(cls):
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(name="SBE Region")
        cls.district = District.objects.create(name="SBE District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="SBE Sub", district=cls.district)

        cls.cceo = User.objects.create(
            id="sbe-cceo",
            email="sbe-cceo@edify.org",
            name="SBE CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            id="sbe-cceo-sp", user=cls.cceo, title="CCEO", country="Uganda"
        )
        cls.other = User.objects.create(
            id="sbe-other",
            email="sbe-other@edify.org",
            name="SBE Other",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.other_sp = StaffProfile.objects.create(
            id="sbe-other-sp", user=cls.other, title="CCEO", country="Uganda"
        )
        cls.pl = User.objects.create(
            id="sbe-pl",
            email="sbe-pl@edify.org",
            name="SBE Lead",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            is_active=True,
        )
        cls.pl_sp = StaffProfile.objects.create(
            id="sbe-pl-sp", user=cls.pl, title="Programme Lead", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.staff, supervisor=cls.pl_sp
        )

        cls.cluster = Cluster.objects.create(
            name="SBE Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=cls.staff.id,
        )
        cls.core = cls._school("SBE-CORE", cls.staff, "core")
        cls.client_school = cls._school("SBE-CLIENT", cls.staff, "client")
        cls.trained = cls._school("SBE-TRAINED", cls.staff, "core_trained")
        cls.champion = cls._school("SBE-CHAMP", cls.staff, "champion")
        cls.theirs = cls._school("SBE-THEIRS", cls.other_sp, "client")
        cls.plan = CorePlan.objects.create(
            id=cplan_id("SBE-CORE", fy=cls.fy),
            school_id="SBE-CORE",
            fy=cls.fy,
            status="Active",
        )
        create_package_slots(cls.plan, "SBE-CORE", ["leadership"])

        cls.partner = Partner.objects.create(name="SBE Partner", active_status=True)
        cls.project = Project.objects.create(
            name="SBE Project",
            category="pilot",
            status="active",
            intervention=SsaIntervention.LEADERSHIP,
            target_interventions=[SsaIntervention.LEADERSHIP],
            manager_staff_id=cls.staff.id,
        )

    @classmethod
    def _school(cls, code, owner, school_type):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type=school_type,
            account_owner_id=owner.id,
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
            planning_readiness="ready_for_support_planning",
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def setUp(self):
        self.client.force_login(self.cceo)


class TheCoreListTicksTest(_Portfolio):
    def test_the_core_school_list_ticks_by_code_under_one_bar(self):
        response = self.client.get("/core-schools", {"fy": self.fy})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_tick"])
        html = response.content.decode()
        self.assertIn('value="SBE-CORE" x-model="selectedSchools" data-core-pick', html)
        self.assertIn('data-select-all="input[data-core-pick]"', html)
        # The three doors, each the one the row's own action opens.
        self.assertIn('hx-get="/planning/bulk-assign-partner-drawer"', html)
        self.assertIn('hx-get="/planning/bulk-schedule-drawer"', html)
        self.assertIn('hx-get="/schools/bulk-assign-project-drawer"', html)
        self.assertIn('name="next" value="/core-schools"', html)
        # The ticks are let go when the list changes under them.
        self.assertIn('@htmx:after-swap="selectedSchools = []"', html)

    def test_the_lifecycle_tables_tick_too(self):
        response = self.client.get("/core-schools", {"fy": self.fy})

        html = response.content.decode()
        self.assertIn(
            'value="SBE-TRAINED" x-model="selectedSchools" data-lifecycle-pick', html
        )
        self.assertIn(
            'value="SBE-CHAMP" x-model="selectedSchools" data-lifecycle-pick', html
        )
        self.assertIn('data-select-all="input[data-lifecycle-pick]"', html)

    def test_the_read_only_oversight_lens_has_no_boxes(self):
        self.client.force_login(self.pl)

        response = self.client.get(
            "/core-schools", {"fy": self.fy, "lens": "oversight"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_oversight_lens"])
        self.assertFalse(response.context["can_tick"])
        self.assertNotContains(response, "data-core-pick")
        self.assertNotContains(response, "data-school-bulk-bar")


class TheBulkScheduleTest(_Portfolio):
    def _codes(self, *codes):
        return [code for code in codes]

    def test_the_drawer_lists_the_portfolio_and_counts_the_rest(self):
        response = self.client.get(
            SCHEDULE_DRAWER,
            {"school_ids": self._codes("SBE-CORE", "SBE-CLIENT", "SBE-THEIRS")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [school.school_id for school in response.context["schools"]],
            ["SBE-CLIENT", "SBE-CORE"],
        )
        self.assertEqual(response.context["outside_scope"], 1)
        self.assertContains(response, 'name="school_ids" value="SBE-CORE"')
        self.assertContains(response, "Schedule 2 schools")
        self.assertContains(response, "outside your planning portfolio")
        purposes = dict(response.context["visit_purposes"])
        self.assertIn("ssa_support", purposes)
        self.assertIn("in_school_training", purposes)

    def test_each_ticked_school_gets_its_own_activity_and_a_core_visit_takes_its_slot(
        self,
    ):
        day = _delivery_day()

        # The package credit runs once the save commits.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                SCHEDULE,
                {
                    "school_ids": self._codes("SBE-CORE", "SBE-CLIENT", "SBE-CHAMP"),
                    "purpose_of_visit": "ssa_support",
                    "scheduled_date": day.isoformat(),
                },
            )

        self.assertEqual(response.status_code, 200, response.content[:600])
        self.assertContains(response, "Scheduled 2 schools.")
        # The Champion school takes donor and story visits only: named and
        # left out, and the rest of the selection still goes.
        self.assertContains(response, "Not scheduled: School SBE-CHAMP")
        self.assertIn("planning-saved", response["HX-Trigger"])

        # Staff's SSA Support at a Core School is booked as itself and takes
        # a visit slot of the package once saved (owner, 2026-10-03;
        # apps.core_schools.package_credit).
        core_visit = Activity.objects.get(school=self.core, deleted_at__isnull=True)
        self.assertEqual(core_visit.purpose_type, "ssa_support")
        self.assertEqual(core_visit.planned_date, day)
        self.assertTrue(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, activity_type="visit", activity_id=core_visit.id
            ).exists(),
            "a visit at a Core School takes its package slot",
        )
        client_visit = Activity.objects.get(
            school=self.client_school, deleted_at__isnull=True
        )
        self.assertEqual(client_visit.planned_date, day)
        self.assertEqual(client_visit.delivery_type, "staff")
        self.assertFalse(Activity.objects.filter(school=self.champion).exists())

    def test_one_intervention_named_in_the_drawer_is_every_school_s(self):
        """Owner, 2026-09-26: "for group scheduling, SSA intervention should
        be the same. it should be chosen from group visit scheduling
        drawer"."""
        from unittest import mock

        drawer = self.client.get(SCHEDULE_DRAWER, {"school_ids": "SBE-CLIENT"})
        self.assertContains(drawer, 'name="focus_intervention"')
        # In-school Training is on the list of purposes too (owner,
        # 2026-10-09: "add in-school training to it too").
        self.assertContains(drawer, 'value="in_school_training"')

        with mock.patch(
            "apps.frontend.views.planning_views._follow_up_requires_training",
            return_value=False,
        ):
            response = self.client.post(
                SCHEDULE,
                {
                    "school_ids": self._codes("SBE-CLIENT"),
                    "purpose_of_visit": "training_follow_up",
                    "focus_intervention": "learning_environment",
                    "scheduled_date": _delivery_day().isoformat(),
                },
            )

        self.assertEqual(response.status_code, 200, response.content[:600])
        visit = Activity.objects.get(school=self.client_school, deleted_at__isnull=True)
        self.assertEqual(visit.focus_intervention, "learning_environment")

    def test_a_colleague_s_school_is_left_out_not_scheduled(self):
        response = self.client.post(
            SCHEDULE,
            {
                "school_ids": self._codes("SBE-CLIENT", "SBE-THEIRS"),
                "purpose_of_visit": "ssa_support",
                "scheduled_date": _delivery_day().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200, response.content[:600])
        self.assertContains(response, "Scheduled 1 school.")
        self.assertContains(response, "1 selected school is outside your planning")
        self.assertFalse(Activity.objects.filter(school=self.theirs).exists())

    def test_nothing_in_the_portfolio_is_a_refusal(self):
        response = self.client.post(
            SCHEDULE,
            {
                "school_ids": self._codes("SBE-THEIRS"),
                "purpose_of_visit": "ssa_support",
                "scheduled_date": _delivery_day().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Activity.objects.filter(school=self.theirs).exists())

    def test_a_purpose_is_asked_for(self):
        response = self.client.post(
            SCHEDULE,
            {
                "school_ids": self._codes("SBE-CLIENT"),
                "scheduled_date": _delivery_day().isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "purpose", status_code=400)
        self.assertFalse(Activity.objects.filter(school=self.client_school).exists())


class ThePlanningPageSchedulesTheTickTest(_Portfolio):
    """Owner, 2026-10-09: "allow group scheduling direct from the planning
    page by using checkbox and alongside assign to partner, the button for
    schedule for visit"."""

    def test_the_selection_bar_opens_the_group_schedule(self):
        response = self.client.get("/planning", {"fy": self.fy})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_bulk_schedule"])
        html = response.content.decode()
        self.assertIn("data-planning-assign-selected", html)
        self.assertIn("data-planning-schedule-selected", html)
        self.assertIn('hx-get="/planning/bulk-schedule-drawer"', html)
        # The save lets the ticks go and re-reads the list in place.
        self.assertIn('@planning-saved.window="selectedSchools = []"', html)

    def test_a_reader_who_cannot_schedule_has_no_button(self):
        from unittest import mock

        from apps.core.permissions import RolePermissionService

        with mock.patch.object(
            RolePermissionService, "can_schedule_activity", return_value=False
        ):
            response = self.client.get("/planning", {"fy": self.fy})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-planning-schedule-selected")


class TheBulkAddToProjectTest(_Portfolio):
    def test_the_drawer_lists_the_schools_and_the_projects(self):
        response = self.client.get(
            PROJECT_DRAWER,
            {"school_ids": ["SBE-CORE", "SBE-CLIENT"], "next": "/core-schools"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [school.school_id for school in response.context["schools"]],
            ["SBE-CLIENT", "SBE-CORE"],
        )
        self.assertContains(response, "Add 2 schools to a project")
        self.assertContains(response, 'action="/schools/bulk-assign-project"')
        self.assertContains(response, 'name="next" value="/core-schools"')
        self.assertContains(response, f'<option value="{self.project.id}"')
        ids = response.context["school_ids"].split(",")
        self.assertEqual(sorted(ids), sorted([self.core.id, self.client_school.id]))

    def test_the_save_takes_codes_and_returns_to_the_list(self):
        response = self.client.post(
            PROJECT_SAVE,
            {
                "school_ids": "SBE-CORE,SBE-CLIENT",
                "project_id": self.project.id,
                "next": "/core-schools",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/core-schools")
        self.assertEqual(
            sorted(
                ProjectSchoolAssignment.objects.filter(
                    project=self.project
                ).values_list("school__school_id", flat=True)
            ),
            ["SBE-CLIENT", "SBE-CORE"],
        )

    def test_a_return_to_another_host_falls_back_to_the_directory(self):
        response = self.client.post(
            PROJECT_SAVE,
            {
                "school_ids": "SBE-CLIENT",
                "project_id": self.project.id,
                "next": "https://evil.example/anywhere",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/schools")


class TheClusterProfileTicksTest(_Portfolio):
    def test_every_school_ticks_for_the_three_doors(self):
        response = self.client.get(f"/clusters/{self.cluster.id}")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # The Champion school is not on the roster: it has its own table
        # (apps.clusters.services, OWN_TABLE_SCHOOL_TYPES).
        for code in ("SBE-CORE", "SBE-CLIENT", "SBE-TRAINED"):
            with self.subTest(school=code):
                self.assertIn(
                    f'value="{code}" x-model="selectedSchools" data-cluster-pick', html
                )
        self.assertIn("data-school-assign-selected", html)
        self.assertIn("data-school-schedule-selected", html)
        self.assertIn("data-school-project-selected", html)
        self.assertIn(f'name="next" value="/clusters/{self.cluster.id}"', html)
        self.assertIn('data-select-all="input[data-cluster-pick]"', html)


class TheSchoolProfileButtonsTest(_Portfolio):
    def test_a_core_school_opens_its_own_doors(self):
        response = self.client.get("/schools/SBE-CORE")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["profile_core_routes"])
        self.assertContains(
            response, 'hx-get="/core-schools/schedule-activity?school_id=SBE-CORE"'
        )
        self.assertContains(
            response, 'hx-get="/core-schools/assign-partner?school_id=SBE-CORE"'
        )
        self.assertContains(
            response, f'hx-get="/schools/{self.core.id}/assign-to-project"'
        )

    def test_a_client_school_opens_the_planning_drawers(self):
        response = self.client.get("/schools/SBE-CLIENT")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["profile_core_routes"])
        self.assertContains(
            response, 'hx-get="/planning/schedule-modal?school_id=SBE-CLIENT"'
        )
        self.assertContains(
            response, 'hx-get="/planning/assign-partner-modal?school_id=SBE-CLIENT"'
        )

    def test_a_school_no_partner_may_take_says_so_on_the_greyed_button(self):
        response = self.client.get("/schools/SBE-CHAMP")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["assign_block"])
        self.assertContains(response, 'data-assign-locked="true"')
        self.assertNotContains(response, "assign-partner-modal?school_id=SBE-CHAMP")

    def test_a_closed_school_offers_neither(self):
        from apps.schools.lifecycle_models import CLOSED_STATUSES

        School.objects.filter(id=self.client_school.id).update(
            operational_status=CLOSED_STATUSES[0]
        )

        response = self.client.get("/schools/SBE-CLIENT")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_schedule"])
        self.assertFalse(response.context["can_assign_partner"])
        self.assertNotContains(response, "data-profile-schedule")
        self.assertNotContains(response, "data-profile-assign")
