"""A cold Country Director dashboard paints its shell first (P-2).

Building the CD dashboard takes seconds at country scale. When its snapshot
is not built yet, the page now renders the header, filters and phone header
at once and fetches the body from the same address, the way the filter form
already does (owner-approved 2026-09-25). These tests hold what makes that
safe:
- a warm dashboard renders whole, byte for byte as with deferral off;
- the body that arrives is the body the filter form would fetch;
- the phone header's action arrives with it, in place;
- with caching off (the test settings) nothing is deferred.
"""

from __future__ import annotations

import re

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.analytics import test_cd_command_center as fixture

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CACHED = dict(CACHES=LOCMEM, DASHBOARD_CACHE_SECONDS=300, COUNTRY_MAP_CACHE_SECONDS=300)
LOADER = "data-cd-dashboard-loader"


def _stable(html: str) -> str:
    """The page without its per-request tokens."""
    html = re.sub(r'nonce="[^"]*"', "", html)
    # CSRF tokens (form fields, meta tag, hx-headers JSON) are 64 characters.
    return re.sub(r"\b[A-Za-z0-9]{64}\b", "<token>", html)


def _header(html: str) -> str:
    match = re.search(r"<header class=\"mobile-role-home.*?</header>", html, re.S)
    return _stable(match.group(0))


class CDDashboardDeferredBodyTest(TestCase):
    setUp = fixture.CDCommandCenterTest.setUp
    _staff = fixture.CDCommandCenterTest._staff
    _school = fixture.CDCommandCenterTest._school
    _ssa = fixture.CDCommandCenterTest._ssa
    _act = fixture.CDCommandCenterTest._act

    def _get(self, url, **headers):
        self.client.force_login(self.cd)
        response = self.client.get(url, **headers)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def _fill(self, view):
        return self._get(
            f"/dashboard?view={view}&fill=1",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="cd-dashboard-body",
        )

    def test_caching_off_never_defers(self):
        html = self._get("/dashboard?view=operations")
        self.assertNotIn(LOADER, html)
        self.assertIn("Country Target Progress", html)

    @override_settings(**CACHED)
    def test_a_cold_dashboard_paints_its_shell_then_its_body(self):
        cache.clear()
        for view in ("map", "operations"):
            with self.subTest(view=view):
                cache.clear()
                shell = self._get(f"/dashboard?view={view}")
                self.assertIn(LOADER, shell)
                self.assertNotIn("Country Target Progress", shell)
                # The header's counts are real already.
                self.assertIn("2 PLs · 2 CCEOs · 3 schools", shell)
                # The phone header holds its action's place, then gets it.
                self.assertIn('id="cd-role-home"', shell)
                self.assertNotIn("data-mobile-primary-action", shell)
                self.assertIn(
                    'class="mobile-role-home__action invisible" aria-hidden="true"',
                    shell,
                )

                filled = self._fill(view)
                self.assertIn("Country Target Progress", filled)
                self.assertIn('id="cd-role-home" hx-swap-oob="true"', filled)
                self.assertIn("data-mobile-primary-action", filled)

                warm = self._get(f"/dashboard?view={view}")
                self.assertNotIn(LOADER, warm)

    @override_settings(**CACHED)
    def test_the_arriving_body_is_the_body_the_filters_fetch(self):
        for view in ("map", "operations"):
            with self.subTest(view=view):
                cache.clear()
                self._get(f"/dashboard?view={view}")
                filled = self._fill(view)
                body = self._get(
                    f"/dashboard?view={view}",
                    HTTP_HX_REQUEST="true",
                    HTTP_HX_TARGET="cd-dashboard-body",
                )
                self.assertTrue(
                    _stable(filled).strip().startswith(_stable(body).strip())
                )

    @override_settings(**CACHED)
    def test_the_arriving_phone_header_is_the_warm_pages_header(self):
        cache.clear()
        self._get("/dashboard?view=map")
        filled = _header(self._fill("map")).replace(' hx-swap-oob="true"', "")
        self.assertEqual(filled, _header(self._get("/dashboard?view=map")))

    def test_a_warm_dashboard_renders_as_it_did_before(self):
        for view in ("map", "operations"):
            with self.subTest(view=view):
                before = self._get(f"/dashboard?view={view}")
                with override_settings(**CACHED):
                    cache.clear()
                    self._get(f"/dashboard?view={view}")
                    self._fill(view)
                    warm = self._get(f"/dashboard?view={view}")
                self.assertEqual(
                    _stable(warm).replace(' id="cd-role-home"', ""),
                    _stable(before).replace(' id="cd-role-home"', ""),
                )
