"""The Content-Security-Policy has to keep matching what the app loads.

A CSP is a second line of defence behind escaping: it decides what injected
markup is allowed to *do* if it ever lands. The failure mode is not that the
policy is too weak — it is that the policy and the templates drift apart, and
the symptom of a missing origin is a component that silently renders unstyled
or inert rather than an error anyone notices.

So this test derives the truth from the templates rather than restating the
policy: every external origin any template loads must be permitted, and the
directives that make the policy worth having must still be there.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from apps.core.middleware import ContentSecurityPolicyMiddleware

ROOT = Path(settings.BASE_DIR)
ORIGIN = re.compile(r"https://[a-z0-9.-]+\.[a-z]{2,}")


def _origins_used() -> set[str]:
    found = set()
    for folder in ("templates", "static/js"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in (".html", ".js"):
                continue
            # static/js/vendor holds the self-hosted third-party bundles. Their
            # minified source mentions origins they do not fetch — Alpine names
            # alpinejs.dev in a warning string, FullCalendar links its own docs
            # — and treating those as "origins this app loads" would push four
            # URLs into the CSP that nothing ever requests. What the page
            # actually loads is the <script src> in the template, which is
            # scanned above and is same-origin.
            if "/js/vendor/" in path.as_posix():
                continue
            found.update(ORIGIN.findall(path.read_text(errors="ignore")))
    return found


class PolicyCoversWhatWeLoadTest(SimpleTestCase):
    def test_every_external_origin_is_permitted(self):
        policy = ContentSecurityPolicyMiddleware.POLICY
        missing = sorted(o for o in _origins_used() if o not in policy)
        self.assertEqual(
            missing,
            [],
            "these origins are loaded by a template but absent from the CSP, "
            f"so the browser will refuse them: {missing}",
        )

    def test_the_policy_is_not_permitted_to_become_a_no_op(self):
        """A policy of `default-src *` would pass the test above and protect
        nothing. These are the directives doing the actual work."""
        policy = ContentSecurityPolicyMiddleware.POLICY
        for directive in (
            "default-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            "connect-src 'self'",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, policy)

    def test_no_wildcard_source(self):
        self.assertNotIn("*", ContentSecurityPolicyMiddleware.POLICY)


class PolicyIsServedTest(TestCase):
    def test_every_response_carries_the_header(self):
        for url in ("/login", "/api/health/live"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn("Content-Security-Policy", response.headers)

    def test_an_error_page_carries_it_too(self):
        """Error pages are the ones most likely to be reached with a crafted
        URL, so they are the ones that least deserve to be uncovered."""
        response = self.client.get("/definitely-not-a-real-route-xyz")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Content-Security-Policy", response.headers)

    def test_a_view_that_sets_its_own_policy_keeps_it(self):
        """The middleware fills a gap; it does not overrule a view that had a
        stricter need and said so."""
        from django.http import HttpResponse

        stricter = "default-src 'none'"

        def view(_request):
            response = HttpResponse("ok")
            response["Content-Security-Policy"] = stricter
            return response

        middleware = ContentSecurityPolicyMiddleware(view)
        self.assertEqual(
            middleware(None)["Content-Security-Policy"],
            stricter,
        )

    def test_a_response_without_one_is_given_the_default(self):
        from django.http import HttpResponse

        middleware = ContentSecurityPolicyMiddleware(lambda _r: HttpResponse("ok"))
        self.assertEqual(
            middleware(None)["Content-Security-Policy"],
            ContentSecurityPolicyMiddleware.POLICY,
        )


class ClickjackingTest(TestCase):
    def test_framing_is_refused_two_ways(self):
        """frame-ancestors is the modern control and X-Frame-Options the
        fallback for anything that predates it. Both, because the cost is a
        header and the failure is someone framing the whole product."""
        response = Client().get("/login")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(response.get("X-Frame-Options"), "DENY")


class SecurityPostureHonestyTest(TestCase):
    """A posture report is read as assurance, so it must not overstate.

    `fieldEncryptionConfigured: true` said, to anyone reading it, that
    restricted fields were encrypted at rest. They were not — apps.core.crypto
    exposes encrypt_field/decrypt_field and no model calls either. Only the key
    was configured, which is the precondition for the control rather than the
    control.
    """

    def test_the_report_does_not_claim_fields_are_encrypted(self):
        from apps.security.services import summary

        report = summary()
        self.assertNotIn(
            "fieldEncryptionConfigured",
            report,
            "that key reads as 'fields are encrypted' and no field is",
        )
        self.assertIn("fieldEncryptionKeyConfigured", report)

    def test_the_encrypted_field_count_matches_reality(self):
        """If someone starts encrypting a field, this is what makes them
        register it — and the number stops being zero honestly."""
        from apps.core import crypto
        from apps.security.services import ENCRYPTED_FIELDS, summary

        self.assertEqual(summary()["encryptedFieldCount"], len(ENCRYPTED_FIELDS))

        callers = []
        for path in (Path(settings.BASE_DIR) / "apps").rglob("*.py"):
            if "crypto.py" in path.name or "test" in path.name:
                continue
            source = path.read_text(errors="ignore")
            if "encrypt_field(" in source or "encrypt_nullable(" in source:
                callers.append(str(path.relative_to(Path(settings.BASE_DIR))))
        self.assertEqual(
            len(callers) > 0,
            len(ENCRYPTED_FIELDS) > 0,
            f"ENCRYPTED_FIELDS says {len(ENCRYPTED_FIELDS)} but the encryption "
            f"helpers are called from {callers}",
        )
        self.assertTrue(hasattr(crypto, "encrypt_field"))

    def test_the_mfa_claim_matches_a_working_flow(self):
        """`mfaImplemented` was False while there was nothing behind it, because
        `mfaEnabledUsers: 0` on its own reads as poor adoption rather than
        absence. It now says True, so this checks the claim against behaviour
        rather than against the constant: an enrolled account must actually be
        stopped at a code prompt."""
        from django.contrib.auth import get_user_model
        from django.test import Client

        from apps.security.services import summary

        self.assertIs(summary()["mfaImplemented"], True)

        user = get_user_model().objects.create_user(
            email="posture-mfa@edify.test",
            password="posture-password-1",
            name="Posture",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        user.mfa_enabled = True
        user.save(update_fields=["mfa_enabled"])

        client = Client()
        client.post(
            "/login",
            {"email": user.email, "password": "posture-password-1"},
        )
        self.assertNotIn(
            "_auth_user_id",
            client.session,
            "the posture report claims MFA is implemented but a password "
            "alone still signs someone in",
        )

    def test_enrolment_is_reported_separately_from_implementation(self):
        """ "Implemented" says nothing about how many accounts are behind it,
        and reading one as the other is how a posture report overstates."""
        from apps.security.services import summary

        report = summary()
        self.assertIn("mfaEnabledUsers", report)
        self.assertIn("mfaRequiredForAll", report)
