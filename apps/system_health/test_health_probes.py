"""Liveness and readiness answer different questions, so they are separate.

There was one probe, `/api/health`, which checked the database — and the
container HEALTHCHECK pointed at it. Docker marks a container unhealthy when
that fails and orchestrators restart it, so a database blip would have
restarted every instance at once: no help to the database, and it destroys the
capacity that would have served traffic the moment the database returned.

The split is the fix. Liveness asks "is this process alive", and its failure
means restart me. Readiness asks "can I serve traffic right now", and its
failure only means take me out of rotation.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase


class LivenessTest(TestCase):
    def test_it_answers_ok(self):
        response = self.client.get("/api/health/live")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_it_survives_the_database_being_down(self):
        """The whole point. A live process with a dead dependency must not be
        killed — restarting it does not bring the database back."""
        with mock.patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=OperationalError("connection refused"),
        ):
            response = self.client.get("/api/health/live")
        self.assertEqual(response.status_code, 200)

    def test_it_touches_no_database(self):
        with self.assertNumQueries(0):
            self.client.get("/api/health/live")


class ReadinessTest(TestCase):
    def test_it_answers_ok_when_the_database_is_reachable(self):
        response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["db"], "up")

    def test_it_refuses_traffic_when_the_database_is_down(self):
        with mock.patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=OperationalError("connection refused"),
        ):
            response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["db"], "down")

    def test_it_stays_cheap(self):
        """A readiness probe runs every few seconds on every instance. Anything
        expensive here is a load generator aimed at the dependency it is meant
        to be protecting."""
        with self.assertNumQueries(1):
            self.client.get("/api/health/ready")

    def test_the_original_path_keeps_its_behaviour(self):
        """Deploy gates already point at /api/health; changing what it means
        would silently alter what they are gating on."""
        self.assertEqual(self.client.get("/api/health").status_code, 200)


class ContainerProbeTest(SimpleTestCase):
    def test_the_dockerfile_healthcheck_uses_liveness(self):
        """A HEALTHCHECK failure restarts the container, so it must not be
        wired to a probe that fails when a dependency does."""
        dockerfile = (Path(settings.BASE_DIR) / "Dockerfile").read_text()
        self.assertIn("/api/health/live", dockerfile)
        self.assertNotIn('/api/health"', dockerfile)
