"""Seed Uganda's administrative boundaries so production actually has them.

Geography is reference data, but it was only ever created by `seed --demo`,
which refuses to run in production. The live database therefore came up with
zero Region, District and SubCounty rows, and because the school upload
resolves a district BY NAME, every school imported with its district text kept
and no foreign key set. District-scoped analytics reported "Coverage: 0 of 0
districts" while the register plainly showed a district against every school.

The seed command now creates this as reference data, but a seed only runs when
somebody sets RUN_SEED and redeploys. Migrations run on every deploy, in the
pre-deploy job, which is the mechanism that actually reaches an already-running
production database. So the boundaries are established here.

Idempotent throughout: get_or_create on every row, and re-running changes
nothing. The reverse is a deliberate no-op — dropping the boundaries would
cascade every school, cluster and assignment hanging off them, which is never
what "roll back one migration" should mean.
"""

from __future__ import annotations

import csv
from pathlib import Path

from django.conf import settings
from django.db import migrations


# Names the operational school register uses that no official list contains.
# The field teams split Wakiso and Mukono into directional working zones, and
# three spellings predate the current UBOS register. Recorded as aliases so the
# mapping is inspectable and revertible, and so a genuinely new district that
# happens to look similar is never quietly absorbed.
DISTRICT_UPLOAD_ALIASES = {
    "Wakiso East": "Wakiso",
    "Wakiso West": "Wakiso",
    "Wakiso North": "Wakiso",
    "Wakiso South": "Wakiso",
    "Mukono North": "Mukono",
    "Mukono South": "Mukono",
    "Sembabule": "Ssembabule",
    "Bukwa": "Bukwo",
    "Bunyangabo": "Bunyangabu",
}


def seed_boundaries(apps, schema_editor):
    # Never during tests. apps/core/reference_data.py is explicit that
    # reference data belongs in a post_migrate ensure_*() rather than a
    # migration, and the reason is exactly this: rows a migration creates land
    # in every test database. Seeding 136 districts and 2,562 sub-counties into
    # a test database breaks the upload tests that build their own two-district
    # fixture and then assert an ambiguous name is reported rather than
    # guessed — it stops being ambiguous once real geography is present.
    #
    # The migration stays because it is the only mechanism that reaches an
    # already-running production database without somebody setting RUN_SEED and
    # redeploying. Tests build their geography explicitly; production cannot.
    if getattr(settings, "IS_TESTING", False):
        return

    Region = apps.get_model("geography", "Region")
    District = apps.get_model("geography", "District")
    SubCounty = apps.get_model("geography", "SubCounty")
    Parish = apps.get_model("geography", "Parish")
    GeographyAlias = apps.get_model("geography", "GeographyAlias")

    csv_path = Path(settings.BASE_DIR) / "uganda_complete_administrative_mapping.csv"
    if not csv_path.exists():
        # Never guess at boundaries. If the reference file is absent the right
        # outcome is an unchanged database, not an invented hierarchy.
        print(f"  geography: reference CSV not found at {csv_path} — skipped.")
        return

    regions: dict[str, object] = {}
    districts: dict[tuple[str, str], object] = {}

    with open(csv_path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            region_name = (row.get("Region") or "").strip()
            district_name = (row.get("District") or "").strip()
            sub_county_name = (row.get("Sub_County") or "").strip()
            if not (region_name and district_name and sub_county_name):
                continue

            if region_name not in regions:
                regions[region_name], _ = Region.objects.get_or_create(
                    name=region_name
                )
            region = regions[region_name]

            key = (region_name, district_name)
            if key not in districts:
                districts[key], _ = District.objects.get_or_create(
                    name=district_name, region=region
                )
            district = districts[key]

            sub_county, _ = SubCounty.objects.get_or_create(
                name=sub_county_name, district=district
            )
            Parish.objects.get_or_create(
                name=f"{sub_county_name} Central", sub_county=sub_county
            )

    by_name = {d.name.strip().casefold(): d for d in District.objects.all()}
    aliases = 0
    for alias, official in DISTRICT_UPLOAD_ALIASES.items():
        district = by_name.get(official.strip().casefold())
        if district is None:
            continue
        _, created = GeographyAlias.objects.get_or_create(
            admin_level="district",
            normalized_alias=alias.strip().casefold(),
            defaults={
                "admin_id": district.id,
                "alias": alias,
                "source": "operational school register",
                "confidence": "curated",
            },
        )
        aliases += int(created)

    print(
        f"  geography: {Region.objects.count()} regions, "
        f"{District.objects.count()} districts, "
        f"{SubCounty.objects.count()} sub-counties, {aliases} new aliases."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0004_correct_dbg_and_restore_terego"),
    ]

    operations = [
        migrations.RunPython(seed_boundaries, migrations.RunPython.noop),
    ]
