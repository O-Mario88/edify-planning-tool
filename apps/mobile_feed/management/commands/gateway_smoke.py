"""Every role's menu, native pages and a school profile, fetched through the
running gateway as the app fetches them (Connect JSON), on a development
machine only.

The gateway decodes the feed strictly: a key the contract does not know
fails the whole screen, and neither the feed's tests (JSON) nor the
gateway's (a recording fetcher) can see it. This walks the real path.

    python manage.py gateway_smoke --settings=config.settings.dev
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

#: Only a gateway on this machine; never a shared or production one.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
#: One demo account per role, as the development seed creates them.
SEED_ACCOUNTS = (
    "cceo@edify.org",
    "pl1@edify.org",
    "regional-lead@edify.org",
    "cd@edify.org",
    "rvp@edify.org",
    "ia@edify.org",
    "hr@edify.org",
    "admin@edify.org",
    "accountant@edify.org",
    "coordinator@edify.org",
    "business-transformation@edify.org",
    "partner-admin@edify.org",
    "partner@edify.org",
    "mfi-admin@edify.org",
    "mfi-officer@edify.org",
)
SLOW_MS = 3000
TIMEOUT_S = 60


class Command(BaseCommand):
    help = "Fetch every role's native pages through the local gateway."

    def add_arguments(self, parser):
        parser.add_argument("--gateway", default="http://127.0.0.1:8090")

    def handle(self, *args, **options):
        gateway = options["gateway"].rstrip("/")
        if not settings.DEBUG:
            raise CommandError("Runs on a development build only (DEBUG is off).")
        where = urlparse(gateway)
        if where.scheme not in ("http", "https") or where.hostname not in LOCAL_HOSTS:
            raise CommandError("Runs against a gateway on this machine only.")
        failures, slow, fetched = self._walk(gateway)
        for failure in failures:
            self.stdout.write(f"FAIL {failure}")
        for page in slow:
            self.stdout.write(f"SLOW {page}")
        self.stdout.write(
            f"{fetched} pages, {len(failures)} failures, {len(slow)} over {SLOW_MS} ms"
        )
        if failures:
            raise CommandError(f"{len(failures)} screens failed.")

    def _walk(self, gateway: str):
        from django.contrib.auth import get_user_model

        from apps.accounts.jwt import issue_access_token
        from apps.schools.models import School

        users = get_user_model().objects.filter(email__in=SEED_ACCOUNTS, is_active=True)
        failures, slow, fetched = [], [], 0
        for user in users:
            token = issue_access_token(user.id, user.active_role)
            status, nav = _call(gateway, token, "NavigationService/GetNavigation", {})
            if status != 200:
                failures.append((user.email, "menu", status))
                continue
            items = [i for s in nav.get("sections", []) for i in s.get("items", [])]
            for path in sorted(
                {i["url"].split("?")[0] for i in items if i.get("native")}
            ):
                started = time.monotonic()
                status, body = _call(
                    gateway, token, "PageScreenService/GetPage", {"path": path}
                )
                took = int((time.monotonic() - started) * 1000)
                fetched += 1
                if status != 200 or body.get("error"):
                    failures.append((user.email, path, status, str(body)[:160]))
                if took > SLOW_MS:
                    slow.append((user.email, path, took))
            self.stdout.write(f"{user.email}: menu and pages read")
        school = (
            School.objects.filter(account_owner_id__isnull=False)
            .values_list("id", flat=True)
            .first()
        )
        reader = users.filter(email="cceo@edify.org").first()
        if school and reader:
            token = issue_access_token(reader.id, reader.active_role)
            status, body = _call(
                gateway,
                token,
                "SchoolProfileService/GetSchoolProfile",
                {"schoolId": school},
            )
            if status != 200:
                failures.append(
                    (reader.email, "school profile", status, str(body)[:160])
                )
        return failures, slow, fetched


def _call(gateway: str, token: str, method: str, body: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{gateway}/edify.screens.v1.{method}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        # nosec B310 - the gateway is checked to be http(s) on this machine
        # (handle), never a file: or custom scheme.
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # nosec B310
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read() or b"{}")
