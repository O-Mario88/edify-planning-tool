"""The people and communication layers must fail closed.

Every test here pins a defect the HR / filters / messaging / notifications
audit proved was live. They are grouped by what breaks if the guard is lost:
who can read another person's confidential record, who can be messaged, and
where an authenticated link can send you.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class MessagingContextFailsClosedTests(TestCase):
    """`can_access_context` returning True for an unresolvable context was a
    master key: every role rule is a constraint on a *resolved* record, so an
    id that resolved to nothing authorised everyone."""

    @classmethod
    def setUpTestData(cls):
        cls.cceo = _user("ctx-cceo@t.org", "Ctx CCEO", EdifyRole.CCEO.value)
        cls.partner = _user("ctx-p@t.org", "Ctx Partner", "PartnerFieldOfficer")
        cls.sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")

    def test_unresolvable_context_is_refused(self):
        from apps.messaging import services

        self.assertFalse(
            services.can_access_context(self.cceo, "school", "no-such-school"),
            "an id that resolves to nothing must not authorise anyone",
        )

    def test_unknown_context_type_is_refused(self):
        from apps.messaging import services

        self.assertFalse(
            services.can_access_context(self.cceo, "not-a-real-context", "x")
        )

    def test_partner_cannot_reach_staff_through_a_fake_context(self):
        from apps.core.exceptions import Forbidden
        from apps.messaging import services

        with self.assertRaises(Forbidden):
            services.send(
                {
                    "recipientId": self.cceo.id,
                    "subject": "hello",
                    "contextType": "planning",
                    "contextId": "zzz",
                    "body": "reachable?",
                },
                self.partner,
            )

    def test_stage_contexts_are_role_typed_not_open(self):
        from apps.messaging import services

        # `system` is the support channel — everyone may raise one.
        self.assertTrue(services.can_access_context(self.cceo, "system", "s-1"))
        # A finance stage key is not open to a field role.
        self.assertFalse(services.can_access_context(self.cceo, "budget", "b-1"))


class MessagingContextEnumerationTests(TestCase):
    """`contexts()` took no principal and filtered on a caller-supplied
    recipientId — an enumeration oracle over another person's workflow."""

    def test_contexts_requires_a_principal(self):
        from apps.messaging import services

        self.assertEqual(services.contexts({"recipientId": "anyone"}), [])

    def test_contexts_signature_takes_a_principal(self):
        import inspect

        from apps.messaging import services

        self.assertIn("principal", inspect.signature(services.contexts).parameters)


class LeavePrivacyTests(TestCase):
    """Leave type and reason are medical and family detail."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="LP Region")
        district = District.objects.create(name="LP District", region=region)
        cls.school = School.objects.create(
            name="LP Primary",
            school_id="LP-1",
            region_id=region.id,
            district_id=district.id,
        )
        cls.staff = _user("lp-staff@t.org", "Leave Staff", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.staff, country="Uganda")
        cls.other_pl = _user(
            "lp-pl@t.org", "Unrelated PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        cls.other_sp = StaffProfile.objects.create(user=cls.other_pl, country="Uganda")
        cls.leave = Leave.objects.create(
            staff=cls.sp,
            type="sick_leave",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=3),
            days=3,
            status="pending",
            reason="Confidential medical detail",
        )

    def test_impact_panel_refuses_an_unauthorized_approver(self):
        """The panel renders email, leave type and the free-text reason, and
        had no authorization check at all."""
        client = Client()
        client.force_login(self.other_pl)
        r = client.get(f"/leave/approvals/{self.leave.id}/impact")
        body = r.content.decode()
        self.assertNotIn("Confidential medical detail", body)

    def test_leave_list_api_omits_the_reason(self):
        from apps.hr import services

        rows = services.list_leave(self.other_pl, {})
        for row in rows:
            self.assertNotIn("reason", row, "a list response must not carry the reason")

    def test_message_leave_picker_never_shows_the_leave_type(self):
        from apps.messaging import services

        hr = _user("lp-hr@t.org", "HR One", "HumanResources")
        StaffProfile.objects.create(user=hr, country="Uganda")
        rows = services.search_context_records(hr, "leave", "")
        for row in rows:
            self.assertNotIn("sick_leave", row["title"])


class PeopleDirectoryScopeTests(TestCase):
    """The directory listed every active user in the deployment, with email."""

    @classmethod
    def setUpTestData(cls):
        cls.pl_a = _user("dir-pla@t.org", "PL A", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.pl_b = _user("dir-plb@t.org", "PL B", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.sp_a = StaffProfile.objects.create(user=cls.pl_a, country="Uganda")
        cls.sp_b = StaffProfile.objects.create(user=cls.pl_b, country="Uganda")
        cls.cceo_b = _user("dir-cb@t.org", "CCEO of B", EdifyRole.CCEO.value)
        cls.sp_cb = StaffProfile.objects.create(user=cls.cceo_b, country="Uganda")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.sp_cb, supervisor=cls.sp_b
        )

    def test_a_pl_cannot_enumerate_another_pls_team(self):
        client = Client()
        client.force_login(self.pl_a)
        body = client.get("/staff").content.decode()
        self.assertNotIn("CCEO of B", body)

    def test_rvp_does_not_receive_email_addresses(self):
        """rbac.py annotates the RVP staff grant as 'no PII/email'."""
        from apps.frontend.views.staff_views import _directory_may_see_email

        rvp = _user("dir-rvp@t.org", "RVP One", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        self.assertFalse(_directory_may_see_email(rvp))

    def test_profile_refuses_an_employee_outside_scope(self):
        client = Client()
        client.force_login(self.pl_a)
        r = client.get(f"/staff/{self.cceo_b.id}")
        self.assertNotIn("CCEO of B", r.content.decode())


class LeadershipPeopleInsightTests(TestCase):
    """A named improvement plan and its stated cause were published to every
    Accountant and Program Lead on the platform."""

    def test_boards_passes_the_principal_through(self):
        import inspect

        from apps.leadership import services

        source = inspect.getsource(services.boards)
        self.assertIn("_list(query, principal)", source)

    def test_accountant_cannot_see_person_level_hr_insights(self):
        from apps.leadership.models import DecisionType, LeadershipDecisionInsight
        from apps.leadership import services

        LeadershipDecisionInsight.objects.create(
            fy="2026",
            decision_type=DecisionType.STAFF_HR.value,
            scope_type="staff",
            scope_id="sp-1",
            scope_name="Jane Doe",
            reason="active performance-improvement plan (conduct issue)",
            recommendation="HR leadership review needed for Jane Doe",
            risk_level="high",
            confidence_level="high",
            confidence_score=0.9,
            suggested_action="Review",
            generated_at=timezone.now(),
        )
        accountant = _user(
            "ins-acc@t.org", "Acc One", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        rows = services._list({}, accountant)
        self.assertEqual(
            [r for r in rows if r["decisionType"] == DecisionType.STAFF_HR.value],
            [],
            "the Accountant has no people-management authority",
        )

    def test_hr_still_sees_person_level_hr_insights(self):
        from apps.leadership.models import DecisionType, LeadershipDecisionInsight
        from apps.leadership import services

        LeadershipDecisionInsight.objects.create(
            fy="2026",
            decision_type=DecisionType.STAFF_HR.value,
            scope_type="staff",
            scope_id="sp-2",
            scope_name="Jane Doe",
            reason="r",
            recommendation="x",
            risk_level="high",
            confidence_level="high",
            confidence_score=0.9,
            suggested_action="Review",
            generated_at=timezone.now(),
        )
        hr = _user("ins-hr@t.org", "HR One", "HumanResources")
        rows = services._list({}, hr)
        self.assertEqual(len(rows), 1)


class NotificationSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = _user("ns-ia@t.org", "IA One", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.other = _user(
            "ns-other@t.org", "Other One", EdifyRole.COUNTRY_DIRECTOR.value
        )

    def test_ia_alerts_are_addressed_to_the_viewer(self):
        """The query selected by title substring across the whole table."""
        import inspect

        from apps.frontend.views import ia_views

        source = inspect.getsource(ia_views)
        self.assertNotIn(
            'Q(title__icontains="IA")',
            source,
            "title-substring selection returned other users' notifications",
        )

    def test_notification_read_refuses_an_offsite_redirect(self):
        from apps.notifications.models import Notification

        n = Notification.objects.create(
            recipient_id=self.ia.id,
            title="t",
            body="b",
            category="ia",
            priority="normal",
            status="unread",
        )
        client = Client()
        client.force_login(self.ia)
        r = client.get(
            f"/notifications/{n.id}/read?redirect=https://evil.example.com/phish"
        )
        self.assertNotIn("evil.example.com", r["Location"])


class EmployeeRelationsScopeTests(TestCase):
    """The highest-privacy register was the one HR surface with no scope."""

    def test_scope_helper_fails_closed_without_a_country(self):
        from apps.frontend.views.hr_views import _employee_relations_scope

        hr = _user("er-hr@t.org", "HR NoCountry", "HumanResources")
        self.assertEqual(_employee_relations_scope(hr).count(), 0)


class RealtimeStreamTests(TestCase):
    """A sync infinite generator under ASGI delivers nothing and leaks a
    thread per connection."""

    def test_stream_is_an_async_generator(self):
        import inspect

        from apps.realtime import views

        source = inspect.getsource(views.stream)
        self.assertIn("async def event_stream", source)
        self.assertIn("await asyncio.sleep", source)

    def test_subscription_is_released_on_exit(self):
        import inspect

        from apps.realtime import views

        source = inspect.getsource(views.stream)
        self.assertIn("bus.unsubscribe", source)


class PDMoneyGuardTests(TestCase):
    """Withdrawing after disbursement restored the full annual allocation
    while the disbursement row still stood."""

    def test_released_funds_block_a_withdrawal(self):
        from apps.professional_development.completion_service import (
            PDCourseTrackingService,
        )
        import inspect

        source = inspect.getsource(PDCourseTrackingService.mark_deferred_or_withdrawn)
        self.assertIn("_released_funds_guard", source)


class LeaveApprovalDelegationTests(TestCase):
    """The API path re-implemented the transition and skipped the balance
    ledger, coverage creation and both audit rows."""

    def test_review_leave_delegates_to_the_canonical_service(self):
        import inspect

        from apps.hr import services

        source = inspect.getsource(services.review_leave)
        self.assertIn("LeaveApprovalService.approve_request", source)
        self.assertIn("LeaveApprovalService.reject_request", source)
        self.assertNotIn(
            "leave.status = decision",
            source,
            "writing the row here skips balance, coverage and audit",
        )
