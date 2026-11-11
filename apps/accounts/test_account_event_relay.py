"""Account changes made in the Go gateway are followed up here exactly as
after a change on the web (owner brief, 2026-11-11): a role change re-prices
the person's planned days; a removed organisation login goes back to be set
up again, and the person's web sessions end."""

from __future__ import annotations

import json
from unittest import mock

from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.partners.models import Partner, PartnerUserSetupStatus

URL = "/api/auth/internal/account-events"
KEY = "test-internal-key-0123456789abcdef"


@override_settings(EDIFY_INTERNAL_KEY=KEY)
class AccountEventRelayTest(TestCase):
    def setUp(self):
        self.person = User.objects.create(
            email="partner.login@relay.test",
            name="Hope Partners",
            roles=["PartnerAdmin"],
            active_role="PartnerAdmin",
            is_active=True,
            status="active",
        )

    def _post(self, payload, key=KEY):
        return self.client.post(
            URL,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-Edify-Internal-Key": key},
        )

    def test_a_role_change_re_prices_the_persons_planned_days(self):
        with mock.patch(
            "apps.accounts.account_event_relay._reprice_planned_days"
        ) as reprice:
            response = self._post({"kind": "roles_changed", "userId": self.person.id})

        self.assertEqual(response.status_code, 200)
        reprice.assert_called_once_with(self.person.id)

    def test_a_removed_login_releases_its_organisation_and_ends_web_sessions(self):
        partner = Partner.objects.create(name="Hope Partners", user=self.person)
        session = SessionStore()
        session["_auth_user_id"] = self.person.id
        session.create()
        # The gateway has already removed the account.
        User.all_objects.filter(id=self.person.id).update(
            deleted_at=timezone.now(), is_active=False, status="disabled"
        )

        response = self._post({"kind": "account_deleted", "userId": self.person.id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["partnerLoginOf"], [partner.id])
        partner.refresh_from_db()
        self.assertIsNone(partner.user_id)
        self.assertEqual(partner.user_setup_status, PartnerUserSetupStatus.PENDING)
        self.assertFalse(
            Session.objects.filter(session_key=session.session_key).exists()
        )

    def test_an_account_that_was_not_removed_is_not_released(self):
        partner = Partner.objects.create(name="Hope Partners", user=self.person)

        response = self._post({"kind": "account_deleted", "userId": self.person.id})

        self.assertEqual(response.status_code, 400)
        partner.refresh_from_db()
        self.assertEqual(partner.user_id, self.person.id)

    def test_without_the_internal_key_nothing_happens(self):
        with mock.patch(
            "apps.accounts.account_event_relay._reprice_planned_days"
        ) as reprice:
            response = self._post(
                {"kind": "roles_changed", "userId": self.person.id}, key="wrong"
            )

        self.assertEqual(response.status_code, 403)
        reprice.assert_not_called()


@override_settings(EDIFY_INTERNAL_KEY=KEY)
class StaffChangedRelayTest(TestCase):
    def test_a_staff_or_team_change_files_cached_analytics_afresh(self):
        from django.core.cache import cache

        from apps.hr.accountability_cache import KEY as REVISION

        cache.set(REVISION, "before", timeout=None)

        response = self.client.post(
            URL,
            data=json.dumps({"kind": "staff_changed"}),
            content_type="application/json",
            headers={"X-Edify-Internal-Key": KEY},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(cache.get(REVISION), "before")


@override_settings(EDIFY_INTERNAL_KEY=KEY)
class ActingNoticeRelayTest(TestCase):
    """Go makes, cancels and moves acting appointments; the notifications
    the web sends after each still go from here."""

    def _post(self, payload):
        return self.client.post(
            URL,
            data=json.dumps(payload),
            content_type="application/json",
            headers={"X-Edify-Internal-Key": KEY},
        )

    def test_each_acting_notice_sends_the_webs_own_notification(self):
        for kind, sender in (
            ("acting_appointed", "_notify_appointed"),
            ("acting_cancelled", "_notify_cancelled"),
            ("acting_rescheduled", "_notify_rescheduled"),
        ):
            with (
                self.subTest(kind=kind),
                mock.patch(f"apps.acting.services.{sender}") as notify,
            ):
                response = self._post({"kind": kind, "subjectId": "appointment-1"})

                self.assertEqual(response.status_code, 200)
                notify.assert_called_once_with("appointment-1")

    def test_a_notice_without_its_appointment_is_refused(self):
        response = self._post({"kind": "acting_appointed"})

        self.assertEqual(response.status_code, 400)
