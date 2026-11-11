"""The Go gateway reads the same acting policy as this application.

Go owns acting appointments (owner brief, 2026-11-11); it embeds
platform/backend/internal/acting/acting_policy.json. This test fails the
moment apps.acting.policy changes without the file being exported again
(python manage.py export_acting_policy), and checks that what the export
says an appointment grants is what an appointment made here records.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from apps.acting import services
from apps.acting.management.commands.export_acting_policy import (
    EXPORT_PATH,
    granted,
    rendered,
)
from apps.acting.policy import ACTING_ROLES


class ActingPolicyExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_policy_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The acting policy changed; run `python manage.py export_acting_policy` "
            "so the Go gateway appoints by the same one.",
        )

    def test_the_export_records_what_an_appointment_here_records(self):
        seat = SimpleNamespace(
            id="seat", user_id="u", user=SimpleNamespace(name="L"), country="UG"
        )
        with mock.patch.object(services, "_seat_members", return_value=[]):
            for entry in ACTING_ROLES.values():
                snapshot = services.grant_snapshot(entry, seat)
                for key, value in granted(entry).items():
                    self.assertEqual(snapshot[key], value, f"{entry.key}: {key}")
