"""Messaging workflow tests.

Covers thread identity (participants + context + subject), context-required
sends, context-permission gating, role-scoped recipients and suggestions,
drafts, workflow-generated threads, archive/unread behaviour, attachments,
and notification fan-out.
"""

from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region
from apps.messaging import services
from apps.messaging.models import (
    Message,
    MessageAttachment,
    MessageDraft,
    MessageThread,
)
from apps.notifications.models import Notification
from apps.schools.models import School


def _user(email, role, name):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class MessagingBaseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("admin@t.test", "Admin", "Admin One")
        cls.cceo1 = _user("cceo1@t.test", "CCEO", "Field One")
        cls.cceo2 = _user("cceo2@t.test", "CCEO", "Field Two")
        cls.pl = _user("pl@t.test", "Program Lead", "Lead One")
        cls.hr = _user("hr@t.test", "HumanResources", "HR One")
        cls.rvp = _user("rvp@t.test", "RegionalVicePresident", "RVP One")
        cls.ia = _user("ia@t.test", "ImpactAssessment", "IA One")
        cls.accountant = _user("acc@t.test", "Accountant", "Accountant One")
        cls.partner = _user("partner@t.test", "PartnerFieldOfficer", "Partner One")

        cls.sp1 = StaffProfile.objects.create(user=cls.cceo1)
        cls.sp2 = StaffProfile.objects.create(user=cls.cceo2)
        cls.sp_pl = StaffProfile.objects.create(user=cls.pl)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.sp1, supervisor=cls.sp_pl
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.sp2, supervisor=cls.sp_pl
        )

        region = Region.objects.create(name="Test Region")
        district = District.objects.create(name="Test District", region=region)
        cls.school1 = School.objects.create(
            school_id="S-0001",
            name="School One",
            district=district,
            region=region,
            account_owner_id=cls.sp1.id,
        )
        cls.school2 = School.objects.create(
            school_id="S-0002",
            name="School Two",
            district=district,
            region=region,
            account_owner_id=cls.sp2.id,
        )
        # Row-level scope for CCEOs comes from StaffSchoolAssignment.
        StaffSchoolAssignment.objects.create(staff=cls.sp1, school_id=cls.school1.id)
        StaffSchoolAssignment.objects.create(staff=cls.sp2, school_id=cls.school2.id)

        # Real records, because `can_access_context` now fails closed. These
        # fixtures used synthetic ids ("c1", "fr-1", "pa-x") that resolved to
        # nothing, and the gate used to wave an unresolvable context through —
        # so the suite was asserting the vulnerability rather than the rule.
        from django.utils import timezone

        from apps.activities.models import Activity
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.partners.models import Partner, PartnerAssignment

        cls.activity1 = Activity.objects.create(
            school_id=cls.school1.id,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=cls.sp1.id,
            planned_date=timezone.now(),
        )
        _today = timezone.now().date()
        cls.fund_request = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=_today,
            week_end_date=_today + timedelta(days=6),
            responsible_user=cls.cceo1.id,
            status="submitted",
        )
        cls.partner_org = Partner.objects.create(
            name="Test Partner", user=cls.partner
        )
        cls.partner_assignment = PartnerAssignment.objects.create(
            partner=cls.partner_org,
            school=cls.school1,
            status="assigned",
        )

    def _send(
        self,
        sender,
        recipient,
        *,
        ctype="system",
        cid=None,
        subject="(no subject)",
        body="hello",
        **extra,
    ):
        return services.send(
            {
                "recipientId": recipient.id,
                "subject": subject,
                "contextType": ctype,
                "contextId": cid or "support-1",
                "body": body,
                **extra,
            },
            sender,
        )


class ContextRequirementTest(MessagingBaseTest):
    def test_message_requires_context(self):
        with self.assertRaises(BadRequest):
            services.send(
                {"recipientId": self.pl.id, "subject": "s", "body": "b"}, self.cceo1
            )

    def test_send_disabled_without_context_via_view(self):
        self.client.force_login(self.cceo1)
        r = self.client.post(
            "/messages/new/",
            {
                "recipient_ids": [self.pl.id],
                "subject": "No context",
                "category": "Planning",
                "body": "should fail",
                "context_type": "",
                "context_id": "",
            },
        )
        # bounced back to compose with an error, nothing created
        self.assertEqual(Message.objects.count(), 0)
        self.assertEqual(r.status_code, 200)

    def test_reply_inherits_context(self):
        m = self._send(self.cceo1, self.pl, ctype="school", cid=self.school1.school_id)
        r = services.reply(m["threadId"], {"body": "reply"}, self.pl)
        self.assertEqual(r["contextType"], "school")
        self.assertEqual(r["contextId"], self.school1.school_id)

    def test_empty_messages_and_replies_are_rejected(self):
        with self.assertRaises(BadRequest):
            self._send(self.cceo1, self.pl, body="   ")
        message = self._send(self.cceo1, self.pl)
        with self.assertRaises(BadRequest):
            services.reply(message["threadId"], {"body": "\n\t"}, self.pl)


class ThreadIdentityTest(MessagingBaseTest):
    def test_same_subject_different_pairs_get_separate_threads(self):
        m1 = self._send(self.admin, self.cceo1, body="A to B private")
        m2 = self._send(self.pl, self.hr, body="C to D private")
        self.assertNotEqual(m1["threadId"], m2["threadId"])

    def test_no_cross_thread_leakage(self):
        m1 = self._send(self.admin, self.cceo1, body="A to B private")
        self._send(self.pl, self.hr, body="C to D private")
        with self.assertRaises(Forbidden):
            services.thread(m1["threadId"], self.hr)

    def test_same_pair_same_context_and_subject_reuses_thread(self):
        m1 = self._send(self.admin, self.cceo1, subject="Budget Q3")
        m2 = self._send(self.cceo1, self.admin, subject="Budget Q3")
        self.assertEqual(m1["threadId"], m2["threadId"])

    def test_group_send_creates_participants(self):
        msg = services.send(
            {
                "recipientIds": [self.pl.id, self.ia.id],
                "ccIds": [self.admin.id],
                "subject": "Group",
                "contextType": "system",
                "contextId": "support-9",
                "body": "b",
            },
            self.cceo1,
        )
        t = MessageThread.objects.get(id=msg["threadId"])
        member_ids = set(t.participants.values_list("user_id", flat=True))
        self.assertEqual(
            member_ids, {self.cceo1.id, self.pl.id, self.ia.id, self.admin.id}
        )
        cc = t.participants.get(user_id=self.admin.id)
        self.assertEqual(cc.recipient_type, "cc")


class ContextPermissionTest(MessagingBaseTest):
    def test_cceo_cannot_message_about_other_cceo_school(self):
        with self.assertRaises(Forbidden):
            self._send(self.cceo1, self.pl, ctype="school", cid=self.school2.school_id)

    def test_cceo_can_message_about_own_school(self):
        msg = self._send(
            self.cceo1, self.pl, ctype="school", cid=self.school1.school_id
        )
        self.assertTrue(msg["id"])

    def test_thread_access_requires_context_permission(self):
        # PL and CCEO2 talk about school2; CCEO1 cannot open it even if the
        # thread id leaks, because school2 is outside CCEO1's scope.
        msg = self._send(
            self.cceo2, self.pl, ctype="school", cid=self.school2.school_id
        )
        with self.assertRaises(Forbidden):
            services.thread_detail(msg["threadId"], self.cceo1)

    def test_reply_rechecks_access_after_assignment_is_revoked(self):
        msg = self._send(
            self.cceo1, self.pl, ctype="school", cid=self.school1.school_id
        )
        StaffSchoolAssignment.objects.filter(
            staff=self.sp1, school_id=self.school1.id
        ).delete()
        with self.assertRaises(Forbidden):
            services.reply(msg["threadId"], {"body": "stale access"}, self.cceo1)

    def test_partner_cannot_access_internal_staff_thread(self):
        msg = self._send(self.cceo1, self.pl, ctype="activity", cid=self.activity1.id)
        with self.assertRaises(Forbidden):
            services.thread_detail(msg["threadId"], self.partner)

    def test_accountant_blocked_from_non_finance_context(self):
        self.assertFalse(
            services.can_access_context(
                self.accountant, "school", self.school1.school_id
            )
        )
        self.assertTrue(
            services.can_access_context(
                self.accountant, "fund_request", self.fund_request.id
            )
        )


class RecipientPolicyTest(MessagingBaseTest):
    def test_hr_cannot_message_partner_by_default(self):
        with self.assertRaises(Forbidden):
            self._send(self.hr, self.partner, ctype="school", cid=self.school1.school_id)

    def test_rvp_cannot_message_partner_by_default(self):
        with self.assertRaises(Forbidden):
            self._send(self.rvp, self.partner, ctype="budget", cid="b-1")

    def test_partner_can_message_cceo(self):
        msg = self._send(
            self.partner,
            self.cceo1,
            ctype="partner_assignment",
            cid=self.partner_assignment.id,
        )
        self.assertTrue(msg["id"])


class SuggestedRecipientTest(MessagingBaseTest):
    def test_context_suggests_correct_recipients_for_school(self):
        out = services.suggested_recipients(self.pl, "school", self.school1.school_id)
        ids = {s["id"] for s in out}
        self.assertIn(self.cceo1.id, ids)  # assigned CCEO

    def test_school_suggestions_include_supervising_pl(self):
        out = services.suggested_recipients(
            self.admin, "school", self.school1.school_id
        )
        ids = {s["id"] for s in out}
        self.assertIn(self.pl.id, ids)

    def test_ia_suggested_for_verification_context(self):
        from apps.activities.models import Activity

        act = Activity.objects.create(
            activity_type="school_visit",
            status="awaiting_ia_verification",
            school=self.school1,
            responsible_staff_id=self.cceo1.id,
            fy="2026",
        )
        out = services.suggested_recipients(self.pl, "verification", act.id)
        ids = {s["id"] for s in out}
        self.assertIn(self.ia.id, ids)

    def test_activity_owner_and_monitor_suggestions_accept_staff_profile_ids(self):
        """Canonical staff ids must not make contextual messaging go blank."""
        from apps.activities.models import Activity

        act = Activity.objects.create(
            activity_type="school_visit",
            status="partner_scheduled",
            school=self.school1,
            delivery_type="partner",
            responsible_staff_id=self.sp1.id,
            monitored_by_staff_id=self.sp_pl.id,
            fy="2026",
        )
        out = services.suggested_recipients(self.admin, "activity", act.id)
        ids = {item["id"] for item in out}
        self.assertIn(self.cceo1.id, ids)
        self.assertIn(self.pl.id, ids)

    def test_accountant_suggested_for_finance_context(self):
        out = services.suggested_recipients(self.pl, "finance", "any-id")
        roles = {s["role"] for s in out}
        self.assertIn("Accountant", roles)

    def test_suggestions_respect_role_policy(self):
        # HR cannot message partners, so a partner-linked school must not
        # surface the partner user for HR.
        out = services.suggested_recipients(self.hr, "school", self.school1.school_id)
        ids = {s["id"] for s in out}
        self.assertNotIn(self.partner.id, ids)


class DraftTest(MessagingBaseTest):
    def test_draft_preserves_context_and_recipients(self):
        d = services.save_draft(
            {
                "subject": "Draft A",
                "category": "Planning",
                "contextType": "school",
                "contextId": self.school1.school_id,
                "recipientIds": [self.pl.id],
                "ccIds": [self.ia.id],
                "body": "draft body",
            },
            self.cceo1,
        )
        d2 = MessageDraft.objects.get(id=d.id)
        self.assertEqual(d2.context_type, "school")
        self.assertEqual(d2.recipient_ids, [self.pl.id])
        self.assertEqual(d2.cc_ids, [self.ia.id])
        # Compose page loads the draft back
        self.client.force_login(self.cceo1)
        r = self.client.get(f"/messages/new/?draft={d.id}")
        self.assertContains(r, "Draft A")


class WorkflowMessageTest(MessagingBaseTest):
    def test_workflow_event_creates_contextual_message(self):
        t = services.workflow_message(
            context_type="ia_return",
            context_id="act-77",
            subject="Evidence returned — School One",
            body="IA returned this activity. Please fix the register and resubmit.",
            recipient_ids=[self.cceo1.id, self.pl.id],
            category="Returned activity",
            priority="high",
        )
        self.assertIsNotNone(t)
        self.assertTrue(t.is_system_generated)
        self.assertEqual(
            set(t.participants.values_list("user_id", flat=True)),
            {self.cceo1.id, self.pl.id},
        )
        # Recipients were notified
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cceo1.id, source_event_type="message"
            ).exists()
        )
        # Repeat events extend the same thread
        t2 = services.workflow_message(
            context_type="ia_return",
            context_id="act-77",
            subject="ignored",
            body="second event",
            recipient_ids=[self.cceo1.id],
        )
        self.assertEqual(t.id, t2.id)
        self.assertEqual(t2.messages.count(), 2)

    def test_single_recipient_system_thread_is_read_only(self):
        thread = services.workflow_message(
            context_type="system",
            context_id=f"analytics-{self.pl.id}",
            subject="Analytics snapshot",
            body="Snapshot ready",
            recipient_ids=[self.pl.id],
        )
        with self.assertRaises(BadRequest):
            services.reply(thread.id, {"body": "reply to system"}, self.pl)


class InboxBehaviourTest(MessagingBaseTest):
    def test_archived_thread_removed_from_inbox(self):
        m = self._send(self.cceo1, self.pl)
        services.archive_thread(m["threadId"], self.pl)
        inbox = services.threads_for_user(self.pl, tab="all")
        self.assertNotIn(m["threadId"], [t["id"] for t in inbox])
        archived = services.threads_for_user(self.pl, tab="archived")
        self.assertIn(m["threadId"], [t["id"] for t in archived])

    def test_unread_count_updates_correctly(self):
        m = self._send(self.cceo1, self.pl, body="unread ping")
        self.assertEqual(services.message_kpis(self.pl)["unread"], 1)
        services.thread_detail(m["threadId"], self.pl)  # opening marks read
        self.assertEqual(services.message_kpis(self.pl)["unread"], 0)

    def test_group_recipient_is_counted_and_can_mark_read(self):
        msg = services.send(
            {
                "recipientIds": [self.pl.id, self.ia.id],
                "subject": "Group unread",
                "contextType": "system",
                "contextId": "support-group-1",
                "body": "Review together",
            },
            self.cceo1,
        )
        self.assertEqual(services.unread_thread_count(self.ia), 1)
        services.mark_read(msg["id"], self.ia)
        self.assertEqual(services.unread_thread_count(self.ia), 0)

    def test_reply_routes_to_other_participant(self):
        m = self._send(self.pl, self.hr, body="original")
        r = services.reply(m["threadId"], {"body": "reply"}, self.hr)
        self.assertEqual(r["recipientId"], self.pl.id)

    def test_send_creates_notification_for_recipient(self):
        msg = self._send(self.pl, self.cceo1, subject="Visit plan")
        n = Notification.objects.get(
            source_event_type="message", source_event_id=msg["id"]
        )
        self.assertEqual(n.recipient_id, self.cceo1.id)
        self.assertEqual(n.target_route, f"/messages/{msg['id']}")

    def test_mark_read_is_scoped_to_recipient(self):
        msg = self._send(self.pl, self.cceo1)
        with self.assertRaises(Forbidden):
            services.mark_read(msg["id"], self.pl)
        services.mark_read(msg["id"], self.cceo1)
        self.assertEqual(Message.objects.get(id=msg["id"]).status, "read")


class AttachmentTest(MessagingBaseTest):
    def test_attachments_upload_and_display(self):
        self.client.force_login(self.cceo1)
        f = SimpleUploadedFile(
            "register.pdf", b"%PDF-1.4 fake", content_type="application/pdf"
        )
        r = self.client.post(
            "/messages/new/",
            {
                "recipient_ids": [self.pl.id],
                "subject": "With file",
                "category": "Planning",
                "context_type": "school",
                "context_id": self.school1.school_id,
                "body": "see attached",
                "attachments": f,
            },
        )
        self.assertEqual(r.status_code, 302)
        att = MessageAttachment.objects.get(file_name="register.pdf")
        self.assertEqual(att.uploaded_by, self.cceo1.id)
        # Renders in the conversation
        thread_id = Message.objects.get(id=att.message_id).thread_id
        r2 = self.client.get(f"/messages?thread={thread_id}")
        self.assertContains(r2, "register.pdf")
        self.assertContains(r2, f"/messages/attachments/{att.id}")

        download = self.client.get(f"/messages/attachments/{att.id}")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download["Content-Type"], "application/pdf")

        self.client.force_login(self.cceo2)
        denied = self.client.get(f"/messages/attachments/{att.id}")
        self.assertEqual(denied.status_code, 404)

    def test_unsafe_attachment_rejects_the_entire_message(self):
        self.client.force_login(self.cceo1)
        upload = SimpleUploadedFile(
            "payload.html", b"<script>alert(1)</script>", content_type="text/html"
        )
        response = self.client.post(
            "/messages/new/",
            {
                "recipient_ids": [self.pl.id],
                "subject": "Unsafe file",
                "category": "Planning",
                "context_type": "school",
                "context_id": self.school1.school_id,
                "body": "do not create",
                "attachments": upload,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Message.objects.filter(body="do not create").exists())


class PageRenderTest(MessagingBaseTest):
    def test_messages_page_renders_three_panels(self):
        self._send(self.cceo1, self.pl, subject="Panel check")
        self.client.force_login(self.pl)
        r = self.client.get("/messages")
        self.assertContains(r, "Workflow Context")
        self.assertContains(r, "Panel check")
        self.assertContains(r, "New Message")

    def test_compose_page_renders_rules_and_steps(self):
        self.client.force_login(self.pl)
        r = self.client.get("/messages/new/")
        self.assertContains(r, "Select Context")
        self.assertContains(r, "Context required for all new messages")
        self.assertContains(r, "Context Summary")

    def test_htmx_thread_partial(self):
        m = self._send(self.cceo1, self.pl, subject="HTMX check")
        self.client.force_login(self.pl)
        r = self.client.get(f"/messages/thread/{m['threadId']}", HTTP_HX_REQUEST="true")
        self.assertContains(r, "HTMX check")
        self.assertContains(r, "Replies inherit this context")

    def test_htmx_filter_clears_stale_conversation_and_context(self):
        self._send(self.cceo1, self.pl, subject="Visible before filter")
        self.client.force_login(self.pl)
        response = self.client.get(
            "/messages",
            {"q": "definitely-no-match"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, 'id="conversation-pane"')
        self.assertContains(response, 'id="context-panel-scroll"')
        self.assertContains(response, 'hx-swap-oob="innerHTML"')
        self.assertNotContains(response, "Visible before filter")

    def test_deep_link_by_message_id_redirects_to_thread(self):
        m = self._send(self.cceo1, self.pl)
        self.client.force_login(self.pl)
        r = self.client.get(f"/messages/{m['id']}")
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"thread={m['threadId']}", r.url)
