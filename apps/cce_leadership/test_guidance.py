"""Team Guidance: the Programme Lead communicates the priorities (owner, 2026-09-13).

The role description: "lead priority setting, planning, and communication for
CCE initiatives at the country level". These tests hold the rules for the
guidance a lead issues to their officers (who writes, who reads, draft →
issue → acknowledge → review, withdraw), the Team Guidance tab and the
officer's panel on their own Priorities page, the notification routes, the
To-Dos, the dashboard interface, and what each costs in queries.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.hr.models import PriorityMilestone, StrategicPriority, StrategicPriorityCycle
from apps.notifications.models import Notification

from . import guidance as service
from .guidance_todos import guidance_todos
from .models import TeamGuidance, TeamGuidanceReceipt

TODAY = timezone.localdate()
FY = "2027"
SHELL = "priority-workspace-view-shell"
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "team-guidance-tests",
    }
}


def _person(uid, name, role, country="Uganda"):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country=country, title=role
    )
    return user, profile


def _priority(code, title, sequence, *, fy=FY, cycle=None):
    return StrategicPriority.objects.create(
        cycle=cycle,
        code=code,
        fy=fy,
        level="country",
        country_id="Uganda",
        title=title,
        strategic_purpose="test",
        sequence=sequence,
    )


class GuidanceFixture(TestCase):
    """A Uganda lead with two officers, a second lead with an officer of their
    own, a Country Director, Admin, and a cycle with two priorities."""

    @classmethod
    def setUpTestData(cls):
        cls.pl, cls.pl_sp = _person("tg-pl", "Guide Lead", "Program Lead")
        cls.cceo, cls.cceo_sp = _person("tg-cceo", "First Officer", "CCEO")
        cls.cceo2, cls.cceo2_sp = _person("tg-cceo2", "Second Officer", "CCEO")
        for officer in (cls.cceo_sp, cls.cceo2_sp):
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl_sp, supervisee=officer
            )
        cls.other_pl, cls.other_pl_sp = _person("tg-pl2", "Other Lead", "Program Lead")
        cls.other_cceo, cls.other_cceo_sp = _person("tg-cceo3", "Other Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.other_pl_sp, supervisee=cls.other_cceo_sp
        )
        cls.cd, _cd_sp = _person("tg-cd", "Country Director", "CountryDirector")
        cls.admin, _admin_sp = _person("tg-admin", "Platform Admin", "Admin")

        # The migrations may already have created the year's cycle.
        cls.cycle, _created = StrategicPriorityCycle.objects.get_or_create(
            financial_year=FY,
            defaults={"title": "FY2027 priorities", "status": "approved"},
        )
        cls.priority = _priority("QUALITY", "Program quality", 1, cycle=cls.cycle)
        cls.other_priority = _priority("REACH", "School reach", 2, cycle=cls.cycle)
        cls.milestone = PriorityMilestone.objects.create(
            priority=cls.other_priority,
            code="SSA_COVERAGE",
            title="Every client school assessed",
            source_text="test",
            milestone_type="output",
            measurement_type="count",
            progress_source="test",
        )

    def _draft(self, lead=None, **extra):
        return service.draft_guidance(
            lead or self.pl,
            {
                "title": "Prioritise SSA collection",
                "instruction": "Collect SSA in every client school before planning.",
                "expected_change": "Plans that answer each school's weakest area.",
                "all_officers": "1",
                "fy": FY,
                **extra,
            },
        )

    def _issued(self, **extra):
        return self._draft(issue="1", **extra)


# ── Rules ────────────────────────────────────────────────────────────────────
class GuidanceRulesTest(GuidanceFixture):
    def test_a_draft_reaches_every_officer_on_the_team_and_nobody_else(self):
        guidance = self._draft()
        self.assertIsNone(guidance.issued_at)
        self.assertEqual(guidance.author_id, self.pl.id)
        self.assertEqual(guidance.country, "Uganda")
        self.assertEqual(
            set(guidance.receipts.values_list("recipient_staff_id", flat=True)),
            {self.cceo_sp.id, self.cceo2_sp.id},
        )
        # A draft stays with the lead.
        self.assertFalse(service.receipts_for_officer(self.cceo).exists())

    def test_chosen_officers_must_be_on_the_leads_team(self):
        guidance = self._draft(all_officers="", recipients=[self.cceo_sp.id])
        self.assertEqual(
            list(guidance.receipts.values_list("recipient_staff_id", flat=True)),
            [self.cceo_sp.id],
        )
        # A User id names the same officer.
        guidance = self._draft(all_officers="", recipients=[self.cceo2.id])
        self.assertEqual(
            list(guidance.receipts.values_list("recipient_staff_id", flat=True)),
            [self.cceo2_sp.id],
        )
        with self.assertRaisesMessage(BadRequest, "Choose officers on your team."):
            self._draft(all_officers="", recipients=[self.other_cceo_sp.id])
        with self.assertRaisesMessage(BadRequest, "Choose the officers"):
            self._draft(all_officers="", recipients=[])

    def test_only_a_programme_lead_writes_guidance(self):
        for principal in (self.cceo, self.cd, self.admin):
            with self.subTest(role=principal.active_role):
                with self.assertRaises(Forbidden):
                    self._draft(lead=principal)

    def test_the_words_the_officers_act_on_are_required(self):
        with self.assertRaisesMessage(BadRequest, "title"):
            self._draft(title=" ")
        with self.assertRaisesMessage(BadRequest, "instruction"):
            self._draft(instruction="")
        with self.assertRaisesMessage(BadRequest, "review date"):
            self._draft(review_on=(TODAY - timedelta(days=1)).isoformat())

    def test_a_milestone_names_its_own_priority(self):
        guidance = self._draft(milestone_id=self.milestone.id)
        self.assertEqual(guidance.priority_id, self.other_priority.id)
        self.assertEqual(guidance.fy, FY)
        with self.assertRaisesMessage(BadRequest, "different priority"):
            self._draft(priority_id=self.priority.id, milestone_id=self.milestone.id)
        with self.assertRaisesMessage(BadRequest, "country priority"):
            self._draft(priority_id="not-a-priority")

    def test_a_priority_comes_from_the_leads_own_country_plan(self):
        kenya = StrategicPriority.objects.create(
            cycle=self.cycle,
            code="KE_QUALITY",
            fy=FY,
            level="country",
            country_id="Kenya",
            title="Kenya quality",
            strategic_purpose="test",
            sequence=3,
        )
        priorities, _milestones = service.priority_choices(self.pl, FY)
        self.assertNotIn(kenya, priorities)
        # A posted id the drawer never offered is refused, not saved.
        with self.assertRaisesMessage(BadRequest, "your country's plan"):
            self._draft(priority_id=kenya.id)
        kenya_milestone = PriorityMilestone.objects.create(
            priority=kenya,
            code="KE_SSA",
            title="Kenya schools assessed",
            source_text="test",
            milestone_type="output",
            measurement_type="count",
            progress_source="test",
        )
        with self.assertRaisesMessage(BadRequest, "your country's plan"):
            self._draft(milestone_id=kenya_milestone.id)
        self.assertEqual(self._draft(priority_id=self.priority.id).country, "Uganda")

    def test_the_state_filter_agrees_with_the_state_column(self):
        due = self._issued(title="Due now")
        TeamGuidance.objects.filter(id=due.id).update(review_on=TODAY)
        waiting = self._issued(title="Still waiting")
        answered = self._draft(
            title="Answered", all_officers="", issue="1", recipients=[self.cceo_sp.id]
        )
        service.acknowledge_guidance(self.cceo, answered.id, "Done.")
        visible = service.with_receipt_counts(service.guidance_visible_to(self.pl))

        def titles(state):
            rows = service.with_state(visible, state, today=TODAY)
            for row in rows:
                self.assertEqual(
                    service.state_of(row, today=TODAY)[0],
                    dict(service.STATE_CHOICES)[state],
                )
            return {row.title for row in rows}

        self.assertEqual(titles(service.STATE_REVIEW), {due.title})
        self.assertEqual(titles(service.STATE_AWAITING), {waiting.title})
        self.assertEqual(titles(service.STATE_ACKNOWLEDGED), {answered.title})

    def test_a_draft_is_corrected_only_by_its_author_and_only_before_issue(self):
        guidance = self._draft()
        with self.assertRaises(NotFoundError):
            service.update_guidance(
                self.other_pl, guidance.id, {"title": "x", "instruction": "y"}
            )
        updated = service.update_guidance(
            self.pl,
            guidance.id,
            {
                "title": "Collect SSA first",
                "instruction": "Collect SSA before planning.",
                "recipients": [self.cceo_sp.id],
            },
        )
        self.assertEqual(updated.title, "Collect SSA first")
        self.assertEqual(updated.receipts.count(), 1)
        service.issue_guidance(self.pl, guidance.id)
        with self.assertRaisesMessage(BadRequest, "can no longer be changed"):
            service.update_guidance(
                self.pl,
                guidance.id,
                {"title": "Changed", "instruction": "Changed", "all_officers": "1"},
            )


class GuidanceHandoffTest(GuidanceFixture):
    def test_issuing_notifies_each_officer_on_their_priorities_page(self):
        guidance = self._issued(review_on=(TODAY + timedelta(days=14)).isoformat())
        self.assertIsNotNone(guidance.issued_at)
        notices = Notification.objects.filter(
            source_event_type=service.EVENT_ISSUED, context_id=guidance.id
        )
        self.assertEqual(
            set(notices.values_list("recipient_id", flat=True)),
            {self.cceo.id, self.cceo2.id},
        )
        self.assertEqual(
            set(notices.values_list("target_route", flat=True)),
            {f"/priorities?guidance={guidance.id}"},
        )
        with self.assertRaisesMessage(BadRequest, "already issued"):
            service.issue_guidance(self.pl, guidance.id)
        with self.assertRaises(NotFoundError):
            service.issue_guidance(self.other_pl, guidance.id)

    def test_an_officer_who_left_the_team_is_dropped_at_issue(self):
        guidance = self._draft()
        StaffSupervisorAssignment.objects.filter(supervisee=self.cceo2_sp).delete()
        service.issue_guidance(self.pl, guidance.id)
        self.assertEqual(
            list(guidance.receipts.values_list("recipient_staff_id", flat=True)),
            [self.cceo_sp.id],
        )
        lonely = self._draft(all_officers="", recipients=[self.cceo_sp.id])
        StaffSupervisorAssignment.objects.filter(supervisee=self.cceo_sp).delete()
        with self.assertRaisesMessage(BadRequest, "on your team"):
            service.issue_guidance(self.pl, lonely.id)

    def test_the_officer_acknowledges_with_a_response_and_the_lead_hears(self):
        guidance = self._issued()
        with self.assertRaisesMessage(BadRequest, "Say what you will do"):
            service.acknowledge_guidance(self.cceo, guidance.id, "  ")
        with self.assertRaises(Forbidden):
            service.acknowledge_guidance(self.pl, guidance.id, "Not mine to answer")
        with self.assertRaises(NotFoundError):
            service.acknowledge_guidance(self.other_cceo, guidance.id, "Not for me")

        receipt = service.acknowledge_guidance(
            self.cceo, guidance.id, "I will collect SSA in my 12 client schools."
        )
        self.assertIsNotNone(receipt.acknowledged_at)
        lead_notice = Notification.objects.get(
            source_event_type=service.EVENT_ACKNOWLEDGED, recipient_id=self.pl.id
        )
        self.assertEqual(
            lead_notice.target_route, f"/priorities/guidance?open={guidance.id}"
        )
        # The officer's own "acknowledge" notice closes; the other officer's
        # stays open.
        self.assertIsNotNone(
            Notification.objects.get(
                source_event_type=service.EVENT_ISSUED, recipient_id=self.cceo.id
            ).resolved_at
        )
        self.assertIsNone(
            Notification.objects.get(
                source_event_type=service.EVENT_ISSUED, recipient_id=self.cceo2.id
            ).resolved_at
        )
        with self.assertRaisesMessage(BadRequest, "already acknowledged"):
            service.acknowledge_guidance(self.cceo, guidance.id, "Again")

    def test_withdrawn_guidance_leaves_the_officers(self):
        guidance = self._issued()
        with self.assertRaises(NotFoundError):
            service.withdraw_guidance(self.other_pl, guidance.id)
        service.withdraw_guidance(self.pl, guidance.id)
        self.assertFalse(service.receipts_for_officer(self.cceo).exists())
        with self.assertRaises(NotFoundError):
            service.acknowledge_guidance(self.cceo, guidance.id, "Too late")
        self.assertFalse(
            Notification.objects.filter(
                source_event_type=service.EVENT_ISSUED,
                context_id=guidance.id,
                resolved_at__isnull=True,
            ).exists()
        )
        with self.assertRaisesMessage(BadRequest, "already withdrawn"):
            service.withdraw_guidance(self.pl, guidance.id)

    def test_the_review_sets_the_next_date_or_closes(self):
        guidance = self._issued(review_on=(TODAY + timedelta(days=3)).isoformat())
        with self.assertRaisesMessage(BadRequest, "not due for review"):
            service.review_guidance(self.pl, guidance.id, "")
        TeamGuidance.objects.filter(id=guidance.id).update(review_on=TODAY)
        with self.assertRaisesMessage(BadRequest, "after today"):
            service.review_guidance(self.pl, guidance.id, TODAY.isoformat())
        with self.assertRaises(NotFoundError):
            service.review_guidance(self.other_pl, guidance.id, "")
        nxt = TODAY + timedelta(days=30)
        self.assertEqual(
            service.review_guidance(self.pl, guidance.id, nxt.isoformat()).review_on,
            nxt,
        )
        TeamGuidance.objects.filter(id=guidance.id).update(review_on=TODAY)
        self.assertIsNone(service.review_guidance(self.pl, guidance.id, "").review_on)


class GuidanceSummaryTest(GuidanceFixture):
    def test_the_dashboard_interface(self):
        self.assertEqual(
            service.guidance_summary(self.pl),
            {"issued": 0, "open": 0, "acknowledged": 0, "awaiting": 0, "latest": []},
        )
        first = self._issued()
        self._draft(title="A draft")
        withdrawn = self._issued(title="Withdrawn")
        service.withdraw_guidance(self.pl, withdrawn.id)
        service.acknowledge_guidance(self.cceo, first.id, "Will do.")
        summary = service.guidance_summary(self.pl)
        self.assertEqual(summary["issued"], 1)
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["acknowledged"], 1)
        self.assertEqual(summary["awaiting"], 1)
        self.assertEqual(
            [
                (row["title"], row["acknowledged"], row["recipients"])
                for row in summary["latest"]
            ],
            [("A draft", 0, 2), ("Prioritise SSA collection", 1, 2)],
        )
        self.assertIsNone(summary["latest"][0]["issued_at"])
        service.acknowledge_guidance(self.cceo2, first.id, "Will do too.")
        self.assertEqual(service.guidance_summary(self.pl)["open"], 0)
        # Anyone else reads nothing through it.
        for principal in (self.other_pl, self.cceo, self.admin):
            with self.subTest(role=principal.active_role, user=principal.id):
                self.assertEqual(service.guidance_summary(principal)["issued"], 0)


# ── Pages and drawers ────────────────────────────────────────────────────────
class TeamGuidancePageTest(GuidanceFixture):
    def test_the_lead_works_the_register_from_the_priorities_tab(self):
        issued = self._issued(review_on=(TODAY + timedelta(days=7)).isoformat())
        draft = self._draft(title="Draft for later")
        service.acknowledge_guidance(self.cceo, issued.id, "On it.")
        self.client.force_login(self.pl)
        response = self.client.get("/priorities/guidance", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="dashboard-tab-guidance"', html)
        self.assertIn("Team Guidance", html)
        self.assertIn("Prioritise SSA collection", html)
        self.assertIn("1 of 2", html)
        self.assertIn("Draft for later", html)
        self.assertIn(f"/priorities/guidance/{draft.id}/issue", html)
        self.assertIn(f"/priorities/guidance/{issued.id}/withdraw", html)
        self.assertIn("/priorities/guidance/new?fy=2027", html)
        self.assertIn("Guidance Awaiting Officer Acknowledgement", html)
        # The state filter narrows the register.
        response = self.client.get("/priorities/guidance", {"fy": FY, "state": "draft"})
        self.assertContains(response, "Draft for later")
        self.assertNotContains(response, "Prioritise SSA collection")

    def test_a_tab_press_returns_the_panel(self):
        self.client.force_login(self.pl)
        response = self.client.get(
            "/priorities/guidance",
            {"fy": FY},
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET=SHELL,
        )
        html = response.content.decode()
        self.assertNotIn("<html", html)
        self.assertIn("data-team-guidance-register", html)
        self.assertNotIn("data-dashboard-view-shell", html)

    def test_other_roles_are_turned_away_and_admin_reads_only(self):
        self._issued()
        for principal in (self.cceo, self.cd):
            with self.subTest(role=principal.active_role):
                self.client.force_login(principal)
                response = self.client.get("/priorities/guidance")
                self.assertNotIn(b"data-team-guidance-register", response.content)
                self.assertNotIn(b"Prioritise SSA collection", response.content)
        self.client.force_login(self.admin)
        response = self.client.get("/priorities/guidance", {"fy": FY})
        self.assertContains(response, "Prioritise SSA collection")
        self.assertContains(response, "Read only.")
        self.assertNotContains(response, "/priorities/guidance/new")
        self.assertNotContains(response, "/withdraw")

    def test_another_lead_cannot_reach_or_change_the_guidance(self):
        guidance = self._draft()
        self.client.force_login(self.other_pl)
        self.assertNotContains(
            self.client.get("/priorities/guidance", {"fy": FY}),
            "Prioritise SSA collection",
        )
        for url in ("", "/edit", "/issue", "/withdraw"):
            with self.subTest(url=url):
                response = self.client.get(
                    f"/priorities/guidance/{guidance.id}{url}", HTTP_HX_REQUEST="true"
                )
                self.assertContains(response, "not in your reach")
        for url in ("/issue/save", "/withdraw/save", "/update"):
            with self.subTest(post=url):
                self.client.post(
                    f"/priorities/guidance/{guidance.id}{url}",
                    {"title": "Hijack", "instruction": "Hijack", "all_officers": "1"},
                )
        guidance.refresh_from_db()
        self.assertIsNone(guidance.issued_at)
        self.assertIsNone(guidance.withdrawn_at)
        self.assertEqual(guidance.title, "Prioritise SSA collection")

    def test_the_new_drawer_records_and_issues(self):
        self.client.force_login(self.pl)
        drawer = self.client.get(
            "/priorities/guidance/new", {"fy": FY}, HTTP_HX_REQUEST="true"
        )
        html = drawer.content.decode()
        self.assertIn('action="/priorities/guidance/record"', html)
        for name in (
            "title",
            "instruction",
            "expected_change",
            "priority_id",
            "milestone_id",
            "review_on",
            "all_officers",
            "recipients",
            "issue",
        ):
            self.assertIn(f'name="{name}"', html)
        self.assertIn("Program quality", html)
        self.assertIn("School reach · Every client school assessed", html)
        # A plain link opens the register with the drawer on top.
        self.assertRedirects(
            self.client.get("/priorities/guidance/new"),
            "/priorities/guidance?open=new",
            fetch_redirect_response=False,
        )
        response = self.client.post(
            "/priorities/guidance/record",
            {
                "fy": FY,
                "title": "Use SSA to plan",
                "instruction": "Plan from each school's SSA.",
                "recipients": [self.cceo_sp.id, self.cceo2_sp.id],
                "issue": "1",
                "next": "/priorities/guidance?fy=2027&open=new",
            },
        )
        self.assertRedirects(
            response, "/priorities/guidance?fy=2027", fetch_redirect_response=False
        )
        guidance = TeamGuidance.objects.get(title="Use SSA to plan")
        self.assertIsNotNone(guidance.issued_at)
        self.assertEqual(guidance.receipts.count(), 2)

    def test_a_refusal_is_shown_not_swallowed(self):
        self.client.force_login(self.pl)
        response = self.client.post(
            "/priorities/guidance/record",
            {"fy": FY, "title": "", "instruction": "x", "all_officers": "1"},
            follow=True,
        )
        self.assertContains(response, "Give the guidance a title")
        self.assertFalse(TeamGuidance.objects.exists())

    def test_the_open_drawer_shows_where_each_officer_stands(self):
        guidance = self._issued()
        service.acknowledge_guidance(self.cceo, guidance.id, "Planning from SSA now.")
        self.client.force_login(self.pl)
        html = self.client.get(
            f"/priorities/guidance/{guidance.id}", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn("First Officer", html)
        self.assertIn("Planning from SSA now.", html)
        self.assertIn("Second Officer", html)
        self.assertIn("Awaiting acknowledgement", html)

    def test_review_and_withdraw_through_the_drawers(self):
        guidance = self._issued()
        TeamGuidance.objects.filter(id=guidance.id).update(review_on=TODAY)
        self.client.force_login(self.pl)
        drawer = self.client.get(
            f"/priorities/guidance/{guidance.id}/review", HTTP_HX_REQUEST="true"
        )
        self.assertContains(
            drawer, f'action="/priorities/guidance/{guidance.id}/review/save"'
        )
        self.client.post(
            f"/priorities/guidance/{guidance.id}/review/save", {"next_review": ""}
        )
        guidance.refresh_from_db()
        self.assertIsNone(guidance.review_on)
        self.client.post(f"/priorities/guidance/{guidance.id}/withdraw/save")
        guidance.refresh_from_db()
        self.assertIsNotNone(guidance.withdrawn_at)

    def test_a_link_opens_the_drawer_it_names(self):
        guidance = self._issued()
        self.client.force_login(self.pl)
        response = self.client.get(
            "/priorities/guidance",
            {"fy": FY, "open": guidance.id, "step": "review"},
        )
        self.assertEqual(
            response.context["autoload_drawer"],
            f"/priorities/guidance/{guidance.id}/review",
        )
        response = self.client.get(
            "/priorities/guidance", {"open": "javascript:alert(1)"}
        )
        self.assertEqual(response.context["autoload_drawer"], "")
        self.client.force_login(self.other_pl)
        response = self.client.get("/priorities/guidance", {"open": guidance.id})
        self.assertEqual(response.context["autoload_drawer"], "")

    def test_a_post_returns_on_site_only(self):
        guidance = self._draft()
        self.client.force_login(self.pl)
        response = self.client.post(
            f"/priorities/guidance/{guidance.id}/issue/save",
            {"next": "https://evil.example/steal"},
        )
        self.assertEqual(response["Location"], "/priorities/guidance")


class OfficerGuidancePanelTest(GuidanceFixture):
    def test_the_officers_priorities_page_loads_the_panel(self):
        self.client.force_login(self.cceo)
        html = self.client.get("/priorities", {"guidance": "abc"}).content.decode()
        self.assertIn('hx-get="/priorities/guidance/inbox?open=abc"', html)
        self.client.force_login(self.pl)
        html = self.client.get("/priorities").content.decode()
        self.assertNotIn("data-team-guidance-inbox-loader", html)

    def test_the_panel_lists_what_reached_the_officer(self):
        issued = self._issued()
        self._draft(title="Still a draft")
        other = self._issued(lead=self.other_pl, title="For another team")
        self.client.force_login(self.cceo)
        response = self.client.get("/priorities/guidance/inbox", {"open": issued.id})
        html = response.content.decode()
        self.assertIn("Prioritise SSA collection", html)
        self.assertIn("Guide Lead", html)
        self.assertIn("1 waiting for your acknowledgement", html)
        self.assertNotIn("Still a draft", html)
        self.assertNotIn(other.title, html)
        self.assertIn(f'hx-get="/priorities/guidance/{issued.id}/acknowledge"', html)
        self.assertIn("data-team-guidance-autoload", html)
        # A name the officer was not sent opens nothing.
        html = self.client.get(
            "/priorities/guidance/inbox", {"open": other.id}
        ).content.decode()
        self.assertNotIn("data-team-guidance-autoload", html)
        # Anyone but an officer gets an empty fragment.
        self.client.force_login(self.pl)
        self.assertEqual(self.client.get("/priorities/guidance/inbox").content, b"")

    def test_the_officer_acknowledges_from_the_drawer(self):
        guidance = self._issued()
        self.client.force_login(self.cceo)
        drawer = self.client.get(
            f"/priorities/guidance/{guidance.id}/acknowledge", HTTP_HX_REQUEST="true"
        )
        self.assertContains(
            drawer, f'action="/priorities/guidance/{guidance.id}/acknowledge/save"'
        )
        self.assertContains(drawer, 'name="response"')
        response = self.client.post(
            f"/priorities/guidance/{guidance.id}/acknowledge/save",
            {
                "response": "Collecting SSA this month.",
                "next": f"/priorities?guidance={guidance.id}",
            },
        )
        self.assertRedirects(response, "/priorities", fetch_redirect_response=False)
        receipt = TeamGuidanceReceipt.objects.get(
            guidance=guidance, recipient_staff_id=self.cceo_sp.id
        )
        self.assertEqual(receipt.response, "Collecting SSA this month.")
        # Read back without a form once acknowledged.
        drawer = self.client.get(
            f"/priorities/guidance/{guidance.id}/acknowledge", HTTP_HX_REQUEST="true"
        )
        self.assertContains(drawer, "Your response")
        self.assertNotContains(drawer, 'name="response"')

    def test_an_officer_not_sent_the_guidance_cannot_open_or_answer_it(self):
        guidance = self._issued()
        self.client.force_login(self.other_cceo)
        drawer = self.client.get(
            f"/priorities/guidance/{guidance.id}/acknowledge", HTTP_HX_REQUEST="true"
        )
        self.assertContains(drawer, "not addressed to you")
        self.assertNotContains(drawer, guidance.instruction)
        self.client.post(
            f"/priorities/guidance/{guidance.id}/acknowledge/save",
            {"response": "Sneaky"},
        )
        self.assertFalse(TeamGuidanceReceipt.objects.filter(response="Sneaky").exists())
        # The lead's drawers are not the officer's door, even for guidance
        # addressed to them.
        self.client.force_login(self.cceo)
        response = self.client.get(
            f"/priorities/guidance/{guidance.id}", HTTP_HX_REQUEST="true"
        )
        self.assertNotIn(guidance.instruction.encode(), response.content)
        self.client.post(f"/priorities/guidance/{guidance.id}/withdraw/save")
        guidance.refresh_from_db()
        self.assertIsNone(guidance.withdrawn_at)


class GuidanceNotificationRoutesTest(SimpleTestCase):
    def test_guidance_events_land_on_the_page_that_acts_on_them(self):
        from apps.notifications.services import NotificationLinkResolver

        self.assertEqual(
            NotificationLinkResolver.resolve(
                "team_guidance_issued", "TeamGuidance", "g1", "CCEO"
            ),
            ("/priorities?guidance=g1", "Acknowledge Guidance"),
        )
        self.assertEqual(
            NotificationLinkResolver.resolve(
                "team_guidance_acknowledged", "TeamGuidance", "g1", "Program Lead"
            ),
            ("/priorities/guidance?open=g1", "Open Team Guidance"),
        )


# ── To-Dos ───────────────────────────────────────────────────────────────────
class GuidanceTodoTest(GuidanceFixture):
    def test_the_officer_is_asked_to_acknowledge_until_they_do(self):
        guidance = self._issued()
        rows = guidance_todos(self.cceo, "CCEO", TODAY)
        self.assertEqual(
            [row["title"] for row in rows], ["Acknowledge guidance from Guide Lead"]
        )
        self.assertEqual(rows[0]["action_url"], f"/priorities?guidance={guidance.id}")
        service.acknowledge_guidance(self.cceo, guidance.id, "Will do.")
        self.assertEqual(guidance_todos(self.cceo, "CCEO", TODAY), [])
        self.assertEqual(len(guidance_todos(self.cceo2, "CCEO", TODAY)), 1)
        service.withdraw_guidance(self.pl, guidance.id)
        self.assertEqual(guidance_todos(self.cceo2, "CCEO", TODAY), [])

    def test_the_lead_reviews_responses_once_the_date_arrives(self):
        guidance = self._issued(review_on=(TODAY + timedelta(days=2)).isoformat())
        self.assertEqual(guidance_todos(self.pl, "Program Lead", TODAY), [])
        TeamGuidance.objects.filter(id=guidance.id).update(review_on=TODAY)
        rows = guidance_todos(self.pl, "Program Lead", TODAY)
        self.assertEqual(
            [row["title"] for row in rows],
            ["Review guidance responses — Prioritise SSA collection"],
        )
        row = rows[0]
        self.assertEqual(row["category"], "Strategic Direction")
        self.assertEqual(
            row["action_url"],
            f"/priorities/guidance?fy={FY}&open={guidance.id}&step=review",
        )
        self.assertEqual(row["status_key"], "due_today")
        self.assertIn("0 of 2", row["description"])
        overdue = guidance_todos(self.pl, "Program Lead", TODAY + timedelta(days=1))[0]
        self.assertEqual(overdue["status_key"], "overdue")
        service.review_guidance(self.pl, guidance.id, "")
        self.assertEqual(guidance_todos(self.pl, "Program Lead", TODAY), [])
        # Other leads and roles see nothing of it.
        self.assertEqual(guidance_todos(self.other_pl, "Program Lead", TODAY), [])
        self.assertEqual(guidance_todos(self.cd, "CountryDirector", TODAY), [])

    def test_registered_and_never_raises(self):
        from apps.command_center.todo_service import MODULE_TODO_BUILDERS

        self.assertIn(
            "apps.cce_leadership.guidance_todos:guidance_todos", MODULE_TODO_BUILDERS
        )
        with patch(
            "apps.cce_leadership.guidance_todos._officer_todos",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(guidance_todos(self.cceo, "CCEO", TODAY), [])


# ── Query budgets ────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class GuidanceQueryBudgetTest(GuidanceFixture):
    """Fixed cost whatever the team size or the number of pieces: every list
    is read once and counted in the database. Measured against a cache this
    process owns, because dev test runs share a real Redis."""

    def _grow(self, start, count):
        for index in range(start, start + count):
            officer, officer_sp = _person(
                f"tg-q{index}", f"Budget Officer {index}", "CCEO"
            )
            StaffSupervisorAssignment.objects.create(
                supervisor=self.pl_sp, supervisee=officer_sp
            )
            guidance = self._issued(
                title=f"Guidance {index}",
                review_on=TODAY.isoformat(),
            )
            TeamGuidance.objects.filter(id=guidance.id).update(review_on=TODAY)
            service.acknowledge_guidance(self.cceo, guidance.id, "Yes.")

    def _queries(self, fn):
        fn()  # warm per-process caches
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_the_register_page(self):
        self.client.force_login(self.pl)

        def page():
            response = self.client.get("/priorities/guidance", {"fy": FY})
            self.assertEqual(response.status_code, 200)

        self._grow(0, 1)
        small = self._queries(page)
        self._grow(1, 5)
        self.assertEqual(self._queries(page), small)

    def test_the_officer_panel_and_the_todo_builders(self):
        def inbox():
            self.client.force_login(self.cceo)
            self.client.get("/priorities/guidance/inbox")

        self._grow(0, 1)
        small_inbox = self._queries(inbox)
        small_lead = self._queries(
            lambda: guidance_todos(self.pl, "Program Lead", TODAY)
        )
        small_officer = self._queries(lambda: guidance_todos(self.cceo2, "CCEO", TODAY))
        self._grow(1, 5)
        self.assertEqual(self._queries(inbox), small_inbox)
        self.assertEqual(
            self._queries(lambda: guidance_todos(self.pl, "Program Lead", TODAY)),
            small_lead,
        )
        self.assertLessEqual(small_lead, 1)
        self.assertEqual(
            self._queries(lambda: guidance_todos(self.cceo2, "CCEO", TODAY)),
            small_officer,
        )
        self.assertLessEqual(small_officer, 2)

    def test_the_dashboard_summary(self):
        self._grow(0, 1)
        small = self._queries(lambda: service.guidance_summary(self.pl))
        self._grow(1, 5)
        self.assertEqual(
            self._queries(lambda: service.guidance_summary(self.pl)), small
        )
        self.assertLessEqual(small, 4)
