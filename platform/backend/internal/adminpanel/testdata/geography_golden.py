"""Write the Geographical Location Setup golden:
/admin-panel/region-district-setup
(extended_views.admin_region_district_setup_view,
pages/admin/region_district_setup.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminpanel/testdata/geography_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdst", two districts in the first region (one secondary, one not
yet classified), an approved Secondary District Group with no districts and
a draft one holding the secondary district; asks the page of the readers who
open it and some who do not, writes the answers with the rows as the
database held them (`tables`), and deletes the rows.
internal/integration/admin_geography_test.go files them again and asks Go.
"""

import json
import os

from django.conf import settings
from django.db import connection

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("geography_golden.py runs only against a _test database")

P = "gdst"
PAGE = "/admin-panel/region-district-setup"
READERS = ("admin@edify.org", "cd@edify.org", "ia@edify.org")
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("district", "secondary_district_group", "secondary_district_group_member")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows():
    from apps.geography.models import (
        District,
        Region,
        SecondaryDistrictGroup,
        SecondaryDistrictGroupMember,
    )

    region = Region.objects.order_by("name").first()
    secondary = District.objects.create(
        id=P + "d1",
        name="Zz Golden Secondary",
        region=region,
        district_type="secondary",
    )
    District.objects.create(id=P + "d2", name="Aa Golden Unclassified", region=region)
    SecondaryDistrictGroup.objects.create(
        id=P + "g1", name="Aa Golden Route", status="approved"
    )
    draft = SecondaryDistrictGroup.objects.create(
        id=P + "g2", name="Bb Golden Route", status="draft"
    )
    SecondaryDistrictGroupMember.objects.create(
        id=P + "m1", group=draft, district=secondary
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
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = "[{}]"
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
