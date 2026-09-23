#!/usr/bin/env python3
"""Grow a disposable, demo-seeded database to production volume.

The demo seed holds 700 schools owned by one CCEO. Production holds roughly
16,000 schools and 123,000 SSA scores (see the cache notes in
config/settings/base.py). A page whose cost grows with the estate looks fine at
700 and falls over at 16,000, so load tests and profiles against the demo seed
certify the wrong thing.

This clones the seeded rows in bulk SQL — schools across every sub-county,
open cluster memberships, staff assignments, two years of SSA records with
their intervention scores, and activities in every live workflow state with
their cost snapshots — spread across every CCEO account. It is synthetic data
shaped like production, not a copy of it.

Refuses to run unless the target database name contains "scale" or
"loadtest", so it cannot be pointed at a real database by accident.

    createdb -T edify_seed_pristine edify_scale
    scripts/scale_local_dataset.py --database edify_scale --schools 15500
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg

ACTIVITY_STATUS_MIX = (
    # (status, evidence_status, ia_verification_status, payment_status, weight)
    ("planned", "none", "pending", "none", 22),
    ("scheduled", "none", "pending", "none", 20),
    ("in_progress", "none", "pending", "none", 4),
    ("evidence_uploaded", "uploaded", "pending", "none", 5),
    ("submitted_to_pl", "uploaded", "pending", "none", 5),
    ("awaiting_ia_verification", "accepted", "pending", "pending_ia", 8),
    ("ia_verified", "accepted", "confirmed", "ia_confirmed", 5),
    ("accountant_confirmed", "accepted", "confirmed", "accountant_cleared", 4),
    ("completed", "accepted", "confirmed", "paid", 25),
    ("returned_by_pl", "returned", "pending", "none", 2),
)


def columns(cur, table: str) -> list[str]:
    cur.execute(
        "select column_name from information_schema.columns "
        "where table_name = %s and table_schema = 'public' order by ordinal_position",
        [table],
    )
    return [row[0] for row in cur.fetchall()]


def clone_sql(
    cur, table: str, source: str, overrides: dict[str, str], extra_from=""
) -> str:
    """INSERT INTO table SELECT <columns, overridden> FROM source."""
    cols = columns(cur, table)
    select = ", ".join(overrides.get(c, f"t.{c}") for c in cols)
    return f"insert into {table} ({', '.join(cols)}) select {select} from {source} {extra_from}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--schools", type=int, default=15_500)
    parser.add_argument("--activities-per-school", type=float, default=1.5)
    parser.add_argument("--host", default=os.environ.get("PGHOST", "localhost"))
    parser.add_argument("--user", default=os.environ.get("PGUSER", "edify"))
    parser.add_argument("--password", default=os.environ.get("PGPASSWORD", "edify"))
    args = parser.parse_args()
    if "scale" not in args.database and "loadtest" not in args.database:
        print("refusing: target database name must contain 'scale' or 'loadtest'")
        return 2

    conn = psycopg.connect(
        host=args.host, user=args.user, password=args.password, dbname=args.database
    )
    conn.autocommit = False
    cur = conn.cursor()
    started = time.monotonic()

    cur.execute("select count(*) from school where id like 'scl%'")
    if cur.fetchone()[0]:
        print("already scaled; start again from a fresh template copy")
        return 2

    cur.execute(
        """
        select sp.id, u.name from staff_profile sp join "user" u on u.id = sp.user_id
        where u.active_role = 'CCEO' and u.deleted_at is null order by u.email
        """
    )
    cceos = cur.fetchall()
    if not cceos:
        print("no CCEO accounts; run `manage.py seed --demo` first")
        return 2
    cur.execute(
        "create temp table scale_owner(n int primary key, staff_id text, name text)"
    )
    cur.executemany(
        "insert into scale_owner values (%s, %s, %s)",
        [(i, sid, name) for i, (sid, name) in enumerate(cceos)],
    )
    owners = len(cceos)

    cur.execute(
        """
        create temp table scale_sc as
        select row_number() over (order by sc.id) - 1 as n, sc.id as sub_county_id,
               sc.name as sub_county_name, d.id as district_id, d.region_id
        from sub_county sc join district d on d.id = sc.district_id
        """
    )
    cur.execute("select count(*) from scale_sc")
    sub_counties = cur.fetchone()[0]

    # ── Schools ──────────────────────────────────────────────────────────
    cur.execute(
        "create temp table scale_school as select g as n, "
        "'scl' || lpad(g::text, 9, '0') as id from generate_series(1, %s) g",
        [args.schools],
    )
    template = (
        "(select * from school where source = 'local_test_upload' order by id limit 1)"
    )
    cur.execute(
        clone_sql(
            cur,
            "school",
            f"scale_school s cross join {template} t",
            {
                "id": "s.id",
                "school_id": "(500000 + s.n)::text",
                "name": "sc.sub_county_name || ' ' || (array['Primary School','UMEA Primary School','Hill Primary','Parents Primary'])[1 + s.n % 4] || ' ' || s.n",
                "district_id": "sc.district_id",
                "region_id": "sc.region_id",
                "sub_county_id": "sc.sub_county_id",
                "parish_id": "null",
                "cluster_id": "null",
                "enrollment": "80 + (s.n * 37) % 820",
                "school_type": "(case when s.n % 20 < 16 then 'client' when s.n % 20 < 19 then 'core' else 'champion' end)",
                "current_fy_ssa_status": "(case when s.n % 5 < 2 then 'done' else 'not_done' end)",
                "account_owner_id": "o.staff_id",
                "account_owner_name_raw": "o.name",
                "account_owner_status": "'matched'",
                "salesforce_account_id": "null",
                "created_at": "now()",
                "updated_at": "now()",
            },
            f"join scale_sc sc on sc.n = s.n % {sub_counties} "
            f"join scale_owner o on o.n = s.n % {owners}",
        )
    )
    print(f"schools +{cur.rowcount:,}")

    cur.execute(
        """
        insert into staff_school_assignment (created_at, updated_at, id, school_id, staff_id)
        select now(), now(), 'ssa' || substr(s.id, 4), s.id, sc.account_owner_id
        from scale_school s join school sc on sc.id = s.id
        """
    )
    print(f"staff assignments +{cur.rowcount:,}")

    # ── Clusters: one per sub-county, ~70% of new schools are members ────
    cluster_template = "(select * from cluster order by id limit 1)"
    cur.execute(
        clone_sql(
            cur,
            "cluster",
            f"scale_sc sc cross join {cluster_template} t",
            {
                "id": "'clu' || lpad(sc.n::text, 9, '0')",
                "name": "sc.sub_county_name || ' Cluster'",
                "sub_county_name": "sc.sub_county_name",
                "district_id": "sc.district_id",
                "region_id": "sc.region_id",
                "sub_county_id": "sc.sub_county_id",
                "responsible_staff_id": f"(select staff_id from scale_owner where n = sc.n % {owners})",
                "created_at": "now()",
                "updated_at": "now()",
            },
        )
    )
    print(f"clusters +{cur.rowcount:,}")
    cur.execute(
        f"""
        update school set cluster_id = 'clu' || lpad((s.n % {sub_counties})::text, 9, '0'),
               cluster_status = 'clustered'
        from scale_school s where school.id = s.id and s.n % 10 < 7
        """
    )
    membership_template = (
        "(select * from school_cluster_membership order by id limit 1)"
    )
    cur.execute(
        clone_sql(
            cur,
            "school_cluster_membership",
            f"school sc cross join {membership_template} t",
            {
                "id": "'scm' || substr(sc.id, 4)",
                "cluster_id": "sc.cluster_id",
                "school_id": "sc.id",
                "cluster_district_id": "sc.district_id",
                "school_district_id": "sc.district_id",
                "ended_at": "null",
                "catchment_id": "null",
                "created_at": "now()",
                "updated_at": "now()",
            },
            "where sc.id like 'scl%' and sc.cluster_id is not null",
        )
    )
    print(f"cluster memberships +{cur.rowcount:,}")
    cur.execute(
        """
        insert into school_cluster_assignment (created_at, updated_at, id, assigned_by, cluster_id, school_id)
        select now(), now(), 'sca' || substr(id, 4), 'scale', cluster_id, id
        from school where id like 'scl%' and cluster_id is not null
        """
    )

    # ── SSA: previous FY for 90%, current FY for 40%, 8 scores each ─────
    cur.execute("select max(fy) from ssa_record")
    current_fy = cur.fetchone()[0]
    previous_fy = str(int(current_fy) - 1)
    for fy, modulo, keep in ((previous_fy, 10, 9), (current_fy, 10, 4)):
        assert fy.isdigit()
        ssa_template = (
            f"(select * from ssa_record where fy = '{fy}' order by id limit 1)"
        )
        cur.execute(
            clone_sql(
                cur,
                "ssa_record",
                f"scale_school s cross join {ssa_template} t",
                {
                    "id": f"'sr{fy[-2:]}' || substr(s.id, 4)",
                    "school_id": "s.id",
                    "fy": f"'{fy}'",
                    "average_score": "round((2 + (s.n * 7919 % 600) / 100.0)::numeric, 1)",
                    "salesforce_id": "null",
                    "source_activity_id": "null",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                f"where s.n % {modulo} < {keep}",
            ),
        )
        print(f"ssa records FY{fy} +{cur.rowcount:,}")
    cur.execute(
        """
        insert into ssa_score (created_at, updated_at, id, intervention, score, ssa_record_id)
        select now(), now(), r.id || '_' || i.n, i.intervention,
               1 + ((length(r.id) * 31 + i.n * 17 + ascii(right(r.id, 1))) % 90) / 10.0, r.id
        from ssa_record r
        cross join (
            select row_number() over () as n, intervention
            from (select distinct intervention from ssa_score) x
        ) i
        where r.id like 'sr%'
        """
    )
    print(f"ssa scores +{cur.rowcount:,}")

    # ── Activities in every live workflow state, with cost snapshots ────
    total_weight = sum(row[-1] for row in ACTIVITY_STATUS_MIX)
    cur.execute(
        "create temp table scale_status(lo int, hi int, status text, ev text, ia text, pay text)"
    )
    lo = 0
    for status, ev, ia, pay, weight in ACTIVITY_STATUS_MIX:
        hi = lo + weight
        cur.execute(
            "insert into scale_status values (%s, %s, %s, %s, %s, %s)",
            [lo, hi, status, ev, ia, pay],
        )
        lo = hi
    count = int(args.schools * args.activities_per_school)
    cur.execute(
        "create temp table scale_activity as select g as n, "
        "'sac' || lpad(g::text, 9, '0') as id, "
        "'scl' || lpad((1 + (g * 7) %% %s)::text, 9, '0') as school_id "
        "from generate_series(1, %s) g",
        [args.schools, count],
    )
    activity_template = "(select * from activity where activity_type = 'school_visit' order by id limit 1)"
    cur.execute(
        clone_sql(
            cur,
            "activity",
            f"scale_activity a join school sc on sc.id = a.school_id "
            f"join scale_status st on (a.n * 13) % {total_weight} >= st.lo "
            f"and (a.n * 13) % {total_weight} < st.hi cross join {activity_template} t",
            {
                "id": "a.id",
                "school_id": "a.school_id",
                "cluster_id": "sc.cluster_id",
                "responsible_staff_id": "sc.account_owner_id",
                "approval_owner_id": "coalesce(sc.account_owner_id, t.approval_owner_id)",
                "primary_driver_id": "a.school_id",
                "status": "st.status",
                "evidence_status": "st.ev",
                "ia_verification_status": "st.ia",
                "payment_status": "st.pay",
                "scheduled_date": "(date '2025-10-06' + ((a.n * 3) % 350))::timestamptz",
                "planned_date": "date '2025-10-06' + ((a.n * 3) % 350)",
                "week_start_date": "date '2025-10-06' + ((a.n * 3) % 350) - extract(isodow from date '2025-10-06' + ((a.n * 3) % 350))::int + 1",
                "week_end_date": "date '2025-10-06' + ((a.n * 3) % 350) - extract(isodow from date '2025-10-06' + ((a.n * 3) % 350))::int + 7",
                "month": "extract(month from date '2025-10-06' + ((a.n * 3) % 350))::int",
                "planned_month": "extract(month from date '2025-10-06' + ((a.n * 3) % 350))::int",
                "salesforce_activity_id": "null",
                "paired_school_visit_id": "null",
                "follow_up_of_activity_id": "null",
                "daily_visit_batch_id": "null",
                "source_ssa_id": "null",
                "ssa_recommendation_id": "null",
                "attended_school_ids": "array[]::varchar[]",
                "created_at": "now()",
                "updated_at": "now()",
            },
        )
    )
    print(f"activities +{cur.rowcount:,}")
    snapshot_template = "(select * from activity_cost_snapshot order by id limit 1)"
    cur.execute(
        clone_sql(
            cur,
            "activity_cost_snapshot",
            f"scale_activity a cross join {snapshot_template} t",
            {
                "id": "'acs' || substr(a.id, 4)",
                "activity_id": "a.id",
                "supersedes_id": "null",
                "created_at": "now()",
                "updated_at": "now()",
            },
        )
    )
    print(f"cost snapshots +{cur.rowcount:,}")
    cur.execute(
        """
        update activity set est_cost_cents = s.operational_cost
        from activity_cost_snapshot s
        where s.activity_id = activity.id and activity.id like 'sac%'
        """
    )

    conn.commit()
    conn.autocommit = True
    cur.execute("vacuum analyze")
    cur.execute(
        "select (select count(*) from school), (select count(*) from ssa_record), "
        "(select count(*) from ssa_score), (select count(*) from activity), "
        "(select count(*) from cluster), pg_size_pretty(pg_database_size(current_database()))"
    )
    schools, records, scores, activities, clusters, size = cur.fetchone()
    print(
        f"\n{args.database}: {schools:,} schools, {records:,} SSA records, "
        f"{scores:,} SSA scores, {activities:,} activities, {clusters:,} clusters, "
        f"{size} — {time.monotonic() - started:.0f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
