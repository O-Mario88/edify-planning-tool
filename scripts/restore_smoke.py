"""Drive the application against a restored database copy.

`backup_restore_rehearsal.sh` proves the bytes came back: every schema,
relation, column, index, constraint definition, row and digest compared against
the dump's own manifest. That is necessary and it is not the question anyone
actually cares about at 3am, which is whether the product *works* on the
restored copy.

Structure can be perfect while the application is unusable. A sequence left
behind its table hands out a primary key that already exists on the first
insert. An extension the schema depends on is missing. A view restored before
the table it selects from is empty. None of those show up in a row count, and
all of them show up on the first page somebody opens.

So this signs in and exercises the read paths every role depends on, against
the restored database and nothing else. Run by the rehearsal script, which
passes the scratch database name in.

WHAT WAS WRONG WITH THE PREVIOUS VERSION
----------------------------------------
Three things, all of the same family as the floors the rehearsal was rebuilt to
remove:

  * `check("sequences carry their position", True, ...)` — the literal `True`.
    The check could not fail. It counted how many sequences had been read from
    and asserted nothing about any of them. It now compares each sequence
    against the maximum value in the column it feeds, which is the failure it
    was named after: a sequence behind its data collides on the first insert.

  * every page was scored on `status_code == 200` after following redirects.
    Measured: an ANONYMOUS client gets HTTP 200 on all eight, final URL
    `/login?next=…`. "8 pages served from the restored copy" was satisfied by
    eight renderings of the login form, so a restore that broke authentication,
    sessions or the user's role would still have passed. Each page now asserts
    that the request that rendered it was authenticated, and a deliberate
    anonymous control asserts that the discriminator works at all.

  * it said "Deliberately read-only" and was not. Measured on a clean restore:
    +331 rows across 13 tables — `hr_value_commitment` +168, `audit_log` +42,
    `domain_event_log` +42, `notification` +24, `django_session` +1 — plus
    in-place field changes to `school` and `user` with no row-count change,
    which is exactly the signature of the corruption the digests exist to
    catch. `force_login` writes `last_login`; `FiscalYearRolloverMiddleware`
    self-heals the fiscal year on the first authenticated request. It now runs
    inside one transaction that is rolled back at the end, and the rehearsal
    re-verifies the copy afterwards to check that claim rather than trust it.

Exit codes: 0 pass, 1 fail, 2 refused, 3 NOT PROVEN — the copy restored fine
but carries no account to sign in as, so the application could not be
exercised. A fresh install is not a broken backup and must not report as one.

Named restore_smoke.py, not restore_smoke_test.py: the _test suffix matches
pytest's collection pattern, and the module-level refusal to run without
RESTORE_SMOKE_DB then aborts the entire suite at collection time. It did.
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

from django.db import connection, transaction  # noqa: E402
from django.test import Client  # noqa: E402

#: Exit code for "restored fine, could not be exercised".
EXIT_NOT_PROVEN = 3

# Every page here is one somebody opens on the first morning after a restore.
# Which ROLE may open which is an authorisation question and not this script's
# business, so each page is required to be served to SOME account rather than
# to one arbitrarily chosen one. Signing in as a single account and requiring
# all eight made the run depend on which role happened to sort first:
# `/system-health` is an administrator's page, `/accounts` is where an
# Accountant lands, a Partner Field Officer starts at
# `/partner/assigned-schools`. A restore that broke a page breaks it for
# everybody, so "no account could open this page" is the failure that matters.
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

# Sequences whose owning column is found through pg_depend, which is how
# Postgres records "this sequence feeds that column".
SEQUENCE_OWNERS = """
SELECT sn.nspname, s.relname, tn.nspname, t.relname, a.attname
FROM pg_catalog.pg_class s
JOIN pg_catalog.pg_namespace sn ON sn.oid = s.relnamespace
JOIN pg_catalog.pg_depend d
  ON d.objid = s.oid AND d.classid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')
JOIN pg_catalog.pg_class t ON t.oid = d.refobjid
JOIN pg_catalog.pg_namespace tn ON tn.oid = t.relnamespace
JOIN pg_catalog.pg_attribute a
  ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
WHERE s.relkind = 'S'
ORDER BY 1, 2
"""

failures: list[str] = []
not_proven: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<46} {detail}")
    if not ok:
        failures.append(label)


def check_sequences() -> None:
    """A sequence behind the column it feeds collides on the first insert.

    This is the check the previous version was named after and did not make.
    Nothing about a row count hints at it, and the application looks perfect
    until somebody creates a record.
    """
    with connection.cursor() as cursor:
        cursor.execute(SEQUENCE_OWNERS)
        owners = cursor.fetchall()
    if not owners:
        check("sequences carry their position", False, "no sequence owns any column")
        return
    behind = []
    for seq_schema, seq_name, tbl_schema, tbl_name, column in owners:
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT (SELECT last_value FROM "{seq_schema}"."{seq_name}"), '
                f'(SELECT max("{column}") FROM "{tbl_schema}"."{tbl_name}")'
            )
            last_value, highest = cursor.fetchone()
        if highest is None:
            continue
        if last_value is None or last_value < highest:
            behind.append(
                f"{seq_schema}.{seq_name}={last_value} but "
                f"max({tbl_name}.{column})={highest}"
            )
    check(
        "sequences are not behind their columns",
        not behind,
        f"{len(owners)} sequence(s) checked" if not behind else "; ".join(behind[:3]),
    )


def candidate_accounts(User, limit: int = 12) -> list:
    """One active account per distinct role, in a deterministic order.

    Deterministic matters: `User._meta.ordering` is `['-created_at']` with no
    tiebreaker, so `.first()` can pick a different account on the source and on
    the restore, and a smoke test whose subject changes between runs is a smoke
    test whose failures cannot be reproduced.
    """
    seen: dict[str, object] = {}
    for account in User.objects.filter(
        is_active=True, deleted_at__isnull=True
    ).order_by("email"):
        role = str(getattr(account, "active_role", "") or "")
        if role not in seen:
            seen[role] = account
        if len(seen) >= limit:
            break
    return [seen[role] for role in sorted(seen)]


def clear_policy_gate(user) -> str:
    """Answer the mandatory policy agreements holding this account at the door.

    `apps.documents.gate.PolicyGateMiddleware` withholds the whole application
    from a user with an unanswered mandatory policy and redirects them to the
    Agreement Center. Every account in a seeded database is in that state, so
    "GET /dashboard -> HTTP 200" was eight renderings of a policy document
    rather than eight pages of the product — the smoke test was measuring the
    interstitial. Answering through the application's own service clears it and
    exercises a write path as well as the read paths. The whole run is inside a
    transaction that is rolled back, and the rehearsal re-verifies the copy
    afterwards, so the evidence is not touched.
    """
    from apps.documents.gate import PolicyGateService
    from apps.documents.models import AcknowledgementChoice
    from apps.documents.services import AcknowledgementService

    state, _ = PolicyGateService.state_for(user)
    if state == "clear":
        return "no mandatory policy outstanding"
    outstanding = list(PolicyGateService.blocking_acknowledgements(user)) + list(
        PolicyGateService.disagreements(user)
    )
    answered = 0
    for ack in outstanding:
        AcknowledgementService.respond(
            user,
            str(ack.id),
            AcknowledgementChoice.AGREE,
            comment="restore rehearsal (rolled back)",
            typed_name=(getattr(user, "full_name", "") or user.email)[:160],
        )
        answered += 1
    return f"answered {answered} mandatory policy agreement(s)"


def check_anonymous_is_refused() -> bool:
    """Prove the signed-in check can tell signed-in from signed-out.

    Without this, "GET /dashboard -> HTTP 200" is satisfied by a rendering of
    the login form, which is what it was satisfied by.
    """
    response = Client().get(PAGES[0], follow=True)
    request_user = getattr(response.wsgi_request, "user", None)
    anonymous = request_user is None or not request_user.is_authenticated
    check(
        "an anonymous visitor is NOT served the app",
        anonymous,
        f"HTTP {response.status_code} at {response.request['PATH_INFO']}",
    )
    return anonymous


def main() -> int:
    # Not "=== Result ===": the rehearsal script owns that heading, and a
    # second one printed here meant a failing run ended with a green Result
    # section sitting directly above the red one.
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

    check_sequences()
    check_anonymous_is_refused()

    user = User.objects.filter(is_active=True, deleted_at__isnull=True).first()
    if user is None:
        # Not a failure of the backup. A database nobody has signed into yet
        # restores perfectly and cannot demonstrate that the application works.
        # The previous version reported this as FAIL with an empty detail line,
        # because `getattr(None, "email", "")` renders as nothing — so the one
        # line that decided the run explained nothing.
        print(
            f"  NOT PROVEN  {'no account to sign in as':<42} "
            f"{User.objects.count()} user row(s), none active and undeleted"
        )
        not_proven.append("no account to sign in as")
        print("\n=== Smoke test result ===")
        print("  SMOKE TEST NOT PROVEN — the copy restored, the app was not exercised.")
        return EXIT_NOT_PROVEN
    check("an account exists to sign in as", True, user.email)

    accounts = candidate_accounts(User)
    print(
        f"  ....  {'accounts available to sign in as':<46} "
        f"{len(accounts)} covering roles: "
        f"{', '.join(str(getattr(a, 'active_role', '?')) for a in accounts)}"
    )

    clients: dict[str, Client] = {}

    def client_for(account) -> Client:
        key = str(account.pk)
        if key not in clients:
            try:
                clear_policy_gate(account)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"  ....  {'mandatory-policy gate':<46} "
                    f"{account.email}: {type(exc).__name__}: {exc}"
                )
            client = Client()
            client.force_login(account)
            clients[key] = client
        return clients[key]

    for path in PAGES:
        served_by = None
        detail = "no account was served this page"
        tried = 0
        for account in accounts:
            tried += 1
            try:
                # A savepoint per attempt, so one page erroring at the database
                # does not poison the transaction for everything after it.
                with transaction.atomic():
                    response = client_for(account).get(path, follow=True)
                request_user = getattr(response.wsgi_request, "user", None)
                signed_in = request_user is not None and request_user.is_authenticated
                landed = response.request["PATH_INFO"]
                if response.status_code == 200 and signed_in and landed == path:
                    served_by = account
                    detail = (
                        f"HTTP 200 to {getattr(account, 'active_role', '?')} "
                        f"({tried} account(s) tried)"
                    )
                    break
                detail = (
                    f"last: HTTP {response.status_code} at {landed}"
                    f"{'' if signed_in else ' — SIGNED OUT, this is the login page'}"
                )
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
                break
        check(f"GET {path}", served_by is not None, detail)

    # The audit chain is hash-linked, so a restore that silently dropped or
    # reordered rows shows up here and nowhere else.
    #
    # full=True, and the number of rows walked is asserted. The default is
    # incremental: it resumes from a recorded checkpoint, and against a restored
    # copy that reported `ok: True, checkedRows: 0` — a chain declared intact
    # without a single row being hashed. Verifying nothing is not verifying.
    try:
        from apps.audit.models import AuditLog
        from apps.audit.services import verify_chain

        rows = AuditLog.objects.count()
        result = verify_chain(full=True)
        intact = bool(result.get("valid", result.get("ok", False)))
        walked = result.get("checkedRows", 0)
        check(
            "audit hash chain intact",
            intact and walked == rows,
            f"walked {walked} of {rows} rows, brokenAt={result.get('brokenAt')}",
        )
    except Exception as exc:  # noqa: BLE001
        check("audit hash chain intact", False, f"{type(exc).__name__}: {exc}")

    print("\n=== Smoke test result ===")
    if failures:
        print(f"  SMOKE TEST FAILED — {len(failures)} check(s): {failures}")
        return 1
    print(
        f"  SMOKE TEST PASSED — {len(PAGES)} pages served to signed-in accounts "
        f"from the restored copy."
    )
    return 0


def run() -> int:
    """Run the whole smoke test inside one transaction, and roll it back.

    The restored copy is evidence. Writing to it changes the thing being
    measured, and the previous version wrote 331 rows into it — including into
    the audit chain it then declared intact.
    """
    try:
        with transaction.atomic():
            code = main()
            transaction.set_rollback(True)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  {'smoke test aborted':<46} {type(exc).__name__}: {exc}")
        return 1
    return code


if __name__ == "__main__":
    sys.exit(run())
