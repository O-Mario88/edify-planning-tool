"""Write the School Evidence EdTech golden: /ia/school-evidence/?tab=edtech
(ia_school_evidence_views.school_evidence_page, its EdTech tab) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/schoolevidence/testdata/edtech_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gset", EdTech deployments in three schools Impact Assessment
reads: confirmed ones checked several times (a later deleted check, a later
pending one), never checked, checked with no access figure, working shares
that round half to even; pending, returned and deleted deployments; enough
this year to page the register and the summary and to fill the checks table
past its fifty; checks recorded by Impact Assessment and by someone else. It
asks the tab of the readers who open it under its filters, writes the
answers with the rows (`tables`) and deletes the rows.
internal/integration/school_evidence_test.go files them again and asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.core.fy import get_fy_date_range, get_operational_fy
from apps.impact.evidence_services import evidence_schools
from apps.impact.models import EdTechCheck, EdTechDeployment

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("edtech_golden.py runs only against a _test database")

User = get_user_model()
P = "gset"
PAGE = "/ia/school-evidence/"
READERS = ("ia@edify.org", "admin@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("impact_edtech_deployment", "impact_edtech_check")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_rows():
    ia = User.objects.get(email="ia@edify.org")
    cceo = User.objects.get(email="cceo1@edify.org")
    a, b, c = list(evidence_schools(ia).order_by("name")[:3])
    fy = get_operational_fy()
    prev = str(int(fy) - 1)
    first = get_fy_date_range(fy)[0].date()
    n = {"d": 0, "c": 0}

    def deployment(
        school,
        year,
        status,
        asset,
        quantity,
        *,
        days,
        funding="grant",
        access=None,
        reason="",
        deleted=False,
        recorder=cceo,
    ):
        n["d"] += 1
        return EdTechDeployment.objects.create(
            id=f"{P}d{n['d']:03d}",
            school=school,
            country="Uganda",
            fy=year,
            asset_type=asset,
            quantity=quantity,
            deployed_on=first + timedelta(days=days),
            funding=funding,
            learners_with_access=access,
            recorded_by_user_id=recorder.id,
            verification_status=status,
            return_reason=reason,
            deleted_at=timezone.now() if deleted else None,
        )

    def check(
        d,
        year,
        status,
        units,
        *,
        days,
        teachers=None,
        learners=None,
        reason="",
        deleted=False,
        recorder=cceo,
    ):
        n["c"] += 1
        EdTechCheck.objects.create(
            id=f"{P}c{n['c']:03d}",
            school=d.school,
            deployment=d,
            country="Uganda",
            fy=year,
            checked_on=first + timedelta(days=days),
            units_functional=units,
            teachers_using=teachers,
            learners_using=learners,
            recorded_by_user_id=recorder.id,
            verification_status=status,
            return_reason=reason,
            deleted_at=timezone.now() if deleted else None,
        )

    tablets = deployment(a, fy, "confirmed", "tablet", 20, days=5, access=100)
    check(tablets, prev, "confirmed", 10, days=-20, teachers=2, learners=40)
    check(tablets, fy, "confirmed", 17, days=30, teachers=3, learners=80)
    check(tablets, fy, "confirmed", 2, days=40, deleted=True)
    check(tablets, fy, "pending", 19, days=45, recorder=ia)
    check(tablets, fy, "pending", 18, days=46, teachers=4)
    check(tablets, fy, "pending", 20, days=47, deleted=True)
    deployment(a, prev, "confirmed", "laptop", 5, days=-90, funding="school")
    projectors = deployment(
        b, fy, "confirmed", "projector", 3, days=12, funding="project"
    )
    check(projectors, fy, "confirmed", 1, days=50)
    desktops = deployment(b, fy, "confirmed", "desktop", 8, days=14, funding="loan")
    check(desktops, fy, "confirmed", 4, days=52, learners=30)
    halves = deployment(b, prev, "confirmed", "tablet", 8, days=-60, access=40)
    check(halves, fy, "confirmed", 1, days=54, teachers=0, learners=0)
    check(
        halves,
        fy,
        "returned",
        3,
        days=55,
        reason="Two of the tablets counted are the teachers' own",
    )
    deployment(c, fy, "pending", "digital_library", 1, days=16, recorder=ia)
    deployment(c, fy, "pending", "digital_library", 2, days=17)
    deployment(
        c,
        fy,
        "returned",
        "connectivity",
        2,
        days=18,
        reason="The router went to the head teacher's house",
    )
    deployment(c, fy, "confirmed", "other", 1, days=19, deleted=True)
    # Enough this year to page the register and the summary, each with a
    # check of use so the checks table passes its fifty.
    schools = (a, b, c)
    assets = ("tablet", "laptop", "desktop", "projector", "other")
    for k in range(50):
        d = deployment(
            schools[k % 3],
            fy,
            "pending" if k % 9 == 0 else "confirmed",
            assets[k % 5],
            2 + k % 6,
            days=60 + k,
        )
        check(
            d,
            fy,
            "pending" if k % 4 == 0 else "confirmed",
            k % 3,
            days=120 + k,
            teachers=k % 5 or None,
            learners=k,
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    fy = get_operational_fy()
    e = {"tab": "edtech"}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            e,
            {**e, "register_page": "2"},
            {**e, "summary_page": "2"},
            {**e, "status": "pending"},
            {**e, "status": "returned"},
            {**e, "asset_type": "tablet"},
            {**e, "asset_type": "rocket"},
            {**e, "fy": str(int(fy) - 1)},
        ],
        sort_keys=True,  # Go writes pager links with sorted keys
    )
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
