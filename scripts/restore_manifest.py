"""Capture and verify a restore manifest — the evidence a backup gate needs.

WHY THIS EXISTS
---------------
A verification that cannot fail is worse than no verification. No verification
leaves an open question that somebody eventually asks. A verification that
always passes closes the question with the wrong answer, and the closed
question is then cited as evidence in a readiness ledger.

`backup_restore_rehearsal.sh` used to verify a restore with three thresholds:
the dump must exceed 100,000 bytes, the restored copy must have at least 50
tables, and it must carry at least 20 foreign keys. Measured against this
schema with EVERY TABLE EMPTY:

    dump of a zero-row database ....... 1,778,821 bytes  (17.8x the floor)
    tables in a wiped database ................... 308   (6.2x the floor)
    FK constraints in a wiped database ........... 382  (19.1x the floor)

All three floors clear by a wide margin on a database containing no data at
all, and the fourth check — per-table row counts — read both sides from the
LIVE SOURCE, so on an empty source every comparison was `0 == 0`.

THE SECOND ROUND OF DEFECTS
---------------------------
Replacing the floors with row digests fixed the row-shaped hole and left the
rest of the database unguarded. Measured, on restores this tool's first version
certified as good:

    * materialised views: `pg_dump` carries the DEFINITION, never the CONTENTS.
      A matview holding 260 rows in the source came back holding 0, and one
      holding 100 timestamped rows came back silently re-dated. Both certified.
    * privileges: dumped with `--no-privileges`, so every GRANT was discarded.
      The certified copy raised `permission denied for table school` for the
      application role. Every run. No tampering.
    * database settings: no `--create`, so `statement_timeout`, `TimeZone` and
      `search_path` set on the database were silently dropped.
    * locale: the scratch database was created with a bare `CREATE DATABASE`,
      inheriting the CLUSTER's locale from template1 rather than the source's.
      An ICU `de-DE-u-co-phonebk` source was certified as a `C.UTF-8` copy —
      every text index in a different order.
    * template1 contamination: a function planted in template1 appeared in the
      "restored" copy and nothing objected.
    * 1,881 missing indexes, a dropped schema, a weakened CHECK, a rewritten
      FK, missing triggers, functions, views and large objects: all certified,
      because nothing looked at any of them.

WHAT THIS DOES NOW
------------------
It compares the restored database against a manifest describing the DUMP — not
the live source, and not a threshold somebody guessed at — and the manifest
describes the whole database, not only the rows.

`capture` opens a REPEATABLE READ transaction, exports its snapshot id, runs
`pg_dump --create --snapshot=<id>` so the dump sees exactly that snapshot, and
reads the manifest INSIDE the same still-open transaction. `--create` is what
carries the database's own encoding, locale and `ALTER DATABASE ... SET`
settings into the artifact; `prepare` reads them back out of the artifact and
retargets them at the scratch database, so the scratch copy is created from the
BACKUP's statements and not from the cluster's defaults.

The manifest records, for every non-system schema:

    * schemas, and every relation with its kind, owner, ACL, persistence,
      reloptions and row-security flags
    * every column: type, NOT NULL, DEFAULT expression, identity, generated,
      collation
    * every index, by `pg_get_indexdef`
    * every constraint, by `pg_get_constraintdef` and validated state — the
      DEFINITION, not a census by type: swapping a CHECK for `CHECK (true)`
      leaves a census identical
    * every view and materialised view definition
    * every function and procedure, by digest of `pg_get_functiondef`
    * every trigger, by `pg_get_triggerdef`
    * every row-security policy, every extension and version, every comment,
      every default ACL
    * large objects: count and content digest
    * the database's encoding, collate, ctype, locale provider, ICU locale,
      ACL and owner, plus its `pg_db_role_setting` entries
    * per-table row counts and order-independent content digests, for ordinary
      tables in EVERY non-system schema
    * materialised view contents, compared separately and reported with the
      reason they can differ
    * sequence positions READ FROM THE DUMP ARTIFACT, not from the live catalog

That last point is a correctness fix, not an addition. Sequences are not
transactional: `pg_dump` reads `last_value` off the sequence when it reaches
it, so a source taking writes drifts away from its own dump while the dump
runs, and comparing the restore against the LIVE catalog reported a perfect
restore as corruption. The artifact's own `setval` calls are the only correct
reference, and they are what this reads.

`verify` reads the same manifest from the restored database, in its own
REPEATABLE READ snapshot, and diffs it. Exit 0 = PASS, 1 = FAIL.

`checkdump` compares the artifact's size and sha256 with the manifest. Run
against the file the manifest was written from it can only ever pass, so the
rehearsal runs it at the point of use — immediately before `pg_restore` and
again immediately after — which is what makes swapping the dump file between
the hash and the restore fail instead of pass.

`evidence` reports how much data the snapshot held. It refuses to call a
round trip of nothing a proof of anything, and it is careful about what it
claims: the count excludes Django's own bookkeeping tables but NOT the
reference data migrations seed, so a fresh install clears it. That is why zero
here is INCONCLUSIVE (exit 3) rather than FAILED — the backup is not shown to
be broken, it is shown to be unproven.

There is no canary row. The previous version carried one, defaulting to an
address that existed in no database anywhere, so it compared None with None and
counted the result as a passing check. Per-table content digests already cover
every field of every row; a second reading that cannot fail is not a second
opinion.

Row-to-text rendering and object-definition rendering must be identical in both
sessions or the digests and definitions are noise, so every GUC that affects
them is pinned on both sides — including `search_path`, which decides whether
`pg_get_viewdef` schema-qualifies its output.

USAGE
-----
    REHEARSAL_DSN=... restore_manifest.py capture <manifest.json> <dump>
    restore_manifest.py checkdump <manifest.json> <dump> [label]
    restore_manifest.py prepare <dump> <scratch-db>
    restore_manifest.py evidence <manifest.json>
    restore_manifest.py rowcount <manifest.json> <table>
    REHEARSAL_DSN=... restore_manifest.py verify <manifest.json>

Importable: nothing runs at import time.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from typing import Any

import psycopg
from psycopg import sql as _sql

#: Environment variable carrying the libpq connection string.
DSN_ENV = "REHEARSAL_DSN"

#: Exit code meaning "not disproved, but not proved either". Distinct from 1 so
#: a caller can tell "your backup is broken" from "this run could not tell".
EXIT_INCONCLUSIVE = 3

#: Tables Django maintains for itself. Rows here are bookkeeping, not the data
#: anyone restores a backup to recover.
BOOKKEEPING_TABLES = frozenset(
    {
        "django_migrations",
        "django_content_type",
        "django_session",
        "django_admin_log",
        "auth_permission",
        "auth_group",
        "auth_group_permissions",
        "environment_stamp",
    }
)

# Rendering must be deterministic across sessions or every digest and every
# object definition is noise. search_path is in here because pg_get_viewdef,
# pg_get_indexdef, pg_get_constraintdef and pg_get_functiondef all decide
# whether to schema-qualify based on it: an ALTER DATABASE ... SET search_path
# on one side and not the other would otherwise render every definition
# differently and fail a perfect restore.
PIN = (
    "SET DateStyle = 'ISO, YMD'",
    "SET IntervalStyle = 'postgres'",
    "SET TimeZone = 'UTC'",
    "SET bytea_output = 'hex'",
    "SET extra_float_digits = 3",
    "SET client_encoding = 'UTF8'",
    "SET lc_monetary = 'C'",
    "SET search_path = ''",
)

#: Every catalog query is scoped by this. pg_catalog stays reachable regardless
#: of search_path, so the queries below still resolve.
USER_SCHEMAS = "n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'"


def _acl(column: str, kind: str, owner: str) -> str:
    """SQL rendering one ACL in a form that survives a dump/restore round trip.

    Postgres stores NULL in `relacl` for an object whose privileges were never
    touched, and materialises the explicit default the moment they are — so
    `GRANT SELECT ... ; REVOKE SELECT ...` leaves `{edify=arwdDxt/edify}`
    where an untouched object holds NULL. Those are the SAME privileges, and
    `pg_dump` emits nothing for either, so a restore legitimately turns the
    first into the second. Comparing the raw column reported that as a
    difference. `acldefault()` collapses the two, and the entries are sorted
    because array order is not meaningful.
    """
    return (
        f"(SELECT coalesce(string_agg(e::text, ',' ORDER BY e::text), '-') "
        f"FROM unnest(coalesce({column}, "
        f"pg_catalog.acldefault('{kind}'::\"char\", {owner}))) e)"
    )


def _relacl() -> str:
    """Relation ACL, with sequences getting the sequence default."""
    return (
        "(SELECT coalesce(string_agg(e::text, ',' ORDER BY e::text), '-') "
        "FROM unnest(coalesce(c.relacl, pg_catalog.acldefault("
        "CASE WHEN c.relkind = 'S' THEN 's'::\"char\" ELSE 'r'::\"char\" END, "
        "c.relowner))) e)"
    )


SCHEMAS_SQL = f"""
SELECT n.nspname,
       pg_catalog.pg_get_userbyid(n.nspowner) || ' acl=' || {_acl("n.nspacl", "n", "n.nspowner")}
FROM pg_catalog.pg_namespace n
WHERE {USER_SCHEMAS}
ORDER BY 1
"""

# relkind: r ordinary table, p partitioned parent, v view, m materialised view,
# S sequence, f foreign table. Indexes are covered by pg_get_indexdef below.
RELATIONS_SQL = f"""
SELECT n.nspname || '.' || c.relname,
       c.relkind::text || ' persistence=' || c.relpersistence::text
         || ' owner=' || pg_catalog.pg_get_userbyid(c.relowner)
         || ' acl=' || {_relacl()}
         || ' rls=' || c.relrowsecurity::text || c.relforcerowsecurity::text
         || ' opts=' || coalesce(c.reloptions::text, '-')
         || ' populated=' || c.relispopulated::text
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS} AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
ORDER BY 1
"""

# NOT NULL, DEFAULT, identity, generated and collation are all things a restore
# can lose without moving a single row count.
COLUMNS_SQL = f"""
SELECT n.nspname || '.' || c.relname || '.' || a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod)
         || ' notnull=' || a.attnotnull::text
         || ' default=' || coalesce(pg_catalog.pg_get_expr(d.adbin, d.adrelid), '-')
         || ' identity=' || coalesce(nullif(a.attidentity::text, ''), '-')
         || ' generated=' || coalesce(nullif(a.attgenerated::text, ''), '-')
         || ' collation=' || coalesce(co.collname, '-')
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
LEFT JOIN pg_catalog.pg_collation co ON co.oid = a.attcollation
WHERE {USER_SCHEMAS} AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY 1
"""

INDEXES_SQL = f"""
SELECT n.nspname || '.' || ci.relname, pg_catalog.pg_get_indexdef(i.indexrelid)
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class ci ON ci.oid = i.indexrelid
JOIN pg_catalog.pg_class ct ON ct.oid = i.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = ct.relnamespace
WHERE {USER_SCHEMAS}
ORDER BY 1
"""

# The DEFINITION, not a census by contype. A census counts 382 foreign keys
# whether or not one of them acquired ON DELETE CASCADE, and counts the same
# number of CHECKs whether or not one of them was replaced by CHECK (true).
CONSTRAINTS_SQL = f"""
SELECT n.nspname || '.' || coalesce(cl.relname, '-') || '.' || co.conname,
       co.contype::text || ' validated=' || co.convalidated::text
         || ' ' || pg_catalog.pg_get_constraintdef(co.oid)
FROM pg_catalog.pg_constraint co
JOIN pg_catalog.pg_namespace n ON n.oid = co.connamespace
LEFT JOIN pg_catalog.pg_class cl ON cl.oid = co.conrelid
WHERE {USER_SCHEMAS}
ORDER BY 1
"""

VIEWDEFS_SQL = f"""
SELECT n.nspname || '.' || c.relname, pg_catalog.pg_get_viewdef(c.oid, true)
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS} AND c.relkind IN ('v', 'm')
ORDER BY 1
"""

# prokind f/p only: pg_get_functiondef refuses aggregates and window functions.
ROUTINES_SQL = f"""
SELECT n.nspname || '.' || p.proname
         || '(' || pg_catalog.pg_get_function_identity_arguments(p.oid) || ')',
       pg_catalog.md5(pg_catalog.pg_get_functiondef(p.oid))
         || ' owner=' || pg_catalog.pg_get_userbyid(p.proowner)
         || ' acl=' || {_acl("p.proacl", "f", "p.proowner")}
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE {USER_SCHEMAS} AND p.prokind IN ('f', 'p')
ORDER BY 1
"""

TRIGGERS_SQL = f"""
SELECT n.nspname || '.' || c.relname || '.' || t.tgname,
       pg_catalog.pg_get_triggerdef(t.oid) || ' enabled=' || t.tgenabled::text
FROM pg_catalog.pg_trigger t
JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS} AND NOT t.tgisinternal
ORDER BY 1
"""

POLICIES_SQL = f"""
SELECT n.nspname || '.' || c.relname || '.' || p.polname,
       p.polcmd::text || ' permissive=' || p.polpermissive::text
         || ' roles=' || p.polroles::text
         || ' using=' || coalesce(pg_catalog.pg_get_expr(p.polqual, p.polrelid), '-')
         || ' check='
         || coalesce(pg_catalog.pg_get_expr(p.polwithcheck, p.polrelid), '-')
FROM pg_catalog.pg_policy p
JOIN pg_catalog.pg_class c ON c.oid = p.polrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS}
ORDER BY 1
"""

EXTENSIONS_SQL = """
SELECT e.extname,
       e.extversion || ' schema='
         || coalesce((SELECT n.nspname FROM pg_catalog.pg_namespace n
                      WHERE n.oid = e.extnamespace), '-')
FROM pg_catalog.pg_extension e
ORDER BY 1
"""

COMMENTS_SQL = f"""
SELECT n.nspname || '.' || c.relname,
       pg_catalog.obj_description(c.oid, 'pg_class')
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS} AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  AND pg_catalog.obj_description(c.oid, 'pg_class') IS NOT NULL
UNION ALL
SELECT n.nspname || '.' || c.relname || '.' || a.attname,
       pg_catalog.col_description(c.oid, a.attnum)
FROM pg_catalog.pg_attribute a
JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE {USER_SCHEMAS} AND a.attnum > 0 AND NOT a.attisdropped
  AND pg_catalog.col_description(c.oid, a.attnum) IS NOT NULL
ORDER BY 1
"""

DEFAULT_ACL_SQL = """
SELECT coalesce(n.nspname, '-') || '.'
         || pg_catalog.pg_get_userbyid(d.defaclrole) || '.' || d.defaclobjtype::text,
       d.defaclacl::text
FROM pg_catalog.pg_default_acl d
LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace
ORDER BY 1
"""

# Large objects are not in any table, so nothing about tables notices when they
# vanish. pg_dump carries them; a restore can lose them.
LARGE_OBJECT_SQL = f"""
SELECT count(*)::bigint,
       coalesce(pg_catalog.md5(pg_catalog.string_agg(h, '' ORDER BY h)), '-')
FROM (
  SELECT pg_catalog.md5(
           m.oid::text || pg_catalog.pg_get_userbyid(m.lomowner)
           || {_acl("m.lomacl", "L", "m.lomowner")}
           || pg_catalog.md5(coalesce(pg_catalog.lo_get(m.oid), ''::bytea))
         ) AS h
  FROM pg_catalog.pg_largeobject_metadata m
) s
"""

# datcollversion is deliberately absent: it is a stamp of the operating
# system's collation library, not a property the backup carries, and a
# legitimate restore onto a differently-patched host would differ.
DATABASE_SQL = f"""
SELECT pg_catalog.pg_encoding_to_char(d.encoding)
         || ' collate=' || d.datcollate || ' ctype=' || d.datctype
         || ' provider=' || d.datlocprovider::text
         || ' icu=' || coalesce(d.daticulocale, '-')
         || ' acl=' || {_acl("d.datacl", "d", "d.datdba")}
         || ' owner=' || pg_catalog.pg_get_userbyid(d.datdba)
FROM pg_catalog.pg_database d
WHERE d.datname = pg_catalog.current_database()
"""

DB_SETTINGS_SQL = """
SELECT coalesce(pg_catalog.pg_get_userbyid(nullif(s.setrole, 0)), '(database)'),
       s.setconfig::text
FROM pg_catalog.pg_db_role_setting s
JOIN pg_catalog.pg_database d ON d.oid = s.setdatabase
WHERE d.datname = pg_catalog.current_database()
ORDER BY 1
"""

# md5 of every row, aggregated in a canonical order -> independent of the
# physical row order, which a restore legitimately changes. ORDER BY h COLLATE
# "C" so the aggregation order cannot depend on the database's collation, which
# is one of the things being compared.
DIGEST_SQL = _sql.SQL(
    "SELECT count(*), coalesce(md5(string_agg(h, '' ORDER BY h COLLATE \"C\")), '-') "
    "FROM (SELECT md5(t::text) AS h FROM {} t) s"
)


def resolve_dsn() -> str:
    """Read the connection string, failing loudly rather than silently local."""
    dsn = os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(
            f"{DSN_ENV} is not set — refusing to guess which database to read"
        )
    return dsn


def _pin(cur: psycopg.Cursor) -> None:
    for statement in PIN:
        cur.execute(statement)


def _pairs(cur: psycopg.Cursor, query: str) -> dict[str, str]:
    cur.execute(query)
    return {row[0]: row[1] for row in cur.fetchall()}


def read_manifest(cur: psycopg.Cursor) -> dict[str, Any]:
    """Read the full manifest through an already-pinned cursor."""
    manifest: dict[str, Any] = {}

    manifest["schemas"] = _pairs(cur, SCHEMAS_SQL)
    manifest["relations"] = _pairs(cur, RELATIONS_SQL)
    manifest["columns"] = _pairs(cur, COLUMNS_SQL)
    manifest["indexes"] = _pairs(cur, INDEXES_SQL)
    manifest["constraints"] = _pairs(cur, CONSTRAINTS_SQL)
    manifest["viewdefs"] = _pairs(cur, VIEWDEFS_SQL)
    manifest["routines"] = _pairs(cur, ROUTINES_SQL)
    manifest["triggers"] = _pairs(cur, TRIGGERS_SQL)
    manifest["policies"] = _pairs(cur, POLICIES_SQL)
    manifest["extensions"] = _pairs(cur, EXTENSIONS_SQL)
    manifest["comments"] = _pairs(cur, COMMENTS_SQL)
    manifest["default_acls"] = _pairs(cur, DEFAULT_ACL_SQL)
    manifest["db_settings"] = _pairs(cur, DB_SETTINGS_SQL)

    cur.execute(LARGE_OBJECT_SQL)
    lo_count, lo_digest = cur.fetchone()
    manifest["large_objects"] = {"count": lo_count, "digest": lo_digest}

    cur.execute(DATABASE_SQL)
    manifest["database"] = cur.fetchone()[0]

    tables = sorted(
        key for key, value in manifest["relations"].items() if value.startswith("r ")
    )
    matviews = sorted(
        key for key, value in manifest["relations"].items() if value.startswith("m ")
    )
    manifest["table_count"] = len(tables)
    manifest["tables"] = tables

    # A materialised view restored WITH NO DATA cannot be read at all --
    # "materialized view has not been populated" is an error, not an empty
    # result -- so asking for its digest crashed the verifier with a traceback
    # instead of reporting the one thing that was wrong with the restore.
    unpopulated = {
        key
        for key, value in manifest["relations"].items()
        if " populated=false" in value
    }
    counts, digests = _digest_relations(cur, tables)
    manifest["row_counts"] = counts
    manifest["row_digests"] = digests

    mv_counts, mv_digests = _digest_relations(cur, matviews, unpopulated)
    manifest["matview_counts"] = mv_counts
    manifest["matview_digests"] = mv_digests

    # Read live only so a drift can be REPORTED. It is not compared: sequences
    # are non-transactional, so this value is already ahead of the dump on any
    # source taking writes. The comparison uses the artifact's setval calls.
    cur.execute("""
        SELECT n.nspname || '.' || c.relname
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'S' ORDER BY 1
    """)
    manifest["sequence_names"] = [row[0] for row in cur.fetchall()]
    manifest["sequence_state"] = _read_sequence_state(cur, manifest["sequence_names"])

    manifest["total_rows"] = sum(counts.values())
    manifest["business_rows"] = sum(
        n
        for table, n in counts.items()
        if table.split(".", 1)[-1] not in BOOKKEEPING_TABLES
    )
    return manifest


def _digest_relations(
    cur: psycopg.Cursor, names: list[str], unpopulated: set[str] | None = None
) -> tuple[dict[str, Any], dict[str, str]]:
    counts: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for name in names:
        if unpopulated and name in unpopulated:
            counts[name] = "UNPOPULATED"
            digests[name] = "UNPOPULATED"
            continue
        schema, _, table = name.partition(".")
        cur.execute(DIGEST_SQL.format(_sql.Identifier(schema, table)))
        count, digest = cur.fetchone()
        counts[name] = count
        digests[name] = digest
    return counts, digests


def _read_sequence_state(cur: psycopg.Cursor, names: list[str]) -> dict[str, str]:
    """Read last_value/is_called per sequence, in the form setval() records."""
    state: dict[str, str] = {}
    for name in names:
        schema, _, seq = name.partition(".")
        cur.execute(
            _sql.SQL("SELECT last_value, is_called FROM {}").format(
                _sql.Identifier(schema, seq)
            )
        )
        last_value, is_called = cur.fetchone()
        state[name] = f"{last_value} is_called={bool(is_called)}"
    return state


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(argv: list[str], what: str) -> str:
    completed = subprocess.run(argv, capture_output=True, text=True)
    if completed.returncode != 0:
        print(f"{what} FAILED (exit {completed.returncode}):", file=sys.stderr)
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(2)
    return completed.stdout


SETVAL_RE = re.compile(
    r"setval\(\s*'((?:[^']|'')+)'\s*,\s*(-?\d+)\s*,\s*(true|false)\s*\)",
    re.IGNORECASE,
)


def sequences_from_dump(dump_path: str) -> dict[str, str]:
    """Read sequence positions out of the ARTIFACT, which is the only correct
    reference for them.

    `pg_dump` reads a sequence's `last_value` when it reaches that sequence.
    Nothing holds it still — sequences are exempt from MVCC — so on a source
    taking writes the live catalog is already ahead of the bytes in the dump by
    the time the dump finishes. Reading the reference from the live catalog
    therefore reported a *perfect* restore as corruption:

        FAIL sequence[public.django_content_type_id_seq]: expected 383 got 363

    where the dump itself contained `setval(..., 363, true)` and 363 is exactly
    what a faithful restore must produce. The artifact's own setval calls are
    read here instead, via a TOC list filtered to SEQUENCE SET entries so no
    table data has to be decompressed.
    """
    toc = _run(["pg_restore", "-l", dump_path], "pg_restore -l")
    wanted = [line for line in toc.splitlines() if "SEQUENCE SET" in line]
    if not wanted:
        return {}
    listing = dump_path + ".seqlist"
    try:
        with open(listing, "w") as handle:
            handle.write("\n".join(wanted) + "\n")
        sql = _run(
            ["pg_restore", "-L", listing, "-f", "-", dump_path],
            "pg_restore (sequence section)",
        )
    finally:
        try:
            os.unlink(listing)
        except OSError:
            pass
    found: dict[str, str] = {}
    for match in SETVAL_RE.finditer(sql):
        name = match.group(1).replace("''", "'").replace('"', "")
        found[name] = f"{match.group(2)} is_called={match.group(3).lower() == 'true'}"
    return found


DB_STMT_RE = re.compile(
    r"^\s*(CREATE\s+DATABASE|ALTER\s+DATABASE|GRANT\b[^;]*?\bON\s+DATABASE"
    r"|REVOKE\b[^;]*?\bON\s+DATABASE)\b",
    re.IGNORECASE | re.DOTALL,
)
CREATE_DB_RE = re.compile(
    r'^\s*CREATE\s+DATABASE\s+("(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)',
    re.IGNORECASE,
)


def database_statements(dump_path: str) -> tuple[str, list[str]]:
    """Extract the artifact's own database-level statements, and its db name.

    `pg_dump --create` puts the database's encoding, locale provider, locale,
    ownership, ACL and every `ALTER DATABASE ... SET` into the archive. Without
    them the rehearsal created its scratch database with a bare
    `CREATE DATABASE`, which inherits the CLUSTER's locale from template1 and
    carries no settings at all — so an ICU-collated source was certified as a
    C.UTF-8 copy, a `search_path` set on the database vanished, and anything a
    colleague had left in template1 was silently present in the "restore".
    """
    text = _run(
        ["pg_restore", "--create", "--schema-only", "-f", "-", dump_path],
        "pg_restore (database section)",
    )
    # Every database-level statement precedes the first CREATE of anything
    # else, so cut there rather than trying to parse a megabyte of schema.
    lines = text.splitlines()
    cut = len(lines)
    for index, line in enumerate(lines):
        upper = line.upper()
        if upper.startswith("CREATE ") and not upper.startswith("CREATE DATABASE"):
            cut = index
            break
    # Comments have to go before the split: pg_dump's own object headers read
    # "-- Name: x; Type: DATABASE; Schema: -; Owner: y" and those semicolons
    # would otherwise chop the CREATE DATABASE statement in half.
    head = "\n".join(
        line
        for line in lines[:cut]
        if not line.lstrip().startswith("--") and not line.startswith("\\")
    )
    statements = [
        statement.strip() + ";"
        for statement in head.split(";")
        if DB_STMT_RE.match(statement.strip())
    ]
    create = next((s for s in statements if CREATE_DB_RE.match(s)), None)
    if create is None:
        raise SystemExit(
            "  FAIL  the dump carries no CREATE DATABASE statement — it was not "
            "taken with pg_dump --create, so it does not carry the database's "
            "encoding, locale or settings"
        )
    name = CREATE_DB_RE.match(create).group(1)
    return name, statements


# The head of every database-level statement pg_dump --create emits, with the
# database name as the last group so only THAT occurrence is rewritten.
#
# Substituting every occurrence of the identifier instead was wrong wherever a
# database and its owning role share a name — which is this project's own
# configuration, and the ordinary one. `ALTER DATABASE edify OWNER TO edify;`
# became `ALTER DATABASE "restore_rehearsal_…" OWNER TO "restore_rehearsal_…";`
# and the run died on `role "restore_rehearsal_…" does not exist`, having
# already created the database. The rehearsal could not complete against dev,
# staging or production.
DB_STMT_HEAD_RE = re.compile(
    r"^\s*(CREATE\s+DATABASE|ALTER\s+DATABASE|COMMENT\s+ON\s+DATABASE|"
    r"DROP\s+DATABASE(?:\s+IF\s+EXISTS)?|GRANT\s+.+?\s+ON\s+DATABASE|"
    r"REVOKE\s+.+?\s+ON\s+DATABASE)\s+"
    r'("(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)',
    re.IGNORECASE | re.DOTALL,
)


def _retarget_database_name(
    statement: str, source_ident: str, target: str
) -> str | None:
    """Point one database-level statement at the scratch database.

    Rewrites the database name where the grammar says the database name is,
    and nothing else. Returns None when the statement's head is not one this
    function understands, or when the name it carries is not the artifact's
    own database — both of which stop the run rather than being guessed at.
    """
    match = DB_STMT_HEAD_RE.match(statement)
    if match is None:
        return None
    if _fold_ident(match.group(2)) != _fold_ident(source_ident):
        return None
    start, end = match.span(2)
    return statement[:start] + target + statement[end:]


def _fold_ident(ident: str) -> str:
    """The name an identifier denotes, quoted or not."""
    ident = ident.strip()
    if ident.startswith('"') and ident.endswith('"'):
        return ident[1:-1].replace('""', '"')
    return ident.lower()


def prepare(dump_path: str, scratch_db: str, expected_source: str = "") -> int:
    """Emit the SQL that creates the scratch database FROM THE ARTIFACT."""
    source_ident, statements = database_statements(dump_path)
    if expected_source:
        named = source_ident.strip('"').replace('""', '"')
        if named != expected_source:
            print(
                f"  FAIL  the artifact is a dump of {named!r}, not of "
                f"{expected_source!r} — this is not the backup this run took",
                file=sys.stderr,
            )
            return 1
    create = next(s for s in statements if CREATE_DB_RE.match(s))
    if "TEMPLATE" not in create.upper():
        print(
            "  FAIL  the artifact's CREATE DATABASE names no TEMPLATE, so the "
            "restore would inherit whatever is in template1",
            file=sys.stderr,
        )
        return 1
    target = '"' + scratch_db.replace('"', '""') + '"'
    for statement in statements:
        retargeted = _retarget_database_name(statement, source_ident, target)
        if retargeted is None:
            print(
                f"  FAIL  cannot retarget a database statement at {scratch_db}: "
                f"{statement[:120]}",
                file=sys.stderr,
            )
            return 1
        print(retargeted)
    print(
        f"-- {len(statements)} database-level statement(s) taken from the artifact, "
        f"retargeted from {source_ident} to {target}",
        file=sys.stderr,
    )
    return 0


def capture(dsn: str, out_manifest: str, out_dump: str) -> dict[str, Any]:
    """Dump the database and describe the dump, from one shared snapshot."""
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        cur = conn.cursor()
        # Isolation level first: Postgres refuses SET TRANSACTION ISOLATION
        # LEVEL once any query has run in the transaction.
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _pin(cur)
        # The snapshot must stay open for the whole dump, which means this
        # session sits idle in a transaction for that long. A source with
        # idle_in_transaction_session_timeout set below the dump time — normal
        # production hygiene, and the default on several managed offerings —
        # would otherwise kill this connection and turn a perfectly good backup
        # into a raw Python traceback. statement_timeout likewise: the manifest
        # read is a full pass over every row of every table.
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute("SET statement_timeout = 0")
        cur.execute("SET lock_timeout = 0")
        cur.execute("SELECT pg_catalog.pg_export_snapshot()")
        snapshot = cur.fetchone()[0]
        print(f"  exported snapshot: {snapshot}")

        started = time.time()
        # --create carries the database's encoding, locale and settings into
        # the artifact. Owner and privileges are NOT suppressed: a backup that
        # discards every GRANT restores to a database the application cannot
        # read, and the gate used to certify exactly that.
        _run(
            [
                "pg_dump",
                "--format=custom",
                "--compress=0",
                "--create",
                f"--snapshot={snapshot}",
                "--file",
                out_dump,
                dsn,
            ],
            "pg_dump",
        )
        dump_secs = time.time() - started

        started = time.time()
        # Read INSIDE the dump's own snapshot: the reference now describes the
        # dump file rather than whatever the live source drifted to since.
        manifest = read_manifest(cur)
        manifest_secs = time.time() - started
        conn.rollback()
    finally:
        conn.close()

    manifest["_dump_seconds"] = round(dump_secs, 3)
    manifest["_manifest_seconds"] = round(manifest_secs, 3)
    manifest["_snapshot"] = snapshot
    manifest["_dump_file"] = os.path.abspath(out_dump)
    manifest["_dump_bytes"] = os.path.getsize(out_dump)
    manifest["_dump_sha256"] = sha256_of(out_dump)
    manifest["dump_sequences"] = sequences_from_dump(out_dump)

    with open(out_manifest, "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True, default=str)

    drift = [
        name
        for name, value in manifest["dump_sequences"].items()
        if manifest["sequence_state"].get(name) != value
    ]
    print(f"  pg_dump           : {dump_secs:.3f}s")
    print(f"  manifest read     : {manifest_secs:.3f}s")
    print(f"  dump bytes        : {manifest['_dump_bytes']}")
    print(f"  dump sha256       : {manifest['_dump_sha256']}")
    print(f"  schemas           : {', '.join(sorted(manifest['schemas'])) or 'none'}")
    print(f"  tables            : {manifest['table_count']}")
    print(f"  indexes           : {len(manifest['indexes'])}")
    print(f"  constraints       : {len(manifest['constraints'])}")
    print(
        f"  views / matviews  : "
        f"{sum(1 for v in manifest['relations'].values() if v.startswith('v '))}"
        f" / {len(manifest['matview_counts'])}"
    )
    print(
        f"  routines/triggers : {len(manifest['routines'])} / "
        f"{len(manifest['triggers'])}"
    )
    print(f"  large objects     : {manifest['large_objects']['count']}")
    print(f"  sequences in dump : {len(manifest['dump_sequences'])}")
    if drift:
        print(
            f"  note: {len(drift)} sequence(s) advanced on the source while the dump "
            f"ran; the dump's own setval values are the reference"
        )
    print(f"  total rows        : {manifest['total_rows']}")
    print(f"  business rows     : {manifest['business_rows']}")
    return manifest


def load_manifest(path: str) -> dict[str, Any]:
    """Load a captured manifest, treating an unreadable one as a hard failure."""
    try:
        with open(path) as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"  FAIL  manifest unreadable at {path}: {exc}") from exc
    if not isinstance(loaded, dict) or "table_count" not in loaded:
        raise SystemExit(
            f"  FAIL  manifest at {path} is not a restore manifest "
            f"(no table_count) — refusing to compare against it"
        )
    return loaded


def check_dump(manifest_path: str, dump_path: str, label: str = "") -> int:
    """Compare the dump artifact on disk with what capture recorded about it.

    Run once, against the file capture just wrote, this cannot fail: the same
    process tree hashed the same bytes seconds earlier. It earns its keep only
    at the point of USE, which is why the rehearsal calls it immediately before
    pg_restore and again immediately after. Swapping the artifact in that window
    was demonstrated to produce a full PASS; it now produces a FAIL.
    """
    manifest = load_manifest(manifest_path)
    suffix = f" ({label})" if label else ""
    failures = []
    try:
        actual_bytes = os.path.getsize(dump_path)
    except OSError as exc:
        print(f"  FAIL  dump artifact unreadable{suffix}: {exc}")
        return 1
    if actual_bytes != manifest["_dump_bytes"]:
        failures.append(f"size: expected {manifest['_dump_bytes']} got {actual_bytes}")
    actual_sha = sha256_of(dump_path)
    if actual_sha != manifest["_dump_sha256"]:
        failures.append(f"sha256: expected {manifest['_dump_sha256']} got {actual_sha}")
    if failures:
        for failure in failures:
            print(f"  FAIL  dump artifact does not match the manifest — {failure}")
        return 1
    print(
        f"  PASS  {'dump artifact intact' + suffix:<42} "
        f"{actual_bytes} bytes, sha256 {actual_sha[:16]}…"
    )
    return 0


def row_count_of(manifest_path: str, table: str) -> int:
    """Report what the dump holds for one table, for callers in shell.

    Exits 1 when the table is absent from the manifest, which is a different
    answer from "zero rows" and must not be confused with it.
    """
    manifest = load_manifest(manifest_path)
    counts = manifest.get("row_counts", {})
    if table in counts:
        return counts[table]
    qualified = f"public.{table}"
    if qualified in counts:
        return counts[qualified]
    print(f"table {table!r} is not in the manifest", file=sys.stderr)
    raise SystemExit(1)


def check_evidence(manifest_path: str) -> int:
    """Report how much data the snapshot held, and refuse to over-claim it.

    This is what replaces the "dump is implausibly small" byte floor. A dump of
    this schema with every table empty measures 1.78 MB, so bytes cannot answer
    the question.

    What it can honestly say: below one row outside Django's bookkeeping tables
    there is nothing for a round trip to prove. What it must NOT claim is that
    clearing the bar means the estate is populated — the count includes the
    reference data migrations seed (2,562 sub-counties, 1,691 parishes, 683 help
    articles ...), so a `migrate`-only install clears it with 6,445 rows and has
    never been used. Zero is therefore INCONCLUSIVE, not FAILED: the backup is
    not shown to be broken, it is shown to be unproven.
    """
    manifest = load_manifest(manifest_path)
    business = manifest.get("business_rows", 0)
    total = manifest.get("total_rows", 0)
    if business <= 0:
        print(
            f"  NOT PROVEN  {'source snapshot carries no data':<38} "
            f"{total} total rows, {business} outside Django bookkeeping"
        )
        print(
            "        A faithful round trip of an empty database is faithful and "
            "proves nothing about preserving data."
        )
        return EXIT_INCONCLUSIVE
    print(
        f"  PASS  {'source snapshot carries data to lose':<42} "
        f"{business} rows outside Django bookkeeping, of {total}"
    )
    return 0


# A cast over an array literal comes back from a dump/restore round trip with
# the cast distributed over the elements:
#
#   source   ... = ANY ((ARRAY['open'::character varying])::text[])
#   restored ... = ANY (ARRAY[('open'::character varying)::text])
#
# Same predicate, same behaviour, different parse tree — Postgres deparsed it,
# pg_dump wrote the text, and Postgres parsed the text back into a slightly
# different tree. Eleven of this schema's indexes and CHECK constraints do it
# on every single restore. Comparing the deparsed text alone therefore failed a
# perfect restore, so a difference that survives only casts and parentheses is
# reported as a renormalisation rather than a failure. Everything else — a
# dropped WHERE clause, a CHECK replaced by CHECK (true), an added ON DELETE
# CASCADE, a unique index that came back non-unique — still fails, because none
# of those is a difference of casts and parentheses.
_CAST_RE = re.compile(
    r'::\s*(?:"[^"]+"|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)'
    r"(?:\s+varying|\s+precision|\s+with(?:out)?\s+time\s+zone)*"
    r"(?:\s*\[\s*\])*"
)


def canonical_sql(text: Any) -> Any:
    """Strip casts and parentheses so only the substance of a definition is left."""
    if not isinstance(text, str):
        return text
    stripped = _CAST_RE.sub(" ", text)
    for punctuation in "()[],":
        stripped = stripped.replace(punctuation, f" {punctuation} ")
    return " ".join(stripped.replace("(", "").replace(")", "").split())


def _abbreviate(value: Any, limit: int = 160) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _Differ:
    """Accumulates per-key failures with bounded, readable messages."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.renormalised: list[str] = []
        self.checks = 0

    def scalar(self, name: str, want: Any, got: Any, detail: str = "") -> None:
        self.checks += 1
        if want != got:
            self.failures.append(
                f"{name}: expected {_abbreviate(want)} got {_abbreviate(got)} "
                f"{detail}".rstrip()
            )

    def mapping(
        self,
        name: str,
        want: dict[str, Any],
        got: dict[str, Any],
        detail: str = "",
        sql: bool = False,
    ) -> None:
        """Diff two mappings per key.

        Per key, not per mapping: a gate that answers "these two 300-entry
        mappings differ" and leaves the operator to find the difference is a
        gate people stop reading. Missing and unexpected keys are summarised
        with a bounded sample rather than one 6 KB line — the previous version
        appended all 308 table names as a single failure string, which then
        slipped past its own "first 20 failures" cap.
        """
        missing = sorted(set(want) - set(got))
        unexpected = sorted(set(got) - set(want))
        self.checks += len(set(want) | set(got))
        if missing:
            self.failures.append(
                f"{name}: {len(missing)} MISSING from the restore: "
                f"{', '.join(missing[:8])}{' …' if len(missing) > 8 else ''}"
            )
        if unexpected:
            self.failures.append(
                f"{name}: {len(unexpected)} UNEXPECTED in the restore: "
                f"{', '.join(unexpected[:8])}{' …' if len(unexpected) > 8 else ''}"
            )
        for key in sorted(set(want) & set(got)):
            if want[key] == got[key]:
                continue
            if sql and canonical_sql(want[key]) == canonical_sql(got[key]):
                self.renormalised.append(f"{name}[{key}]")
                continue
            self.failures.append(
                f"{name}[{key}]: expected {_abbreviate(want[key])} "
                f"got {_abbreviate(got[key])} {detail}".rstrip()
            )


def diff_manifest(
    expected: dict[str, Any], actual: dict[str, Any]
) -> tuple[list[str], int, list[str]]:
    """Diff a restored database against the captured reference."""
    differ = _Differ()

    differ.scalar("database properties", expected["database"], actual["database"])
    differ.mapping("db_setting", expected["db_settings"], actual["db_settings"])
    differ.mapping("schema", expected["schemas"], actual["schemas"])
    differ.mapping("relation", expected["relations"], actual["relations"])
    differ.mapping("column", expected["columns"], actual["columns"], sql=True)
    differ.mapping("index", expected["indexes"], actual["indexes"], sql=True)
    differ.mapping(
        "constraint", expected["constraints"], actual["constraints"], sql=True
    )
    differ.mapping("viewdef", expected["viewdefs"], actual["viewdefs"], sql=True)
    differ.mapping("routine", expected["routines"], actual["routines"])
    differ.mapping("trigger", expected["triggers"], actual["triggers"], sql=True)
    differ.mapping("policy", expected["policies"], actual["policies"], sql=True)
    differ.mapping("extension", expected["extensions"], actual["extensions"])
    differ.mapping("comment", expected["comments"], actual["comments"])
    differ.mapping("default_acl", expected["default_acls"], actual["default_acls"])
    differ.scalar("large_objects", expected["large_objects"], actual["large_objects"])

    differ.scalar("table_count", expected["table_count"], actual["table_count"])
    differ.scalar("total_rows", expected["total_rows"], actual["total_rows"])
    differ.mapping("row_count", expected["row_counts"], actual["row_counts"])
    differ.mapping(
        "row_digest",
        expected["row_digests"],
        actual["row_digests"],
        "(CONTENT differs — same row count)",
    )

    # Sequences: expected comes from the ARTIFACT's setval calls, never from
    # the live source. See sequences_from_dump().
    differ.mapping(
        "sequence", expected.get("dump_sequences", {}), actual["sequence_state"]
    )

    # Materialised views are the one thing pg_dump genuinely does not carry.
    # The archive holds the DEFINITION plus a REFRESH that re-executes at
    # restore time, so the contents of the copy are recomputed rather than
    # restored. When they come out different, the operator's mental model —
    # "my backup preserves my database" — is wrong about this relation, and
    # that is worth failing over rather than not looking.
    differ.mapping(
        "matview_rows",
        expected["matview_counts"],
        actual["matview_counts"],
        "(pg_dump carries no matview CONTENTS; the restore RE-COMPUTED it)",
    )
    differ.mapping(
        "matview_digest",
        expected["matview_digests"],
        actual["matview_digests"],
        "(pg_dump carries no matview CONTENTS; the restore RE-COMPUTED it)",
    )
    return differ.failures, differ.checks, differ.renormalised


def snapshot(dsn: str, out_path: str) -> int:
    """Write a manifest of the database as it stands right now.

    Used either side of the application smoke test. The smoke test claims to be
    read-only; the previous one made the claim in its docstring while inserting
    331 rows and changing fields of `school` and `user` in place. Two snapshots
    and a diff check the claim instead of trusting it, and they compare the copy
    with ITSELF, so a legitimately non-deterministic relation (a materialised
    view over now(), say) cannot masquerade as the smoke test writing.
    """
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _pin(cur)
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute("SET statement_timeout = 0")
        manifest = read_manifest(cur)
        conn.rollback()
    finally:
        conn.close()
    with open(out_path, "w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True, default=str)
    return 0


def compare(before_path: str, after_path: str, label: str) -> int:
    """Diff two manifests of the same database, taken at different times."""
    before = load_manifest(before_path)
    after = load_manifest(after_path)
    # Sequences are the one thing that legitimately moves without anybody
    # writing a row: reading a sequence advances it. Compare them anyway --
    # the smoke test is not supposed to consume identifiers either.
    before = dict(before, dump_sequences=before["sequence_state"])
    after = dict(after)
    failures, checks, _ = diff_manifest(before, after)
    if failures:
        print(f"  FAIL  {label} — {len(failures)} of {checks} checks moved")
        for failure in failures[:25]:
            print("    FAIL " + failure)
        if len(failures) > 25:
            print(f"    ... and {len(failures) - 25} more")
        return 1
    print(f"  PASS  {label:<42} {checks} checks, nothing moved")
    return 0


def verify(dsn: str, in_manifest: str) -> int:
    """Read the restored database and diff it against the captured manifest."""
    expected = load_manifest(in_manifest)
    conn = psycopg.connect(dsn, autocommit=False)
    try:
        cur = conn.cursor()
        # One snapshot for the whole read, so the reading cannot be internally
        # inconsistent if anything writes to the copy while it runs. It has to
        # be the first statement in the transaction.
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        _pin(cur)
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute("SET statement_timeout = 0")
        started = time.time()
        actual = read_manifest(cur)
        secs = time.time() - started
        conn.rollback()
    finally:
        conn.close()

    failures, checks, renormalised = diff_manifest(expected, actual)
    print(
        f"  verify ran {checks} checks in {secs:.3f}s over "
        f"{actual['table_count']} tables / {actual['total_rows']} rows / "
        f"{len(actual['indexes'])} indexes / {len(actual['constraints'])} constraints"
    )
    if renormalised:
        # Reported, never silent: an operator has to be able to see which
        # definitions were treated as equivalent rather than compared byte for
        # byte, and decide for themselves.
        print(
            f"  note: {len(renormalised)} definition(s) came back re-parsed into an "
            f"equivalent form (casts/parentheses): "
            f"{', '.join(renormalised[:4])}"
            f"{' …' if len(renormalised) > 4 else ''}"
        )
    if failures:
        print(f"  FAIL  restored copy differs from the dump — {len(failures)} check(s)")
        for failure in failures[:25]:
            print("    FAIL " + failure)
        if len(failures) > 25:
            print(f"    ... and {len(failures) - 25} more")
        return 1
    print(
        f"  PASS  {'restored copy matches the dump':<42} "
        f"{checks} checks over {actual['table_count']} tables, "
        f"{actual['total_rows']} rows"
    )
    return 0


USAGE = (
    "usage: restore_manifest.py capture <manifest.json> <dump>\n"
    "       restore_manifest.py checkdump <manifest.json> <dump> [label]\n"
    "       restore_manifest.py prepare <dump> <scratch-db> [expected-source-db]\n"
    "       restore_manifest.py evidence <manifest.json>\n"
    "       restore_manifest.py rowcount <manifest.json> <table>\n"
    "       restore_manifest.py snapshot <manifest.json>\n"
    "       restore_manifest.py compare <before.json> <after.json> <label>\n"
    "       restore_manifest.py verify <manifest.json>"
)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    command = argv[1]
    if command == "capture" and len(argv) == 4:
        capture(resolve_dsn(), argv[2], argv[3])
        return 0
    if command == "checkdump" and len(argv) in (4, 5):
        return check_dump(argv[2], argv[3], argv[4] if len(argv) == 5 else "")
    if command == "prepare" and len(argv) in (4, 5):
        return prepare(argv[2], argv[3], argv[4] if len(argv) == 5 else "")
    if command == "evidence" and len(argv) == 3:
        return check_evidence(argv[2])
    if command == "rowcount" and len(argv) == 4:
        print(row_count_of(argv[2], argv[3]))
        return 0
    if command == "snapshot" and len(argv) == 3:
        return snapshot(resolve_dsn(), argv[2])
    if command == "compare" and len(argv) == 5:
        return compare(argv[2], argv[3], argv[4])
    if command == "verify" and len(argv) == 3:
        return verify(resolve_dsn(), argv[2])
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
