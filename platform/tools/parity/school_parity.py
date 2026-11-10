"""Parity check: the Go gateway's school slice against the existing API.

For every active account it mints an access token with the existing identity
code, then asks both backends the same question on the SAME isolated database:

  existing  GET /api/schools              (Django, called in-process)
  gateway   SchoolService/ListMySchools   (Go, called over HTTP)

and requires, per account:

  * a role the slice serves (CCEO, Program Lead): the gateway returns exactly
    the schools the existing API returns, with the same identifiers, names,
    types and enrolments. Never a school the existing API withholds.
  * any other role: the gateway refuses (permission_denied).

Run from the repository root with the gateway already listening:

    .venv/bin/python platform/tools/parity/school_parity.py [--gateway http://127.0.0.1:8090]

It only reads. It refuses to run unless Django's database is on this machine.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
SERVED_ROLES = {"CCEO", "Program Lead"}
PAGE_SIZE = 200
COMPARED_FIELDS = (
    ("schoolId", "schoolId"),
    ("name", "name"),
    ("schoolType", "schoolType"),
    ("enrollment", "enrollment"),
    ("clusterStatus", "clusterStatus"),
    ("currentFySsaStatus", "currentFySsaStatus"),
    ("planningReadiness", "planningReadiness"),
)
LIST_PATH = "/edify.schools.v1.SchoolService/ListMySchools"


def setup_django() -> None:
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(REPO_ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    from django.conf import settings

    database = settings.DATABASES["default"]
    host = str(database.get("HOST") or "")
    if host not in LOCAL_HOSTS and not host.startswith("/"):
        raise SystemExit(
            f"refused: Django's database host {host!r} is not this machine"
        )
    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]


def existing_schools(client, token: str) -> tuple[int, dict[str, dict]]:
    """Every school the existing API lists for this token, keyed by record id."""
    schools: dict[str, dict] = {}
    page = 1
    while True:
        response = client.get(
            "/api/schools",
            {"page": page, "pageSize": PAGE_SIZE},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        if response.status_code != 200:
            return response.status_code, {}
        body = response.json()
        for row in body["data"]:
            schools[row["id"]] = row
        if page >= body["totalPages"]:
            return 200, schools
        page += 1


def gateway_schools(base_url: str, token: str) -> tuple[str, dict[str, dict]]:
    """Every school the gateway lists, keyed by record id, or its error code."""
    schools: dict[str, dict] = {}
    page = 1
    while True:
        request = urllib.request.Request(
            base_url + LIST_PATH,
            data=json.dumps({"page": {"page": page, "pageSize": PAGE_SIZE}}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed local URL
                body = json.load(response)
        except urllib.error.HTTPError as error:
            return json.load(error).get("code", str(error.code)), {}
        for row in body.get("schools", []):
            schools[row["id"]] = row
        if page >= int(body.get("page", {}).get("totalPages", 0)):
            return "ok", schools
        page += 1


def compare(user, expected: dict[str, dict], actual: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    extra = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    if extra:
        problems.append(
            f"{user.email}: gateway returned {len(extra)} school(s) the existing API withholds"
        )
    if missing:
        problems.append(f"{user.email}: gateway is missing {len(missing)} school(s)")
    for school_id in set(expected) & set(actual):
        for existing_field, gateway_field in COMPARED_FIELDS:
            if expected[school_id].get(existing_field) != actual[school_id].get(
                gateway_field
            ):
                problems.append(
                    f"{user.email}: school {school_id} differs on {existing_field}: "
                    f"{expected[school_id].get(existing_field)!r} != {actual[school_id].get(gateway_field)!r}"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gateway", default="http://127.0.0.1:8090")
    args = parser.parse_args()

    setup_django()
    from rest_framework.test import APIClient

    from apps.accounts.jwt import issue_access_token
    from apps.accounts.models import User

    client = APIClient()
    problems: list[str] = []
    served = refused = compared_schools = 0

    users = User.objects.filter(
        is_active=True, deleted_at__isnull=True, status="active"
    )
    for user in users.order_by("email"):
        token = issue_access_token(user.id, user.active_role)
        code, actual = gateway_schools(args.gateway, token)
        if user.active_role not in SERVED_ROLES:
            refused += 1
            if code != "permission_denied":
                problems.append(
                    f"{user.email} ({user.active_role}): expected a refusal, gateway answered {code}"
                )
            continue
        status, expected = existing_schools(client, token)
        if status != 200 or code != "ok":
            problems.append(f"{user.email}: existing API {status}, gateway {code}")
            continue
        served += 1
        compared_schools += len(expected)
        problems.extend(compare(user, expected, actual))

    print(f"accounts served and compared: {served}")
    print(f"accounts correctly refused:   {refused}")
    print(f"school rows compared:         {compared_schools}")
    for problem in problems:
        print("MISMATCH", problem)
    print(
        "PARITY OK" if not problems else f"PARITY FAILED ({len(problems)} problem(s))"
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
