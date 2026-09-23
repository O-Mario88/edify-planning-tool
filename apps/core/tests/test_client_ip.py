"""Where the client's address comes from (apps.core.client_ip).

Every rate limit and audit row used to take the leftmost X-Forwarded-For
entry, which is whatever the client sent: rotating it bought a fresh login
window per request (AUD-010 bypassed). These pin that the address comes from a
trusted hop — the platform's own header, or X-Forwarded-For counted from the
right — and otherwise from the peer that opened the connection.
"""

from __future__ import annotations

import uuid

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from apps.core.client_ip import client_ip
from apps.core.throttling import (
    RouteRateThrottle,
    reset_throttle_state,
    throttle_by_ip,
)


def _peer() -> str:
    """A client address no other test (or parallel worker) shares."""
    return "10.%d.%d.%d" % tuple(uuid.uuid4().bytes[:3])


class ClientIpTest(SimpleTestCase):
    rf = RequestFactory()

    def test_without_a_trusted_source_the_peer_is_the_client(self):
        request = self.rf.get("/", REMOTE_ADDR="192.0.2.10")
        self.assertEqual(client_ip(request), "192.0.2.10")

    def test_an_untrusted_forwarded_header_is_ignored(self):
        request = self.rf.get(
            "/", HTTP_X_FORWARDED_FOR="203.0.113.66", REMOTE_ADDR="192.0.2.10"
        )
        self.assertEqual(client_ip(request), "192.0.2.10")

    @override_settings(TRUSTED_PROXY_HOPS=1)
    def test_forwarded_addresses_are_counted_from_the_right(self):
        request = self.rf.get(
            "/",
            HTTP_X_FORWARDED_FOR="203.0.113.66, 198.51.100.4",
            REMOTE_ADDR="192.0.2.10",
        )
        # The entry our one proxy appended, not the client's own claim.
        self.assertEqual(client_ip(request), "198.51.100.4")

    @override_settings(TRUSTED_PROXY_HOPS=2)
    def test_more_hops_than_entries_takes_the_leftmost_that_exists(self):
        request = self.rf.get(
            "/", HTTP_X_FORWARDED_FOR="198.51.100.4", REMOTE_ADDR="192.0.2.10"
        )
        self.assertEqual(client_ip(request), "198.51.100.4")

    @override_settings(CLIENT_IP_HEADER="HTTP_DO_CONNECTING_IP")
    def test_the_platform_header_wins_over_forwarded_for(self):
        request = self.rf.get(
            "/",
            HTTP_DO_CONNECTING_IP="198.51.100.4",
            HTTP_X_FORWARDED_FOR="203.0.113.66, 10.244.0.1",
            REMOTE_ADDR="10.244.0.2",
        )
        self.assertEqual(client_ip(request), "198.51.100.4")

    @override_settings(CLIENT_IP_HEADER="HTTP_DO_CONNECTING_IP", TRUSTED_PROXY_HOPS=1)
    def test_values_that_are_not_addresses_are_skipped(self):
        request = self.rf.get(
            "/",
            HTTP_DO_CONNECTING_IP="not-an-address",
            HTTP_X_FORWARDED_FOR="also-not-one",
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertEqual(client_ip(request), "192.0.2.10")
        self.assertIsNone(client_ip(self.rf.get("/", REMOTE_ADDR="")))


class ThrottleIdentityTest(SimpleTestCase):
    rf = RequestFactory()

    def _exhaust(self, name, limit, request_for):
        """True if the window refuses the request after `limit` allowed ones."""
        for attempt in range(limit):
            self.assertTrue(
                throttle_by_ip(request_for(attempt), name=name, limit=limit),
                f"attempt {attempt} was refused early",
            )
        return not throttle_by_ip(request_for(limit), name=name, limit=limit)

    def _name(self):
        # A window name no other test shares, so nothing needs resetting.
        return f"test.client-ip.{uuid.uuid4().hex}"

    def test_a_rotating_spoofed_entry_does_not_reset_the_window(self):
        peer = _peer()

        def spoofed(attempt):
            return self.rf.post(
                "/login", HTTP_X_FORWARDED_FOR=f"203.0.113.{attempt}", REMOTE_ADDR=peer
            )

        self.assertTrue(self._exhaust(self._name(), 3, spoofed))

    @override_settings(TRUSTED_PROXY_HOPS=1)
    def test_a_spoofed_leftmost_entry_behind_a_proxy_changes_nothing(self):
        def spoofed(attempt):
            return self.rf.post(
                "/login",
                HTTP_X_FORWARDED_FOR=f"203.0.113.{attempt}, 198.51.100.4",
                REMOTE_ADDR="10.244.0.2",
            )

        self.assertTrue(self._exhaust(self._name(), 3, spoofed))

    @override_settings(TRUSTED_PROXY_HOPS=1)
    def test_the_proxy_appended_entry_is_the_identity(self):
        name = self._name()

        def from_client(address):
            return self.rf.post(
                "/login",
                HTTP_X_FORWARDED_FOR=f"203.0.113.9, {address}",
                REMOTE_ADDR="10.244.0.2",
            )

        self.assertTrue(self._exhaust(name, 2, lambda _: from_client("198.51.100.4")))
        # A different client behind the same proxy has its own window.
        self.assertTrue(throttle_by_ip(from_client("198.51.100.5"), name=name, limit=2))

    @override_settings(CLIENT_IP_HEADER="HTTP_DO_CONNECTING_IP")
    def test_production_keys_on_the_platform_header(self):
        name = self._name()

        def request_for(connecting, spoof="203.0.113.1"):
            return self.rf.post(
                "/login",
                HTTP_DO_CONNECTING_IP=connecting,
                HTTP_X_FORWARDED_FOR=f"{spoof}, 10.244.0.1",
                REMOTE_ADDR="10.244.0.2",
            )

        self.assertTrue(
            self._exhaust(
                name, 2, lambda n: request_for("198.51.100.4", spoof=f"203.0.113.{n}")
            )
        )
        self.assertTrue(throttle_by_ip(request_for("198.51.100.5"), name=name, limit=2))

    def test_with_no_header_the_key_is_the_peer(self):
        name = self._name()
        peer = _peer()
        self.assertTrue(
            self._exhaust(name, 2, lambda _: self.rf.post("/login", REMOTE_ADDR=peer))
        )
        self.assertTrue(
            throttle_by_ip(
                self.rf.post("/login", REMOTE_ADDR=_peer()), name=name, limit=2
            )
        )

    def test_the_api_throttle_uses_the_same_identity(self):
        request = self.rf.post(
            "/api/auth/login",
            HTTP_X_FORWARDED_FOR="203.0.113.66",
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertEqual(RouteRateThrottle().get_ident(request), "192.0.2.10")


class LoginThrottleEndToEndTest(TestCase):
    """The done-when: rotating a fake X-Forwarded-For no longer resets the
    web sign-in throttle."""

    @override_settings(RATE_LIMIT_LOGIN_PER_MIN=3)
    def test_rotating_a_fake_forwarded_for_still_hits_the_login_limit(self):
        peer = _peer()
        self.client.defaults["REMOTE_ADDR"] = peer
        reset_throttle_state([f"auth.login:{peer}"])
        self.addCleanup(reset_throttle_state, [f"auth.login:{peer}"])
        statuses = [
            self.client.post(
                "/login",
                {"email": f"nobody{n}@example.test", "password": "wrong"},
                HTTP_X_FORWARDED_FOR=f"203.0.113.{n}",
            ).status_code
            for n in range(4)
        ]
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)

    def test_the_audit_context_records_the_trusted_address(self):
        from apps.core.request_context import get_request_context

        seen = {}

        def view(request):
            from django.http import HttpResponse

            seen["ip"] = get_request_context().ip_address
            return HttpResponse("ok")

        from apps.core.middleware import RequestContextMiddleware

        RequestContextMiddleware(view)(
            RequestFactory().get(
                "/", HTTP_X_FORWARDED_FOR="203.0.113.66", REMOTE_ADDR="192.0.2.10"
            )
        )
        self.assertEqual(seen["ip"], "192.0.2.10")
