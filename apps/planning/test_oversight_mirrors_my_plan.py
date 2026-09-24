"""Oversight mirrors My Plan, person by person.

Owner, 2026-09-24: "Planning Oversight, Core School Oversight, Cluster
Oversight should all fetch data from My Plan pages (for the PL and for the
CCEOs) since all their plans are in My Plan page."

My Plan is where a Programme Lead and each CCEO keep their own work, so it is
the list every oversight page is checked against. The invariant is one-way on
purpose: everything on a person's My Plan appears under that person on each
oversight page that covers its kind of work. Oversight may show more — the
partner work a CCEO monitors, overdue work My Plan moves to the Dashboard,
closed work — because watching a plan is a wider question than working it.
It may never show less, and it may never file a person's work under somebody
else or split one person into two.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan.services import get_frontend_context
from apps.schools.models import School

#: The My Plan lists that hold a person's own activities. Each row carries the
#: activity id; cluster trainings are expanded into one row per invited school,
#: which is why the ids are collected into a set.
_MY_PLAN_LISTS = (
    "school_visits",
    "cluster_trainings",
    "cluster_meetings",
    "core_school_visits",
    "core_school_trainings",
    "programme_activities",
)


def my_plan_ids(user, **query) -> set[str]:
    """Every activity id on this person's My Plan for the query."""
    context = get_frontend_context(user, {key: str(v) for key, v in query.items()})
    ids = {row["id"] for key in _MY_PLAN_LISTS for row in context.get(key, [])}
    for section in context.get("programme_school_work", []):
        ids |= {row["id"] for row in section["rows"]}
    return ids


def _user(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    profile = StaffProfile.objects.create(user=user, title=name)
    return user, profile


class MirrorFixture(TestCase):
    """A Programme Lead and two CCEOs, with the work each keeps on My Plan.

    The activities are written the ways production writes them: some carry a
    StaffProfile id as the responsible officer and some a User id (the two id
    spaces ``apps.core.scoping.owner_ids`` exists for), some are dated with no
    planned month (legacy rows), and some fall in the next fiscal year, which
    is where September planning lands.
    """

    @classmethod
    def setUpTestData(cls):
        today = date.today()
        cls.fy = get_operational_fy(today)
        cls.next_fy = str(int(cls.fy) + 1)
        # Soon, but inside this fiscal year: a row's fy and its date must agree,
        # or the fixture itself would be the inconsistency under test.
        cls.soon = min(today + timedelta(days=3), date(int(cls.fy), 9, 30))

        cls.region = Region.objects.create(name="Mirror Region")
        cls.district = District.objects.create(
            name="Mirror District", region=cls.region
        )

        cls.pl_user, cls.pl = _user(
            "lead@mirror.test", "Lead Mirror", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = _user("james@mirror.test", "James", EdifyRole.CCEO)
        cls.mary_user, cls.mary = _user("mary@mirror.test", "Mary", EdifyRole.CCEO)
        for officer in (cls.james, cls.mary):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.pl
            )
        cls.cd_user, _ = _user("cd@mirror.test", "Director", EdifyRole.COUNTRY_DIRECTOR)

        cls.cluster = Cluster.objects.create(
            name="Mirror Cluster",
            region=cls.region,
            district=cls.district,
            responsible_staff_id=cls.james.id,
        )
        cls.client_school = cls._school("MIR-1", "Mirror Client", cls.james_user.id)
        cls.core_school = cls._school(
            "MIR-2", "Mirror Core", cls.james_user.id, school_type="core"
        )
        cls.mary_school = cls._school("MIR-3", "Mary Client", cls.mary_user.id)
        cls.pl_school = cls._school("MIR-4", "Lead Client", cls.pl_user.id)

        make = cls._activity
        cls.james_work = [
            # Written by activities.services.create: a StaffProfile id.
            make("school_visit", cls.james.id, school=cls.client_school),
            # Written by an older path: the User id. Same person.
            make("follow_up_visit", cls.james_user.id, school=cls.client_school),
            make("core_visit", cls.james.id, school=cls.core_school),
            make("in_school_training", cls.james.id, school=cls.core_school),
            make("cluster_meeting", cls.james.id, cluster=cls.cluster),
            make("cluster_training", cls.james_user.id, cluster=cls.cluster),
            # Completed work stays on My Plan until it is closed.
            make(
                "school_visit",
                cls.james.id,
                school=cls.client_school,
                status="submitted_to_pl",
            ),
            # A legacy row: dated, but with no planned month.
            make(
                "coaching_visit",
                cls.james.id,
                school=cls.client_school,
                planned_month=None,
            ),
        ]
        cls.james_next_fy = make(
            "school_visit",
            cls.james.id,
            school=cls.client_school,
            fy=cls.next_fy,
            planned=date(int(cls.fy), 10, 6),
        )
        cls.mary_work = [
            make("school_visit", cls.mary_user.id, school=cls.mary_school),
            make("cluster_meeting", cls.mary.id, cluster=cls.cluster),
        ]
        cls.pl_work = [
            make("school_visit", cls.pl.id, school=cls.pl_school),
            make("school_visit", cls.pl_user.id, school=cls.pl_school),
        ]

    @classmethod
    def _school(cls, code, name, owner, *, school_type="client"):
        return School.objects.create(
            school_id=code,
            name=name,
            district=cls.district,
            region=cls.region,
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
            school_type=school_type,
            account_owner_id=owner,
            account_owner_status="matched",
        )

    @classmethod
    def _activity(
        cls,
        activity_type,
        owner_id,
        *,
        school=None,
        cluster=None,
        status="scheduled",
        fy=None,
        planned=None,
        planned_month="auto",
    ):
        planned = planned or cls.soon
        return Activity.objects.create(
            activity_type=activity_type,
            school=school,
            cluster=cluster,
            responsible_staff_id=owner_id,
            fy=fy or cls.fy,
            planned_date=planned,
            planned_month=planned.month if planned_month == "auto" else planned_month,
            status=status,
        )

    def people(self):
        """Each person, with the ids of the work they keep on My Plan."""
        return (
            (self.pl_user, self.pl, self.pl_work),
            (self.james_user, self.james, self.james_work),
            (self.mary_user, self.mary, self.mary_work),
        )


class MyPlanHoldsTheFixtureTest(MirrorFixture):
    """The premise: every row above really is on its owner's My Plan."""

    def test_each_person_sees_their_own_work_on_my_plan(self):
        for user, _profile, work in self.people():
            with self.subTest(person=user.name):
                self.assertEqual(
                    my_plan_ids(user, fy=self.fy, period="fy"),
                    {a.id for a in work},
                )


class PlanningOversightMirrorsMyPlanTest(MirrorFixture):
    """Planning Oversight files each person's My Plan under that person."""

    def _team_groups(self, **params):
        self.client.force_login(self.pl_user)
        response = self.client.get(
            "/team-planning-oversight/", {"fy": self.fy, **params}
        )
        self.assertEqual(response.status_code, 200)
        return response.context["groups"]

    def _ids_under(self, groups, profile) -> set[str]:
        """Ids in every group filed under this person — there must be one."""
        mine = [
            group
            for group in groups
            if str(group["id"]) in {str(profile.id), str(profile.user_id)}
        ]
        self.assertLessEqual(
            len(mine), 1, f"{profile.title} is split across {len(mine)} tabs"
        )
        return {item.activity_id for group in mine for item in group["items"]}

    def test_the_team_page_holds_every_person_s_my_plan_under_them(self):
        groups = self._team_groups()
        for user, profile, _work in self.people():
            with self.subTest(person=user.name):
                expected = my_plan_ids(user, fy=self.fy, period="fy")
                self.assertTrue(expected)
                self.assertEqual(
                    expected - self._ids_under(groups, profile),
                    set(),
                )

    def test_one_person_is_one_tab_whichever_id_space_wrote_their_work(self):
        groups = self._team_groups()
        names = [group["name"] for group in groups]
        self.assertEqual(len(names), len(set(names)), names)

    def test_every_supervised_officer_has_a_tab_even_with_nothing_planned(self):
        idle_user, idle = _user("idle@mirror.test", "Idle", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=idle, supervisor=self.pl)
        ids = {str(group["id"]) for group in self._team_groups()}
        self.assertIn(str(idle.id), ids)

    def test_a_month_on_oversight_holds_that_month_of_my_plan(self):
        month = self.soon.month
        groups = self._team_groups(period="month", month=month)
        for user, profile, _work in self.people():
            with self.subTest(person=user.name):
                expected = my_plan_ids(user, fy=self.fy, month=month)
                self.assertEqual(expected - self._ids_under(groups, profile), set())

    def test_the_next_fiscal_year_mirrors_too(self):
        groups = self._team_groups(fy=self.next_fy)
        self.assertEqual(
            my_plan_ids(self.james_user, fy=self.next_fy, period="fy")
            - self._ids_under(groups, self.james),
            set(),
        )

    def test_the_country_page_files_each_team_under_its_lead(self):
        self.client.force_login(self.cd_user)
        response = self.client.get(
            f"/country-planning-oversight/team/{self.pl.id}", {"fy": self.fy}
        )
        self.assertEqual(response.status_code, 200)
        groups = response.context["owner_groups"]
        for user, profile, _work in self.people():
            with self.subTest(person=user.name):
                expected = my_plan_ids(user, fy=self.fy, period="fy")
                self.assertEqual(expected - self._ids_under(groups, profile), set())


class ClusterOversightMirrorsMyPlanTest(MirrorFixture):
    """Cluster Oversight lists each person's meetings and group trainings."""

    def _session_ids(self, tab) -> set[str]:
        return {
            item.activity_id
            for item in tab.get("meetings", []) + tab.get("trainings", [])
        }

    def _my_plan_cluster_ids(self, user) -> set[str]:
        context = get_frontend_context(user, {"fy": self.fy, "period": "fy"})
        rows = context["cluster_meetings"] + context["cluster_trainings"]
        return {row["id"] for row in rows if row.get("cluster_id")}

    def test_the_lead_page_holds_each_person_s_cluster_sessions(self):
        from apps.clusters.oversight_service import cluster_oversight_table_data

        data = cluster_oversight_table_data(self.pl_user, fy=self.fy)
        tabs = {str(tab["id"]): tab for tab in data["cceo_tabs"]}
        for user, profile, _work in self.people():
            with self.subTest(person=user.name):
                key = "my-clusters" if profile == self.pl else str(profile.id)
                self.assertEqual(
                    self._my_plan_cluster_ids(user) - self._session_ids(tabs[key]),
                    set(),
                )


class CoreSchoolsOversightMirrorsMyPlanTest(MirrorFixture):
    """Core School Oversight lists the core visits and trainings on My Plan."""

    def _my_plan_core_ids(self, user) -> set[str]:
        context = get_frontend_context(user, {"fy": self.fy, "period": "fy"})
        rows = context["core_school_visits"] + context["core_school_trainings"]
        return {row["id"] for row in rows}

    def test_the_lead_page_holds_each_officer_s_planned_core_work(self):
        from apps.core_schools.oversight_service import core_schools_oversight_data

        data = core_schools_oversight_data(self.pl_user, fy=self.fy)
        tabs = {str(tab["id"]): tab for tab in data["cceo_tabs"]}
        expected = self._my_plan_core_ids(self.james_user)
        self.assertTrue(expected)
        planned = {item.activity_id for item in tabs[str(self.james.id)]["core_work"]}
        self.assertEqual(expected - planned, set())

    def test_the_country_page_holds_each_officer_s_planned_core_work(self):
        from apps.core_schools.oversight_service import core_schools_oversight_data

        data = core_schools_oversight_data(self.cd_user, fy=self.fy)
        lead = next(lead for lead in data["leads"] if lead["id"] == self.pl.id)
        tabs = {str(tab["id"]): tab for tab in lead["cceo_tabs"]}
        planned = {item.activity_id for item in tabs[str(self.james.id)]["core_work"]}
        self.assertEqual(self._my_plan_core_ids(self.james_user) - planned, set())

    def test_the_package_chart_is_drawn_for_the_people_who_hold_the_schools(self):
        """Planned work opens a tab; it does not put a person on the chart.

        The chart sums each person's core packages. Mary holds no core school:
        her visit to James's opens her tab, but a chart row for her would be
        all zeros — and a first range of such rows drew no bars at all.
        """
        from apps.core_schools.oversight_service import core_schools_oversight_data

        mary_visit = self._activity("core_visit", self.mary.id, school=self.core_school)
        data = core_schools_oversight_data(self.pl_user, fy=self.fy)
        tabs = {str(tab["id"]): tab for tab in data["cceo_tabs"]}
        self.assertIn(
            mary_visit.id,
            {item.activity_id for item in tabs[str(self.mary.id)]["core_work"]},
        )
        charted = [str(tab["id"]) for tab in data["package_chart_tabs"]]
        self.assertEqual(charted, [str(data["cceo_tabs"][0]["id"]), str(self.james.id)])

    def test_the_page_lists_the_planned_core_work(self):
        self.client.force_login(self.pl_user)
        response = self.client.get("/core-schools-oversight/", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Planned core visits and trainings"')
        for activity in self.james_work:
            if activity.school_id == self.core_school.id:
                self.assertContains(response, f'data-core-work-row="{activity.id}"')

    def test_a_cluster_training_reaching_a_core_school_is_core_work(self):
        """My Plan moves the core school's row of a group training to the core
        training table; oversight lists it there too, once per core school."""
        from apps.core_schools.oversight_service import planned_core_work

        training = next(
            a for a in self.james_work if a.activity_type == "cluster_training"
        )
        self.assertIn(training.id, self._my_plan_core_ids(self.james_user))
        rows = [
            item
            for item in planned_core_work(self.pl_user, fy=self.fy)
            if item.activity_id == training.id
        ]
        self.assertEqual([row.school_id for row in rows], [self.core_school.id])
        self.assertTrue(rows[0].via_cluster)


class OneRuleForWhatIsOnAPlanTest(TestCase):
    """My Plan and oversight agree on which statuses are a person's plan."""

    def test_every_status_my_plan_shows_is_read_by_oversight(self):
        from apps.core.enums import ActivityStatus
        from apps.my_plan.services import ACTIVE_MY_PLAN_EXCLUDED_STATUSES
        from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

        on_my_plan = {
            status.value
            for status in ActivityStatus
            if status.value not in ACTIVE_MY_PLAN_EXCLUDED_STATUSES
        }
        self.assertEqual(on_my_plan - set(LIVE_ACTIVITY_STATUSES), set())


class ReleasedAndLegacyRowsTest(MirrorFixture):
    """The edges where the two pages used to disagree."""

    def test_released_work_is_on_neither_page(self):
        released = [
            self._activity(
                "school_visit", self.james.id, school=self.client_school, status=status
            )
            for status in ("deferred", "not_planned")
        ]
        self.assertFalse(
            {a.id for a in released}
            & my_plan_ids(self.james_user, fy=self.fy, period="fy")
        )
        from apps.planning import oversight_service

        seen = {
            i.activity_id
            for i in oversight_service.build_items(self.pl_user, fy=self.fy)
        }
        self.assertFalse({a.id for a in released} & seen)

    def test_a_row_dated_only_by_its_schedule_sits_in_its_month(self):
        from datetime import datetime, time

        from django.utils import timezone

        legacy = self._activity("school_visit", self.mary.id, school=self.mary_school)
        Activity.objects.filter(id=legacy.id).update(
            planned_date=None,
            planned_month=None,
            scheduled_date=timezone.make_aware(datetime.combine(self.soon, time(9))),
        )
        month = self.soon.month
        self.assertIn(legacy.id, my_plan_ids(self.mary_user, fy=self.fy, month=month))
        from apps.planning import oversight_service

        in_month = {
            i.activity_id
            for i in oversight_service.build_items(
                self.pl_user, fy=self.fy, month=month
            )
        }
        self.assertIn(legacy.id, in_month)
