"""Team leadership for the Programme Lead (Programme Lead alignment, 2026-09-13).

"Line-management, supervision, leadership, and support to CCEOs." These tests
hold the pages and handoffs Track T built around that responsibility:

* /my-team — the team home: rendered from the roster, refused to other roles,
  flat in query cost as the team grows;
* the staff profile's back link and the line manager's Supervision panel, which
  never appears for HR, the Country Director or another lead;
* the People Directory without HR-only controls for a team reader;
* /trainings sending the lead and the officer where their trainings live;
* notification routes that land a Programme Lead where they can act;
* the escalation To-Dos and the SLA notice naming the real addressee;
* Team Leave: the section strip, cover involving the team, one heatmap build,
  a calendar narrowed to the lead's own team;
* Team Assignments: the strip on Actions Sent and Extra Work, and a milestone
  picker from the assigner's own country;
* Field Debrief supervision: mark reviewed, the Awaiting my review tab, and
  every refusal.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.schools.models import School

FY = get_operational_fy()
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-team-leadership",
    }
}


def _person(key, role, *, name=None, country="Uganda"):
    user = User.objects.create(
        id=f"tl-{key}"[:30],
        email=f"tl-{key}@edify.test",
        name=name or f"Lead {key}",
        roles=[role],
        active_role=role,
        is_active=True,
        status="active",
    )
    profile = StaffProfile.objects.create(
        id=f"tlsp-{key}"[:30],
        user=user,
        title=role,
        country=country,
        onboarding_state="active",
    )
    return user, profile


class TeamFixture(TestCase):
    """A Uganda Programme Lead with three officers, a second lead with one, a
    Country Director and HR in the same country."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="TL Region")
        cls.district = District.objects.create(name="TL District", region=cls.region)
        cls.pl, cls.pl_sp = _person("pl", "Program Lead", name="Pat Lead")
        cls.officers = []
        for i in range(3):
            user, sp = _person(f"cceo{i}", "CCEO", name=f"Officer {i}")
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl_sp, supervisee=sp
            )
            school = School.objects.create(
                school_id=f"TL-{i}",
                name=f"TL School {i}",
                region=cls.region,
                district=cls.district,
            )
            StaffSchoolAssignment.objects.create(staff=sp, school_id=school.id)
            cls.officers.append((user, sp))
        cls.cceo, cls.cceo_sp = cls.officers[0]
        cls.other_pl, cls.other_pl_sp = _person(
            "pl2", "Program Lead", name="Percy Lead"
        )
        cls.stranger, cls.stranger_sp = _person("cceo9", "CCEO", name="Not Yours")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.other_pl_sp, supervisee=cls.stranger_sp
        )
        cls.cd, cls.cd_sp = _person("cd", "CountryDirector", name="Cody Director")
        cls.hr, cls.hr_sp = _person("hr", "HumanResources", name="Hana HR")

    def _login(self, user):
        self.client.force_login(user)


# ── My Team ──────────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class MyTeamPageTests(TeamFixture):
    def test_the_lead_sees_their_officers_and_what_waits_on_them(self):
        self._login(self.pl)
        page = self.client.get("/my-team")
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "pages/my_team/index.html")
        for i in range(3):
            self.assertContains(page, f"Officer {i}")
        self.assertNotContains(page, "Not Yours")
        self.assertContains(page, "Needs your action")
        self.assertContains(page, f"/staff/{self.cceo.id}?from=/my-team")
        keys = {item["metric_key"] for item in page.context["kpi_strip_items"]}
        self.assertEqual(
            keys,
            {
                "pl_team_officers_on_my_team",
                "pl_team_officers_on_pace_for_fy_targets",
                "pl_team_officers_at_target_risk_this_month",
                "pl_team_team_handoffs_waiting_on_you",
                "pl_team_team_exceptions_needing_your_action",
                "pl_team_team_portfolio_ssa_coverage_this_fy",
            },
        )
        # The missing agreements are the lead's to start, on a page they open.
        self.assertContains(page, f"/performance-conversation?staff={self.cceo_sp.id}")

    def test_an_unknown_fy_falls_back_to_the_operational_year(self):
        self._login(self.pl)
        page = self.client.get("/my-team?fy=1999")
        self.assertEqual(page.context["fy"], FY)

    def test_other_roles_are_refused(self):
        for user in (self.cceo, self.cd, self.hr):
            with self.subTest(role=user.active_role):
                self._login(user)
                page = self.client.get("/my-team")
                self.assertNotEqual(page.status_code, 200)
                self.assertNotIn("Officer 1", page.content.decode())

    def _page_cost(self, team_size):
        keep = {sp.id for _, sp in self.officers[:team_size]}
        StaffSupervisorAssignment.objects.filter(supervisor=self.pl_sp).exclude(
            supervisee_id__in=keep
        ).delete()
        self._login(self.pl)
        self.client.get("/my-team")
        with CaptureQueriesContext(connection) as ctx:
            page = self.client.get("/my-team")
        self.assertEqual(len(page.context["rows"]), team_size)
        return len(ctx)

    def test_the_page_costs_the_same_for_three_officers_as_for_one(self):
        three = self._page_cost(3)
        one = self._page_cost(1)
        self.assertEqual(three, one)


# ── Staff profile and People Directory ───────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class StaffProfileSupervisionTests(TeamFixture):
    def test_the_lead_gets_the_supervision_panel_and_a_way_back_to_my_team(self):
        self._login(self.pl)
        page = self.client.get(f"/staff/{self.cceo.id}?from=/my-team")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["back_href"], "/my-team")
        self.assertContains(page, "Back to My Team")
        self.assertContains(page, "data-staff-supervision")
        self.assertContains(page, f"/performance-conversation?staff={self.cceo_sp.id}")
        self.assertContains(page, f"/team/coaching?cceo={self.cceo_sp.id}")
        self.assertContains(page, f"/team-targets/staff-drawer?staff={self.cceo.id}")
        self.assertContains(page, "/leave/tracker?q=Officer%200")

    def test_the_back_link_follows_the_referrer_and_ignores_foreign_targets(self):
        self._login(self.pl)
        page = self.client.get(
            f"/staff/{self.cceo.id}?from=https://evil.example.com/my-team"
        )
        self.assertEqual(page.context["back_href"], "/my-team")
        self._login(self.hr)
        page = self.client.get(
            f"/staff/{self.cceo.id}", HTTP_REFERER="http://testserver/leave/tracker?q=x"
        )
        self.assertEqual(page.context["back_href"], "/leave/tracker")
        page = self.client.get(f"/staff/{self.cceo.id}")
        self.assertEqual(page.context["back_href"], "/staff")

    def test_hr_and_the_country_director_read_the_profile_without_the_panel(self):
        for user in (self.hr, self.cd):
            with self.subTest(role=user.active_role):
                self._login(user)
                page = self.client.get(f"/staff/{self.cceo.id}")
                self.assertEqual(page.status_code, 200)
                self.assertIsNone(page.context["supervision"])
                self.assertNotContains(page, "data-staff-supervision")

    def test_another_lead_cannot_open_the_officer(self):
        self._login(self.other_pl)
        page = self.client.get(f"/staff/{self.cceo.id}")
        self.assertNotEqual(page.status_code, 200)

    def test_a_covering_lead_reads_the_covered_officer(self):
        now = timezone.now()
        leave = Leave.objects.create(
            staff=self.other_pl_sp,
            type="personal_time_off",
            start_date=(now.date() - timedelta(days=1)).isoformat(),
            end_date=(now.date() + timedelta(days=3)).isoformat(),
            days=4,
            days_charged=4,
            status="approved",
        )
        TemporaryCoverageAssignment.objects.create(
            leave_request=leave,
            original_staff=self.other_pl_sp,
            covering_staff=self.pl_sp,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=3),
            status="active",
        )
        self._login(self.pl)
        page = self.client.get(f"/staff/{self.stranger.id}")
        self.assertEqual(page.status_code, 200)
        self.assertIsNotNone(page.context["supervision"])


class PeopleDirectoryTests(TeamFixture):
    def test_a_team_reader_gets_no_hr_controls_and_no_role_tabs(self):
        self._login(self.pl)
        page = self.client.get("/staff?tab=pl")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "New Staff Member")
        self.assertNotContains(page, 'aria-label="Staff views"')
        self.assertNotContains(page, "Pending onboarding")
        # A tab that is not rendered does not filter: the officers still list.
        self.assertEqual(page.context["active_tab"], "all")
        self.assertContains(page, "Officer 1")
        self.assertNotIn("average_coverage_gap", page.context["kpis"])

    def test_readers_who_administer_users_keep_them(self):
        self._login(self.hr)
        page = self.client.get("/staff")
        self.assertContains(page, "New Staff Member")
        self.assertContains(page, 'aria-label="Staff views"')
        self.assertContains(page, "Pending onboarding")


class TrainingsRedirectTests(TeamFixture):
    def test_the_lead_goes_to_programme_rollout_and_the_officer_to_my_plan(self):
        self._login(self.pl)
        page = self.client.get("/trainings")
        self.assertRedirects(
            page, "/programme-rollout?view=trainings", fetch_redirect_response=False
        )
        self._login(self.cceo)
        page = self.client.get("/trainings")
        self.assertRedirects(page, "/my-plan", fetch_redirect_response=False)


# ── Notification routes ──────────────────────────────────────────────────────
class NotificationRouteTests(TestCase):
    def _route(self, event, role, context_id="X1"):
        return NotificationLinkResolver.resolve(event, "Activity", context_id, role)[0]

    def test_no_programme_lead_or_coordinator_route_lands_on_my_team(self):
        cases = {
            ("critical_school_ssa", "Program Lead"): "/programme-rollout?view=ssa",
            ("critical_school_ssa", "ProjectCoordinator"): "/planning",
            ("partner_scheduled_activity", "Program Lead"): "/partner-oversight/",
            ("partner_scheduled_activity", "ProjectCoordinator"): "/my-plan",
            ("evidence_returned", "Program Lead"): "/evidence/?tab=returned",
            ("evidence_returned", "ProjectCoordinator"): "/evidence/?tab=returned",
        }
        for (event, role), expected in cases.items():
            with self.subTest(event=event, role=role):
                self.assertEqual(self._route(event, role), expected)

    def test_business_transformation_notices_reach_a_lead_somewhere_they_can_open(self):
        self.assertEqual(self._route("bt.loan.use_concern", "Program Lead"), "/schools")
        self.assertEqual(
            self._route("bt.facility.created", "Program Lead"), "/dashboard"
        )
        # The BT officer keeps their workspace.
        self.assertEqual(
            self._route("bt.case.recommended", "BusinessTransformationOfficer"),
            "/business-transformation",
        )

    def test_a_reviewed_debrief_opens_the_debrief(self):
        route, label = NotificationLinkResolver.resolve(
            "field_debrief_reviewed", "field_debrief", "D42", "CCEO"
        )
        self.assertEqual((route, label), ("/debriefs/D42", "Read Feedback"))


# ── Escalations ──────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class EscalationTodoTests(TeamFixture):
    def _raise(self, user, subject="Vehicle for cluster day"):
        from apps.flags import escalation_service

        return escalation_service.raise_escalation(
            {"subject": subject, "detail": "No vehicle is available."}, user
        )

    def _todos(self, user):
        from apps.flags.escalation_todos import pl_escalation_todos

        return pl_escalation_todos(user, user.active_role, date.today())

    def test_the_lead_is_asked_to_decide_and_the_row_closes_with_the_decision(self):
        from apps.flags import escalation_service

        esc = self._raise(self.cceo)
        rows = self._todos(self.pl)
        self.assertEqual([r["id"] for r in rows], [f"esc-decide-{esc.id}"])
        self.assertEqual(rows[0]["title"], "Decide escalation from Officer 0")
        self.assertEqual(rows[0]["action_url"], "/escalations")
        # Grouped under the responsibility vocabulary the queue uses for a lead.
        from apps.command_center.todo_service import PL_RESPONSIBILITY_CATEGORIES

        self.assertEqual(rows[0]["category"], "Team Leadership")
        self.assertIn(rows[0]["category"], PL_RESPONSIBILITY_CATEGORIES)
        # The board lists the same item as decidable.
        board = escalation_service.board(self.pl)
        self.assertEqual([r["id"] for r in board["inbox"]], [esc.id])
        escalation_service.resolve(
            esc.id, {"decision": "approved", "decision_note": "Hire one."}, self.pl
        )
        self.assertEqual(self._todos(self.pl), [])

    def test_nobody_else_gets_the_row(self):
        self._raise(self.cceo)
        self.assertEqual(self._todos(self.other_pl), [])
        from apps.flags.escalation_todos import pl_escalation_todos

        self.assertEqual(pl_escalation_todos(self.cceo, "CCEO", date.today()), [])
        self.assertEqual(
            pl_escalation_todos(self.cd, "CountryDirector", date.today()), []
        )

    def test_a_decision_delegated_back_asks_the_lead_to_act(self):
        from apps.flags import escalation_service

        StaffSupervisorAssignment.objects.create(
            supervisor=self.cd_sp, supervisee=self.pl_sp
        )
        esc = self._raise(self.pl, subject="Partner replacement")
        escalation_service.resolve(
            esc.id,
            {"decision": "delegated_back", "decision_note": "Your call."},
            self.cd,
        )
        rows = self._todos(self.pl)
        self.assertEqual([r["id"] for r in rows], [f"esc-delegated-{esc.id}"])
        self.assertIn("Country Director", rows[0]["description"])

    def test_the_builder_is_registered_and_bulk(self):
        from apps.command_center.todo_service import MODULE_TODO_BUILDERS

        self.assertIn(
            "apps.flags.escalation_todos:pl_escalation_todos", MODULE_TODO_BUILDERS
        )

        def cost():
            with CaptureQueriesContext(connection) as ctx:
                self._todos(self.pl)
            return len(ctx)

        self._raise(self.cceo, subject="One")
        one = cost()
        for i, (user, _) in enumerate(self.officers):
            self._raise(user, subject=f"More {i}")
        self.assertEqual(cost(), one)

    def test_the_overdue_notice_names_the_level_it_waits_on(self):
        from apps.flags import escalation_service
        from apps.flags.models import LeadershipEscalation

        esc = self._raise(self.cceo)
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=30)
        )
        escalation_service.sweep_overdue()
        notice = Notification.objects.get(
            recipient_id=self.cceo.id,
            source_event_type="leadership_escalation_overdue",
        )
        self.assertIn("a decision from the Programme Lead", notice.body)
        self.assertNotIn("RVP", notice.body)


# ── Team Leave ───────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class TeamLeaveTests(TeamFixture):
    def _leave(self, profile, *, status="approved", start=-1, end=3, cover=None):
        today = date.today()
        return Leave.objects.create(
            staff=profile,
            type="personal_time_off",
            start_date=(today + timedelta(days=start)).isoformat(),
            end_date=(today + timedelta(days=end)).isoformat(),
            days=4,
            days_charged=4,
            status=status,
            covering_staff=cover,
        )

    def test_each_team_leave_page_carries_the_leave_strip_for_the_lead(self):
        self._login(self.pl)
        for path in ("/leave/approvals", "/leave/tracker", "/leave/team-availability"):
            with self.subTest(path=path):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'aria-label="Leave sections"')
                self.assertContains(page, 'href="/leave/team-availability"')

    def test_the_tracker_shows_cover_involving_the_team(self):
        _, second = self.officers[1]
        leave = self._leave(self.cceo_sp, cover=second)
        now = timezone.now()
        TemporaryCoverageAssignment.objects.create(
            leave_request=leave,
            original_staff=self.cceo_sp,
            covering_staff=second,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=3),
            status="active",
        )
        other_leave = self._leave(self.stranger_sp)
        TemporaryCoverageAssignment.objects.create(
            leave_request=other_leave,
            original_staff=self.stranger_sp,
            covering_staff=self.other_pl_sp,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=3),
            status="active",
        )
        self._login(self.pl)
        page = self.client.get("/leave/tracker")
        covered = {c.original_staff_id for c in page.context["coverages"]}
        self.assertEqual(covered, {self.cceo_sp.id})

    def test_team_availability_builds_the_heatmap_once(self):
        from apps.hr.leave_services import TeamAvailabilityService

        self._login(self.pl)
        with patch.object(
            TeamAvailabilityService,
            "get_4week_heatmap",
            wraps=TeamAvailabilityService.get_4week_heatmap,
        ) as heatmap:
            page = self.client.get("/leave/team-availability")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(heatmap.call_count, 1)

    def test_the_calendar_shows_a_lead_only_their_team_and_the_cd_the_country(self):
        self._leave(self.cceo_sp)
        self._leave(self.stranger_sp)

        def staff_on(page):
            return {
                e["extendedProps"].get("staff")
                for e in page.context["events"]
                if e["extendedProps"].get("type") == "Approved Leave"
            }

        self._login(self.pl)
        seen = staff_on(self.client.get("/leave/calendar"))
        self.assertIn("Officer 0", seen)
        self.assertNotIn("Not Yours", seen)
        self._login(self.cd)
        seen = staff_on(self.client.get("/leave/calendar"))
        self.assertTrue({"Officer 0", "Not Yours"} <= seen)


# ── Team Assignments ─────────────────────────────────────────────────────────
class TeamAssignmentsTests(TeamFixture):
    def test_actions_sent_and_extra_work_carry_the_strip_and_my_actions_does_not(self):
        self._login(self.pl)
        for path in ("/actions/sent", "/extra-work"):
            with self.subTest(path=path):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, 'aria-label="Team Assignments sections"')
        page = self.client.get("/actions/mine")
        self.assertNotContains(page, 'aria-label="Team Assignments sections"')

    def test_the_milestone_picker_lists_the_assigners_own_country(self):
        from apps.hr.models import PriorityMilestone, StrategicPriority

        def milestone(country, level, title):
            priority = StrategicPriority.objects.create(
                fy=FY,
                level=level,
                country_id=country,
                title=f"{title} priority",
                strategic_purpose="Purpose",
                status="published",
            )
            return PriorityMilestone.objects.create(
                priority=priority,
                code=f"M-{title}",
                title=title,
                source_text=title,
                milestone_type="output",
                progress_source="activity",
            )

        uganda = milestone("Uganda", "country", "Uganda schools trained")
        kenya = milestone("Kenya", "country", "Kenya schools trained")
        regional = milestone(None, "regional", "Region-wide reach")
        self._login(self.pl)
        page = self.client.get(f"/extra-work/assign-drawer?fy={FY}")
        ids = {m.id for m in page.context["milestones"]}
        self.assertIn(uganda.id, ids)
        self.assertNotIn(kenya.id, ids)
        self.assertNotIn(regional.id, ids)
        kenyan_pl, kenyan_sp = _person("kpl", "Program Lead", country="Kenya")
        self._login(kenyan_pl)
        page = self.client.get(f"/extra-work/assign-drawer?fy={FY}")
        self.assertEqual({m.id for m in page.context["milestones"]}, {kenya.id})
        # A country with no priorities of its own links to the regional ones.
        tanzanian, _ = _person("tpl", "Program Lead", country="Tanzania")
        self._login(tanzanian)
        page = self.client.get(f"/extra-work/assign-drawer?fy={FY}")
        self.assertEqual({m.id for m in page.context["milestones"]}, {regional.id})


# ── Field Debrief supervision ────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class DebriefSupervisionTests(TeamFixture):
    def _submit(self, user, title="Cluster day"):
        from apps.debriefs.field_debrief_service import FieldDebriefService

        return FieldDebriefService.submit(
            user, {"title": title, "summary": "What happened.", "kind": "activity"}
        )

    def test_the_supervising_lead_marks_a_debrief_reviewed_and_the_officer_hears(self):
        from apps.audit.models import AuditLog
        from apps.debriefs.field_debrief_service import FieldDebriefService

        debrief = self._submit(self.cceo)
        reviewed = FieldDebriefService.mark_reviewed(
            self.pl, debrief.id, "Good session; start earlier next time."
        )
        self.assertEqual(reviewed.status, "reviewed")
        self.assertEqual(reviewed.reviewed_by_user_id, self.pl.id)
        self.assertEqual(reviewed.review_note, "Good session; start earlier next time.")
        notice = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type="field_debrief_reviewed"
        )
        self.assertEqual(notice.target_route, f"/debriefs/{debrief.id}")
        self.assertTrue(
            AuditLog.objects.filter(
                action="field_debrief_reviewed", subject_id=debrief.id
            ).exists()
        )
        with self.assertRaises(BadRequest):
            FieldDebriefService.mark_reviewed(self.pl, debrief.id, "Again")

    def test_refusals(self):
        from apps.debriefs.field_debrief_service import FieldDebriefService

        debrief = self._submit(self.cceo)
        with self.assertRaises(NotFoundError):
            FieldDebriefService.mark_reviewed(self.other_pl, debrief.id, "Not mine")
        with self.assertRaises(Forbidden):
            FieldDebriefService.mark_reviewed(self.cd, debrief.id, "Country reader")
        with self.assertRaises(BadRequest):
            FieldDebriefService.mark_reviewed(self.pl, debrief.id, "   ")
        own = self._submit(self.pl, title="My own day")
        with self.assertRaises(Forbidden):
            FieldDebriefService.mark_reviewed(self.pl, own.id, "Self review")
        debrief.refresh_from_db()
        self.assertEqual(debrief.status, "submitted")

    def test_awaiting_my_review_lists_the_teams_unreviewed_debriefs_only(self):
        from apps.debriefs.dashboard_service import FieldDebriefDashboardService
        from apps.debriefs.field_debrief_service import FieldDebriefService

        waiting = self._submit(self.cceo, title="Waiting")
        done = self._submit(self.officers[1][0], title="Done")
        FieldDebriefService.mark_reviewed(self.pl, done.id, "Read.")
        self._submit(self.stranger, title="Other team")
        self._submit(self.pl, title="My own")
        ctx = FieldDebriefDashboardService.get_dashboard(
            self.pl, {"tab": "awaiting_review"}
        )
        self.assertTrue(ctx["can_review_team"])
        self.assertEqual(ctx["awaiting_review_count"], 1)
        self.assertEqual([r["id"] for r in ctx["table_rows"]], [waiting.id])
        self.assertEqual(ctx["table_rows"][0]["submitted_by_name"], "Officer 0")
        cd_ctx = FieldDebriefDashboardService.get_dashboard(
            self.cd, {"tab": "awaiting_review"}
        )
        self.assertFalse(cd_ctx["can_review_team"])
        self.assertEqual(cd_ctx["table_rows"], [])

    def test_the_tracker_table_costs_the_same_for_one_row_as_for_five(self):
        from apps.debriefs.dashboard_service import FieldDebriefDashboardService
        from apps.debriefs.models import DailyDebrief

        def cost():
            with CaptureQueriesContext(connection) as ctx:
                rows = FieldDebriefDashboardService._table_rows(
                    DailyDebrief.objects.order_by("-date")[:10]
                )
            return len(ctx), len(rows)

        self._submit(self.cceo, title="First")
        one, count = cost()
        self.assertEqual(count, 1)
        for i in range(4):
            self._submit(self.officers[i % 3][0], title=f"More {i}")
        five, count = cost()
        self.assertEqual(count, 5)
        self.assertEqual(five, one)

    def test_the_detail_page_offers_review_and_coaching_to_the_supervising_lead_only(
        self,
    ):
        debrief = self._submit(self.cceo)
        self._login(self.pl)
        page = self.client.get(f"/debriefs/{debrief.id}")
        self.assertContains(page, 'value="mark_reviewed"')
        self.assertContains(
            page,
            f"/team/coaching/new?cceo={self.cceo_sp.id}&amp;kind=debrief_feedback"
            f"&amp;debrief={debrief.id}",
        )
        self._login(self.cd)
        page = self.client.get(f"/debriefs/{debrief.id}")
        self.assertNotContains(page, 'value="mark_reviewed"')
        self.assertNotContains(page, "/team/coaching/new")

    def test_a_review_without_feedback_says_why_and_changes_nothing(self):
        debrief = self._submit(self.cceo)
        self._login(self.pl)
        page = self.client.post(
            "/debriefs/action",
            {"action": "mark_reviewed", "debrief_id": debrief.id, "feedback": ""},
            follow=True,
        )
        self.assertContains(page, "Write your feedback for the officer")
        debrief.refresh_from_db()
        self.assertEqual(debrief.status, "submitted")
        page = self.client.post(
            "/debriefs/action",
            {"action": "mark_reviewed", "debrief_id": debrief.id, "feedback": "Seen."},
            follow=True,
        )
        debrief.refresh_from_db()
        self.assertEqual(debrief.status, "reviewed")
        self.assertContains(page, "Programme Lead's feedback")
        self.assertContains(page, "data-debrief-review")
