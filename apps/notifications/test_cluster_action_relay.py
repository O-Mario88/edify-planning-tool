"""Cluster Action notices reach Edify's own notifications (owner brief,
2026-11-11, parts 5.2 and 15: "Use the existing notification system").

The Go gateway owns the Cluster Action Register and decides who is told what;
it relays each notice here with the internal service key, and the notice is
written through notify_from_person, so the bell, push and email follow as for
any other. A notice relayed twice is one notification.
"""

from __future__ import annotations

import json

from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.notifications.models import Notification

URL = "/api/notifications/internal/cluster-action-notices"
KEY = "test-internal-key-0123456789abcdef"


def _notice(**extra):
    return {
        "noticeId": "0b7d4b7e-9a51-4f6b-8d0e-1c2b3a4d5e6f",
        "recipientId": "",
        "senderId": "",
        "event": "cluster_action_submitted",
        "title": "New Cluster Support Request",
        "body": "Cluster B: your Cluster Leader has requested training for Hope Primary.",
        "targetRoute": "/clusters/c1",
        "contextRef": "CA-7K3P9Q",
        **extra,
    }


@override_settings(EDIFY_INTERNAL_KEY=KEY)
class ClusterActionRelayTest(TestCase):
    def setUp(self):
        self.cceo = User.objects.create(
            email="cceo@relay.test",
            name="Paul",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        self.leader = User.objects.create(
            email="leader@relay.test",
            name="Grace",
            roles=["ClusterLeader"],
            active_role="ClusterLeader",
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

    def test_a_notice_becomes_an_ordinary_notification(self):
        response = self._post(
            _notice(recipientId=self.cceo.id, senderId=self.leader.id)
        )
        self.assertEqual(response.status_code, 201, response.content)
        note = Notification.objects.get(recipient_id=self.cceo.id)
        self.assertEqual(note.title, "New Cluster Support Request")
        self.assertEqual(note.context_type, "cluster_action")
        self.assertEqual(note.context_id, "CA-7K3P9Q")
        self.assertEqual(note.target_route, "/clusters/c1")
        self.assertEqual(note.sender_id, self.leader.id)
        self.assertTrue(note.action_required)

    def test_a_notice_relayed_twice_is_one_notification(self):
        payload = _notice(recipientId=self.cceo.id, senderId=self.leader.id)
        self._post(payload)
        again = self._post(payload)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(recipient_id=self.cceo.id).count(), 1
        )
        self.assertEqual(
            Notification.objects.get(recipient_id=self.cceo.id).reminder_count, 0
        )

    def test_a_reminder_tells_the_same_person_again(self):
        self._post(_notice(recipientId=self.cceo.id, senderId=self.leader.id))
        self._post(
            _notice(
                recipientId=self.cceo.id,
                senderId=self.leader.id,
                noticeId="1c8e5c8f-0b62-4a7c-9e1f-2d3c4b5e6f70",
            )
        )
        note = Notification.objects.get(recipient_id=self.cceo.id)
        self.assertEqual(note.reminder_count, 1)

    def test_the_endpoint_is_closed_without_the_key(self):
        self.assertEqual(
            self._post(_notice(recipientId=self.cceo.id), key="wrong").status_code, 403
        )
        self.assertEqual(
            self._post(_notice(recipientId=self.cceo.id), key="").status_code, 403
        )
        with override_settings(EDIFY_INTERNAL_KEY=""):
            self.assertEqual(
                self._post(_notice(recipientId=self.cceo.id)).status_code, 404
            )
        self.assertFalse(Notification.objects.exists())

    def test_an_unknown_or_inactive_recipient_is_refused(self):
        self.cceo.is_active = False
        self.cceo.save(update_fields=["is_active"])
        self.assertEqual(self._post(_notice(recipientId=self.cceo.id)).status_code, 400)
        self.assertEqual(self._post(_notice(recipientId="nobody")).status_code, 400)
        self.assertEqual(
            self._post(_notice(recipientId=self.leader.id, title="")).status_code, 400
        )
        self.assertFalse(Notification.objects.exists())
