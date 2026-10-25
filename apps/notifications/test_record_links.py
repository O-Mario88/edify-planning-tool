"""A notification opens the record it is about (owner, 2026-10-25:
"notifications should be linked direct to the page the notification is
about"), not a list or dashboard the reader then has to search.

Every surface ends at the notification's own link: the bell and the
notification centre use it directly, and a phone notification or an email
goes through /notifications/<id>/open to it. Where the page opens one record
in a drawer, the link names it (?open=<id>); where the record has a page of
its own, the link is that page.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.notifications.services import NotificationLinkResolver


def route(event, context_type, context_id, role):
    return NotificationLinkResolver.resolve(event, context_type, context_id, role)[0]


class RecordLinkTest(SimpleTestCase):
    def test_regional_cce_handoffs_open_the_engagement_or_report(self):
        for event, context_type, role, expected in (
            (
                "cce_training_feedback_shared",
                "RegionalEngagement",
                "Program Lead",
                "/cce-leadership/feedback?open=e1",
            ),
            (
                "cce_training_feedback_acknowledged",
                "RegionalEngagement",
                "RegionalProgramLead",
                "/cce-leadership/engagements?open=e1",
            ),
            (
                "cce_report_submitted",
                "RegionalCceReport",
                "RegionalVicePresident",
                "/cce-leadership/reports?open=e1",
            ),
            (
                "cce_report_reviewed",
                "RegionalCceReport",
                "RegionalProgramLead",
                "/cce-leadership/reports?open=e1",
            ),
        ):
            with self.subTest(event=event):
                self.assertEqual(route(event, context_type, "e1", role), expected)

    def test_returned_evidence_opens_the_activity_to_fix(self):
        for role in ("CCEO", "PartnerFieldOfficer"):
            with self.subTest(role=role):
                self.assertEqual(
                    route("evidence_returned", "activity", "a1", role), "/my-plan/a1"
                )

    def test_a_completion_to_review_opens_its_review(self):
        self.assertEqual(
            route("activity_submitted_for_review", "Activity", "a1", "ProjectLeader"),
            "/pl/review-queue?open=a1",
        )

    def test_without_a_record_the_page_itself_is_still_offered(self):
        self.assertEqual(
            route("cceo_coaching_shared", "CceoCoaching", None, "CCEO"), "/my-coaching"
        )
        self.assertEqual(route("evidence_returned", None, None, "CCEO"), "/my-plan")
