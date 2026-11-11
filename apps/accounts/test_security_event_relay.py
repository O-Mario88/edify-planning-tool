"""Sign-ins through the Go gateway raise the same Admin alerts as the web's.

Go owns signing in (owner brief, 2026-11-11); when a sign-in there reaches the
failed-login alert threshold or escalates a lockout, the gateway relays the
event here with the internal service key, and the Admin security incident and
the administrators' notification are raised exactly as for a web sign-in.
"""

from __future__ import annotations

import json

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.admin_ops.models import SystemIncident
from apps.notifications.models import Notification

URL = "/api/auth/internal/security-events"
KEY = "test-internal-key-0123456789abcdef"


@override_settings(EDIFY_INTERNAL_KEY=KEY)
class SecurityEventRelayTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            email="admin@relay.test",
            name="Ada",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )
        self.cceo = User.objects.create(
            email="paul.n@relay.test",
            name="Paul",
            roles=["CCEO"],
            active_role="CCEO",
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

    def test_a_failed_login_streak_raises_the_admin_security_incident(self):
        response = self._post(
            {"kind": "failed_login_threshold", "userId": self.cceo.id, "streak": 5}
        )

        self.assertEqual(response.status_code, 200)
        incident = SystemIncident.objects.get()
        self.assertIn("pa**", incident.title)
        self.assertEqual(incident.detail["streak"], 5)
        self.assertNotIn("password", json.dumps(incident.detail).lower())

    def test_an_escalated_lockout_notifies_the_administrators(self):
        response = self._post({"kind": "lockout_escalated", "userId": self.cceo.id})

        self.assertEqual(response.status_code, 200)
        notice = Notification.objects.get(recipient_id=self.admin.id)
        self.assertIn("Paul", notice.title)
        self.assertEqual(notice.context_id, self.cceo.id)

    def test_without_the_internal_key_nothing_is_raised(self):
        response = self._post(
            {"kind": "failed_login_threshold", "userId": self.cceo.id, "streak": 5},
            key="wrong",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(SystemIncident.objects.exists())

    def test_the_endpoint_is_closed_while_no_key_is_configured(self):
        with override_settings(EDIFY_INTERNAL_KEY=""):
            response = self._post({"kind": "lockout_escalated", "userId": self.cceo.id})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Notification.objects.exists())

    def test_an_unknown_event_or_account_is_refused(self):
        self.assertEqual(
            self._post({"kind": "unlock_everyone", "userId": self.cceo.id}).status_code,
            400,
        )
        self.assertEqual(
            self._post({"kind": "lockout_escalated", "userId": "nobody"}).status_code,
            400,
        )
        self.assertEqual(
            self._post(
                {"kind": "failed_login_threshold", "userId": self.cceo.id, "streak": -1}
            ).status_code,
            400,
        )
