"""
Management command: verify_release

Ask a live deployment what it is serving, and compare it against what this
working tree builds. Exits non-zero when they differ.

This exists because "did the approved design reach production?" was being
answered by looking at a page. A page can look right while serving a stale
bundle, and it can look wrong for reasons that have nothing to do with the
release. Neither impression is evidence. Two manifest digests are.

    python manage.py verify_release --url https://www.edifyplanning.app
    python manage.py verify_release --url https://... --expect-commit 017c4fdd

What it checks:

  * the deployment answers /api/health/build at all (a deployment that cannot
    say what it is running is itself the finding);
  * its static manifest digest equals this tree's;
  * the hashed asset filenames it reports equal this tree's, per asset, so a
    mismatch names the file rather than just failing;
  * every reported asset is actually fetchable, with a CSS content type — a
    manifest entry pointing at a 404 is the exact failure that makes a
    correct-looking build serve an unstyled page;
  * the commit, when the caller says which one to expect.

It deliberately does NOT compare rendered HTML or screenshots. Those belong to
visual regression; this command answers the narrower question that must be
settled first, and answers it deterministically.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from django.core.management.base import BaseCommand, CommandError

TIMEOUT_S = 30
CHECKED_ASSETS = (
    "css/main.css",
    "css/design-system.css",
    "css/components.css",
    "css/fonts.css",
)


def _validated_base_url(raw_url: str) -> str:
    """Return one canonical HTTP(S) deployment URL or fail closed.

    ``urllib`` supports local-file and custom URL handlers.  A release verifier
    only has a reason to contact a web deployment, so accepting those schemes
    would turn an operator typo (or an untrusted CI input) into an unexpected
    local-file read.  Credentials, queries and fragments are rejected too: the
    command appends fixed health and static paths and must not reinterpret a
    more complex URL.
    """
    candidate = str(raw_url or "").strip().rstrip("/")
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CommandError("--url must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise CommandError("--url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise CommandError("--url must not contain a query string or fragment")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


class Command(BaseCommand):
    help = "Verify a live deployment serves the artifact this tree builds."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            required=True,
            help="Base URL of the deployment, e.g. https://www.edifyplanning.app",
        )
        parser.add_argument(
            "--expect-commit",
            default="",
            help="Fail unless the deployment reports this commit (prefix match).",
        )
        parser.add_argument(
            "--skip-asset-fetch",
            action="store_true",
            help="Skip downloading each asset to confirm it resolves.",
        )

    def handle(self, *args, **options):
        base = _validated_base_url(options["url"])
        failures: list[str] = []

        remote = self._get_json(f"{base}/api/health/build", failures)
        if remote is None:
            # Nothing else can be checked, and this is the finding.
            self._report(failures)
            raise CommandError(
                "The deployment did not return build provenance. Deploy an "
                "image built after /api/health/build was added, or fix "
                "whatever is blocking it."
            )

        local = self._local_build_info()

        self.stdout.write(f"Deployment: {base}")
        self.stdout.write(
            f"  commit          {remote.get('commit')}\n"
            f"  release         {remote.get('release')}\n"
            f"  built           {remote.get('buildTime')}\n"
            f"  manifest        {remote.get('staticManifestHash')}\n"
            f"  from image      {remote.get('builtImage')}"
        )
        self.stdout.write(f"This tree manifest {local['staticManifestHash']}")

        expected_commit = options["expect_commit"].strip()
        if expected_commit:
            actual = str(remote.get("commit") or "")
            if not actual or not actual.startswith(expected_commit):
                failures.append(
                    f"commit: expected {expected_commit}..., serving {actual or 'unknown'}"
                )

        remote_manifest = remote.get("staticManifestHash")
        if local["staticManifestHash"] in ("unknown", None):
            failures.append(
                "this tree has no built manifest — run collectstatic before "
                "verifying, or the comparison means nothing"
            )
        elif remote_manifest != local["staticManifestHash"]:
            failures.append(
                f"static manifest: production {remote_manifest}, "
                f"this tree {local['staticManifestHash']} — production is "
                "serving a different static bundle"
            )

        self._compare_assets(remote, failures)

        if not options["skip_asset_fetch"]:
            self._fetch_assets(base, remote, failures)

        self._report(failures)
        if failures:
            raise CommandError(f"{len(failures)} release check(s) failed.")
        self.stdout.write(
            self.style.SUCCESS("\nProduction serves the artifact this tree builds.")
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _local_build_info(self) -> dict:
        from apps.core.build_info import asset_hash, build_info

        info = dict(build_info())
        info["assets"] = {name: asset_hash(name) for name in CHECKED_ASSETS}
        return info

    def _compare_assets(self, remote: dict, failures: list[str]) -> None:
        local = self._local_build_info()["assets"]
        remote_assets = remote.get("assets") or {}
        self.stdout.write("\nAssets:")
        for name in CHECKED_ASSETS:
            want, got = local.get(name), remote_assets.get(name)
            if want is None:
                # Not every deployment has every optional stylesheet; only
                # complain when production claims one this tree does not build.
                if got:
                    failures.append(
                        f"{name}: production serves {got}, not in this tree"
                    )
                continue
            if want == got:
                self.stdout.write(f"  ok    {name} -> {got}")
            else:
                self.stdout.write(self.style.ERROR(f"  STALE {name}"))
                self.stdout.write(f"        production {got}\n        this tree {want}")
                failures.append(f"{name}: production {got}, this tree {want}")

    def _fetch_assets(self, base: str, remote: dict, failures: list[str]) -> None:
        self.stdout.write("\nAsset reachability:")
        for name, hashed in (remote.get("assets") or {}).items():
            if not hashed:
                continue
            url = f"{base}/static/{hashed}"
            try:
                request = urllib.request.Request(url, method="GET")
                # nosec B310 -- _validated_base_url restricts the operator's
                # base URL to HTTP(S); this URL only appends a manifest path.
                with urllib.request.urlopen(  # nosec B310
                    request, timeout=TIMEOUT_S
                ) as response:
                    status = response.status
                    ctype = response.headers.get("Content-Type", "")
                    body = response.read(64)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: {url} did not load ({exc})")
                self.stdout.write(self.style.ERROR(f"  FAIL  {name}"))
                continue
            if status != 200:
                failures.append(f"{name}: {url} returned {status}")
                self.stdout.write(self.style.ERROR(f"  {status}  {name}"))
            elif name.endswith(".css") and "css" not in ctype:
                # A stylesheet served as text/html is the signature of a
                # missing file behind a catch-all: the browser silently
                # discards it and the page renders unstyled.
                failures.append(f"{name}: served as {ctype!r}, not CSS")
                self.stdout.write(self.style.ERROR(f"  TYPE  {name} -> {ctype}"))
            elif not body:
                failures.append(f"{name}: served an empty body")
                self.stdout.write(self.style.ERROR(f"  EMPTY {name}"))
            else:
                self.stdout.write(f"  ok    {name}")

    def _get_json(self, url: str, failures: list[str]) -> dict | None:
        try:
            # nosec B310 -- every caller derives this URL from the validated
            # HTTP(S) base URL and a fixed health endpoint.
            with urllib.request.urlopen(  # nosec B310
                url, timeout=TIMEOUT_S
            ) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            failures.append(f"{url} returned HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{url} could not be reached ({exc})")
        return None

    def _report(self, failures: list[str]) -> None:
        if not failures:
            return
        self.stdout.write(self.style.ERROR(f"\n{len(failures)} problem(s):"))
        for item in failures:
            self.stdout.write(self.style.ERROR(f"  - {item}"))
