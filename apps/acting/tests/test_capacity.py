"""The acceptance scenarios, through real requests.

John is a Program Lead with Sarah, David and Michael; Mary is the Country
Director and Peter a Program Lead. Each test signs a person in and asks for
pages the way a browser does, so the page gate, the acting middleware, the
scope and the navigation are all the ones production runs.
"""

from __future__ import annotations

from unittest import mock

from django.test import override_settings

from apps.accounts.models import User
from apps.acting import services
from apps.acting.models import ActingAssignment
from apps.audit.models import AuditLog
from apps.frontend.views import dashboard_embed

from .fixtures import (
    NOVEMBER_1,
    OCTOBER_1,
    OCTOBER_15,
    OCTOBER_31,
    SEPTEMBER_30,
    ActingFixture,
    on_day,
)

# Pages a Program Lead opens and a CCEO does not: team planning, execution,
# oversight, training oversight, staff activity, performance.
PL_PAGES = (
    "/team-planning-oversight/",
    "/team-planning-oversight/?view=trainings",
    "/my-team",
    "/pl/review-queue",
    "/cluster-oversight/",
    "/core-schools-oversight/",
    "/staff-activity/follow-ups",
    "/analytics/program-lead",
    "/programme-rollout",
    "/quality-checks",
    "/actions/sent",
)
# Pages both roles open, which the acting capacity reads for the whole team.
SHARED_PAGES = (
    "/dashboard",
    "/calendar",
    "/schools",
    "/partner-oversight/",
    "/projects/monitoring",
    "/priorities/master",
    "/work-plan",
)
# What an appointment leaves with the Lead.
PL_WITHHELD = (
    "/fund-approvals",
    "/leave/approvals",
    "/performance-reviews",
    "/recovery-plans",
)
# A person's own money, leave and targets: worked in their own role.
PERSONAL = ("/fund-requests/weekly", "/my-targets", "/personal-time-off/")

CD_PAGES = (
    "/country-planning-oversight/",
    "/analytics/country-director",
    "/coverage",
)
# A Programme Lead reads these two on their dashboard: the dashboard's own
# requests carry this header (apps.frontend.views.dashboard_embed).
EMBEDDED = {dashboard_embed.EMBED_HEADER: dashboard_embed.EMBED_VALUE}
PL_DASHBOARD_SECTIONS = (
    "/planning-monitor/?view=planning",
    "/planning-monitor/?view=execution",
    "/staff-activity",
)
# "/admin-panel/users" left this list on 2026-10-09: the Admin's alone, so
# not the Director's to withhold (apps.acting.tests.test_scope).
CD_WITHHELD = (
    "/cost-settings",
    "/planning/fiscal-years",
    "/admin-panel/staff-setup-queue",
    "/country-budget",
    "/fund-approvals",
    "/leave/approvals",
    "/performance-reviews",
)


@override_settings(ALLOWED_HOSTS=["testserver"])
class RequestCase(ActingFixture):
    def get(self, user, path, on, **extra):
        self.client.force_login(User.objects.get(id=user.id))
        with on_day(on):
            return self.client.get(path, **extra)

    def post(self, user, path, on, data=None, **extra):
        self.client.force_login(User.objects.get(id=user.id))
        with on_day(on):
            return self.client.post(path, data or {}, **extra)

    def assertOpens(self, user, paths, on):
        for path in paths:
            self.assertEqual(self.get(user, path, on).status_code, 200, path)

    def assertRefused(self, user, paths, on):
        """A page the role in use cannot open sends a browser back to the
        dashboard and answers 403 to anything else."""
        for path in paths:
            response = self.get(user, path, on)
            self.assertIn(response.status_code, (302, 403), path)
            if response.status_code == 302:
                self.assertEqual(response["Location"], "/dashboard", path)


class ActingProgramLeadAcceptanceTests(RequestCase):
    def setUp(self):
        self.appointment = self.appoint_sarah()

    def test_before_october_sarah_has_no_lead_access(self):
        self.assertRefused(self.sarah, PL_PAGES, SEPTEMBER_30)

    def test_on_the_first_of_october_she_has_it_with_nobody_doing_anything(self):
        self.assertOpens(self.sarah, PL_PAGES, OCTOBER_1)
        self.assertOpens(self.sarah, SHARED_PAGES, OCTOBER_1)
        stored = ActingAssignment.objects.get(id=self.appointment.id)
        self.assertIsNone(stored.activated_at)  # no job ran; the date did it

    def test_she_has_it_to_the_last_day_and_not_a_day_longer(self):
        self.assertOpens(self.sarah, PL_PAGES[:3], OCTOBER_31)
        self.assertRefused(self.sarah, PL_PAGES, NOVEMBER_1)
        sarah = User.objects.get(id=self.sarah.id)
        self.assertEqual((sarah.roles, sarah.active_role), (["CCEO"], "CCEO"))

    def test_she_reads_the_whole_team_and_the_lead(self):
        body = self.get(
            self.sarah, "/planning-monitor/?view=planning", OCTOBER_15, headers=EMBEDDED
        )
        self.assertEqual(body.status_code, 200)
        text = body.content.decode()
        for name in ("John Lead", "Sarah Officer", "David Officer", "Michael Officer"):
            self.assertIn(name, text)
        for stranger in ("Agnes Officer", "Peter Lead", "Achieng Officer"):
            self.assertNotIn(stranger, text)

    def test_the_dashboard_sections_open_for_her_as_they_do_for_john(self):
        for path in PL_DASHBOARD_SECTIONS:
            for who in (self.sarah, self.john):
                response = self.get(who, path, OCTOBER_15, headers=EMBEDDED)
                self.assertEqual(response.status_code, 200, (who.name, path))
            before = self.get(self.sarah, path, SEPTEMBER_30, headers=EMBEDDED)
            self.assertIn(before.status_code, (302, 403), path)

    def test_staff_activity_is_the_teams_with_the_lead_and_no_one_elses(self):
        text = self.get(
            self.sarah, "/staff-activity", OCTOBER_15, headers=EMBEDDED
        ).content.decode()
        for name in ("John Lead", "David Officer", "Michael Officer"):
            self.assertIn(name, text)
        for stranger in ("Agnes Officer", "Peter Lead", "Achieng Officer"):
            self.assertNotIn(stranger, text)

    def test_she_opens_the_leads_and_the_officers_calendars_and_no_others(self):
        for profile in (self.john_sp, self.david_sp, self.michael_sp):
            response = self.get(
                self.sarah, f"/calendar?person={profile.id}", OCTOBER_15
            )
            self.assertEqual(response.status_code, 200, profile.id)
        text = self.get(
            self.sarah, f"/calendar?person={self.john_sp.id}", OCTOBER_15
        ).content.decode()
        for name in ("John Lead", "David Officer", "Michael Officer"):
            self.assertIn(name, text)
        self.assertNotIn("Agnes Officer", text)

    def test_john_remains_a_full_program_lead_throughout(self):
        for day in (SEPTEMBER_30, OCTOBER_15, NOVEMBER_1):
            self.assertOpens(self.john, PL_PAGES[:4], day)
        self.assertOpens(self.john, PL_WITHHELD[:3], OCTOBER_15)
        john = User.objects.get(id=self.john.id)
        self.assertEqual(
            (john.roles, john.active_role), (["Program Lead"], "Program Lead")
        )

    def test_david_who_was_not_appointed_gains_nothing(self):
        self.assertRefused(self.david, PL_PAGES, OCTOBER_15)

    def test_money_leave_and_people_decisions_stay_with_john(self):
        self.assertRefused(self.sarah, PL_WITHHELD, OCTOBER_15)

    def test_her_own_money_leave_and_targets_are_under_her_own_role(self):
        self.assertRefused(self.sarah, PERSONAL, OCTOBER_15)
        self.post(self.sarah, "/auth/switch-role", OCTOBER_15, {"role": "CCEO"})
        self.assertOpens(self.sarah, PERSONAL, OCTOBER_15)

    def test_the_sidebar_offers_the_leads_pages_less_the_withheld(self):
        text = self.get(self.sarah, "/dashboard", OCTOBER_15).content.decode()
        self.assertIn('href="/my-team"', text)
        self.assertIn('href="/team-planning-oversight/"', text)
        for withheld in ("/fund-approvals", "/leave/approvals", "/performance-reviews"):
            self.assertNotIn(f'href="{withheld}"', text)

    def test_the_account_menu_says_who_she_is_and_what_she_acts_as(self):
        text = self.get(self.sarah, "/dashboard", OCTOBER_15).content.decode()
        self.assertIn("CCEO · Acting PL", text)
        self.assertIn("October 2026", text)
        self.assertIn("data-acting-indicator", text)
        # Nothing of the kind for anyone else, or outside the month.
        for user, day in ((self.john, OCTOBER_15), (self.sarah, NOVEMBER_1)):
            other = self.get(user, "/dashboard", day).content.decode()
            self.assertNotIn("data-acting-indicator", other)
            self.assertNotIn("data-acting-switch", other)

    def test_she_switches_between_her_own_role_and_the_acting_one(self):
        self.post(self.sarah, "/auth/switch-role", OCTOBER_15, {"role": "CCEO"})
        self.assertFalse(
            ActingAssignment.objects.get(id=self.appointment.id).in_capacity
        )
        self.assertRefused(self.sarah, PL_PAGES[:3], OCTOBER_15)
        text = self.get(self.sarah, "/dashboard", OCTOBER_15).content.decode()
        self.assertIn("data-acting-switch", text)
        self.assertNotIn("data-acting-indicator", text)

        self.post(self.sarah, "/auth/switch-role", OCTOBER_15, {"role": "acting"})
        self.assertTrue(
            ActingAssignment.objects.get(id=self.appointment.id).in_capacity
        )
        self.assertOpens(self.sarah, PL_PAGES[:3], OCTOBER_15)
        # Neither switch wrote a role to the account.
        sarah = User.objects.get(id=self.sarah.id)
        self.assertEqual((sarah.roles, sarah.active_role), (["CCEO"], "CCEO"))
        entered = AuditLog.objects.filter(action="acting_capacity.entered").count()
        left = AuditLog.objects.filter(action="acting_capacity.left").count()
        self.assertEqual((entered, left), (1, 1))

    def test_the_acting_switch_is_refused_to_anyone_without_an_appointment(self):
        for user, day in ((self.david, OCTOBER_15), (self.sarah, NOVEMBER_1)):
            self.post(user, "/auth/switch-role", day, {"role": "acting"})
            self.assertRefused(user, PL_PAGES[:2], day)
        # And naming the role itself gets nobody anywhere.
        self.post(self.david, "/auth/switch-role", OCTOBER_15, {"role": "Program Lead"})
        self.assertEqual(User.objects.get(id=self.david.id).active_role, "CCEO")
        self.assertRefused(self.david, PL_PAGES[:2], OCTOBER_15)

    def test_a_cancelled_appointment_stops_on_the_next_request(self):
        self.assertOpens(self.sarah, PL_PAGES[:2], OCTOBER_15)
        with on_day(OCTOBER_15):
            services.cancel(self.john, self.appointment.id)
        self.assertRefused(self.sarah, PL_PAGES, OCTOBER_15)


class ActingCountryDirectorAcceptanceTests(RequestCase):
    def setUp(self):
        self.appointment = self.appoint_peter()

    def test_before_october_peter_has_no_director_access(self):
        self.assertRefused(self.peter, CD_PAGES, SEPTEMBER_30)

    def test_in_october_he_has_the_countrys_operational_pages(self):
        self.assertOpens(self.peter, CD_PAGES, OCTOBER_1)
        self.assertOpens(self.peter, ("/planning-monitor/",), OCTOBER_1)
        self.assertOpens(
            self.peter,
            ("/calendar", "/staff-activity", "/partner-oversight/"),
            OCTOBER_31,
        )

    def test_in_november_he_is_a_program_lead_again(self):
        self.assertRefused(self.peter, CD_PAGES, NOVEMBER_1)
        self.assertOpens(
            self.peter, ("/my-team", "/team-planning-oversight/"), NOVEMBER_1
        )
        peter = User.objects.get(id=self.peter.id)
        self.assertEqual(
            (peter.roles, peter.active_role), (["Program Lead"], "Program Lead")
        )

    def test_mary_remains_the_director_with_everything_she_had(self):
        self.assertOpens(self.mary, CD_PAGES, OCTOBER_15)
        self.assertOpens(self.mary, CD_WITHHELD[:3], OCTOBER_15)

    def test_administration_money_and_people_decisions_stay_with_mary(self):
        self.assertRefused(self.peter, CD_WITHHELD, OCTOBER_15)

    def test_he_reads_the_countrys_targets_and_distributes_none(self):
        self.assertOpens(self.peter, ("/target-distribution",), OCTOBER_15)
        # The Director's Priorities entry is that page, for him as for Mary.
        for who in (self.peter, self.mary):
            sent = self.get(who, "/priorities/master", OCTOBER_15)
            self.assertNotEqual(sent.get("Location"), "/dashboard", who.name)
        for path in ("/target-distribution/action", "/target-distribution/import"):
            response = self.post(self.peter, path, OCTOBER_15)
            self.assertEqual(response.status_code, 403, path)

    def test_he_reads_the_country_and_no_other(self):
        text = self.get(
            self.peter, "/country-planning-oversight/", OCTOBER_15
        ).content.decode()
        self.assertIn("John Lead", text)
        for kenyan in ("Otieno Lead", "Achieng Officer"):
            self.assertNotIn(kenyan, text)

    def test_his_own_team_is_under_his_own_role(self):
        self.assertRefused(self.peter, ("/my-team",), OCTOBER_15)
        self.post(self.peter, "/auth/switch-role", OCTOBER_15, {"role": "Program Lead"})
        self.assertOpens(self.peter, ("/my-team",), OCTOBER_15)
        self.assertRefused(self.peter, CD_PAGES, OCTOBER_15)

    def test_the_account_menu_says_lead_acting_director(self):
        text = self.get(
            self.peter, "/country-planning-oversight/", OCTOBER_15
        ).content.decode()
        self.assertIn("Program Lead · Acting CD", text)
        self.assertIn("October 2026", text)


class WriteGateTests(RequestCase):
    """Changes outside what an appointment delegates are refused before the
    view runs, whatever the view itself would have decided."""

    def test_an_acting_director_cannot_change_the_rate_card_or_accounts(self):
        self.appoint_peter()
        for path in (
            "/cost-settings/initialize-default",
            "/country-budget/action",
            "/acting-leadership/appoint",
        ):
            response = self.post(self.peter, path, OCTOBER_15)
            self.assertEqual(response.status_code, 403, path)
            self.assertIn(b"not part of your Acting Country Director", response.content)
        refused = AuditLog.objects.filter(action="acting_capacity.write_refused")
        self.assertEqual(refused.count(), 3)
        self.assertFalse(refused.first().success)

    def test_an_acting_director_follows_up_and_decides_nothing(self):
        """Owner, 2026-10-07: their task is to manage and follow up with the
        team members, not to hold every privilege of the seat."""
        from django.urls import resolve

        from apps.acting.middleware import may_write_route
        from apps.core.acting import acting_context

        self.appoint_peter()
        context = acting_context(self.acting(self.peter))
        for path in (
            "/country-planning-oversight/send",
            "/team-planning-oversight/send",
            "/planning-monitor/send",
            "/partner-oversight/send",
            "/country-planning-oversight/execution/follow-up",
            "/staff-activity/people/x/follow-up/send",
            "/escalations",
        ):
            self.assertTrue(may_write_route(context, resolve(path).func), path)
        for path in (
            "/partner-oversight/allowance-grant",
            "/partner-oversight/withdraw/submit",
            "/partner-oversight/withdraw/bulk",
            "/partner-oversight/withdraw/review",
            "/partner-oversight/verify/submit",
            "/partner-oversight/resolve/submit",
            "/training-ceilings/set",
            "/calendar/events",
        ):
            self.assertFalse(may_write_route(context, resolve(path).func), path)
            self.assertEqual(
                self.post(self.peter, path, OCTOBER_15).status_code, 403, path
            )

    def test_an_acting_lead_manages_the_team_and_decides_nothing_about_partners(self):
        from django.urls import resolve

        from apps.acting.middleware import may_write_route
        from apps.core.acting import acting_context

        self.appoint_sarah()
        context = acting_context(self.acting(self.sarah))
        for path in (
            "/team-planning-oversight/send",
            "/planning-monitor/send",
            "/pl/review-queue/x/confirm",
            "/training-ceilings/set",
            "/team/coaching/record",
            "/staff-activity/people/x/follow-up/send",
            "/partner-oversight/withdraw/review",
        ):
            self.assertTrue(may_write_route(context, resolve(path).func), path)
        for path in (
            "/partner-oversight/allowance-grant",
            "/training-ceilings/country/set",
        ):
            self.assertFalse(may_write_route(context, resolve(path).func), path)
            self.assertEqual(
                self.post(self.sarah, path, OCTOBER_15).status_code, 403, path
            )

    def test_an_acting_director_cannot_write_through_the_api(self):
        self.appoint_peter()
        self.client.force_login(User.objects.get(id=self.peter.id))
        with on_day(OCTOBER_15):
            response = self.client.patch("/api/notifications/mark-all-read")
        self.assertEqual(response.status_code, 403)
        # In his own role the same request is his to make.
        self.post(self.peter, "/auth/switch-role", OCTOBER_15, {"role": "Program Lead"})
        with on_day(OCTOBER_15):
            response = self.client.patch("/api/notifications/mark-all-read")
        self.assertEqual(response.status_code, 200)

    def test_reads_and_the_persons_own_account_are_never_caught(self):
        self.appoint_peter()
        self.assertEqual(
            self.post(self.peter, "/staff-activity/beat", OCTOBER_15).status_code, 204
        )
        response = self.post(self.peter, "/logout", OCTOBER_15)
        self.assertEqual(response.status_code, 302)

    def test_an_acting_lead_cannot_decide_money_or_change_read_only_pages(self):
        self.appoint_sarah()
        for path in ("/fund-approvals/action", "/target-distribution/team/action"):
            response = self.post(self.sarah, path, OCTOBER_15)
            self.assertEqual(response.status_code, 403, path)

    def test_nobody_in_their_own_role_meets_the_gate(self):
        self.appoint_sarah()
        self.assertFalse(
            AuditLog.objects.filter(action="acting_capacity.write_refused").exists()
        )
        response = self.post(self.john, "/staff-activity/beat", OCTOBER_15)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            AuditLog.objects.filter(action="acting_capacity.write_refused").exists()
        )


class ActionAttributionTests(RequestCase):
    """Every act in an acting capacity says so on the audit row."""

    def test_an_act_in_the_acting_capacity_carries_the_whole_answer(self):
        appointment = self.appoint_sarah()
        self.post(self.sarah, "/fund-approvals/action", OCTOBER_15)
        row = AuditLog.objects.filter(
            action="acting_capacity.write_refused", actor_id=self.sarah.id
        ).latest("created_at")
        stamp = row.payload["acting"]
        self.assertEqual(stamp["assignment_id"], appointment.id)  # why she had access
        self.assertEqual(stamp["permanent_role"], "CCEO")  # who she is
        self.assertEqual(stamp["acting_role"], "Program Lead")  # what she acted as
        self.assertEqual(stamp["acting_label"], "Acting Program Lead")
        self.assertEqual(stamp["acting_for"]["name"], "John Lead")  # whose seat
        self.assertEqual(stamp["appointed_by"]["name"], "John Lead")  # who appointed
        self.assertEqual(stamp["period"], {"start": "2026-10-01", "end": "2026-10-31"})

    def test_an_act_in_her_own_role_carries_no_acting_stamp(self):
        self.appoint_sarah()
        self.post(self.sarah, "/auth/switch-role", OCTOBER_15, {"role": "CCEO"})
        self.post(self.sarah, "/auth/switch-role", OCTOBER_15, {"role": "CCEO"})
        row = AuditLog.objects.filter(
            action="role_switch", actor_id=self.sarah.id
        ).latest("created_at")
        self.assertNotIn("acting", row.payload or {})
        # Nor does anything John does, in October or ever.
        self.post(self.john, "/auth/switch-role", OCTOBER_15, {"role": "Program Lead"})
        johns = AuditLog.objects.filter(actor_id=self.john.id).latest("created_at")
        self.assertNotIn("acting", johns.payload or {})

    def test_the_record_lists_what_was_done_under_the_appointment(self):
        # Made for the month the suite is run in, so the audit rows' real
        # timestamps fall inside it.
        month = services.month_options()[0]["value"]
        appointment = services.appoint(
            self.john, appointee_staff_id=self.sarah_sp.id, month=month
        )
        self.client.force_login(User.objects.get(id=self.sarah.id))
        self.client.post("/fund-approvals/action")
        acts = list(services.actions_under(appointment))
        self.assertEqual([a.action for a in acts], ["acting_capacity.write_refused"])
        self.client.force_login(User.objects.get(id=self.john.id))
        response = self.client.get(f"/acting-leadership/{appointment.id}")
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn("Sarah Officer · CCEO · Acting PL", text)
        self.assertIn("acting_capacity.write_refused", text)


class ActingLeadershipPageTests(RequestCase):
    def test_a_lead_sees_their_appointments_sorted_by_where_they_are(self):
        self.appoint_sarah()
        text = self.get(self.john, "/acting-leadership", SEPTEMBER_30).content.decode()
        self.assertIn("Appoint Acting PL", text)
        self.assertIn('data-acting-state="upcoming"', text)
        text = self.get(self.john, "/acting-leadership", OCTOBER_15).content.decode()
        self.assertIn('data-acting-state="active"', text)
        for part in (
            "Sarah Officer",
            "CCEO",
            "Acting Program Lead",
            "October 1 – October 31, 2026",
            "John Lead",
        ):
            self.assertIn(part, text)
        text = self.get(self.john, "/acting-leadership", NOVEMBER_1).content.decode()
        self.assertIn('data-acting-state="expired"', text)

    def test_each_reader_sees_their_own_reach(self):
        sarahs = self.appoint_sarah()
        peters = self.appoint_peter()
        seen = {}
        for who in (
            self.john,
            self.mary,
            self.hope,
            self.sarah,
            self.david,
            self.peter,
            self.wanjiru,
            self.otieno,
        ):
            response = self.get(who, "/acting-leadership", SEPTEMBER_30)
            self.assertEqual(response.status_code, 200, who.name)
            text = response.content.decode()
            seen[who.name] = (
                f'data-acting-row="{sarahs.id}"' in text,
                f'data-acting-row="{peters.id}"' in text,
            )
        self.assertEqual(
            seen,
            {
                "John Lead": (True, False),
                "Mary Director": (True, True),
                "Hope People": (True, True),
                "Sarah Officer": (True, False),
                "David Officer": (False, False),
                "Peter Lead": (False, True),
                "Wanjiru Director": (False, False),
                "Otieno Lead": (False, False),
            },
        )

    def test_only_who_may_appoint_is_offered_the_button(self):
        for who, offered in (
            (self.john, True),
            (self.mary, True),
            (self.hope, False),
            (self.sarah, False),
        ):
            text = self.get(who, "/acting-leadership", SEPTEMBER_30).content.decode()
            self.assertEqual("data-appoint-acting" in text, offered, who.name)

    def test_the_drawer_appoints_in_two_steps(self):
        drawer = self.get(self.john, "/acting-leadership/appoint", SEPTEMBER_30)
        text = drawer.content.decode()
        self.assertEqual(drawer.status_code, 200)
        for name in ("Sarah Officer", "David Officer", "Michael Officer"):
            self.assertIn(name, text)
        for stranger in ("Agnes Officer", "Peter Lead", "John Lead<"):
            self.assertNotIn(stranger, text)
        self.assertIn("October 1 – October 31, 2026", text)  # worked out, not typed

        review = self.post(
            self.john,
            "/acting-leadership/appoint",
            SEPTEMBER_30,
            {"appointee": self.sarah_sp.id, "month": "2026-10", "step": "review"},
        )
        self.assertIn(b"Confirm Appointment", review.content)
        self.assertIn(b"including your own operational scope", review.content)
        self.assertFalse(ActingAssignment.objects.exists())

        saved = self.post(
            self.john,
            "/acting-leadership/appoint",
            SEPTEMBER_30,
            {"appointee": self.sarah_sp.id, "month": "2026-10", "step": "confirm"},
        )
        self.assertEqual(saved["HX-Redirect"], "/acting-leadership")
        appointment = ActingAssignment.objects.get()
        self.assertEqual(appointment.appointee_id, self.sarah.id)

    def test_a_crafted_request_for_someone_out_of_reach_is_refused(self):
        for who, staff_id in (
            (self.john, self.agnes_sp.id),  # another team's officer
            (self.john, self.peter_sp.id),  # a Lead
            (self.mary, self.otieno_sp.id),  # another country's Lead
            (self.mary, self.sarah_sp.id),  # an officer, directly
        ):
            response = self.post(
                who,
                "/acting-leadership/appoint",
                SEPTEMBER_30,
                {"appointee": staff_id, "month": "2026-10", "step": "confirm"},
            )
            self.assertNotIn("HX-Redirect", response)
        for who in (self.sarah, self.hope, self.david):
            response = self.post(
                who,
                "/acting-leadership/appoint",
                SEPTEMBER_30,
                {"appointee": self.david_sp.id, "month": "2026-10", "step": "confirm"},
            )
            self.assertEqual(response.status_code, 403)
        self.assertFalse(ActingAssignment.objects.exists())

    def test_another_teams_appointment_cannot_be_opened_or_cancelled_by_id(self):
        appointment = self.appoint_sarah()
        for who in (self.peter, self.wanjiru, self.david):
            for path in ("", "/cancel", "/reschedule"):
                response = self.get(
                    who, f"/acting-leadership/{appointment.id}{path}", SEPTEMBER_30
                )
                self.assertEqual(response.status_code, 404, (who.name, path))
            self.post(who, f"/acting-leadership/{appointment.id}/cancel", SEPTEMBER_30)
        self.assertIsNone(ActingAssignment.objects.get(id=appointment.id).cancelled_at)

    def test_the_lead_cancels_from_the_drawer(self):
        appointment = self.appoint_sarah()
        response = self.post(
            self.john,
            f"/acting-leadership/{appointment.id}/cancel",
            OCTOBER_15,
            {"reason": "Back early"},
        )
        self.assertEqual(response["HX-Redirect"], "/acting-leadership")
        stored = ActingAssignment.objects.get(id=appointment.id)
        self.assertEqual(stored.cancel_reason, "Back early")
        text = self.get(self.john, "/acting-leadership", OCTOBER_15).content.decode()
        self.assertIn('data-acting-state="cancelled"', text)

    def test_the_lead_moves_an_upcoming_appointment_from_the_drawer(self):
        appointment = self.appoint_sarah()
        drawer = self.get(
            self.john, f"/acting-leadership/{appointment.id}/reschedule", SEPTEMBER_30
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertIn(b"Change acting month", drawer.content)
        response = self.post(
            self.john,
            f"/acting-leadership/{appointment.id}/reschedule",
            SEPTEMBER_30,
            {"month": "2026-11"},
        )
        self.assertEqual(response["HX-Redirect"], "/acting-leadership")
        stored = ActingAssignment.objects.get(id=appointment.id)
        self.assertEqual(stored.effective_label, "November 1 – November 30, 2026")
        # Once it has begun the drawer offers nothing to save.
        begun = self.get(
            self.john, f"/acting-leadership/{appointment.id}/reschedule", NOVEMBER_1
        )
        self.assertIn(b"data-acting-no-change", begun.content)

    def test_the_cancel_drawer_says_what_cancelling_does(self):
        appointment = self.appoint_sarah()
        drawer = self.get(
            self.john, f"/acting-leadership/{appointment.id}/cancel", OCTOBER_15
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertIn(b"loses Acting PL access at once", drawer.content)
        self.assertIn(b"stays in History", drawer.content)


class TimelineAttributionTests(RequestCase):
    """History a person reads names the capacity an act was done in."""

    def test_an_audit_row_reads_permanent_role_then_acting_role(self):
        from apps.frontend.templatetags.acting import audit_capacity

        self.appoint_sarah()
        self.post(self.sarah, "/fund-approvals/action", OCTOBER_15)
        acting_row = AuditLog.objects.filter(
            action="acting_capacity.write_refused", actor_id=self.sarah.id
        ).latest("created_at")
        self.assertEqual(audit_capacity(acting_row), "CCEO · Acting Program Lead")

        self.post(self.john, "/auth/switch-role", OCTOBER_15, {"role": "Program Lead"})
        own_row = AuditLog.objects.filter(actor_id=self.john.id).latest("created_at")
        self.assertEqual(audit_capacity(own_row), "Program Lead")
        # A row with no payload, or a plain mapping, reads as its own role.
        self.assertEqual(
            audit_capacity({"actor_role": "CCEO", "payload": None}), "CCEO"
        )
        self.assertEqual(audit_capacity({"actor_role": "", "payload": "text"}), "")

    def test_the_records_acts_are_paged_by_asking_the_drawer_again(self):
        month = services.month_options()[0]["value"]
        appointment = services.appoint(
            self.john, appointee_staff_id=self.sarah_sp.id, month=month
        )
        self.client.force_login(User.objects.get(id=self.sarah.id))
        for _ in range(3):
            self.client.post("/fund-approvals/action")
        self.client.force_login(User.objects.get(id=self.john.id))
        with mock.patch("apps.core.pagination.TABLE_PAGE_SIZE", 2):
            first = self.client.get(f"/acting-leadership/{appointment.id}")
            second = self.client.get(f"/acting-leadership/{appointment.id}?page=2")
        self.assertIn(b"Showing 1\xe2\x80\x932 of 3", first.content)
        self.assertIn(
            f"/acting-leadership/{appointment.id}?page=2".encode(), first.content
        )
        self.assertIn(b"Showing 3\xe2\x80\x933 of 3", second.content)
