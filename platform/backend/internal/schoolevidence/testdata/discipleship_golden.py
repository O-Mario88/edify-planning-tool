"""Write the School Evidence Discipleship golden: /ia/school-evidence/?tab=
discipleship (ia_school_evidence_views.school_evidence_page, its
Discipleship tab) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/schoolevidence/testdata/discipleship_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gsed", discipleship records in three schools Impact Assessment
reads: confirmed records across last year and this (the share of learners in
groups rising, falling and unchanged; one with no enrolment; two this year
in one school so the later counts), pending records by Impact Assessment
and by someone else, a returned one with its reason, a deleted one, enough
this year to page the register; and approved, submitted and other-year
change stories on spiritual domains. It asks the tab of the readers who open
it under its filters, writes the answers with the rows (`tables`) and
deletes the rows.
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
from apps.impact.models import DiscipleshipIndicatorRecord
from apps.targets.models import MostSignificantChangeStory

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("discipleship_golden.py runs only against a _test database")

User = get_user_model()
P = "gsed"
PAGE = "/ia/school-evidence/"
READERS = ("ia@edify.org", "admin@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("impact_discipleship_record", "mscs_story")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_rows():
    ia = User.objects.get(email="ia@edify.org")
    cceo = User.objects.get(email="cceo1@edify.org")
    schools = list(evidence_schools(ia).order_by("name")[:3])
    fy = get_operational_fy()
    prev = str(int(fy) - 1)
    start, _ = get_fy_date_range(fy)
    first = start.date()
    n = 0

    def record(
        school,
        year,
        status,
        *,
        days,
        devotions=None,
        groups=None,
        in_groups=None,
        enrolled=None,
        staff=None,
        lead=None,
        bible=None,
        recorder=cceo,
        reason="",
        deleted=False,
    ):
        nonlocal n
        DiscipleshipIndicatorRecord.objects.create(
            id=f"{P}{n:03d}",
            school=school,
            country="Uganda",
            fy=year,
            observed_on=first + timedelta(days=days),
            devotions_per_week=devotions,
            discipleship_groups_active=groups,
            learners_in_groups=in_groups,
            learners_enrolled=enrolled,
            staff_in_devotions_pct=staff,
            spiritual_lead_in_post=lead,
            bible_lessons_timetabled=bible,
            recorded_by_user_id=recorder.id,
            verification_status=status,
            return_reason=reason,
            deleted_at=timezone.now() if deleted else None,
        )
        n += 1

    a, b, c = schools
    # School a: the share rises (30% last year, 45% now), two this year.
    record(
        a,
        prev,
        "confirmed",
        days=-200,
        devotions=3,
        groups=4,
        in_groups=60,
        enrolled=200,
        staff=50,
        lead=True,
        bible=True,
    )
    record(
        a,
        fy,
        "confirmed",
        days=10,
        devotions=4,
        groups=5,
        in_groups=80,
        enrolled=200,
        staff=60,
        lead=True,
        bible=False,
    )
    record(
        a,
        fy,
        "confirmed",
        days=40,
        devotions=5,
        groups=6,
        in_groups=90,
        enrolled=200,
        staff=75,
        lead=True,
        bible=True,
    )
    # School b: the share falls (an exact half, rounded to even both years).
    record(
        b,
        prev,
        "confirmed",
        days=-150,
        devotions=2,
        groups=3,
        in_groups=25,
        enrolled=40,
        lead=False,
        bible=False,
    )
    record(
        b,
        fy,
        "confirmed",
        days=20,
        devotions=2,
        groups=2,
        in_groups=1,
        enrolled=8,
        staff=25,
        lead=False,
    )
    # School c: nobody enrolled this year (not measured); unchanged last year.
    record(
        c,
        prev,
        "confirmed",
        days=-100,
        devotions=1,
        groups=1,
        in_groups=10,
        enrolled=50,
    )
    record(
        c,
        fy,
        "confirmed",
        days=30,
        devotions=1,
        groups=1,
        in_groups=12,
        enrolled=0,
        staff=10,
        bible=True,
    )
    # Pending: by Impact Assessment (not theirs to verify) and by someone else.
    record(a, fy, "pending", days=50, devotions=3, recorder=ia)
    record(b, fy, "pending", days=51, groups=2, in_groups=7)
    # Returned with its reason; and one deleted.
    record(
        c,
        fy,
        "returned",
        days=52,
        devotions=6,
        reason="The enrolment is the whole school, not the class",
    )
    record(
        c,
        fy,
        "confirmed",
        days=60,
        devotions=9,
        in_groups=50,
        enrolled=50,
        deleted=True,
    )
    # Enough this year to page the register.
    for k in range(45):
        record(
            schools[k % 3],
            fy,
            "pending" if k % 5 == 0 else "confirmed",
            days=-1 - k,
            devotions=k % 7,
            groups=k % 4,
        )

    s = 0

    def story(school, status, *, days, intervention="christlike_behaviour", outcome=""):
        nonlocal s
        MostSignificantChangeStory.objects.create(
            id=f"{P}s{s:02d}",
            user_id=cceo.id,
            school=school,
            country="Uganda",
            title=f"Change story {s}",
            narrative="A learner's change, told by the head teacher.",
            story_date=first + timedelta(days=days),
            status=status,
            intervention=intervention,
            outcome_area=outcome,
        )
        s += 1

    story(a, "approved", days=15)
    story(a, "approved", days=25, intervention="exposure_to_word_of_god")
    story(b, "approved", days=35)
    story(b, "submitted", days=36)
    story(c, "approved", days=-30)
    story(c, "approved", days=37, intervention="leadership")


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
    d = {"tab": "discipleship"}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            d,
            {**d, "register_page": "2"},
            {**d, "status": "pending"},
            {**d, "status": "returned"},
            {**d, "register_page": "9"},
            {**d, "fy": str(int(fy) - 1)},
            {**d, "fy": str(int(fy) + 1)},
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
