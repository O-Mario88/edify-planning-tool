"""Collaboration with the Country Director and training partners (Program Lead
alignment, owner 2026-09-13).

The Programme Lead "partners with regional leads, country directors, and
local training organizations to align goals and build capacity". These tests
hold the rules that make that collaboration real:

* the Country Director's flag loop closes both ways, with a resolution note;
* the partner engagement log — who records, who reads, what is refused, what
  the partner receives, and the To-Dos it derives;
* a stalled partner delivery escalates to the raiser's own Country Director
  through the escalation channel;
* messaging contexts stay inside the Programme Lead's team and partner scope.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.cce_leadership.models import EngagementKind, RegionalEngagement
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.flags import services as flag_services
from apps.flags.models import CdFlag, LeadershipEscalation
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.partners import engagement_services as services
from apps.partners.engagement_todos import partner_engagement_todos
from apps.partners.models import Partner, PartnerAssignment, PartnerEngagement
from apps.schools.models import School


def _today():
    """The platform's date, read when a test runs rather than when the module
    is imported. A module-level constant went stale when the suite ran across
    midnight in Africa/Nairobi, and the scheduling rules then refused every
    "today" as a day that had passed."""
    return timezone.localdate()


LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "partner-engagement-tests",
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
        status="active",
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country=country, title=role
    )
    return user, profile


class EngagementFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = services.get_operational_fy(_today())
        cls.region = Region.objects.create(name="PE Region", country="Uganda")
        cls.kenya_region = Region.objects.create(name="PE Kenya", country="Kenya")
        cls.district = District.objects.create(
            name="PE District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="PE-SCH",
            name="Hope Primary",
            region=cls.region,
            district=cls.district,
        )

        cls.pl, cls.pl_sp = _person("pe-pl", "Uganda Lead", "Program Lead")
        cls.cceo, cls.cceo_sp = _person("pe-cceo", "Uganda Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        cls.other_pl, cls.other_pl_sp = _person("pe-pl2", "Second Lead", "Program Lead")
        cls.other_cceo, cls.other_cceo_sp = _person("pe-cceo2", "Other Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.other_pl_sp, supervisee=cls.other_cceo_sp
        )
        cls.kenya_pl, cls.kenya_pl_sp = _person(
            "pe-kpl", "Kenya Lead", "Program Lead", country="Kenya"
        )
        cls.cd, cls.cd_sp = _person("pe-cd", "Uganda Director", "CountryDirector")
        cls.kenya_cd, cls.kenya_cd_sp = _person(
            "pe-kcd", "Kenya Director", "CountryDirector", country="Kenya"
        )
        cls.rpl, cls.rpl_sp = _person("pe-rpl", "Regional Lead", "RegionalProgramLead")
        StaffGeographyAssignment.objects.create(
            staff=cls.rpl_sp, region_id=cls.region.id
        )
        cls.admin, _ = _person("pe-admin", "Admin", "Admin")

        cls.partner_login = User.objects.create(
            id="pe-plogin",
            email="pe-plogin@partner.org",
            name="Partner Login",
            roles=["PartnerAdmin"],
            active_role="PartnerAdmin",
            is_active=True,
            status="active",
        )
        cls.partner = Partner.objects.create(
            name="Bright Trainers", active_status=True, user=cls.partner_login
        )
        cls.no_login_partner = Partner.objects.create(
            name="Quiet Trainers", active_status=True
        )
        cls.inactive_partner = Partner.objects.create(
            name="Closed Trainers", active_status=False
        )

        cls.training = Activity.objects.create(
            activity_type="training",
            school=cls.school,
            fy=cls.fy,
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id=cls.partner.id,
            status="completed",
            planned_date=_today() - timedelta(days=12),
        )
        cls.observation = RegionalEngagement.objects.create(
            author_id=cls.rpl.id,
            kind=EngagementKind.TRAINING_OBSERVATION,
            held_on=_today() - timedelta(days=10),
            fy=cls.fy,
            country="Uganda",
            program_lead_ids=[cls.pl_sp.id],
            subject="Observed: Bright Trainers leadership training",
            activity=cls.training,
            recommendation="strengthen",
            feedback="Facilitators read slides; model the practice instead.",
            feedback_shared_at=timezone.now() - timedelta(days=9),
        )

    def _record(self, user=None, **extra):
        data = {
            "partner_id": self.partner.id,
            "kind": "review_meeting",
            "held_on": _today().isoformat(),
            "subject": "Quarterly review",
            "notes": "Reviewed the term's trainings.",
            "agreed_improvements": "Model each practice before teachers try it.",
            **extra,
        }
        return services.record_engagement(user or self.pl, data)


# ── Engagement rules ─────────────────────────────────────────────────────────
class EngagementRulesTest(EngagementFixture):
    def test_the_programme_lead_and_the_director_record_with_their_country(self):
        mine = self._record(follow_up_due=(_today() + timedelta(days=7)).isoformat())
        self.assertEqual(mine.author_id, self.pl.id)
        self.assertEqual(mine.author_role, "Program Lead")
        self.assertEqual(mine.country, "Uganda")
        self.assertEqual(mine.fy, self.fy)
        theirs = self._record(self.kenya_cd)
        self.assertEqual(theirs.country, "Kenya")

    def test_other_roles_are_refused(self):
        for user in (self.cceo, self.rpl, self.admin, self.partner_login):
            with self.assertRaises(Forbidden, msg=user.active_role):
                self._record(user)
        self.assertFalse(PartnerEngagement.objects.exists())

    def test_it_refuses_incomplete_or_impossible_records(self):
        cases = [
            (
                {"held_on": (_today() + timedelta(days=1)).isoformat()},
                "once it has happened",
            ),
            (
                {"follow_up_due": (_today() - timedelta(days=1)).isoformat()},
                "cannot be before",
            ),
            (
                {
                    "agreed_improvements": "",
                    "follow_up_due": (_today() + timedelta(days=3)).isoformat(),
                },
                "improvements were agreed",
            ),
            ({"partner_id": "nope"}, "training partner"),
            ({"partner_id": self.inactive_partner.id}, "inactive"),
            ({"kind": "gossip"}, "kind of engagement"),
            ({"subject": ""}, "subject"),
        ]
        for extra, message in cases:
            with self.assertRaisesMessage(BadRequest, message):
                self._record(**extra)

    def test_a_linked_observation_must_be_one_the_author_reads_of_that_partner(self):
        linked = self._record(source_engagement_id=self.observation.id)
        self.assertEqual(linked.source_engagement_id, self.observation.id)
        # Shared with the Uganda lead, not with a second lead.
        with self.assertRaisesMessage(BadRequest, "Regional Lead observation"):
            self._record(self.other_pl, source_engagement_id=self.observation.id)
        with self.assertRaisesMessage(BadRequest, "Quiet Trainers delivered"):
            self._record(
                partner_id=self.no_login_partner.id,
                source_engagement_id=self.observation.id,
            )

    def test_only_the_author_changes_a_record_and_only_until_it_is_shared(self):
        engagement = self._record()
        with self.assertRaises(NotFoundError):
            services.update_engagement(self.other_pl, engagement.id, {"subject": "x"})
        with self.assertRaises(Forbidden):
            # The director reads it, and still may not change it.
            services.update_engagement(
                self.cd,
                engagement.id,
                {"partner_id": self.partner.id, "kind": "joint_planning"},
            )
        services.update_engagement(
            self.pl,
            engagement.id,
            {
                "kind": "joint_planning",
                "held_on": _today().isoformat(),
                "subject": "Joint planning for Term 3",
            },
        )
        engagement.refresh_from_db()
        self.assertEqual(engagement.subject, "Joint planning for Term 3")
        self.assertEqual(engagement.partner_id, self.partner.id)

        services.share_with_partner(self.pl, engagement.id)
        with self.assertRaisesMessage(BadRequest, "can no longer be changed"):
            services.update_engagement(
                self.pl,
                engagement.id,
                {
                    "kind": "joint_planning",
                    "held_on": _today().isoformat(),
                    "subject": "y",
                },
            )

    def test_closing_a_follow_up_takes_a_finding_from_the_author(self):
        engagement = self._record(follow_up_due=_today().isoformat())
        with self.assertRaises(NotFoundError):
            services.complete_follow_up(self.other_pl, engagement.id, "Done")
        with self.assertRaisesMessage(BadRequest, "follow-up found"):
            services.complete_follow_up(self.pl, engagement.id, "  ")
        services.complete_follow_up(self.pl, engagement.id, "Facilitators now model.")
        engagement.refresh_from_db()
        self.assertIsNotNone(engagement.follow_up_done_at)
        with self.assertRaisesMessage(BadRequest, "already closed"):
            services.complete_follow_up(self.pl, engagement.id, "Again")
        no_follow_up = self._record(agreed_improvements="")
        with self.assertRaisesMessage(BadRequest, "no follow-up"):
            services.complete_follow_up(self.pl, no_follow_up.id, "Nothing to close")

    def test_sharing_notifies_the_partner_login_and_needs_one(self):
        engagement = self._record()
        services.share_with_partner(self.pl, engagement.id)
        notice = Notification.objects.get(
            recipient_id=self.partner_login.id,
            source_event_type=services.EVENT_SHARED,
        )
        self.assertEqual(notice.target_route, f"/partners/{self.partner.id}")
        with self.assertRaisesMessage(BadRequest, "already shared"):
            services.share_with_partner(self.pl, engagement.id)

        quiet = self._record(partner_id=self.no_login_partner.id)
        with self.assertRaisesMessage(BadRequest, "no login"):
            services.share_with_partner(self.pl, quiet.id)
        with self.assertRaises(NotFoundError):
            services.share_with_partner(self.other_pl, quiet.id)


# ── Visibility ───────────────────────────────────────────────────────────────
class EngagementVisibilityTest(EngagementFixture):
    def test_each_role_reads_what_the_rules_give_it(self):
        uganda = self._record()
        second = self._record(self.other_pl)
        kenya = self._record(self.kenya_pl)
        shared = self._record(subject="Shared review")
        services.share_with_partner(self.pl, shared.id)

        def ids(user):
            return set(
                services.engagements_visible_to(user).values_list("id", flat=True)
            )

        self.assertEqual(ids(self.pl), {uganda.id, shared.id})
        self.assertEqual(ids(self.other_pl), {second.id})
        self.assertEqual(ids(self.cd), {uganda.id, second.id, shared.id})
        self.assertEqual(ids(self.kenya_cd), {kenya.id})
        self.assertEqual(ids(self.rpl), {uganda.id, second.id, shared.id})
        self.assertEqual(ids(self.admin), {uganda.id, second.id, kenya.id, shared.id})
        self.assertEqual(ids(self.partner_login), {shared.id})
        self.assertEqual(ids(self.cceo), set())


# ── Summary and the Regional Lead's observations ─────────────────────────────
class EngagementSummaryTest(EngagementFixture):
    def test_the_dashboard_summary_counts_the_readers_engagements(self):
        self._record(follow_up_due=_today().isoformat())
        self._record(partner_id=self.no_login_partner.id)
        self._record(self.other_pl)
        summary = services.engagement_summary(self.pl, self.fy)
        self.assertEqual(summary["recorded"], 2)
        self.assertEqual(summary["partners_engaged"], 2)
        self.assertEqual(summary["follow_ups_due"], 1)
        self.assertEqual(len(summary["latest"]), 2)
        self.assertEqual(
            set(summary["latest"][0]),
            {
                "id",
                "subject",
                "partner_id",
                "partner_name",
                "kind_label",
                "held_on",
                "follow_up",
                "follow_up_tone",
                "url",
            },
        )
        self.assertEqual(
            services.engagement_summary(self.cceo, self.fy),
            {"recorded": 0, "follow_ups_due": 0, "partners_engaged": 0, "latest": []},
        )

    def test_an_observation_stays_open_until_the_partner_is_engaged_after_it(self):
        self.assertEqual(
            [
                e["observation"].id
                for e in services.open_observation_follow_ups(self.pl)
            ],
            [self.observation.id],
        )
        # Nobody else is asked: it was shared with this Programme Lead only.
        self.assertEqual(services.open_observation_follow_ups(self.other_pl), [])
        self.assertEqual(services.open_observation_follow_ups(self.cd), [])

        # An engagement held before the observation does not answer it.
        self._record(held_on=(_today() - timedelta(days=20)).isoformat())
        self.assertEqual(len(services.open_observation_follow_ups(self.pl)), 1)
        # One held since does, whoever recorded it.
        self._record(self.cd, kind="quality_follow_up")
        self.assertEqual(services.open_observation_follow_ups(self.pl), [])

    def test_a_continue_recommendation_asks_for_nothing(self):
        RegionalEngagement.objects.filter(id=self.observation.id).update(
            recommendation="continue"
        )
        self.assertEqual(services.open_observation_follow_ups(self.pl), [])


# ── To-Dos ───────────────────────────────────────────────────────────────────
class EngagementTodoTest(EngagementFixture):
    def _ids(self, user, role):
        return {
            row["id"]: row for row in partner_engagement_todos(user, role, _today())
        }

    def test_follow_ups_come_due_and_leave_when_closed(self):
        later = self._record(follow_up_due=(_today() + timedelta(days=3)).isoformat())
        due = self._record(
            held_on=(_today() - timedelta(days=5)).isoformat(),
            follow_up_due=(_today() - timedelta(days=1)).isoformat(),
        )
        rows = self._ids(self.pl, "Program Lead")
        self.assertNotIn(f"pengage-followup-{later.id}", rows)
        row = rows[f"pengage-followup-{due.id}"]
        self.assertEqual(
            row["title"], "Follow up Bright Trainers on the agreed improvements"
        )
        self.assertEqual(row["category"], "Collaboration")
        self.assertEqual(row["status_key"], "overdue")
        self.assertEqual(
            row["action_url"],
            f"/partners/{self.partner.id}?engagement={due.id}&step=follow-up",
        )
        services.complete_follow_up(self.pl, due.id, "Done.")
        self.assertNotIn(
            f"pengage-followup-{due.id}", self._ids(self.pl, "Program Lead")
        )

    def test_the_director_gets_their_own_follow_ups_only(self):
        self._record(follow_up_due=_today().isoformat())
        mine = self._record(self.cd, follow_up_due=_today().isoformat())
        rows = self._ids(self.cd, "CountryDirector")
        self.assertEqual(set(rows), {f"pengage-followup-{mine.id}"})

    def test_the_observation_row_opens_the_record_drawer_with_it_linked(self):
        rows = self._ids(self.pl, "Program Lead")
        row = rows[f"pengage-observation-{self.observation.id}"]
        self.assertEqual(
            row["title"], "Follow up Bright Trainers on the Regional Lead's observation"
        )
        self.assertEqual(
            row["action_url"],
            f"/partners/{self.partner.id}?record=1&source={self.observation.id}",
        )
        self._record(source_engagement_id=self.observation.id)
        self.assertNotIn(
            f"pengage-observation-{self.observation.id}",
            self._ids(self.pl, "Program Lead"),
        )

    def test_an_acknowledged_flag_asks_to_be_resolved(self):
        flag = CdFlag.objects.create(
            raised_by_user_id=self.cd.id,
            raised_by_name=self.cd.name,
            assigned_to_user_id=self.pl.id,
            category="quality",
            note="Check the SSA gap",
            status="acknowledged",
        )
        row = self._ids(self.pl, "Program Lead")[f"cdflag-resolve-{flag.id}"]
        self.assertEqual(row["action_url"], f"/quality-checks?resolve={flag.id}")
        flag_services.update_flag(
            flag.id, {"action": "resolve", "note": "Fixed"}, self.pl
        )
        self.assertNotIn(
            f"cdflag-resolve-{flag.id}", self._ids(self.pl, "Program Lead")
        )

    def test_other_roles_get_nothing(self):
        self._record(follow_up_due=_today().isoformat())
        for user, role in ((self.cceo, "CCEO"), (self.rpl, "RegionalProgramLead")):
            self.assertEqual(partner_engagement_todos(user, role, _today()), [])


# ── Pages and drawers ────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class EngagementPagesTest(EngagementFixture):
    def test_partner_oversight_carries_the_log_for_the_programme_lead(self):
        # Held before the Regional Lead's observation, so it does not answer it.
        engagement = self._record(held_on=(_today() - timedelta(days=20)).isoformat())
        self.client.force_login(self.pl)
        response = self.client.get("/partner-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-partner-engagements")
        self.assertContains(response, "data-partner-engagement-new")
        # The title-bar action is a link that also works without HTMX.
        self.assertContains(response, 'href="/partner-oversight/?record=1"')
        self.assertContains(response, engagement.subject)
        self.assertContains(response, "Partner Follow-Ups Due")
        # The Regional Lead's observation waits on the partner.
        self.assertContains(response, "data-partner-engagement-observations")

    def test_the_officer_reads_partner_delivery_without_the_log(self):
        self._record()
        self.client.force_login(self.cceo)
        response = self.client.get("/partner-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-partner-engagements")

    def test_the_profile_shows_the_director_the_country_log(self):
        engagement = self._record(self.other_pl)
        self.client.force_login(self.cd)
        response = self.client.get(f"/partners/{self.partner.id}")
        self.assertContains(response, engagement.subject)
        self.assertContains(response, "Recorded by")

    def test_the_partner_reads_only_what_was_shared_with_it(self):
        hidden = self._record(subject="Internal review")
        shared = self._record(subject="Agreed with the partner")
        services.share_with_partner(self.pl, shared.id)
        self.client.force_login(self.partner_login)
        response = self.client.get(f"/partners/{self.partner.id}")
        self.assertContains(response, shared.subject)
        self.assertNotContains(response, hidden.subject)
        self.assertNotContains(response, "data-partner-engagement-new")

    def test_the_record_drawer_and_post(self):
        self.client.force_login(self.pl)
        drawer = self.client.get(
            f"/partner-engagements/new?partner={self.partner.id}&source={self.observation.id}"
        )
        self.assertContains(drawer, 'action="/partner-engagements/record"')
        self.assertContains(drawer, f'value="{self.observation.id}" selected')

        response = self.client.post(
            "/partner-engagements/record",
            {
                "partner_id": self.partner.id,
                "kind": "quality_follow_up",
                "held_on": _today().isoformat(),
                "subject": "Follow-up on the observation",
                "agreed_improvements": "Model the practice.",
                "follow_up_due": (_today() + timedelta(days=14)).isoformat(),
                "source_engagement_id": self.observation.id,
                "next": f"/partners/{self.partner.id}?record=1&source={self.observation.id}",
            },
        )
        self.assertRedirects(
            response, f"/partners/{self.partner.id}", fetch_redirect_response=False
        )
        self.assertTrue(
            PartnerEngagement.objects.filter(
                author_id=self.pl.id, source_engagement=self.observation
            ).exists()
        )

    def test_a_refused_record_says_why(self):
        self.client.force_login(self.pl)
        response = self.client.post(
            "/partner-engagements/record",
            {
                "partner_id": self.partner.id,
                "kind": "review_meeting",
                "held_on": (_today() + timedelta(days=2)).isoformat(),
                "subject": "Tomorrow",
                "next": "/partner-oversight/",
            },
            follow=True,
        )
        self.assertContains(response, "once it has happened")
        self.assertFalse(PartnerEngagement.objects.exists())

    def test_drawers_refuse_readers_who_may_not_act(self):
        engagement = self._record(follow_up_due=_today().isoformat())
        self.client.force_login(self.cceo)
        self.assertContains(
            self.client.get("/partner-engagements/new"), "Only a Programme Lead"
        )
        self.assertContains(
            self.client.get(f"/partner-engagements/{engagement.id}"),
            "not one you can open",
        )
        self.client.force_login(self.cd)
        follow_up = self.client.get(f"/partner-engagements/{engagement.id}/follow-up")
        self.assertContains(follow_up, "Only the person who recorded")
        self.assertNotContains(follow_up, 'action="/partner-engagements/')
        # The director reads the record, read-only.
        opened = self.client.get(f"/partner-engagements/{engagement.id}")
        self.assertContains(opened, engagement.agreed_improvements)
        self.assertNotContains(opened, "/update")
        response = self.client.post(
            f"/partner-engagements/{engagement.id}/follow-up/save",
            {"follow_up_note": "Not mine", "next": "/partner-oversight/"},
        )
        self.assertEqual(response.status_code, 302)
        engagement.refresh_from_db()
        self.assertIsNone(engagement.follow_up_done_at)

    def test_a_todo_link_opens_the_follow_up_drawer_on_the_profile(self):
        engagement = self._record(follow_up_due=_today().isoformat())
        self.client.force_login(self.pl)
        response = self.client.get(
            f"/partners/{self.partner.id}?engagement={engagement.id}&step=follow-up"
        )
        self.assertContains(
            response, f'hx-get="/partner-engagements/{engagement.id}/follow-up"'
        )
        # Another lead's link opens nothing.
        self.client.force_login(self.other_pl)
        response = self.client.get(
            f"/partners/{self.partner.id}?engagement={engagement.id}&step=follow-up"
        )
        self.assertNotContains(response, "data-partner-engagement-autoload")


# ── The Country Director's flag loop ─────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class FlagLoopTest(EngagementFixture):
    def _raise(self, assignee=None):
        return flag_services.raise_flag(
            {"assignedToUserId": (assignee or self.pl).id, "note": "SSA gap in Hope"},
            self.cd,
        )

    def test_the_director_picks_programme_leads_in_their_country(self):
        ids = {row["id"] for row in flag_services.program_leads(self.cd)}
        self.assertEqual(ids, {self.pl.id, self.other_pl.id})
        admin_ids = {row["id"] for row in flag_services.program_leads(self.admin)}
        self.assertIn(self.kenya_pl.id, admin_ids)
        with self.assertRaisesMessage(BadRequest, "in your country"):
            self._raise(self.kenya_pl)
        with self.assertRaisesMessage(BadRequest, "in your country"):
            self._raise(self.cceo)

    def test_acknowledging_tells_the_director_and_answers_the_raise_notice(self):
        flag = self._raise()
        raised = Notification.objects.get(
            recipient_id=self.pl.id, source_event_type="cd_flag_raised"
        )
        flag_services.update_flag(flag["id"], {"action": "acknowledge"}, self.pl)
        raised.refresh_from_db()
        self.assertIsNotNone(raised.resolved_at)
        told = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type="cd_flag_acknowledged"
        )
        self.assertEqual(told.target_route, "/quality-checks")
        with self.assertRaisesMessage(BadRequest, "already been acknowledged"):
            flag_services.update_flag(flag["id"], {"action": "acknowledge"}, self.pl)

    def test_resolving_needs_a_note_and_closes_the_loop(self):
        flag = self._raise()
        flag_services.update_flag(flag["id"], {"action": "acknowledge"}, self.pl)
        with self.assertRaisesMessage(BadRequest, "resolution note"):
            flag_services.update_flag(flag["id"], {"action": "resolve"}, self.pl)
        with self.assertRaises(NotFoundError):
            flag_services.update_flag(
                flag["id"], {"action": "resolve", "note": "x"}, self.other_pl
            )
        flag_services.update_flag(
            flag["id"], {"action": "resolve", "note": "Collected the SSA."}, self.pl
        )
        stored = CdFlag.objects.get(id=flag["id"])
        self.assertEqual(stored.status, "resolved")
        self.assertEqual(stored.resolution_note, "Collected the SSA.")
        resolved = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type="cd_flag_resolved"
        )
        self.assertEqual(resolved.target_route, "/quality-checks")
        self.assertIn("Collected the SSA.", resolved.body)
        acknowledged = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type="cd_flag_acknowledged"
        )
        self.assertIsNotNone(acknowledged.resolved_at)

    def test_the_page_resolves_through_a_drawer_and_shows_a_refusal(self):
        flag = self._raise()
        self.client.force_login(self.pl)
        drawer = self.client.get(
            f"/quality-checks?resolve={flag['id']}", headers={"HX-Request": "true"}
        )
        self.assertContains(drawer, 'name="note"')
        self.assertContains(drawer, "Resolution note")
        # A To-Do link opens the page with the drawer on load.
        page = self.client.get(f"/quality-checks?resolve={flag['id']}")
        self.assertContains(page, "data-flag-autoload")
        # An open flag's two actions are one Actions menu (owner, 2026-09-26).
        self.assertContains(
            page,
            '<button type="submit" class="row-menu__item" role="menuitem">'
            "Acknowledge</button>",
        )
        self.assertContains(
            page,
            'class="row-menu__item" role="menuitem" '
            f'hx-get="/quality-checks?resolve={flag["id"]}"',
        )

        refused = self.client.post(
            "/quality-checks",
            {"action": "resolve", "flag_id": flag["id"], "note": ""},
            follow=True,
        )
        self.assertContains(refused, "resolution note")
        self.assertEqual(CdFlag.objects.get(id=flag["id"]).status, "open")

        done = self.client.post(
            "/quality-checks",
            {"action": "resolve", "flag_id": flag["id"], "note": "Done and checked."},
            follow=True,
        )
        self.assertContains(done, "Done and checked.")
        self.assertEqual(CdFlag.objects.get(id=flag["id"]).status, "resolved")

    def test_another_lead_gets_no_resolve_form(self):
        flag = self._raise()
        self.client.force_login(self.other_pl)
        drawer = self.client.get(
            f"/quality-checks?resolve={flag['id']}", headers={"HX-Request": "true"}
        )
        self.assertNotContains(drawer, 'name="note"')
        self.client.post(
            "/quality-checks",
            {"action": "resolve", "flag_id": flag["id"], "note": "Not mine"},
        )
        self.assertEqual(CdFlag.objects.get(id=flag["id"]).status, "open")

    def test_the_events_route_to_pages_the_recipients_open(self):
        for event in ("cd_flag_acknowledged", "cd_flag_resolved"):
            route, _label = NotificationLinkResolver.resolve(
                event, "CdFlag", "f1", "CountryDirector"
            )
            self.assertEqual(route, "/quality-checks")
        route, _label = NotificationLinkResolver.resolve(
            "partner_engagement_shared", "Partner", "p1", "PartnerAdmin"
        )
        self.assertEqual(route, "/partners/p1")


# ── Partner-delivery escalation ──────────────────────────────────────────────
class PartnerEscalationTest(EngagementFixture):
    def _item(self):
        from apps.planning import partner_oversight_service as svc

        assignment = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo_sp.id,
            monitoring_staff_id=self.cceo_sp.id,
            expected_activity_type="school_visit",
            status="assigned",
        )
        return svc.build_item_by_assignment(assignment.id)

    def test_it_reaches_the_leads_own_director_on_the_escalation_board(self):
        from apps.flags import escalation_service
        from apps.planning import partner_oversight_actions as actions
        from apps.planning.action_service import ActionError
        from apps.planning.models import TeamAction

        StaffSupervisorAssignment.objects.create(
            supervisor=self.cd_sp, supervisee=self.pl_sp
        )
        item = self._item()
        escalation = actions.escalate_to_country_director(
            sender=self.pl, item=item, note="Called twice; no date."
        )
        self.assertIsInstance(escalation, LeadershipEscalation)
        self.assertEqual(escalation.addressed_role, "CD")
        self.assertEqual(escalation.assigned_to_user_id, self.cd.id)
        self.assertEqual(escalation.category, "partner_performance")
        self.assertIn("Called twice", escalation.detail)
        self.assertFalse(TeamAction.objects.exists())
        board = escalation_service.board(self.cd)
        self.assertIn(escalation.id, {row["id"] for row in board["inbox"]})
        self.assertEqual(escalation_service.board(self.kenya_cd)["inbox"], [])
        with self.assertRaisesMessage(ActionError, "Already escalated"):
            actions.escalate_to_country_director(
                sender=self.pl, item=item, note="Again."
            )
        self.assertEqual(
            actions.escalation_addressee_label(self.pl),
            "Uganda Director (Country Director)",
        )

    def test_without_a_reporting_line_it_goes_to_the_director_role_in_country(self):
        from apps.planning import partner_oversight_actions as actions

        escalation = actions.escalate_to_country_director(
            sender=self.pl, item=self._item(), note="No date after two calls."
        )
        self.assertIsNone(escalation.assigned_to_user_id)
        self.assertEqual(escalation.country_id, "Uganda")
        notified = set(
            Notification.objects.filter(
                source_event_type="leadership_escalation_open"
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(notified, {self.cd.id})

    def test_the_send_view_reports_the_escalation(self):
        item = self._item()
        self.client.force_login(self.pl)
        response = self.client.post(
            "/partner-oversight/send",
            {
                "intent": "escalate",
                "assignment_id": item.partner_assignment_id,
                "note": "Tried twice.",
            },
            headers={"HX-Request": "true"},
        )
        self.assertContains(response, "Escalated to the Country Director")
        self.assertTrue(LeadershipEscalation.objects.exists())


# ── Messaging contexts ───────────────────────────────────────────────────────
class MessagingScopeTest(EngagementFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import Leave
        from apps.clusters.models import Cluster
        from apps.fund_requests.models import WeeklyFundRequest

        cls.cluster = Cluster.objects.create(
            name="Hope Cluster", region=cls.region, district=cls.district
        )
        cls.cluster_assignment = PartnerAssignment.objects.create(
            cluster=cls.cluster,
            partner=cls.partner,
            assigning_staff_id=cls.cceo_sp.id,
            monitoring_staff_id=cls.cceo_sp.id,
            status="assigned",
        )
        cls.other_assignment = PartnerAssignment.objects.create(
            school=cls.school,
            partner=cls.partner,
            assigning_staff_id=cls.other_cceo_sp.id,
            monitoring_staff_id=cls.other_cceo_sp.id,
            status="assigned",
        )
        cls.team_leave = Leave.objects.create(
            staff=cls.cceo_sp,
            type="annual_leave",
            start_date="2026-10-01",
            end_date="2026-10-03",
            days=3,
        )
        cls.other_leave = Leave.objects.create(
            staff=cls.other_cceo_sp,
            type="annual_leave",
            start_date="2026-10-01",
            end_date="2026-10-03",
            days=3,
        )
        week = date(2026, 9, 14)
        cls.team_request = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=week,
            week_end_date=week + timedelta(days=6),
            responsible_user=cls.cceo.id,
            status="submitted_to_pl",
        )
        cls.other_request = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=week,
            week_end_date=week + timedelta(days=6),
            responsible_user=cls.other_cceo.id,
            status="submitted_to_pl",
        )

    def test_a_cluster_assignment_is_labelled_by_its_cluster(self):
        from apps.messaging import services as messaging

        _record, label = messaging.resolve_context_record(
            "partner_assignment", self.cluster_assignment.id
        )
        self.assertEqual(label, "Bright Trainers — Hope Cluster (cluster)")
        titles = [
            row["title"]
            for row in messaging.search_context_records(self.pl, "partner_assignment")
        ]
        self.assertIn("Bright Trainers — Hope Cluster (cluster)", titles)

    def test_partner_assignments_stay_inside_the_oversight_scope(self):
        from apps.messaging import services as messaging

        check = messaging.can_access_context
        self.assertTrue(
            check(self.pl, "partner_assignment", self.cluster_assignment.id)
        )
        self.assertTrue(
            check(self.cceo, "partner_assignment", self.cluster_assignment.id)
        )
        self.assertFalse(check(self.pl, "partner_assignment", self.other_assignment.id))
        self.assertFalse(
            check(self.cceo, "partner_assignment", self.other_assignment.id)
        )
        self.assertTrue(
            check(self.other_pl, "partner_assignment", self.other_assignment.id)
        )
        self.assertTrue(check(self.cd, "partner_assignment", self.other_assignment.id))
        picker = {
            row["id"]
            for row in messaging.search_context_records(self.pl, "partner_assignment")
        }
        self.assertIn(self.cluster_assignment.id, picker)
        self.assertNotIn(self.other_assignment.id, picker)

    def test_leave_and_weekly_requests_stay_inside_the_team(self):
        from apps.messaging import services as messaging

        check = messaging.can_access_context
        self.assertTrue(check(self.pl, "leave", self.team_leave.id))
        self.assertFalse(check(self.pl, "leave", self.other_leave.id))
        self.assertTrue(check(self.cd, "leave", self.other_leave.id))
        self.assertTrue(check(self.pl, "fund_request", self.team_request.id))
        self.assertFalse(check(self.pl, "fund_request", self.other_request.id))
        self.assertTrue(check(self.cceo, "fund_request", self.team_request.id))
        self.assertFalse(check(self.cceo, "fund_request", self.other_request.id))
        picker = {
            row["id"]
            for row in messaging.search_context_records(self.pl, "fund_request")
        }
        self.assertEqual(picker, {self.team_request.id})


# ── Query cost ───────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class EngagementQueryBudgetTest(EngagementFixture):
    """Fixed cost whatever the number of engagements. Measured against a
    cache this process owns, because dev test runs share a real Redis."""

    def _grow(self, count):
        for index in range(count):
            engagement = self._record(
                subject=f"Review {index}",
                follow_up_due=_today().isoformat(),
            )
            self._record(self.cd, subject=f"Director review {index}")
            if index % 2:
                services.share_with_partner(self.pl, engagement.id)

    def test_the_register_does_not_grow_with_its_rows(self):
        from django.test import RequestFactory

        from apps.frontend.views.partner_engagement_views import engagement_register

        def measure(user):
            request = RequestFactory().get("/partner-oversight/")
            request.user = user
            engagement_register(request, fy=self.fy)
            with CaptureQueriesContext(connection) as ctx:
                context = engagement_register(request, fy=self.fy)
            return len(ctx), len(context["rows"])

        self._grow(2)
        small, small_rows = measure(self.cd)
        small_pl, _ = measure(self.pl)
        self._grow(6)
        large, large_rows = measure(self.cd)
        large_pl, _ = measure(self.pl)
        self.assertGreater(large_rows, small_rows)
        self.assertEqual(large, small)
        self.assertEqual(large_pl, small_pl)
        self.assertLessEqual(large_pl, 12)

    def test_the_partner_oversight_page_does_not_grow_with_engagements(self):
        def measure():
            self.client.force_login(self.pl)
            self.client.get("/partner-oversight/")
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get("/partner-oversight/")
            self.assertEqual(response.status_code, 200)
            return len(ctx)

        self._grow(2)
        small = measure()
        self._grow(6)
        self.assertLessEqual(measure(), small)

    def test_the_flag_register_does_not_grow_with_its_flags(self):
        """The assignee's name is read once for the page, not once per row."""

        def raise_some(count):
            for index in range(count):
                flag_services.raise_flag(
                    {
                        "assignedToUserId": (self.pl, self.other_pl)[index % 2].id,
                        "note": f"Flag {index}",
                    },
                    self.cd,
                )

        def measure():
            self.client.force_login(self.cd)
            self.client.get("/quality-checks")
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get("/quality-checks")
            self.assertEqual(response.status_code, 200)
            return len(ctx), response

        raise_some(2)
        small, _ = measure()
        raise_some(6)
        large, response = measure()
        self.assertContains(response, "Second Lead")
        self.assertEqual(response.content.decode().count("data-flag-row="), 8)
        self.assertLessEqual(large, small)

    def test_the_todos_do_not_grow_with_records(self):
        def measure():
            partner_engagement_todos(self.pl, "Program Lead", _today())
            with CaptureQueriesContext(connection) as ctx:
                rows = partner_engagement_todos(self.pl, "Program Lead", _today())
            return len(ctx), rows

        self._grow(2)
        small, small_rows = measure()
        self._grow(5)
        large, large_rows = measure()
        self.assertGreater(len(large_rows), len(small_rows))
        self.assertEqual(large, small)
        self.assertLessEqual(large, 10)
