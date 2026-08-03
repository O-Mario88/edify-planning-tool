"""A deployment must be able to say what it is running.

The question this audit exists to answer — "is the approved design actually
being served to real users?" — had no mechanism behind it. Production exposed
no commit, no build time, and no identifier for the static bundle, so the only
available answer was to open a page and form an impression. An impression
cannot distinguish "the new build looks like this" from "this is the old
build", which is precisely the distinction that matters.

These tests pin the mechanism, not the opinion:

  * /api/health/build answers, unauthenticated, and is never cached;
  * it reports the static manifest digest, which is what makes two deployments
    comparable;
  * the service worker is served uncacheable, because a cached worker is the
    classic way a PWA pins itself to a dead build;
  * Geist is the single global UI font, so a second family cannot drift in.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from apps.core.build_info import UNKNOWN, build_info, static_manifest_digest

REPO = Path(settings.BASE_DIR)


class BuildEndpointTest(TestCase):
    def test_it_answers_without_a_session(self):
        """CI and deploy gates have no session. A provenance check that
        requires a login is a check nobody runs."""
        response = self.client.get("/api/health/build")
        self.assertEqual(response.status_code, 200)

    def test_it_reports_the_fields_a_release_check_compares(self):
        payload = json.loads(self.client.get("/api/health/build").content)
        for key in ("commit", "release", "buildTime", "staticManifestHash", "assets"):
            self.assertIn(key, payload)

    def test_it_is_never_cached(self):
        """A cached answer to "which build is this?" is worse than none: it is
        confidently wrong for as long as the cache lives."""
        response = self.client.get("/api/health/build")
        self.assertIn("no-store", response["Cache-Control"])

    def test_it_leaks_no_secret(self):
        body = self.client.get("/api/health/build").content.decode().lower()
        for forbidden in ("secret", "password", "token", "api_key", "database_url"):
            self.assertNotIn(forbidden, body)

    def test_it_never_invents_provenance(self):
        """Outside a built image there is no commit. It must say so rather
        than report something plausible."""
        info = build_info()
        self.assertIn(info["commit"], (UNKNOWN,) if not info["builtImage"] else ())
        self.assertIsInstance(info["staticManifestHash"], str)

    def test_it_uses_the_platform_runtime_commit_when_the_image_has_none(self):
        """App Platform bindables are runtime-only for Dockerfile builds."""
        build_info.cache_clear()
        self.addCleanup(build_info.cache_clear)
        with patch.dict(os.environ, {"GIT_COMMIT": "a" * 40}):
            self.assertEqual(build_info()["commit"], "a" * 40)

    def test_it_uses_the_platform_runtime_release_when_the_image_has_none(self):
        """Runtime provenance must identify the production release too."""
        build_info.cache_clear()
        self.addCleanup(build_info.cache_clear)
        with patch.dict(os.environ, {"RELEASE": "production-a" * 3}):
            self.assertEqual(build_info()["release"], "production-a" * 3)


class ReleaseVerifierUrlSafetyTest(SimpleTestCase):
    def test_it_refuses_non_http_urls_before_opening_them(self):
        with self.assertRaisesMessage(
            CommandError, "--url must be an absolute http:// or https:// URL"
        ):
            call_command("verify_release", url="file:///etc/passwd")

    def test_it_refuses_credentials_in_the_deployment_url(self):
        with self.assertRaisesMessage(
            CommandError, "--url must not contain credentials"
        ):
            call_command(
                "verify_release", url="https://operator:secret@example.invalid"
            )


class ImageBuildProvenanceTest(SimpleTestCase):
    def test_portable_writer_creates_the_file_the_runtime_requires(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "staticfiles.json"
            output = root / "build-info.json"
            manifest.write_bytes(b'{"paths":{}}')
            env = os.environ.copy()
            env.update({"GIT_COMMIT": "a" * 40, "RELEASE": "production-test"})

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.write_build_info",
                    "--manifest",
                    str(manifest),
                    "--output",
                    str(output),
                ],
                cwd=REPO,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["commit"], "a" * 40)
            self.assertEqual(payload["release"], "production-test")
            self.assertRegex(payload["build_time"], r"^\d{4}-\d{2}-\d{2}T")
            self.assertEqual(
                payload["static_manifest_hash"],
                "42c15180e501471c",
            )

    def test_dockerfile_uses_the_portable_writer_not_a_heredoc(self):
        dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("RUN python -m scripts.write_build_info", dockerfile)
        self.assertNotIn("RUN python - <<", dockerfile)

    def test_manifest_identity_ignores_json_key_order_and_whitespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(
                '{"paths":{"css/main.css":"css/main.abc.css"},"version":"1"}',
                encoding="utf-8",
            )
            second.write_text(
                '{\n  "version": "1",\n  "paths": {\n'
                '    "css/main.css": "css/main.abc.css"\n  }\n}',
                encoding="utf-8",
            )

            self.assertNotEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                static_manifest_digest(first),
                static_manifest_digest(second),
            )


class ServiceWorkerCacheTest(TestCase):
    def test_the_worker_is_not_cacheable(self):
        """A worker cached by the browser or the CDN keeps serving the app
        shell it was built with, so a correct deployment still reaches users
        as the previous build."""
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        cache_control = response.get("Cache-Control", "")
        self.assertTrue(
            "no-cache" in cache_control or "no-store" in cache_control,
            f"sw.js must not be cacheable, got Cache-Control: {cache_control!r}",
        )

    def test_the_worker_caches_only_versioned_static_assets(self):
        """Cache-first is only safe for content-hashed URLs.

        Two shapes are correct, and which one appears depends on whether the
        running configuration hashes asset names: with hashing, a fetch
        handler restricted to /static/; without it (as in tests and local
        development), no fetch handler at all, because anything cached would
        be served past the next edit. Both are asserted — what must never
        appear is a handler that caches pages or API responses, which is how
        a deploy stops reaching anyone who has visited before.
        """
        body = self.client.get("/sw.js").content.decode()
        has_fetch_handler = "addEventListener('fetch'" in body

        if has_fetch_handler:
            self.assertIn("/static/", body)
            for forbidden in ("/api/", "/dashboard", "text/html"):
                self.assertNotIn(
                    forbidden,
                    body,
                    f"the service worker must not handle {forbidden}",
                )

        # True in both shapes: old caches are dropped when a new worker takes
        # over, so a deploy cannot leave the previous build on disk.
        self.assertIn("caches.delete", body)
        self.assertIn("skipWaiting", body)


class GlobalFontTest(SimpleTestCase):
    """Geist is the single UI font.

    It is self-hosted deliberately (7401147a) after production was found
    falling back to a system font. The risk now is not the wrong font but a
    *second* font: one page importing another family is how a product starts
    looking like two products.
    """

    #: Families that may legitimately appear in a font stack: the fallbacks
    #: after Geist, and the generic keywords.
    ALLOWED = {
        "geist",
        "ui-sans-serif",
        "system-ui",
        "-apple-system",
        "blinkmacsystemfont",
        "segoe ui",
        "roboto",
        "helvetica neue",
        "arial",
        "sans-serif",
        "serif",
        "monospace",
        "ui-monospace",
        "sfmono-regular",
        "menlo",
        "monaco",
        "consolas",
        "liberation mono",
        "courier new",
        "noto color emoji",
        "apple color emoji",
        "segoe ui emoji",
        "segoe ui symbol",
        "noto sans",
        "inherit",
        "initial",
        "unset",
        "revert",
    }

    def test_geist_is_declared_and_self_hosted(self):
        fonts_css = (REPO / "static/css/fonts.css").read_text()
        self.assertIn("Geist", fonts_css)
        for weight in ("Geist-Variable.woff2",):
            self.assertTrue(
                (REPO / "static/fonts" / weight).exists(),
                f"{weight} must be committed — a CDN font is a third-party "
                "dependency on every page load",
            )

    #: Third-party stylesheets shipped as-is. Their internal font stacks are
    #: the vendor's business; rewriting them would fork the dependency, and
    #: they are scoped to their own widgets.
    VENDORED = ("leaflet",)

    def test_no_second_font_family_creeps_in(self):
        offenders = []
        for path in sorted((REPO / "static/css").rglob("*.css")):
            if any(v in path.name.lower() for v in self.VENDORED):
                continue
            source = path.read_text()
            for match in re.finditer(r"font-family\s*:\s*([^;}]+)", source, re.I):
                declaration = match.group(1)
                # A declaration is frequently `var(--font-sans, <stack>)`.
                # Drop the var() wrapper and keep the fallback stack inside it,
                # rather than treating "inherit)" as a font named "inherit)".
                declaration = re.sub(r"var\(\s*--[\w-]+\s*,?", "", declaration)
                declaration = declaration.replace(")", "")
                declaration = re.sub(r"!important", "", declaration, flags=re.I)
                for family in declaration.split(","):
                    name = family.strip().strip("\"'").lower()
                    if not name or name.startswith("--"):
                        continue
                    if name not in self.ALLOWED:
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(
            sorted(set(offenders)),
            [],
            "one product, one typeface — add to ALLOWED only with a reason",
        )
