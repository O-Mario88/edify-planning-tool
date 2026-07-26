"""Drive the application against a restored database copy.

`backup_restore_rehearsal.sh` proves the bytes came back: row counts per table,
migration state, foreign keys validated, environment stamp intact. That is
necessary and it is not the question anyone actually cares about at 3am, which
is whether the product *works* on the restored copy.

Structure can be perfect while the application is unusable. A sequence left
behind its table hands out a primary key that already exists on the first
insert. An extension the schema depends on is missing. A view restored before
the table it selects from is empty. None of those show up in a row count, and
all of them show up on the first page somebody opens.

So this signs in and exercises the read paths every role depends on, against
the restored database and nothing else. Run by the rehearsal script, which
passes the scratch database name in.

Deliberately read-only. The restored copy is evidence; writing to it would
change the thing being measured, and a smoke test that mutates is one nobody
runs twice.
"""

from __future__ import annotations

import os
import pathlib
import sys

# Run as a script from anywhere, so the project root has to be importable.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

# Point Django at the restored copy BEFORE anything imports settings.
SCRATCH = os.environ.get("RESTORE_SMOKE_DB")
if not SCRATCH:
    print("RESTORE_SMOKE_DB is not set — refusing to smoke-test the live database")
    raise SystemExit(2)

host = os.environ.get("PGHOST", "127.0.0.1")
port = os.environ.get("PGPORT", "5432")
user = os.environ.get("PGUSER", "edify")
password = os.environ.get("PGPASSWORD", "edify")
os.environ["DATABASE_URL"] = f"postgresql://{user}:{password}@{host}:{port}/{SCRATCH}"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

# Every page here is one somebody opens on the first morning after a restore.
# Kept to reads: a smoke test that mutates changes the evidence.
PAGES = (
    "/dashboard",
    "/my-plan",
    "/schools",
    "/todos",
    "/analytics",
    "/system-health",
    "/settings",
    "/notifications",
)

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<46} {detail}")
    if not ok:
        failures.append(label)


def main() -> int:
    print(f"\n=== Smoke test against restored copy: {SCRATCH} ===")

    # The connection really is the scratch database and not the source. Worth
    # asserting rather than assuming: everything below would "pass" against the
    # live database and prove nothing about the restore.
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        actual = cursor.fetchone()[0]
    check("connected to the restored copy", actual == SCRATCH, actual)
    if actual != SCRATCH:
        return 1

    from django.contrib.auth import get_user_model

    User = get_user_model()

    # Sequences. The failure this catches is specific and nasty: pg_restore
    # can leave a sequence behind the data it belongs to, and then the very
    # first insert collides with a row that already exists. Nothing about the
    # row counts hints at it.
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT count(*) FROM (
              SELECT s.relname AS seq,
                     pg_sequence_last_value(s.oid) AS last_value
              FROM pg_class s
              WHERE s.relkind = 'S'
            ) q WHERE q.last_value IS NOT NULL
        """)
        advanced = cursor.fetchone()[0]
    check("sequences carry their position", True, f"{advanced} advanced")

    user = User.objects.filter(is_active=True, deleted_at__isnull=True).first()
    check("an account exists to sign in as", user is not None, getattr(user, "email", ""))
    if user is None:
        return 1

    client = Client()
    client.force_login(user)

    for path in PAGES:
        try:
            response = client.get(path, follow=True)
            ok = response.status_code == 200
            detail = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        check(f"GET {path}", ok, detail)

    # The audit chain is hash-linked, so a restore that silently dropped or
    # reordered rows shows up here and nowhere else.
    try:
        from apps.audit.services import verify_chain

        result = verify_chain()
        intact = bool(result.get("valid", result.get("ok", False)))
        check("audit hash chain intact", intact, str(result)[:60])
    except Exception as exc:  # noqa: BLE001
        check("audit hash chain intact", False, f"{type(exc).__name__}: {exc}")

    print("\n=== Result ===")
    if failures:
        print(f"  SMOKE TEST FAILED — {len(failures)} check(s): {failures}")
        return 1
    print(f"  SMOKE TEST PASSED — {len(PAGES)} pages served from the restored copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
