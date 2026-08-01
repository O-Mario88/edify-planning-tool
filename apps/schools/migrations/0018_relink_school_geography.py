"""Link schools to the districts they were always meant to have.

Every school in production carries the district name its upload supplied
(``uploaded_district_text``) and no district foreign key, because geography did
not exist when they were imported. The importer resolves geography only at
import time, so creating the boundaries in the previous migration does not fix
rows that are already there — this does, without asking anyone to re-upload a
16,000-school register.

Deliberately conservative:

  * only rows whose district is null are touched, so a link somebody has
    already corrected by hand is never overwritten;
  * matching is exact-name then alias, the same two steps the upload uses. No
    fuzzy matching — a school assigned to the wrong district is worse than one
    visibly assigned to none, because the first is invisible;
  * sub-county is left alone. It is blank in every uploaded row, and inferring
    one from the district would be inventing data.
"""

from __future__ import annotations

from django.conf import settings
from django.db import migrations


def relink(apps, schema_editor):
    # Paired with geography.0005, which does not seed during tests — with no
    # districts to match there is nothing to link, and a test database's
    # schools must keep whatever geography their own fixtures gave them.
    if getattr(settings, "IS_TESTING", False):
        return

    District = apps.get_model("geography", "District")
    GeographyAlias = apps.get_model("geography", "GeographyAlias")
    School = apps.get_model("schools", "School")

    districts = {
        d.name.strip().casefold(): d
        for d in District.objects.select_related("region").all()
    }
    if not districts:
        print("  schools: no districts exist — nothing to link.")
        return

    by_id = {d.id: d for d in districts.values()}
    aliases = {
        alias.strip().casefold(): by_id[admin_id]
        for alias, admin_id in GeographyAlias.objects.filter(
            admin_level="district"
        ).values_list("normalized_alias", "admin_id")
        if admin_id in by_id
    }

    pending = []
    linked = 0
    unresolved: dict[str, int] = {}

    queryset = (
        School.objects.filter(district__isnull=True)
        .exclude(uploaded_district_text__isnull=True)
        .exclude(uploaded_district_text="")
    )
    for school in queryset.iterator(chunk_size=1000):
        key = (school.uploaded_district_text or "").strip().casefold()
        district = districts.get(key) or aliases.get(key)
        if district is None:
            name = (school.uploaded_district_text or "").strip()
            unresolved[name] = unresolved.get(name, 0) + 1
            continue
        school.district = district
        school.region = district.region
        pending.append(school)
        linked += 1
        if len(pending) >= 1000:
            School.objects.bulk_update(pending, ["district", "region"])
            pending.clear()

    if pending:
        School.objects.bulk_update(pending, ["district", "region"])

    print(f"  schools: linked {linked} school(s) to their district.")
    if unresolved:
        total = sum(unresolved.values())
        top = sorted(unresolved.items(), key=lambda kv: -kv[1])[:5]
        print(
            f"  schools: {total} still unresolved; commonest names "
            + ", ".join(f"{name!r} x{count}" for name, count in top)
        )


def unlink(apps, schema_editor):
    """No-op on purpose.

    Clearing these would not restore a previous state — it would destroy links
    that may since have been corrected by hand, and the rows carry no record of
    which ones this migration set.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0017_update_current_partner_types"),
        ("geography", "0005_seed_uganda_boundaries"),
    ]

    operations = [
        migrations.RunPython(relink, unlink),
    ]
