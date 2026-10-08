"""Whose calendar a reader may open (owner, 2026-10-07).

"can we have leads have access to calendar page for their cceo, cd to have
calendar for every one organized by tabs with theirs first", and then: "make
sure the table pill counters are also accurate and refreshes with changing
data".

The Calendar opens on the reader's own, as it always did
(`test_calendar_workspace.CalendarRoleScheduleAudienceTest`). A Programme
Lead has a tab for each CCEO on their team beside it, the Country Director a
tab for every Programme Lead's team and under it that team's people. Each tab
carries the number of activities its calendar draws. Somebody else's calendar
is read, never run.
"""

from datetime import date
from html.parser import HTMLParser
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities import calendar_people
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

DAY = date(2026, 7, 16)
MONTH = "/calendar?year=2026&month=7"

LEAD = EdifyRole.COUNTRY_PROGRAM_LEAD.value
CCEO = EdifyRole.CCEO.value
DIRECTOR = EdifyRole.COUNTRY_DIRECTOR.value


class _Roster(TestCase):
    """Two Programme Leads with their CCEOs, a CCEO who reports to nobody,
    and the Country Director."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="People Tabs Region")
        cls.district = District.objects.create(
            name="People Tabs District", region=cls.region
        )
        cls.director, cls.director_staff = cls.person(DIRECTOR, "Dora Director")
        cls.lead, cls.lead_staff = cls.person(LEAD, "Lena Lead")
        cls.other_lead, cls.other_lead_staff = cls.person(LEAD, "Otto Lead")
        cls.amos, cls.amos_staff = cls.person(CCEO, "Amos Officer")
        cls.beth, cls.beth_staff = cls.person(CCEO, "Beth Officer")
        cls.carl, cls.carl_staff = cls.person(CCEO, "Carl Officer")
        cls.loose, cls.loose_staff = cls.person(CCEO, "Lou Loose")
        for supervisor, supervisee in (
            (cls.lead_staff, cls.amos_staff),
            (cls.lead_staff, cls.beth_staff),
            (cls.other_lead_staff, cls.carl_staff),
        ):
            StaffSupervisorAssignment.objects.create(
                supervisor=supervisor, supervisee=supervisee
            )
        cls.amos_school = cls.school("PT-001", "Amos School", cls.amos_staff)
        cls.far_school = cls.school("PT-002", "Far School", cls.carl_staff)

    @classmethod
    def person(cls, role, name, **extra):
        user = User.objects.create_user(
            email=f"{name.lower().replace(' ', '.')}@people-tabs.example.com",
            name=name,
            roles=extra.pop("roles", [role]),
            active_role=role,
        )
        return user, StaffProfile.objects.create(user=user, title=role, **extra)

    @classmethod
    def school(cls, code, name, holder):
        school = School.objects.create(
            school_id=code,
            name=name,
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=holder, school_id=school.id)
        return school

    @staticmethod
    def visit(holder_id, *, day=DAY, **fields):
        fields.setdefault("activity_type", "school_visit")
        fields.setdefault("status", "scheduled")
        return Activity.objects.create(
            fy=get_operational_fy(day),
            quarter=get_quarter_for_date(day),
            planned_date=day,
            responsible_staff_id=holder_id,
            **fields,
        )

    def read(self, user, query=""):
        self.client.force_login(user)
        response = self.client.get(MONTH + query)
        self.assertEqual(response.status_code, 200)
        return response

    @staticmethod
    def strip(response, name="calendar_people_tabs"):
        return [
            (tab["label"], tab["count"], tab["is_active"])
            for tab in response.context[name]
        ]

    @staticmethod
    def drawn(response):
        """The ids of the activities the calendar draws."""
        return set(response.context["activities"].values_list("id", flat=True))


class ProgrammeLeadCalendarTabsTest(_Roster):
    def test_a_lead_has_their_own_calendar_first_and_a_tab_for_each_cceo(self):
        self.visit(self.lead_staff.id)
        self.visit(self.amos_staff.id)
        self.visit(self.amos_staff.id)
        self.visit(self.carl_staff.id)

        response = self.read(self.lead)

        self.assertEqual(
            self.strip(response),
            [
                ("My calendar", 1, True),
                ("Amos Officer", 2, False),
                ("Beth Officer", 0, False),
            ],
        )
        # One strip: a Lead's people are the tabs themselves.
        self.assertEqual(response.context["calendar_member_tabs"], [])
        self.assertContains(response, 'aria-label="Whose calendar"')
        self.assertNotContains(response, "Carl Officer")

    def test_a_cceos_tab_draws_what_their_own_calendar_draws(self):
        """Their work under either id it was written with, the partner work
        they monitor, and nothing of anybody else's."""
        mine = self.visit(self.lead_staff.id)
        by_profile = self.visit(self.amos_staff.id, school=self.amos_school)
        by_user = self.visit(self.amos.id)
        monitored = self.visit(
            None,
            delivery_type="partner",
            monitored_by_staff_id=self.amos_staff.id,
            status="partner_scheduled",
        )
        self.visit(self.beth_staff.id)
        self.visit(self.amos_staff.id, status="cancelled")

        theirs = self.read(self.lead, f"&person={self.amos_staff.id}")
        own = self.read(self.amos)

        self.assertEqual(self.drawn(theirs), {by_profile.id, by_user.id, monitored.id})
        self.assertEqual(self.drawn(theirs), self.drawn(own))
        self.assertNotIn(mine.id, self.drawn(theirs))
        self.assertEqual(theirs.context["calendar_person"].name, "Amos Officer")

    def test_the_number_on_a_tab_is_the_number_its_calendar_draws(self):
        """Owner, 2026-10-07: "make sure the table pill counters are also
        accurate". Under the page's filters as well."""
        self.visit(self.lead_staff.id)
        for _ in range(3):
            self.visit(self.amos_staff.id)
        self.visit(self.amos_staff.id, activity_type="cluster_meeting")
        self.visit(self.amos_staff.id, status="completed")
        self.visit(self.beth_staff.id)
        self.visit(self.beth_staff.id, day=date(2026, 8, 3))

        for query in ("", "&activity_type=school_visit", "&status=completed"):
            with self.subTest(filters=query):
                tabs = {
                    tab["label"]: tab
                    for tab in self.read(self.lead, query).context[
                        "calendar_people_tabs"
                    ]
                }
                for label, tab in tabs.items():
                    opened = self.client.get(f"/calendar?{tab['qs']}")
                    self.assertEqual(
                        tab["count"],
                        opened.context["event_counts"]["activity"],
                        f"{label} {query}",
                    )
                    self.assertEqual(tab["count"], len(self.drawn(opened)))

    def test_a_person_off_the_leads_own_team_opens_nobodys_calendar(self):
        self.visit(self.lead_staff.id)
        self.visit(self.carl_staff.id)

        for key in (
            self.carl_staff.id,
            self.other_lead_staff.id,
            self.director_staff.id,
            "nobody",
        ):
            with self.subTest(person=key):
                response = self.read(self.lead, f"&person={key}")
                self.assertIsNone(response.context["calendar_person"])
                self.assertEqual(
                    set(
                        response.context["activities"].values_list(
                            "responsible_staff_id", flat=True
                        )
                    ),
                    {self.lead_staff.id},
                )
                self.assertEqual(self.strip(response)[0], ("My calendar", 1, True))

    def test_a_cceos_calendar_is_read_never_run(self):
        """No tick box, no country-event form, and the notice about work on a
        day off names its owner instead of telling the reader to move it."""
        on_holiday = self.visit(
            self.amos_staff.id, day=date(2026, 10, 9), school=self.amos_school
        )

        self.client.force_login(self.lead)
        response = self.client.get(
            f"/calendar?year=2026&month=10&person={self.amos_staff.id}"
        )

        self.assertEqual(response.context["pickable_total"], 0)
        self.assertNotContains(response, "data-activity-pick")
        self.assertFalse(response.context["can_add_calendar_event"])
        self.assertContains(
            response, "Amos Officer has 1 activity to reschedule in October"
        )
        self.assertNotContains(response, "choose Reschedule")
        self.assertContains(response, f'href="/my-plan/{on_holiday.id}"')

    def test_no_tick_box_on_a_cceos_tab_whatever_the_lead_holds_of_it(self):
        """Owner, 2026-10-07: "only the owners can make changes from the
        calendar. calendar oversights are strictly read only the checkboxes
        for making changes should only be available to the owners". The rule
        is the tab's, not a consequence of who may run what: with every
        activity made tickable, a CCEO's tab still has none and the reader's
        own keeps its boxes."""
        self.visit(self.lead_staff.id)
        self.visit(self.amos_staff.id, school=self.amos_school)
        self.visit(
            self.amos_staff.id,
            delivery_type="partner",
            monitored_by_staff_id=self.lead_staff.id,
            status="partner_scheduled",
        )

        with patch(
            "apps.activities.group_actions.tickable_ids",
            side_effect=lambda rows, principal: {row.id for row in rows},
        ):
            theirs = self.read(self.lead, f"&person={self.amos_staff.id}")
            own = self.read(self.lead)

        self.assertEqual(theirs.context["event_counts"]["activity"], 2)
        self.assertEqual(theirs.context["pickable_total"], 0)
        for mark in ("data-activity-pick", "data-select-all", "data-activity-bar"):
            self.assertNotContains(theirs, mark)
        self.assertNotContains(theirs, "Apply for Leave")
        # Nothing on it posts: the one form is the month's filters.
        forms = [
            (attrs.get("method", "get").lower(), attrs.get("action"))
            for tag, attrs, inside in _workspace(theirs)
            if tag == "form" and inside
        ]
        self.assertEqual(forms, [("get", "/calendar")])
        # The Lead's own visit, and the partner's work they monitor: that one
        # is on both calendars and has its box on the Lead's own only.
        self.assertEqual(own.context["pickable_total"], 2)
        self.assertContains(own, "data-activity-pick")
        self.assertContains(own, "Apply for Leave")

    def test_their_approved_leave_is_drawn_and_a_waiting_request_is_not(self):
        for status, day in (("approved", "2026-07-20"), ("pending", "2026-07-22")):
            Leave.objects.create(
                staff=self.amos_staff,
                type="personal_time_off",
                start_date=day,
                end_date=day,
                days=1,
                status=status,
            )
        Leave.objects.create(
            staff=self.lead_staff,
            type="personal_time_off",
            start_date="2026-07-21",
            end_date="2026-07-21",
            days=1,
            status="approved",
        )

        response = self.read(self.lead, f"&person={self.amos_staff.id}")

        self.assertEqual(response.context["event_counts"]["leave"], 1)
        self.assertContains(response, "Amos Officer leave")
        self.assertNotContains(response, "Your leave")
        self.assertNotContains(response, "Awaiting approval")

    def test_an_entry_is_a_link_only_where_the_record_opens_for_the_lead(self):
        """A Lead reads their team's work, and is refused a visit to a school
        outside the team's portfolios: that entry is drawn, not linked."""
        opens = self.visit(self.amos_staff.id, school=self.amos_school)
        placeless = self.visit(self.amos_staff.id, activity_type="programme_event")
        refused = self.visit(self.amos_staff.id, school=self.far_school)

        response = self.read(self.lead, f"&person={self.amos_staff.id}")

        self.assertEqual(self.drawn(response), {opens.id, placeless.id, refused.id})
        for activity in (opens, placeless, refused):
            linked = f'href="/my-plan/{activity.id}"' in response.content.decode()
            self.assertEqual(
                linked,
                RolePermissionService.can_view_record(self.lead, activity),
                activity.id,
            )
        self.assertContains(response, f'href="/my-plan/{opens.id}"')
        self.assertNotContains(response, f'href="/my-plan/{refused.id}"')
        self.assertEqual(self.client.get(f"/my-plan/{opens.id}").status_code, 200)

    def test_the_tab_stays_open_through_the_month_the_view_and_the_filters(self):
        response = self.read(
            self.lead, f"&person={self.amos_staff.id}&status=scheduled&view=agenda"
        )

        person = f"person={self.amos_staff.id}"
        for name in ("prev_qs", "next_qs", "today_qs", "month_view_qs", "clear_qs"):
            self.assertIn(person, response.context[name], name)
        self.assertContains(
            response,
            f'<input type="hidden" name="person" value="{self.amos_staff.id}">',
        )
        # A tab keeps the month, the view and the filters; "My calendar"
        # drops the person and nothing else.
        own, amos, _beth = response.context["calendar_people_tabs"]
        self.assertEqual(own["qs"], "year=2026&month=7&status=scheduled&view=agenda")
        self.assertEqual(amos["qs"], f"{own['qs']}&{person}")
        self.assertContains(
            response, f'href="/calendar?{amos["qs"]}"'.replace("&", "&amp;")
        )

    def test_a_cceo_working_in_a_second_role_keeps_their_tab(self):
        """The role HELD decides the team (apps.core.role_holding)."""
        dual, dual_staff = self.person(
            EdifyRole.PROJECT_COORDINATOR.value,
            "Dina Dual",
            roles=[CCEO, EdifyRole.PROJECT_COORDINATOR.value],
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.lead_staff, supervisee=dual_staff
        )

        labels = [label for label, _, _ in self.strip(self.read(self.lead))]

        self.assertEqual(
            labels, ["My calendar", "Amos Officer", "Beth Officer", "Dina Dual"]
        )

    def test_a_tab_costs_the_same_whatever_the_size_of_the_team(self):
        def cost():
            with CaptureQueriesContext(connection) as queries:
                self.read(self.lead, f"&person={self.amos_staff.id}")
            return len(queries)

        self.visit(self.amos_staff.id, school=self.amos_school)
        cost()  # sign-in and first-request caches
        small = cost()
        for index in range(6):
            _, staff = self.person(CCEO, f"Extra Officer {index}")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.lead_staff, supervisee=staff
            )
            self.visit(staff.id)
            self.visit(self.amos_staff.id, school=self.amos_school)

        self.assertEqual(cost(), small)


class CountryDirectorCalendarTabsTest(_Roster):
    def test_the_director_has_their_own_first_then_a_tab_for_every_team(self):
        self.visit(self.director_staff.id)
        self.visit(self.lead_staff.id)
        self.visit(self.amos_staff.id)
        self.visit(self.amos_staff.id)
        self.visit(self.carl_staff.id)
        self.visit(self.loose_staff.id)

        response = self.read(self.director)

        self.assertEqual(
            self.strip(response),
            [
                ("My calendar", 1, True),
                ("Lena Lead's team", 3, False),
                ("Otto Lead's team", 1, False),
                ("No Programme Lead", 1, False),
            ],
        )
        # No team is open, so there is no second strip yet.
        self.assertEqual(response.context["calendar_member_tabs"], [])
        self.assertEqual(
            set(
                response.context["activities"].values_list(
                    "responsible_staff_id", flat=True
                )
            ),
            {self.director_staff.id},
        )
        self.assertTrue(response.context["can_add_calendar_event"])

    def test_a_team_opens_on_its_lead_with_its_people_in_a_second_strip(self):
        lead_visit = self.visit(self.lead_staff.id)
        self.visit(self.amos_staff.id)

        own = self.read(self.director)
        team_tab = own.context["calendar_people_tabs"][1]
        response = self.client.get(f"/calendar?{team_tab['qs']}")

        self.assertEqual(response.context["calendar_person"].name, "Lena Lead")
        self.assertEqual(self.drawn(response), {lead_visit.id})
        self.assertEqual(
            self.strip(response),
            [
                ("My calendar", 0, False),
                ("Lena Lead's team", 2, True),
                ("Otto Lead's team", 0, False),
                ("No Programme Lead", 0, False),
            ],
        )
        self.assertEqual(
            self.strip(response, "calendar_member_tabs"),
            [
                ("Lena Lead", 1, True),
                ("Amos Officer", 1, False),
                ("Beth Officer", 0, False),
            ],
        )
        self.assertContains(response, 'aria-label="Lena Lead&#x27;s team"')
        self.assertFalse(response.context["can_add_calendar_event"])

    def test_the_director_opens_any_officers_calendar(self):
        theirs = self.visit(self.carl_staff.id, school=self.far_school)
        self.visit(self.amos_staff.id)

        response = self.read(self.director, f"&person={self.carl_staff.id}")

        self.assertEqual(self.drawn(response), {theirs.id})
        self.assertEqual(
            self.strip(response, "calendar_member_tabs"),
            [("Otto Lead", 0, False), ("Carl Officer", 1, True)],
        )
        self.assertEqual(response.context["pickable_total"], 0)
        self.assertContains(response, f'href="/my-plan/{theirs.id}"')
        self.assertEqual(self.client.get(f"/my-plan/{theirs.id}").status_code, 200)

    def test_a_cceo_with_no_lead_is_under_no_programme_lead(self):
        theirs = self.visit(self.loose_staff.id)

        response = self.read(self.director, f"&person={self.loose_staff.id}")

        self.assertEqual(self.drawn(response), {theirs.id})
        self.assertEqual(response.context["calendar_team_name"], "No Programme Lead")
        self.assertEqual(
            self.strip(response, "calendar_member_tabs"), [("Lou Loose", 1, True)]
        )

    def test_the_numbers_on_both_strips_are_what_each_calendar_draws(self):
        for holder, visits in (
            (self.lead_staff, 2),
            (self.amos_staff, 3),
            (self.beth_staff, 1),
            (self.carl_staff, 4),
        ):
            for _ in range(visits):
                self.visit(holder.id)

        response = self.read(self.director, f"&person={self.amos_staff.id}")

        members = response.context["calendar_member_tabs"]
        for tab in members:
            opened = self.client.get(f"/calendar?{tab['qs']}")
            self.assertEqual(
                tab["count"], opened.context["event_counts"]["activity"], tab["label"]
            )
        # A team's number is its people's, added up.
        team = response.context["calendar_people_tabs"][1]
        self.assertEqual(team["count"], sum(tab["count"] for tab in members))
        self.assertEqual(team["count"], 6)

    def test_somebody_who_is_on_no_team_has_no_tab(self):
        accountant, accountant_staff = self.person(
            EdifyRole.PROGRAM_ACCOUNTANT.value, "Ada Accountant"
        )
        self.visit(accountant_staff.id)

        response = self.read(self.director, f"&person={accountant_staff.id}")

        self.assertIsNone(response.context["calendar_person"])
        self.assertNotContains(response, "Ada Accountant")

    @override_settings(ALLOW_CD_OPERATIONAL_PLANNING=False)
    def test_a_director_kept_to_aggregates_has_only_their_own_calendar(self):
        """Such a deployment refuses the Director every activity record, and
        an officer's calendar is those records."""
        own = self.visit(self.director_staff.id)
        self.visit(self.amos_staff.id)

        response = self.read(self.director, f"&person={self.amos_staff.id}")

        self.assertEqual(response.context["calendar_people_tabs"], [])
        self.assertIsNone(response.context["calendar_person"])
        self.assertEqual(self.drawn(response), {own.id})
        self.assertNotContains(response, "Whose calendar")


class _Elements(HTMLParser):
    """The start tags of a page, each with whether it sits inside the element
    of the id asked for."""

    VOID = {"input", "br", "img", "meta", "link", "hr", "source", "path", "rect"}

    def __init__(self, ident):
        super().__init__()
        self.ident = ident
        self.open: list[bool] = []
        self.found: list[tuple[str, dict, bool]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.found.append((tag, attrs, any(self.open)))
        if tag not in self.VOID:
            self.open.append(attrs.get("id") == self.ident)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.open:
            self.open.pop()


def _workspace(response) -> list[tuple[str, dict, bool]]:
    parser = _Elements("calendar-workspace")
    parser.feed(response.content.decode())
    return parser.found


class TheStripsAreLiveTest(_Roster):
    """Owner, 2026-10-07: "make sure the table pill counters are also
    accurate and refreshes with changing data". The page reads its live part
    again when the plan changes (static/js/live-regions.js); the strips and
    their numbers are inside that part, so they change with the month below
    them. Who is told of a change is `apps.activities.test_live`."""

    def test_both_strips_are_inside_the_part_of_the_page_that_is_read_again(self):
        self.visit(self.amos_staff.id)
        response = self.read(self.director, f"&person={self.amos_staff.id}")
        markup = response.content.decode()

        strips = [
            inside
            for _tag, attrs, inside in _workspace(response)
            if "oversight-entity-tabs" in (attrs.get("class") or "").split()
        ]

        self.assertEqual(strips, [True, True])
        region = markup[markup.index('id="calendar-workspace"') :]
        self.assertIn("data-live-region", region[: region.index(">")])

    def test_a_lead_and_the_director_are_told_when_an_officers_plan_changes(self):
        """The people who can have that officer's tab open."""
        from apps.activities import live

        visit = self.visit(self.amos_staff.id, school=self.amos_school)
        live.reset()

        told = live.audience(
            staff_ids=(visit.responsible_staff_id,), school_id=visit.school_id
        )

        self.assertIn(str(self.amos.id), told)
        self.assertIn(str(self.lead.id), told)
        self.assertIn(str(self.director.id), told)
        self.assertNotIn(str(self.other_lead.id), told)

    def test_a_read_after_a_change_carries_the_new_numbers(self):
        visit = self.visit(self.amos_staff.id)
        second = self.visit(self.amos_staff.id)
        query = f"&person={self.amos_staff.id}"
        self.assertEqual(self.strip(self.read(self.lead, query))[1][1], 2)

        second.status = "cancelled"
        second.save(update_fields=["status"])
        self.assertEqual(self.strip(self.read(self.lead, query))[1][1], 1)

        visit.delete()
        self.visit(self.amos_staff.id)
        self.visit(self.beth_staff.id)
        self.assertEqual(
            self.strip(self.read(self.lead, query)),
            [
                ("My calendar", 0, False),
                ("Amos Officer", 1, True),
                ("Beth Officer", 1, False),
            ],
        )


class EverybodyElseKeepsOneCalendarTest(_Roster):
    def test_no_strip_for_a_reader_who_opens_only_their_own(self):
        readers = [self.amos, self.loose]
        for role in (
            EdifyRole.IMPACT_ASSESSMENT.value,
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.PROGRAM_ACCOUNTANT.value,
            EdifyRole.HUMAN_RESOURCES.value,
            EdifyRole.ADMIN.value,
        ):
            readers.append(self.person(role, f"Reader {role}")[0])
        self.visit(self.beth_staff.id)

        for reader in readers:
            with self.subTest(role=reader.active_role):
                response = self.read(reader, f"&person={self.beth_staff.id}")
                self.assertEqual(response.context["calendar_people_tabs"], [])
                self.assertIsNone(response.context["calendar_person"])
                self.assertNotContains(response, "Whose calendar")

    def test_a_lead_with_nobody_on_their_team_has_no_strip(self):
        solo, _ = self.person(LEAD, "Solo Lead")

        response = self.read(solo)

        self.assertEqual(response.context["calendar_people_tabs"], [])
        self.assertNotContains(response, "Whose calendar")

    def test_the_project_calendar_has_no_people_strip(self):
        response = self.read(
            self.lead, f"&project_scope=special&person={self.amos_staff.id}"
        )

        self.assertEqual(response.context["calendar_people_tabs"], [])
        self.assertIsNone(response.context["calendar_person"])


class PlanCountsTest(_Roster):
    def test_one_query_counts_every_holder_under_both_of_their_ids(self):
        self.visit(self.amos_staff.id)
        self.visit(self.amos.id)
        self.visit(
            None,
            delivery_type="partner",
            monitored_by_staff_id=self.amos_staff.id,
        )
        # Monitoring staff work is not holding it.
        self.visit(self.beth_staff.id, monitored_by_staff_id=self.amos_staff.id)
        holders = {
            "amos": frozenset({self.amos_staff.id, self.amos.id}),
            "beth": frozenset({self.beth_staff.id, self.beth.id}),
            "carl": frozenset({self.carl_staff.id, self.carl.id}),
        }

        with self.assertNumQueries(1):
            counts = calendar_people.plan_counts(Activity.objects.all(), holders)

        self.assertEqual(counts, {"amos": 3, "beth": 1, "carl": 0})

    def test_nobody_to_count_asks_nothing(self):
        with self.assertNumQueries(0):
            self.assertEqual(
                calendar_people.plan_counts(Activity.objects.all(), {}), {}
            )
