"""A Programme Lead sees every plan of the people who report to them.

Owner, 2026-10-02: "PL are not seeing all the plans for their cceos ... PLs
are supposed to see every planning details for their team member grouped by
week, month, quarter and FY ... some activities are seen on the CCEO side but
hidden from the PL."

With a clean reporting line the Lead's pages already mirrored each My Plan
(test_oversight_mirrors_my_plan). What hid a plan was how each page decided
who was on the team: the role an account was switched to rather than the role
its person holds, an account that had been deactivated, the page year a week
was read against, and the portfolio assignment a school's holder had left
behind. These hold each of those.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest import mock

from apps.accounts.models import StaffSchoolAssignment, StaffSupervisorAssignment
from apps.activities.models import Activity
from apps.analytics.pl_week_service import build_week, monday_of
from apps.core.rbac import EdifyRole
from apps.core.role_holding import holds_role, holds_role_q
from apps.hr.team_roster import team_members
from apps.planning.action_models import TeamAction
from apps.planning.planning_monitor import planning_monitor
from apps.planning.test_oversight_mirrors_my_plan import MirrorFixture, _user
from apps.accounts.models import User


def _switch(user, role: str) -> None:
    """The account also holds ``role`` and is working in it today."""
    user.roles = [*user.roles, role]
    user.active_role = role
    user.save(update_fields=["roles", "active_role"])


class RoleHeldTest(MirrorFixture):
    def test_a_role_in_use_or_held_counts(self):
        self.assertTrue(holds_role(self.james_user, EdifyRole.CCEO))
        _switch(self.james_user, EdifyRole.PROJECT_COORDINATOR.value)
        self.assertTrue(holds_role(self.james_user, EdifyRole.CCEO))
        self.assertTrue(holds_role(self.james_user, EdifyRole.PROJECT_COORDINATOR))
        self.assertFalse(holds_role(self.james_user, EdifyRole.COUNTRY_PROGRAM_LEAD))
        self.assertIn(
            self.james_user,
            User.objects.filter(holds_role_q(EdifyRole.CCEO, prefix="")),
        )


class OfficerWorkingInAnotherRoleTest(MirrorFixture):
    """James also coordinates a project and is switched to that role."""

    def setUp(self):
        _switch(self.james_user, EdifyRole.PROJECT_COORDINATOR.value)

    def _tabs(self):
        self.client.force_login(self.pl_user)
        response = self.client.get("/team-planning-oversight/", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        return {tab["label"]: tab for tab in response.context["tabs"]}

    def test_they_keep_their_tab_on_the_team_plan(self):
        tabs = self._tabs()
        self.assertIn("James", tabs)
        # The whole year reads forward through the planning horizon, so the
        # tab holds next year's plan as well.
        self.assertEqual(
            {item.activity_id for item in tabs["James"]["items"]},
            {activity.id for activity in [*self.james_work, self.james_next_fy]},
        )

    def test_they_stay_on_the_leads_team(self):
        self.assertIn(
            self.james.id, {member.id for member in team_members(self.pl_user)}
        )

    def test_they_stay_on_the_leads_week(self):
        week = build_week(self.pl_user, fy=self.fy, week=self.soon.isoformat())
        planned = {person["name"]: person["planned"] for person in week["people"]}
        self.assertIn("James", planned)
        self.assertGreater(planned["James"], 0)

    def test_a_lead_working_in_another_role_still_heads_their_team(self):
        """The Country Director's lens files the team under the Lead."""
        from apps.planning import oversight_service as oversight

        _switch(self.pl_user, EdifyRole.CCEO.value)
        leads = {lead["id"] for lead in oversight.system_program_leads()}
        self.assertIn(self.pl.id, leads)
        items = oversight.build_items(self.cd_user, fy=self.fy)
        james = [i for i in items if i.activity_id == self.james_work[0].id]
        self.assertEqual(james[0].supervising_pl_id, self.pl.id)


class DeactivatedOfficerTest(MirrorFixture):
    """An account switched off leaves the team; the plan it held stays."""

    def setUp(self):
        self.mary_user.is_active = False
        self.mary_user.save(update_fields=["is_active"])

    def test_the_week_keeps_them_while_they_hold_work_in_it(self):
        self.assertNotIn(self.mary.id, {m.id for m in team_members(self.pl_user)})
        week = build_week(self.pl_user, fy=self.fy, week=self.soon.isoformat())
        planned = {person["name"]: person["planned"] for person in week["people"]}
        self.assertEqual(planned.get("Mary"), len(self.mary_work))

    def test_with_nothing_in_the_week_they_get_no_tab(self):
        far = monday_of(self.soon) + timedelta(days=56)
        with mock.patch("apps.analytics.pl_week_service.WEEK_REACH", 60):
            week = build_week(self.pl_user, fy=self.fy, week=far.isoformat())
        self.assertNotIn("Mary", {person["name"] for person in week["people"]})

    def test_the_team_plan_keeps_their_tab(self):
        self.client.force_login(self.pl_user)
        response = self.client.get("/team-planning-oversight/", {"fy": self.fy})
        labels = {tab["label"]: tab["count"] for tab in response.context["tabs"]}
        self.assertEqual(labels.get("Mary"), len(self.mary_work))


class WeekAcrossTheYearEndTest(MirrorFixture):
    """A week is its seven days, whichever fiscal year each is in."""

    def test_the_week_of_the_year_end_holds_both_years_plans(self):
        year_end = date(int(self.fy), 9, 30)
        week_start = monday_of(year_end)
        if (week_start + timedelta(days=6)) <= year_end:
            self.skipTest("this fiscal year ends on a Sunday")
        before = self._activity(
            "school_visit", self.james.id, school=self.client_school, planned=year_end
        )
        after = self._activity(
            "school_visit",
            self.james.id,
            school=self.client_school,
            fy=self.next_fy,
            planned=year_end + timedelta(days=1),
        )
        self.client.force_login(self.pl_user)
        for page_fy in (self.fy, self.next_fy):
            with self.subTest(page_fy=page_fy):
                response = self.client.get(
                    "/team-planning-oversight/",
                    {
                        "fy": page_fy,
                        "period": "week",
                        "week": week_start.strftime("%G-W%V"),
                    },
                )
                shown = {
                    item.activity_id
                    for tab in response.context["tabs"]
                    if tab["key"] == "team"
                    for item in tab["items"]
                }
                self.assertLessEqual({before.id, after.id}, shown)
                self.assertIn("Week of", response.context["period_label"])


class LeadsMonitorIsTheirOwnPeopleTest(MirrorFixture):
    """The monitor files a school by its holder, for the Lead as for the
    country."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.schools.ownership_transfer import hold_schools

        for school in (cls.client_school, cls.core_school):
            hold_schools([school.id], cls.james.id)
        hold_schools([cls.mary_school.id], cls.mary.id)
        hold_schools([cls.pl_school.id], cls.pl.id)
        cls.other_lead_user, cls.other_lead = _user(
            "lead2@mirror.test", "Other Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.stranger_user, cls.stranger = _user(
            "stranger@mirror.test", "Stranger", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.stranger, supervisor=cls.other_lead
        )
        cls.stranger_school = cls._school("MIR-9", "Stranger Client", cls.stranger.id)
        hold_schools([cls.stranger_school.id], cls.stranger.id)

    def _names(self):
        monitor = planning_monitor(self.pl_user, fy=self.fy)
        return [o.name for lead in monitor["leads"] for o in lead.officers]

    def test_a_stale_assignment_adds_nobody_from_another_team(self):
        """The school's previous holder kept its portfolio row: the school is
        still the new holder's, on the new holder's Lead's monitor."""
        StaffSchoolAssignment.objects.create(
            staff=self.james, school_id=self.stranger_school.id
        )
        self.assertNotIn("Stranger", self._names())
        self.assertEqual(sorted(self._names()), ["James", "Lead Mirror", "Mary"])

    def test_a_deactivated_holder_is_counted_in_both_id_spaces(self):
        self.james_user.is_active = False
        self.james_user.save(update_fields=["is_active"])
        monitor = planning_monitor(self.pl_user, fy=self.fy)
        james = next(
            o for lead in monitor["leads"] for o in lead.officers if o.name == "James"
        )
        # school_visit (profile id), follow_up_visit (User id), coaching and
        # the submitted visit at the client school; the core visit and the
        # in-school training at the Core school.
        self.assertEqual(james.staff_visits, 6)


class PartnerShareOnTheMonitorTest(MirrorFixture):
    def test_the_partner_remainder_and_the_core_partner_half_are_counted(self):
        from apps.core_schools.models import CorePlan, cplan_id
        from apps.core_schools.services import create_package_slots
        from apps.partners.models import Partner, PartnerAssignment
        from apps.schools.ownership_transfer import hold_schools

        hold_schools([self.client_school.id, self.core_school.id], self.james.id)
        plan = CorePlan.objects.create(
            id=cplan_id("MIR-2", fy=self.fy),
            school_id="MIR-2",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(plan, "MIR-2", ["leadership"])
        partner = Partner.objects.create(name="Mirror Partner", active_status=True)
        PartnerAssignment.objects.create(
            school=self.core_school,
            partner=partner,
            status=PartnerAssignment.STATUS_PENDING_SCHEDULING,
            support_type="Visit",
            visit_number="1",
            assigning_staff_id=self.james.id,
        )

        monitor = planning_monitor(self.pl_user, fy=self.fy)
        james = next(
            o for lead in monitor["leads"] for o in lead.officers if o.name == "James"
        )
        self.assertEqual(james.core_partner_target, 2)
        self.assertEqual(james.core_partner_visits, 1)
        self.assertEqual(james.core_partner_trainings, 0)
        self.assertEqual(james.core_partner_visits_tone, "warning")
        # One client school against 558 client visits: nothing is beyond reach.
        self.assertEqual((james.partner_needed, james.partner_remaining), (0, 0))
        self.assertEqual(monitor["totals"].core_partner_visits, 1)

    def test_a_count_opens_the_rows_behind_it(self):
        self.client.force_login(self.pl_user)
        response = self.client.get(
            "/planning-monitor/",
            {"fy": self.fy},
            HTTP_X_EDIFY_EMBED="dashboard",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Core partner visits")
        self.assertContains(response, "/team-planning-oversight/?period=fy")
        self.assertContains(response, f"&owner={self.james.id}&activity=visits")
        self.assertContains(response, "&owner=mine&activity=visits")
        self.assertContains(response, "/partner-oversight/?period=fy")
        self.assertContains(response, f"&member={self.james.id}")


class SendToTheOfficerFromTheMonitorTest(MirrorFixture):
    """The Lead reads an officer's schools and plans and changes none of
    them; they ask the officer who holds the school."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.schools.ownership_transfer import hold_schools

        hold_schools([cls.mary_school.id], cls.mary.id)
        hold_schools([cls.pl_school.id], cls.pl.id)
        # Nothing planned at Mary's school.
        Activity.objects.filter(school=cls.mary_school).delete()

    def _send(self, user, school, gap="no_visit"):
        self.client.force_login(user)
        return self.client.post(
            "/planning-monitor/send",
            {"school_id": school.id, "gap": gap, "fy": self.fy},
            HTTP_HX_REQUEST="true",
        )

    def test_the_list_offers_send_to_the_holder(self):
        self.client.force_login(self.pl_user)
        response = self.client.get(
            "/planning-monitor/",
            {"fy": self.fy, "gap": "no_visit"},
            HTTP_X_EDIFY_EMBED="dashboard",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "Send to Mary")
        self.assertContains(response, 'hx-post="/planning-monitor/send"')

    def test_sending_opens_one_action_for_the_holder(self):
        response = self._send(self.pl_user, self.mary_school)
        self.assertContains(response, "Sent to Mary")
        action = TeamAction.objects.get(school_id=self.mary_school.id)
        self.assertEqual(action.recipient_id, self.mary_user.id)
        self.assertEqual(action.issue_type, "planning_school_gap")
        self.assertEqual(action.sender_id, self.pl_user.id)

        again = self._send(self.pl_user, self.mary_school)
        self.assertContains(again, "Already sent to Mary")
        self.assertEqual(TeamAction.objects.count(), 1)

        self.client.force_login(self.pl_user)
        listed = self.client.get(
            "/planning-monitor/",
            {"fy": self.fy, "gap": "no_visit"},
            HTTP_X_EDIFY_EMBED="dashboard",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(listed, "data-monitor-sent")

    def test_the_leads_own_school_is_theirs_to_plan(self):
        Activity.objects.filter(school=self.pl_school).delete()
        response = self._send(self.pl_user, self.pl_school)
        self.assertContains(response, "not held by one of your officers")
        self.assertFalse(TeamAction.objects.exists())

    def test_a_planned_school_is_not_sent(self):
        response = self._send(self.pl_user, self.client_school)
        self.assertContains(response, "no longer has this gap")
        self.assertFalse(TeamAction.objects.exists())

    def test_only_the_lead_sends(self):
        response = self._send(self.cd_user, self.mary_school)
        self.assertContains(response, "belongs to the Programme Lead")
        self.assertFalse(TeamAction.objects.exists())
