"""Coaching, one level down and one level up (owner, 2026-09-13).

The Programme Lead's role description: "line-management, supervision,
leadership, and support to CCEOs", "professional coaching for assigned
CCEOs", and "partner with regional leads … to align goals and build
capacity". These tests hold the rules for the coaching a lead writes for
their officers (who writes, who reads, the share → acknowledge → follow-up
handoff, the monthly one-to-one), the coaching the Regional Lead shares with
a Programme Lead, training feedback passed on to the officer who delivered the
training, the pages and drawers, the To-Dos, and what each costs in queries.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.notifications.models import Notification

from . import coaching, services
from .models import CceoCoaching, CoachingKind, EngagementKind
from .tests import CceFixture, _person, _ratings
from .todos import coaching_todos

TODAY = timezone.localdate()
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "cce-coaching-tests",
    }
}


class CoachingFixture(CceFixture):
    """The Regional Lead fixture plus a second officer on the Uganda lead's
    team, a second Uganda lead with an officer of their own, a Kenya lead with
    a Kenya officer, a Kenya director, Admin, a partner-delivered training and
    a field debrief."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.debriefs.models import DailyDebrief
        from apps.partners.models import Partner

        cls.cceo2, cls.cceo2_sp = _person("cce-cceo2", "Second Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo2_sp
        )
        cls.other_pl, cls.other_pl_sp = _person("cce-pl2", "Other Lead", "Program Lead")
        cls.other_cceo, cls.other_cceo_sp = _person(
            "cce-cceo3", "Other Officer", "CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.other_pl_sp, supervisee=cls.other_cceo_sp
        )
        cls.kenya_cceo, cls.kenya_cceo_sp = _person(
            "cce-kcceo", "Kenya Officer", "CCEO", country="Kenya"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.kenya_pl_sp, supervisee=cls.kenya_cceo_sp
        )
        cls.kenya_cd, cls.kenya_cd_sp = _person(
            "cce-kcd", "Kenya Director", "CountryDirector", country="Kenya"
        )
        cls.admin, _admin_sp = _person("cce-admin", "Platform Admin", "Admin")

        cls.partner = Partner.objects.create(name="Grace Trainers")
        day = TODAY - timedelta(days=2)
        cls.partner_training = Activity.objects.create(
            activity_type="training",
            school=cls.school,
            fy="2026",
            quarter="Q4",
            delivery_type="partner",
            assigned_partner_id=cls.partner.id,
            monitored_by_staff_id=cls.cceo_sp.id,
            status="completed",
            planned_date=day,
            scheduled_date=timezone.now() - timedelta(days=2),
        )
        cls.other_training = Activity.objects.create(
            activity_type="training",
            school=cls.school,
            fy="2026",
            quarter="Q4",
            delivery_type="staff",
            responsible_staff_id=cls.other_cceo.id,
            status="completed",
            planned_date=day,
            scheduled_date=timezone.now() - timedelta(days=2),
        )
        cls.debrief = DailyDebrief.objects.create(
            fy="2026",
            date=timezone.now() - timedelta(days=1),
            submitted_at=timezone.now() - timedelta(days=1),
            submitted_by_user_id=cls.cceo.id,
            submitted_by_role="CCEO",
            staff_id=cls.cceo_sp.id,
            debrief_type="staff",
            kind="activity",
            status="submitted",
            title="Leadership training day",
        )
        cls.other_debrief = DailyDebrief.objects.create(
            fy="2026",
            date=timezone.now() - timedelta(days=1),
            submitted_at=timezone.now() - timedelta(days=1),
            submitted_by_user_id=cls.cceo2.id,
            submitted_by_role="CCEO",
            staff_id=cls.cceo2_sp.id,
            debrief_type="staff",
            kind="activity",
            status="submitted",
            title="Visit day",
        )

    def _coach(self, lead=None, officer=None, **extra):
        return coaching.record_coaching(
            lead or self.pl,
            {
                "cceo_staff_id": (officer or self.cceo_sp).id,
                "kind": CoachingKind.ONE_TO_ONE,
                "held_on": TODAY.isoformat(),
                "strengths": "Clear lesson modelling.",
                "agreed_actions": "Plan two follow-up visits.",
                **extra,
            },
        )

    def _visible(self, principal, record):
        return coaching.coaching_visible_to(principal).filter(id=record.id).exists()


# ── Rules ────────────────────────────────────────────────────────────────────
class CoachingRulesTest(CoachingFixture):
    def test_the_lead_records_coaching_for_an_officer_on_their_team(self):
        record = self._coach()
        self.assertEqual(record.author_id, self.pl.id)
        self.assertEqual(record.cceo_staff_id, self.cceo_sp.id)
        self.assertEqual(record.cceo_user_id, self.cceo.id)
        self.assertEqual(record.country, "Uganda")
        self.assertIn("Uganda Officer", record.subject)
        self.assertIsNone(record.shared_at, "a new record is a draft")
        # The officer may be named by their User id too.
        by_user = self._coach(officer=self.cceo, cceo_staff_id=self.cceo.id)
        self.assertEqual(by_user.cceo_staff_id, self.cceo_sp.id)

    def test_it_refuses_an_officer_off_the_team_a_future_date_and_an_empty_note(self):
        with self.assertRaisesMessage(BadRequest, "on your team"):
            self._coach(cceo_staff_id=self.other_cceo_sp.id)
        with self.assertRaisesMessage(BadRequest, "once it has happened"):
            self._coach(held_on=(TODAY + timedelta(days=1)).isoformat())
        with self.assertRaisesMessage(BadRequest, "what the coaching covered"):
            self._coach(strengths="", agreed_actions="")
        with self.assertRaisesMessage(BadRequest, "cannot be before"):
            self._coach(follow_up_due=(TODAY - timedelta(days=3)).isoformat())
        with self.assertRaisesMessage(BadRequest, "actions agreed before"):
            self._coach(agreed_actions="", follow_up_due=TODAY.isoformat())
        with self.assertRaisesMessage(BadRequest, "what kind"):
            self._coach(kind=CoachingKind.REGIONAL_FEEDBACK)

    def test_only_the_programme_lead_records_coaching(self):
        for person in (self.cceo, self.cd, self.lead, self.admin):
            with self.subTest(role=person.active_role):
                with self.assertRaises(Forbidden):
                    self._coach(lead=person)

    def test_an_observation_takes_the_five_ratings_and_the_activity_watched(self):
        observation = {
            "kind": CoachingKind.TRAINING_OBSERVATION,
            **_ratings(3),
        }
        with self.assertRaisesMessage(BadRequest, "Choose the training"):
            self._coach(**observation)
        with self.assertRaisesMessage(BadRequest, "from 1 to 4"):
            self._coach(
                **{**observation, "rating_facilitation": 5},
                activity_id=self.training.id,
            )
        with self.assertRaisesMessage(BadRequest, "delivered or monitored"):
            self._coach(**observation, activity_id=self.other_training.id)
        record = self._coach(**observation, activity_id=self.training.id)
        self.assertEqual(record.average_rating, 3.0)
        # A partner training the officer monitored counts as theirs.
        monitored = self._coach(**observation, activity_id=self.partner_training.id)
        self.assertEqual(monitored.activity_id, self.partner_training.id)
        one_to_one = self._coach(**_ratings(4))
        self.assertEqual(one_to_one.ratings, [], "only observations are rated")

    def test_a_debrief_it_answers_must_be_the_officers_own(self):
        with self.assertRaisesMessage(BadRequest, "this officer submitted"):
            self._coach(
                kind=CoachingKind.DEBRIEF_FEEDBACK, debrief_id=self.other_debrief.id
            )
        record = self._coach(
            kind=CoachingKind.DEBRIEF_FEEDBACK, debrief_id=self.debrief.id
        )
        self.assertEqual(record.debrief_id, self.debrief.id)


# ── Visibility ───────────────────────────────────────────────────────────────
class CoachingVisibilityTest(CoachingFixture):
    def test_drafts_stay_with_the_author_and_shared_coaching_reaches_its_readers(self):
        record = self._coach()
        self.assertTrue(self._visible(self.pl, record))
        self.assertTrue(self._visible(self.admin, record))
        for person in (self.cceo, self.cd, self.lead, self.other_pl):
            with self.subTest(draft_hidden_from=person.name):
                self.assertFalse(self._visible(person, record))

        coaching.share_coaching(self.pl, record.id)
        for person in (self.pl, self.cceo, self.cd, self.lead, self.admin):
            with self.subTest(shared_reaches=person.name):
                self.assertTrue(self._visible(person, record))
        for person in (
            self.cceo2,
            self.other_pl,
            self.kenya_cd,
            self.kenya_pl,
            self.rvp,
        ):
            with self.subTest(shared_hidden_from=person.name):
                self.assertFalse(self._visible(person, record))

    def test_a_lead_stops_reading_an_officer_who_left_their_team(self):
        record = self._coach()
        StaffSupervisorAssignment.objects.filter(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        ).delete()
        self.assertFalse(self._visible(self.pl, record))
        with self.assertRaises(NotFoundError):
            coaching.share_coaching(self.pl, record.id)

    def test_the_regional_lead_reads_only_the_countries_of_their_region(self):
        kenya = coaching.record_coaching(
            self.kenya_pl,
            {
                "cceo_staff_id": self.kenya_cceo_sp.id,
                "kind": CoachingKind.RECOGNITION,
                "held_on": TODAY.isoformat(),
                "strengths": "Brilliant cluster meeting.",
            },
        )
        coaching.share_coaching(self.kenya_pl, kenya.id)
        self.assertFalse(self._visible(self.lead, kenya))
        self.assertTrue(self._visible(self.kenya_cd, kenya))
        self.assertFalse(self._visible(self.cd, kenya))


# ── Handoffs ─────────────────────────────────────────────────────────────────
class CoachingHandoffTest(CoachingFixture):
    def test_share_notifies_the_officer_and_acknowledgement_notifies_the_lead(self):
        record = self._coach()
        coaching.share_coaching(self.pl, record.id)
        notice = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type="cceo_coaching_shared"
        )
        self.assertEqual(notice.target_route, "/my-coaching")
        with self.assertRaisesMessage(BadRequest, "already shared"):
            coaching.share_coaching(self.pl, record.id)

        with self.assertRaisesMessage(BadRequest, "what you will do"):
            coaching.acknowledge_coaching(self.cceo, record.id, "  ")
        with self.assertRaises(NotFoundError):
            coaching.acknowledge_coaching(self.cceo2, record.id, "Not mine")
        with self.assertRaises(Forbidden):
            coaching.acknowledge_coaching(self.pl, record.id, "On their behalf")

        coaching.acknowledge_coaching(self.cceo, record.id, "I will plan the visits.")
        record.refresh_from_db()
        self.assertEqual(record.cceo_response, "I will plan the visits.")
        back = Notification.objects.get(
            recipient_id=self.pl.id, source_event_type="cceo_coaching_acknowledged"
        )
        self.assertEqual(back.target_route, "/team/coaching")
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at, "the ask is closed once answered")

        with self.assertRaisesMessage(BadRequest, "already acknowledged"):
            coaching.acknowledge_coaching(self.cceo, record.id, "Again")
        with self.assertRaisesMessage(Forbidden, "can no longer be changed"):
            coaching.update_coaching(
                self.pl,
                record.id,
                {"held_on": TODAY.isoformat(), "strengths": "Rewritten"},
            )

    def test_a_shared_record_can_be_corrected_until_acknowledged_and_says_so(self):
        record = self._coach()
        coaching.share_coaching(self.pl, record.id)
        Notification.objects.filter(recipient_id=self.cceo.id).update(status="read")
        coaching.update_coaching(
            self.pl,
            record.id,
            {
                "held_on": TODAY.isoformat(),
                "strengths": "Clear modelling and pacing.",
                "agreed_actions": "Plan two follow-up visits.",
            },
        )
        record.refresh_from_db()
        self.assertEqual(record.strengths, "Clear modelling and pacing.")
        notice = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type="cceo_coaching_shared"
        )
        self.assertEqual(notice.status, "unread", "the officer is told it changed")

    def test_only_the_author_changes_shares_or_follows_up(self):
        record = self._coach(follow_up_due=TODAY.isoformat())
        # A second lead who also supervises the officer still cannot touch it.
        StaffSupervisorAssignment.objects.create(
            supervisor=self.other_pl_sp, supervisee=self.cceo_sp
        )
        for action in (
            lambda: coaching.share_coaching(self.other_pl, record.id),
            lambda: coaching.complete_follow_up(self.other_pl, record.id, "Done"),
            lambda: coaching.update_coaching(
                self.other_pl, record.id, {"held_on": TODAY.isoformat()}
            ),
        ):
            with self.assertRaises(NotFoundError):
                action()
        with self.assertRaises(Forbidden):
            coaching.complete_follow_up(self.cd, record.id, "Done")

    def test_a_follow_up_needs_a_date_and_a_note_and_closes_once(self):
        no_date = self._coach()
        with self.assertRaisesMessage(BadRequest, "no follow-up date"):
            coaching.complete_follow_up(self.pl, no_date.id, "Checked")
        record = self._coach(follow_up_due=TODAY.isoformat())
        with self.assertRaisesMessage(BadRequest, "what you found"):
            coaching.complete_follow_up(self.pl, record.id, "")
        coaching.complete_follow_up(self.pl, record.id, "Both visits planned.")
        record.refresh_from_db()
        self.assertIsNotNone(record.follow_up_done_at)
        with self.assertRaisesMessage(BadRequest, "already closed"):
            coaching.complete_follow_up(self.pl, record.id, "Again")


# ── Cadence and the interfaces other pages read ──────────────────────────────
class CadenceAndSummaryTest(CoachingFixture):
    def _raw(self, officer_sp, officer, **fields):
        return CceoCoaching.objects.create(
            author_id=self.pl.id,
            cceo_staff_id=officer_sp.id,
            cceo_user_id=officer.id,
            fy="2026",
            country="Uganda",
            subject="Coaching",
            **{"kind": CoachingKind.ONE_TO_ONE, **fields},
        )

    def test_the_one_to_one_is_due_from_the_tenth_until_one_is_held_this_month(self):
        before = coaching.monthly_one_to_ones(self.pl, today=date(2026, 9, 5))
        self.assertEqual({r["state"] for r in before["rows"]}, {"not_yet"})
        self.assertEqual(before["due"], 0)

        self._raw(self.cceo_sp, self.cceo, held_on=date(2026, 9, 8))
        self._raw(self.cceo2_sp, self.cceo2, held_on=date(2026, 8, 28))
        self._raw(
            self.cceo2_sp,
            self.cceo2,
            held_on=date(2026, 9, 9),
            kind=CoachingKind.RECOGNITION,
        )
        month = coaching.monthly_one_to_ones(self.pl, today=date(2026, 9, 12))
        states = {r["staff_id"]: r["state"] for r in month["rows"]}
        self.assertEqual(states[self.cceo_sp.id], "held")
        self.assertEqual(
            states[self.cceo2_sp.id],
            "due",
            "last month's one-to-one and this month's recognition do not count",
        )
        self.assertEqual((month["held"], month["due"]), (1, 1))

    def test_last_coaching_by_cceo_and_the_summary(self):
        old = self._raw(
            self.cceo_sp,
            self.cceo,
            held_on=TODAY - timedelta(days=20),
            follow_up_due=TODAY - timedelta(days=1),
        )
        self._raw(
            self.cceo_sp,
            self.cceo,
            held_on=TODAY - timedelta(days=2),
            kind=CoachingKind.FIELD_OBSERVATION,
            shared_at=timezone.now(),
        )
        last = coaching.last_coaching_by_cceo(
            self.pl, [self.cceo_sp.id, self.cceo2_sp.id, self.other_cceo_sp.id]
        )
        self.assertEqual(set(last), {self.cceo_sp.id}, "never coached is absent")
        entry = last[self.cceo_sp.id]
        self.assertEqual(entry["kind"], CoachingKind.FIELD_OBSERVATION)
        self.assertEqual(entry["kind_label"], "School visit observation")
        self.assertTrue(entry["shared"])
        self.assertFalse(entry["acknowledged"])
        self.assertTrue(entry["open_follow_up"], "the older record's follow-up is open")
        self.assertEqual(
            set(entry),
            {
                "held_on",
                "kind",
                "kind_label",
                "shared",
                "acknowledged",
                "open_follow_up",
            },
        )
        # The director reads only shared coaching; the other lead none of it.
        self.assertEqual(
            coaching.last_coaching_by_cceo(self.cd, [self.cceo_sp.id])[self.cceo_sp.id][
                "open_follow_up"
            ],
            False,
        )
        self.assertEqual(
            coaching.last_coaching_by_cceo(self.other_pl, [self.cceo_sp.id]), {}
        )

        summary = coaching.coaching_summary(self.pl, today=TODAY)
        self.assertEqual(summary["team_size"], 2)
        self.assertEqual(summary["drafts"], 1)
        self.assertEqual(summary["awaiting_acknowledgement"], 1)
        self.assertEqual(summary["follow_ups_due"], 1)
        self.assertLessEqual(
            {
                "team_size",
                "coached_this_month",
                "awaiting_acknowledgement",
                "follow_ups_due",
                "drafts",
            },
            set(summary),
        )
        old.follow_up_done_at = timezone.now()
        old.save()
        self.assertEqual(coaching.coaching_summary(self.pl)["follow_ups_due"], 0)


# ── Regional Lead feedback, passed on ────────────────────────────────────────
class FeedbackPassOnTest(CoachingFixture):
    def _shared_observation(self, activity=None):
        observation = self._observe(
            **({"activity_id": activity.id} if activity else {})
        )
        if not observation.program_lead_ids:
            observation.program_lead_ids = [self.pl_sp.id]
            observation.save()
        services.share_feedback(self.lead, observation.id)
        return observation

    def test_acknowledged_feedback_is_passed_to_the_officer_who_delivered_it(self):
        observation = self._shared_observation()
        with self.assertRaisesMessage(BadRequest, "Acknowledge the Regional Lead"):
            coaching.pass_feedback_to_cceo(self.pl, observation.id)
        services.acknowledge_feedback(self.pl, observation.id, "Trainers model first.")

        record = coaching.pass_feedback_to_cceo(self.pl, observation.id)
        self.assertEqual(record.kind, CoachingKind.REGIONAL_FEEDBACK)
        self.assertEqual(record.cceo_staff_id, self.cceo_sp.id)
        self.assertEqual(record.source_engagement_id, observation.id)
        self.assertEqual(record.ratings, [3, 3, 3, 3, 3])
        self.assertEqual(record.agreed_actions, "Trainers model first.")
        self.assertIn("Model the lesson", record.growth_areas)
        self.assertIsNotNone(record.shared_at, "passed on means shared")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo.id, source_event_type="cceo_coaching_shared"
            ).exists()
        )
        with self.assertRaisesMessage(BadRequest, "already passed"):
            coaching.pass_feedback_to_cceo(self.pl, observation.id)
        self.assertEqual(
            coaching.passed_engagement_ids([observation.id]), {observation.id}
        )

    def test_partner_delivered_feedback_has_no_officer_to_pass_to(self):
        observation = self._shared_observation(self.partner_training)
        services.acknowledge_feedback(self.pl, observation.id, "Raise it with them.")
        with self.assertRaisesMessage(BadRequest, "not delivered by an officer"):
            coaching.pass_feedback_to_cceo(self.pl, observation.id)
        with self.assertRaises(Forbidden):
            coaching.pass_feedback_to_cceo(self.cd, observation.id)

    def test_a_refused_pass_on_leaves_the_feedback_unacknowledged(self):
        observation = self._shared_observation(self.partner_training)
        self.client.force_login(self.pl)
        self.client.post(
            f"/cce-leadership/feedback/{observation.id}/acknowledge",
            {"response": "Raise it with them.", "pass_to_cceo": "1"},
        )
        observation.refresh_from_db()
        self.assertIsNone(observation.acknowledged_at)

    def test_the_drawer_offers_the_pass_on_and_the_register_names_who_delivered(self):
        staff = self._shared_observation()
        partner = self._shared_observation(self.partner_training)
        self.client.force_login(self.pl)
        drawer = self.client.get(f"/cce-leadership/feedback/{staff.id}")
        self.assertContains(drawer, "Pass this feedback to Uganda Officer")
        partner_drawer = self.client.get(f"/cce-leadership/feedback/{partner.id}")
        self.assertNotContains(partner_drawer, "Pass this feedback")

        self.client.post(
            f"/cce-leadership/feedback/{staff.id}/acknowledge",
            {"response": "Model first.", "pass_to_cceo": "1"},
        )
        self.assertTrue(CceoCoaching.objects.filter(source_engagement=staff).exists())

        page = self.client.get("/cce-leadership/feedback")
        self.assertContains(page, "Delivered by")
        self.assertContains(page, "Grace Trainers · partner")
        self.assertContains(page, f'href="/activities/{staff.activity_id}"')
        self.assertContains(page, "passed to the officer")
        self.assertNotContains(page, '<th scope="col">Country</th>', html=False)
        self.assertContains(page, "Regional Lead Coaching", msg_prefix="the tab rail")

        self.client.force_login(self.cd)
        director = self.client.get("/cce-leadership/feedback")
        self.assertContains(director, '<th scope="col">Country</th>', html=False)
        self.assertNotContains(director, "Open training")

    def test_acknowledged_feedback_can_still_be_passed_on_later(self):
        observation = self._shared_observation()
        services.acknowledge_feedback(self.pl, observation.id, "Model first.")
        self.client.force_login(self.pl)
        drawer = self.client.get(f"/cce-leadership/feedback/{observation.id}")
        self.assertContains(drawer, "Pass to Uganda Officer")
        self.client.post(f"/cce-leadership/feedback/{observation.id}/pass", {})
        self.assertEqual(
            CceoCoaching.objects.filter(source_engagement=observation).count(), 1
        )


# ── Regional Lead coaching to the Programme Lead ─────────────────────────────
class RegionalLeadCoachingTest(CoachingFixture):
    def _conversation(self, **extra):
        return services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "notes": "Reviewed the team's coaching rhythm.",
                "agreed_actions": "Hold every one-to-one by the tenth.",
                **extra,
            },
        )

    def test_the_regional_lead_shares_coaching_and_the_programme_lead_answers(self):
        conversation = self._conversation()
        self.assertFalse(
            services.regional_coaching_visible_to(self.pl).exists(),
            "notes stay private",
        )
        services.share_feedback(self.lead, conversation.id)
        notice = Notification.objects.get(
            recipient_id=self.pl.id, source_event_type="cce_pl_coaching_shared"
        )
        self.assertEqual(notice.target_route, "/cce-leadership/coaching")
        self.assertTrue(
            services.regional_coaching_visible_to(self.pl)
            .filter(id=conversation.id)
            .exists()
        )
        for person in (self.cd, self.kenya_pl, self.other_pl, self.cceo):
            with self.subTest(hidden_from=person.name):
                self.assertFalse(services.regional_coaching_visible_to(person).exists())
        self.assertFalse(
            services.feedback_visible_to(self.pl).filter(id=conversation.id).exists(),
            "training feedback stays training observations only",
        )

        with self.assertRaisesMessage(BadRequest, "actions agreed"):
            services.acknowledge_regional_coaching(self.pl, conversation.id, "")
        with self.assertRaises(Forbidden):
            services.acknowledge_regional_coaching(self.cd, conversation.id, "Noted")
        with self.assertRaises(NotFoundError):
            services.acknowledge_regional_coaching(self.kenya_pl, conversation.id, "Hm")

        services.acknowledge_regional_coaching(
            self.pl, conversation.id, "All one-to-ones by the tenth from October."
        )
        back = Notification.objects.get(
            recipient_id=self.lead.id, source_event_type="cce_pl_coaching_acknowledged"
        )
        self.assertEqual(back.target_route, "/cce-leadership/engagements")
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        with self.assertRaisesMessage(BadRequest, "already acknowledged"):
            services.acknowledge_regional_coaching(self.pl, conversation.id, "Again")
        with self.assertRaisesMessage(Forbidden, "can no longer be changed"):
            services.update_engagement(
                self.lead, conversation.id, {"held_on": TODAY.isoformat()}
            )

    def test_only_coaching_and_observations_are_shared(self):
        meeting = services.record_engagement(
            self.lead,
            {"kind": EngagementKind.RVP_MEETING, "held_on": TODAY.isoformat()},
        )
        with self.assertRaisesMessage(BadRequest, "Only a training observation"):
            services.share_feedback(self.lead, meeting.id)

    def test_the_log_shares_it_and_the_programme_lead_acknowledges_from_the_page(self):
        conversation = self._conversation()
        self.client.force_login(self.lead)
        log = self.client.get("/cce-leadership/engagements")
        self.assertContains(log, f"/cce-leadership/engagements/{conversation.id}/share")
        drawer = self.client.get(
            f"/cce-leadership/engagements/{conversation.id}/share",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(drawer, "the actions agreed and the follow-up date")
        self.client.post(f"/cce-leadership/engagements/{conversation.id}/share/save")
        conversation.refresh_from_db()
        self.assertIsNotNone(conversation.feedback_shared_at)

        self.client.force_login(self.pl)
        page = self.client.get(f"/cce-leadership/coaching?open={conversation.id}")
        self.assertContains(page, "Regional Lead Coaching")
        self.assertContains(page, "Hold every one-to-one by the tenth.")
        self.assertContains(
            page, f'hx-get="/cce-leadership/coaching/{conversation.id}"'
        )
        self.assertContains(page, "Training Feedback", msg_prefix="the tab rail")
        drawer = self.client.get(f"/cce-leadership/coaching/{conversation.id}")
        self.assertContains(drawer, "Acknowledge coaching")
        self.client.post(
            f"/cce-leadership/coaching/{conversation.id}/acknowledge",
            {"response": "By the tenth from October."},
        )
        conversation.refresh_from_db()
        self.assertEqual(conversation.lead_response, "By the tenth from October.")

        self.client.force_login(self.cd)
        director = self.client.get("/cce-leadership/coaching")
        self.assertEqual(director.status_code, 200)
        self.assertNotContains(director, "Hold every one-to-one by the tenth.")

    def test_ticking_share_on_an_engagement_nobody_acknowledges_is_refused(self):
        self.client.force_login(self.lead)
        response = self.client.post(
            "/cce-leadership/engagements/record",
            {
                "kind": EngagementKind.RVP_MEETING,
                "held_on": TODAY.isoformat(),
                "share_now": "1",
            },
            follow=True,
        )
        self.assertContains(response, "Only a coaching conversation or a training")
        self.assertFalse(
            services.engagements_visible_to(self.lead)
            .filter(kind=EngagementKind.RVP_MEETING)
            .exists()
        )
        self.client.post(
            "/cce-leadership/engagements/record",
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "agreed_actions": "Coach the two newest officers.",
                "share_now": "1",
            },
        )
        shared = services.engagements_visible_to(self.lead).get(
            kind=EngagementKind.PL_COACHING
        )
        self.assertIsNotNone(shared.feedback_shared_at)


# ── Pages and drawers ────────────────────────────────────────────────────────
class CoachingPagesTest(CoachingFixture):
    def _refused(self, response):
        return (
            response.status_code in (302, 403) or b"Access Denied" in response.content
        )

    def test_who_opens_which_coaching_page(self):
        record = self._coach()
        coaching.share_coaching(self.pl, record.id)
        allowed = {
            "/team/coaching": (self.pl, self.cd, self.lead, self.admin),
            "/my-coaching": (self.cceo, self.admin),
            "/cce-leadership/coaching": (self.pl, self.cd, self.lead),
        }
        refused = {
            "/team/coaching": (self.cceo, self.rvp),
            "/my-coaching": (self.pl, self.cd, self.rvp),
            "/cce-leadership/coaching": (self.cceo, self.rvp),
        }
        for url, people in allowed.items():
            for person in people:
                with self.subTest(url=url, role=person.active_role):
                    self.client.force_login(person)
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, "Access Denied")
        for url, people in refused.items():
            for person in people:
                with self.subTest(url=url, role=person.active_role, refused=True):
                    self.client.force_login(person)
                    self.assertTrue(self._refused(self.client.get(url)))

    def test_the_lead_records_shares_and_follows_up_from_the_drawers(self):
        self.client.force_login(self.pl)
        page = self.client.get("/team/coaching")
        self.assertContains(page, "Log coaching")
        self.assertContains(page, "data-coaching-one-to-ones")
        self.assertContains(page, "Second Officer")
        self.assertContains(page, "Recovery Plans", msg_prefix="the team strip")
        for url in (
            "/team/coaching/new",
            f"/team/coaching/new?cceo={self.cceo_sp.id}&kind=one_to_one",
            f"/team/coaching/new?kind=field_observation&cceo={self.cceo_sp.id}",
            f"/team/coaching/new?cceo={self.cceo_sp.id}&kind=debrief_feedback&debrief={self.debrief.id}",
        ):
            with self.subTest(url=url):
                drawer = self.client.get(url, HTTP_HX_REQUEST="true")
                self.assertEqual(drawer.status_code, 200)
                self.assertContains(drawer, 'action="/team/coaching/record"')
        observation = self.client.get(
            f"/team/coaching/new?kind=training_observation&cceo={self.cceo_sp.id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(observation, "Biblical integration")
        debrief = self.client.get(
            f"/team/coaching/new?cceo={self.cceo_sp.id}&kind=debrief_feedback&debrief={self.debrief.id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(debrief, "Leadership training day")

        response = self.client.post(
            "/team/coaching/record",
            {
                "cceo_staff_id": self.cceo_sp.id,
                "kind": CoachingKind.ONE_TO_ONE,
                "held_on": TODAY.isoformat(),
                "strengths": "Strong cluster facilitation.",
                "agreed_actions": "Visit two schools with low SSA scores.",
                "follow_up_due": TODAY.isoformat(),
                "share_now": "1",
                "next": f"/team/coaching?open=new&cceo={self.cceo_sp.id}&kind=one_to_one",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"/team/coaching?cceo={self.cceo_sp.id}",
            "the drawer does not reopen after saving",
        )
        record = CceoCoaching.objects.get(author_id=self.pl.id)
        self.assertIsNotNone(record.shared_at)

        self.assertContains(
            self.client.get(f"/team/coaching/{record.id}", HTTP_HX_REQUEST="true"),
            f'action="/team/coaching/{record.id}/update"',
        )
        self.assertContains(
            self.client.get(
                f"/team/coaching/{record.id}/follow-up", HTTP_HX_REQUEST="true"
            ),
            "Close follow-up",
        )
        self.client.post(
            f"/team/coaching/{record.id}/follow-up/save",
            {"follow_up_note": "One school visited."},
        )
        record.refresh_from_db()
        self.assertEqual(record.follow_up_note, "One school visited.")

        draft = self._coach(officer=self.cceo2_sp)
        self.assertContains(
            self.client.get(f"/team/coaching/{draft.id}/share", HTTP_HX_REQUEST="true"),
            "Share with Second Officer",
        )
        self.client.post(f"/team/coaching/{draft.id}/share/save")
        draft.refresh_from_db()
        self.assertIsNotNone(draft.shared_at)

    def test_a_refused_form_says_why(self):
        self.client.force_login(self.pl)
        response = self.client.post(
            "/team/coaching/record",
            {
                "cceo_staff_id": self.other_cceo_sp.id,
                "kind": CoachingKind.ONE_TO_ONE,
                "held_on": TODAY.isoformat(),
                "strengths": "Good.",
            },
            follow=True,
        )
        self.assertContains(response, "Choose an officer on your team.")
        self.assertFalse(CceoCoaching.objects.exists())

    def test_a_form_never_returns_off_site(self):
        """`next` comes from the browser, so the return is checked: another
        host, a scheme-relative path and a path a browser reads as another
        host ("/\\evil") all fall back to the register."""
        record = self._coach()
        self.client.force_login(self.pl)
        for target in (
            "https://evil.example/team/coaching",
            "//evil.example/team/coaching",
            "/\\evil.example/team/coaching",
        ):
            with self.subTest(target=target):
                response = self.client.post(
                    f"/team/coaching/{record.id}/share/save", {"next": target}
                )
                self.assertEqual(response["Location"], "/team/coaching")
                CceoCoaching.objects.filter(id=record.id).update(shared_at=None)

        engagement = services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "agreed_actions": "Coach the newest officers.",
            },
        )
        services.share_feedback(self.lead, engagement.id)
        response = self.client.post(
            f"/cce-leadership/coaching/{engagement.id}/acknowledge",
            {
                "response": "I will coach them this month.",
                "next": f"/cce-leadership/coaching?open={engagement.id}&x=1",
            },
        )
        self.assertEqual(
            response["Location"],
            "/cce-leadership/coaching?x=1",
            "the acknowledged drawer does not reopen",
        )
        response = self.client.post(
            f"/cce-leadership/coaching/{engagement.id}/acknowledge",
            {"response": "Again.", "next": "/\\evil.example/"},
        )
        self.assertEqual(response["Location"], "/cce-leadership/coaching")

    def test_the_director_reads_without_write_controls_and_cannot_write(self):
        record = self._coach()
        coaching.share_coaching(self.pl, record.id)
        self.client.force_login(self.cd)
        page = self.client.get("/team/coaching")
        self.assertContains(page, "Read only.")
        self.assertContains(page, record.subject)
        self.assertNotContains(page, "Log coaching")
        self.assertNotContains(page, "data-coaching-one-to-ones")
        drawer = self.client.get(f"/team/coaching/{record.id}", HTTP_HX_REQUEST="true")
        self.assertNotContains(drawer, "/update")
        self.assertContains(
            self.client.get("/team/coaching/new", HTTP_HX_REQUEST="true"),
            "Programme Lead records coaching.",
        )
        self.client.post(
            "/team/coaching/record",
            {
                "cceo_staff_id": self.cceo_sp.id,
                "kind": CoachingKind.ONE_TO_ONE,
                "held_on": TODAY.isoformat(),
                "strengths": "Written by the director.",
            },
        )
        self.client.post(
            f"/team/coaching/{record.id}/follow-up/save", {"follow_up_note": "x"}
        )
        self.assertEqual(CceoCoaching.objects.count(), 1)
        record.refresh_from_db()
        self.assertIsNone(record.follow_up_done_at)

    def test_the_officer_acknowledges_from_my_coaching(self):
        record = self._coach()
        coaching.share_coaching(self.pl, record.id)
        draft = self._coach(strengths="Private draft.")
        self.client.force_login(self.cceo)
        page = self.client.get(f"/my-coaching?open={record.id}")
        self.assertContains(page, record.subject)
        self.assertContains(page, f'hx-get="/my-coaching/{record.id}"')
        self.assertNotContains(page, "Private draft.")
        drawer = self.client.get(f"/my-coaching/{record.id}", HTTP_HX_REQUEST="true")
        self.assertContains(drawer, "Acknowledge coaching")
        self.assertContains(
            self.client.get(f"/my-coaching/{draft.id}", HTTP_HX_REQUEST="true"),
            "not shared with you",
        )
        self.client.post(
            f"/my-coaching/{record.id}/acknowledge",
            {"response": "I will visit both schools."},
        )
        record.refresh_from_db()
        self.assertIsNotNone(record.acknowledged_at)

        self.client.force_login(self.cceo2)
        self.assertContains(
            self.client.get(f"/my-coaching/{record.id}", HTTP_HX_REQUEST="true"),
            "not shared with you",
        )

    def test_plain_links_open_the_log_with_the_drawer_on_top(self):
        self.client.force_login(self.pl)
        response = self.client.get(
            f"/team/coaching/new?cceo={self.cceo_sp.id}&kind=debrief_feedback&debrief={self.debrief.id}"
        )
        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.path, "/team/coaching")
        self.assertEqual(parse_qs(location.query)["open"], ["new"])

        page = self.client.get(response["Location"])
        self.assertContains(page, "data-cce-autoload")
        self.assertContains(page, "/team/coaching/new?cceo=")

        others = coaching.record_coaching(
            self.other_pl,
            {
                "cceo_staff_id": self.other_cceo_sp.id,
                "kind": CoachingKind.RECOGNITION,
                "held_on": TODAY.isoformat(),
                "strengths": "Great work.",
            },
        )
        page = self.client.get(f"/team/coaching?open={others.id}&step=share")
        self.assertNotContains(page, "data-cce-autoload", msg_prefix="not in reach")

    def test_the_register_filters_by_officer_kind_and_state(self):
        shared = self._coach()
        coaching.share_coaching(self.pl, shared.id)
        draft = self._coach(officer=self.cceo2_sp, strengths="Draft for two.")
        self.client.force_login(self.pl)
        by_officer = self.client.get(f"/team/coaching?cceo={self.cceo2.id}")
        self.assertContains(by_officer, draft.subject)
        self.assertNotContains(by_officer, f'/team/coaching/{shared.id}"')
        by_state = self.client.get("/team/coaching?state=draft")
        self.assertContains(by_state, f'/team/coaching/{draft.id}"')
        self.assertNotContains(by_state, f'/team/coaching/{shared.id}"')
        by_kind = self.client.get("/team/coaching?kind=recognition")
        self.assertContains(by_kind, "No coaching recorded yet")


class CoachingNotificationRoutesTest(SimpleTestCase):
    def test_coaching_events_land_on_the_page_that_acts_on_them(self):
        from apps.notifications.services import NotificationLinkResolver

        for event, role, route in (
            ("cceo_coaching_shared", "CCEO", "/my-coaching"),
            ("cceo_coaching_acknowledged", "Program Lead", "/team/coaching"),
            ("cce_pl_coaching_shared", "Program Lead", "/cce-leadership/coaching"),
            (
                "cce_pl_coaching_acknowledged",
                "RegionalProgramLead",
                "/cce-leadership/engagements",
            ),
        ):
            with self.subTest(event=event):
                self.assertEqual(
                    NotificationLinkResolver.resolve(event, "CceoCoaching", "x", role)[
                        0
                    ],
                    route,
                )


# ── To-Dos ───────────────────────────────────────────────────────────────────
class CoachingTodoTest(CoachingFixture):
    MID_MONTH = date(2026, 9, 15)

    def _raw(self, officer_sp, officer, **fields):
        return CceoCoaching.objects.create(
            author_id=self.pl.id,
            cceo_staff_id=officer_sp.id,
            cceo_user_id=officer.id,
            fy="2026",
            country="Uganda",
            subject=fields.pop("subject", "Coaching"),
            **{"kind": CoachingKind.ONE_TO_ONE, **fields},
        )

    def test_the_builder_is_registered_and_rows_have_the_queue_shape(self):
        from apps.command_center.todo_service import MODULE_TODO_BUILDERS

        self.assertIn("apps.cce_leadership.todos:coaching_todos", MODULE_TODO_BUILDERS)
        rows = coaching_todos(self.pl, "Program Lead", self.MID_MONTH)
        self.assertTrue(rows)
        expected = {
            "id",
            "title",
            "description",
            "category",
            "priority",
            "status_key",
            "status_label",
            "status_tone",
            "due_label",
            "due_tone",
            "linked",
            "action_label",
            "action_url",
            "actionable",
            "source",
            "_due_sort",
        }
        for row in rows:
            with self.subTest(row=row["id"]):
                self.assertEqual(set(row), expected)
                self.assertIsInstance(row["_due_sort"], date)
        self.assertEqual(coaching_todos(self.cd, "CountryDirector", self.MID_MONTH), [])

    def test_the_lead_is_asked_to_hold_share_follow_up_and_acknowledge(self):
        self._raw(self.cceo_sp, self.cceo, held_on=date(2026, 9, 3))
        draft = self._raw(
            self.cceo2_sp,
            self.cceo2,
            held_on=date(2026, 8, 20),
            kind=CoachingKind.RECOGNITION,
            subject="Recognition for cluster work",
        )
        CceoCoaching.objects.filter(id=draft.id).update(
            created_at=timezone.now() - timedelta(days=3)
        )
        fresh = self._raw(self.cceo2_sp, self.cceo2, held_on=date(2026, 8, 30))
        follow_up = self._raw(
            self.cceo_sp,
            self.cceo,
            held_on=date(2026, 8, 1),
            kind=CoachingKind.PERFORMANCE_CHECKIN,
            agreed_actions="Submit the catch-up plan.",
            follow_up_due=date(2026, 9, 10),
            shared_at=timezone.now(),
        )
        conversation = services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "agreed_actions": "Coach the newest officers.",
            },
        )
        services.share_feedback(self.lead, conversation.id)

        rows = {
            r["title"]: r
            for r in coaching_todos(self.pl, "Program Lead", self.MID_MONTH)
        }
        self.assertIn("Hold September one-to-one with Second Officer", rows)
        self.assertNotIn("Hold September one-to-one with Uganda Officer", rows)
        hold = rows["Hold September one-to-one with Second Officer"]
        self.assertTrue(hold["action_url"].startswith("/team/coaching?open=new"))
        self.assertIn(f"cceo={self.cceo2_sp.id}", hold["action_url"])
        # The lead's queue groups coaching under the responsibility it serves.
        self.assertEqual(hold["category"], "Performance & Coaching")

        share = rows["Share coaching notes with Second Officer"]
        self.assertEqual(
            share["action_url"], f"/team/coaching?open={draft.id}&step=share"
        )
        self.assertNotIn(
            fresh.id, " ".join(r["id"] for r in rows.values()), "two days' grace"
        )

        chase = rows["Follow up agreed actions with Uganda Officer"]
        self.assertEqual(chase["status_key"], "overdue")
        self.assertIn(follow_up.id, chase["action_url"])

        regional = rows["Acknowledge Regional Lead coaching"]
        self.assertEqual(
            regional["action_url"], f"/cce-leadership/coaching?open={conversation.id}"
        )
        self.assertEqual(regional["category"], "Collaboration")

        before_the_tenth = [
            r["title"]
            for r in coaching_todos(self.pl, "Program Lead", date(2026, 9, 9))
        ]
        self.assertFalse(any(t.startswith("Hold ") for t in before_the_tenth))

    def test_the_officer_is_asked_to_acknowledge_and_the_row_closes_itself(self):
        record = self._coach()
        self.assertEqual(
            coaching_todos(self.cceo, "CCEO", TODAY), [], "drafts are private"
        )
        coaching.share_coaching(self.pl, record.id)
        rows = coaching_todos(self.cceo, "CCEO", TODAY)
        self.assertEqual(
            [r["title"] for r in rows], ["Acknowledge coaching from Uganda Lead"]
        )
        self.assertEqual(rows[0]["action_url"], f"/my-coaching?open={record.id}")
        coaching.acknowledge_coaching(self.cceo, record.id, "Will do.")
        self.assertEqual(coaching_todos(self.cceo, "CCEO", TODAY), [])

    def test_a_failing_source_never_breaks_the_queue(self):
        with patch.object(coaching, "monthly_one_to_ones", side_effect=RuntimeError):
            self.assertEqual(
                coaching_todos(self.pl, "Program Lead", self.MID_MONTH), []
            )


# ── Query cost ───────────────────────────────────────────────────────────────
@override_settings(CACHES=LOCMEM)
class CoachingQueryBudgetTest(TestCase):
    """Fixed cost whatever the team size: every list is fetched once for the
    whole team and split in Python. Measured against a cache this process
    owns, because dev test runs share a real Redis."""

    @classmethod
    def setUpTestData(cls):
        cls.pl, cls.pl_sp = _person("cq-pl", "Budget Lead", "Program Lead")
        cls.lead, cls.lead_sp = _person(
            "cq-rpl", "Budget Regional", "RegionalProgramLead"
        )
        cls.officers = []
        for index in range(6):
            officer, officer_sp = _person(
                f"cq-cceo{index}", f"Budget Officer {index}", "CCEO"
            )
            cls.officers.append((officer, officer_sp))

    def _grow_team(self, size):
        for officer, officer_sp in self.officers[:size]:
            StaffSupervisorAssignment.objects.get_or_create(
                supervisor=self.pl_sp, supervisee=officer_sp
            )
            if CceoCoaching.objects.filter(cceo_staff_id=officer_sp.id).exists():
                continue
            for kind, shared in (
                (CoachingKind.ONE_TO_ONE, True),
                (CoachingKind.FIELD_OBSERVATION, False),
            ):
                CceoCoaching.objects.create(
                    author_id=self.pl.id,
                    cceo_staff_id=officer_sp.id,
                    cceo_user_id=officer.id,
                    kind=kind,
                    held_on=date(2026, 8, 20),
                    fy="2026",
                    country="Uganda",
                    subject=f"{kind} with {officer.name}",
                    agreed_actions="Plan visits.",
                    follow_up_due=date(2026, 9, 10),
                    shared_at=timezone.now() if shared else None,
                )
            # Old enough drafts to be reminded about.
            CceoCoaching.objects.filter(cceo_staff_id=officer_sp.id).update(
                created_at=timezone.now() - timedelta(days=5)
            )

    def _page_queries(self, url):
        self.client.force_login(self.pl)
        self.client.get(url)  # warm per-process caches
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_the_coaching_page_does_not_grow_with_the_team(self):
        self._grow_team(2)
        small = self._page_queries("/team/coaching")
        self._grow_team(6)
        large = self._page_queries("/team/coaching")
        self.assertEqual(CceoCoaching.objects.filter(author_id=self.pl.id).count(), 12)
        self.assertLessEqual(
            large, small, f"{small} queries for 2 officers, {large} for 6"
        )

    def test_the_coaching_todos_do_not_grow_with_the_team(self):
        today = date(2026, 9, 15)

        def measure():
            coaching_todos(self.pl, "Program Lead", today)
            with CaptureQueriesContext(connection) as ctx:
                rows = coaching_todos(self.pl, "Program Lead", today)
            return len(ctx), rows

        self._grow_team(2)
        small, small_rows = measure()
        self._grow_team(6)
        large, large_rows = measure()
        self.assertGreater(len(large_rows), len(small_rows), "the fixture really grew")
        self.assertEqual(large, small)
        self.assertLessEqual(large, 8)

    def test_the_officer_page_does_not_grow_with_their_records(self):
        officer, officer_sp = self.officers[0]
        self._grow_team(1)

        def measure():
            self.client.force_login(officer)
            self.client.get("/my-coaching")
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.client.get("/my-coaching").status_code, 200)
            return len(ctx)

        small = measure()
        for index in range(6):
            CceoCoaching.objects.create(
                author_id=self.pl.id,
                cceo_staff_id=officer_sp.id,
                cceo_user_id=officer.id,
                kind=CoachingKind.RECOGNITION,
                held_on=TODAY,
                fy="2026",
                subject=f"Recognition {index}",
                strengths="Great.",
                shared_at=timezone.now(),
            )
        self.assertLessEqual(measure(), small)

    def test_last_coaching_by_cceo_is_two_queries_for_any_team(self):
        self._grow_team(6)
        ids = [sp.id for _officer, sp in self.officers]
        with CaptureQueriesContext(connection) as ctx:
            result = coaching.last_coaching_by_cceo(self.pl, ids, team_ids=ids)
        self.assertEqual(len(result), 6)
        self.assertEqual(len(ctx), 2)

    def test_the_regional_coaching_page_does_not_grow_with_conversations(self):
        def measure():
            self.client.force_login(self.pl)
            self.client.get("/cce-leadership/coaching")
            with CaptureQueriesContext(connection) as ctx:
                response = self.client.get("/cce-leadership/coaching")
            self.assertEqual(response.status_code, 200)
            return len(ctx)

        def converse(count):
            from .models import RegionalEngagement

            for index in range(count):
                RegionalEngagement.objects.create(
                    author_id=self.lead.id,
                    kind=EngagementKind.PL_COACHING,
                    held_on=TODAY,
                    fy="2026",
                    country="Uganda",
                    program_lead_ids=[self.pl_sp.id],
                    subject=f"Coaching {index}",
                    agreed_actions="Hold one-to-ones.",
                    feedback_shared_at=timezone.now(),
                )

        converse(1)
        small = measure()
        converse(5)
        self.assertLessEqual(measure(), small)


class OtherRolesUnaffectedTest(CoachingFixture):
    def test_the_existing_training_feedback_todo_is_unchanged_for_the_lead(self):
        from apps.command_center.todo_service import _cce_leadership_todos

        conversation = services.record_engagement(
            self.lead,
            {
                "kind": EngagementKind.PL_COACHING,
                "held_on": TODAY.isoformat(),
                "program_lead_ids": [self.pl_sp.id],
                "agreed_actions": "Coach the newest officers.",
            },
        )
        services.share_feedback(self.lead, conversation.id)
        titles = [
            t["title"] for t in _cce_leadership_todos(self.pl, "Program Lead", TODAY)
        ]
        self.assertNotIn(
            "Acknowledge training feedback",
            titles,
            "a coaching conversation is not training feedback",
        )
        self.assertTrue(User.objects.filter(id=self.pl.id).exists())
