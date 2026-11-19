"""Write the partner portal's golden: Assigned Schools (/partner/schools),
the Activity Log (/partner/activities) and Assigned Activities
(/partner/assignments) (partner_views.partner_schools_view,
partner_activities_view and partner_assignments_view) as the existing feed
reads them.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/partnerassigned/testdata/portal_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpta", for the partner login's organisation: fifty activities
over the schools it works with (so the log runs past its sixty and a page of
fifty), one at a school it had no work at, one at a cluster, one with
neither, one returned by IA and one cancelled (left out unless asked for);
and assignments awaiting a date (one at a school with a catalogue item and a
focus, one at a cluster with neither), one scheduled and one handed back. It
asks each page of the partner logins and the staff who open them, with each
status and page, writes the answers with the rows as the database held them
(`tables`), and deletes the rows.
internal/integration/partner_portal_test.go files them again and asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.scoping import resolve_partner_ids

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("portal_golden.py runs only against a _test database")

User = get_user_model()
P = "gpta"
PAGES = ("/partner/schools", "/partner/activities", "/partner/assignments")
READERS = (
    "partner@edify.org",
    "partner-admin@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "cceo1@edify.org",
    "cd@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("activity", "partner_assignment")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(today):
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.clusters.models import Cluster
    from apps.partners.models import Partner, PartnerAssignment
    from apps.schools.models import School

    partner_id = resolve_partner_ids(User.objects.get(email="partner@edify.org"))[0]
    partner = Partner.objects.get(id=partner_id)
    held = list(
        Activity.objects.filter(assigned_partner_id=partner_id, deleted_at__isnull=True)
        .exclude(school=None)
        .values_list("school_id", flat=True)
        .distinct()
    )
    schools = list(School.objects.filter(id__in=held).order_by("id"))
    other = School.objects.exclude(id__in=held).order_by("id").first()
    cluster = Cluster.objects.filter(deleted_at__isnull=True).order_by("id").first()
    fy = str(today.year + 1 if today.month >= 10 else today.year)

    def activity(key, status, days, **kw):
        return Activity.objects.create(
            id=P + key,
            activity_type=kw.pop("activity_type", "school_visit"),
            status=status,
            delivery_type="partner",
            assigned_partner_id=partner_id,
            planned_date=today - timedelta(days=days),
            fy=fy,
            **kw,
        )

    for n in range(50):
        activity(
            f"log{n:02d}",
            ("completed", "scheduled", "ia_verified", "closed")[n % 4],
            n * 3 + 1,
            school=schools[n % len(schools)],
        )
    activity("other", "completed", 2, school=other)
    activity(
        "cluster",
        "completed",
        5,
        school=None,
        cluster=cluster,
        activity_type="cluster_training",
    )
    activity("nowhere", "submitted_to_ia", 8, school=None)
    activity("returned", "returned_by_ia", 11, school=schools[0])
    activity("cancelled", "cancelled", 1, school=other)

    item = ActivityCatalogueItem.objects.order_by("display_name").first()
    for key, status, kw in (
        (
            "pending",
            "assigned",
            {
                "school": schools[0],
                "catalogue_item": item,
                "focus_intervention": "leadership",
            },
        ),
        ("cluster", "pending_scheduling", {"cluster": cluster}),
        ("scheduled", "partner_scheduled", {"school": schools[1 % len(schools)]}),
        ("handed_back", "returned_to_staff", {"school": schools[0]}),
    ):
        PartnerAssignment.objects.create(
            id=P + key, partner=partner, status=status, **kw
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows(timezone.localdate())
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = ",".join(PAGES)
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            {},
            {"status": "cancelled"},
            {"status": "completed"},
            {"status": "nonsense"},
            {"activities_page": "2"},
            {"schools_page": "2"},
        ]
    )
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
