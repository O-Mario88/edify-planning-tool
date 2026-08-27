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


class ReadinessNamesADegradedCacheTest(TestCase):
    """It used to answer 200 {"status": "ok"} with Redis genuinely down.

    That was reproduced against a running instance: the cache had fallen back to
    a per-process LocMemCache, so the login rate limit had become per-worker and
    cached figures had begun to differ between workers — and the only place
    either was visible was a page a human had to open.
    """

    def setUp(self):
        from config import urls

        urls._cache_probe["at"] = 0.0  # the probe memoises for 30s
        self.addCleanup(lambda: urls._cache_probe.update({"at": 0.0}))

    def _get(self):
        return self.client.get("/api/health/ready").json()

    def test_an_unreachable_cache_is_reported_as_degraded(self):
        with mock.patch("django.core.cache.cache.get", return_value=None):
            body = self._get()
        self.assertEqual(body["cache"], "down")
        self.assertEqual(
            body["status"],
            "degraded",
            "readiness reported healthy while its cache was unreachable",
        )

    def test_a_raising_cache_does_not_break_the_probe(self):
        """A probe that 500s is worse than the failure it was watching for."""
        with mock.patch(
            "django.core.cache.cache.set", side_effect=RuntimeError("no redis")
        ):
            response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cache"], "down")

    def test_a_degraded_cache_does_not_take_the_instance_out_of_rotation(self):
        """Redis is shared, so a 503 here would pull every instance at once and
        turn a degradation into a full outage."""
        with mock.patch("django.core.cache.cache.get", return_value=None):
            response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 200)

    def test_the_database_still_decides_the_status_code(self):
        with mock.patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=OperationalError("connection refused"),
        ):
            response = self.client.get("/api/health/ready")
        self.assertEqual(response.status_code, 503)

    def test_the_probe_is_memoised(self):
        """It runs every few seconds on every instance; an un-memoised probe is
        a load generator aimed at the dependency it is protecting."""
        with mock.patch(
            "django.core.cache.cache.set", wraps=None, return_value=None
        ) as probe:
            self.client.get("/api/health/ready")
            self.client.get("/api/health/ready")
            self.client.get("/api/health/ready")
        self.assertEqual(
            probe.call_count, 1, "the cache was probed on every readiness call"
        )


class ContainerProbeTest(SimpleTestCase):
    def test_the_dockerfile_healthcheck_uses_liveness(self):
        """A HEALTHCHECK failure restarts the container, so it must not be
        wired to a probe that fails when a dependency does."""
        dockerfile = (Path(settings.BASE_DIR) / "Dockerfile").read_text()
        self.assertIn("/api/health/live", dockerfile)
        self.assertNotIn('/api/health"', dockerfile)
