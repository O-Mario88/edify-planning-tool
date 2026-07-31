"""Current UBOS sub-county identity registry.

Boundary polygons are presentation data. The rows in ``SubCounty`` are the
operational identities a school profile may select, so they are reconciled
from the coded NPHC registry without using point-in-polygon inference.

This importer is deliberately additive:

* existing sub-counties and school foreign keys are never renamed, moved, or
  deleted;
* an exact coded row wins, followed by one unambiguous normalized name in the
  already-known parent district;
* only genuinely missing coded identities are created;
* the three non-spatial refugee-camp reporting records are not presented as
  administrative boundaries.

City folding is shared with the offline boundary compiler. The legacy
135-boundary overview additionally draws Terego within Arua, but that
presentation fallback must not collapse Terego's operational identity.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SOURCE_NAME = "UBOS_NPHC_2024_LIVE"
REGISTRY_RELATIVE_PATH = Path(
    "data/geography/uganda_subcounty_registry_ubos_nphc2024_live.json"
)
REGION_NAME_BY_CODE = {
    "1": "Central",
    "2": "Eastern",
    "3": "Northern",
    "4": "Western",
}

DISTRICT_ALIASES = {
    "LUWERO": "LUWEERO",
}
CURRENT_CITY_PARENTS = {
    "ARUACITY": "ARUA",
    "FORTPORTALCITY": "KABAROLE",
    "GULUCITY": "GULU",
    "HOIMACITY": "HOIMA",
    "JINJACITY": "JINJA",
    "LIRACITY": "LIRA",
    "MASAKACITY": "MASAKA",
    "MBALECITY": "MBALE",
    "MBARARACITY": "MBARARA",
    "SOROTICITY": "SOROTI",
}
LEGACY_BOUNDARY_PARENTS = {
    "TEREGO": "ARUA",
}


def canonical(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (value or "").upper())


def district_canonical(value: str | None) -> str:
    key = canonical(value)
    key = CURRENT_CITY_PARENTS.get(key, key)
    return DISTRICT_ALIASES.get(key, key)


def boundary_district_canonical(value: str | None) -> str:
    """Canonical district key for the legacy 135-boundary overview only."""

    key = district_canonical(value)
    return LEGACY_BOUNDARY_PARENTS.get(key, key)


def default_registry_path() -> Path:
    from django.conf import settings

    return Path(settings.BASE_DIR) / REGISTRY_RELATIVE_PATH


def load_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or default_registry_path()
    payload = json.loads(registry_path.read_text())
    if payload.get("record_count") != len(payload.get("records", [])):
        raise ValueError("UBOS sub-county registry count does not match its records")
    return payload


def _display_name(record: dict[str, Any], duplicate_names: Counter) -> str:
    name = str(record["name"]).title()
    identity = (
        district_canonical(record["district_name"]),
        canonical(record["name"]),
    )
    if duplicate_names[identity] > 1:
        return f"{name} — {str(record['county_name']).title()}"
    return name


def ensure_ubos_districts(
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Add current UBOS districts beneath already-loaded parent regions."""

    from django.db import transaction

    from apps.core.geography import normalize_uganda_admin_name
    from apps.geography.models import District, Region

    stats = {
        "already_present": 0,
        "created": 0,
        "planned_create": 0,
        "missing_parent_region": 0,
    }
    regions = list(Region.objects.all())
    if not regions:
        return stats

    payload = load_registry(path)
    regions_by_key = {
        normalize_uganda_admin_name(region.name): region for region in regions
    }
    existing_keys = {
        district_canonical(name)
        for name in District.objects.values_list("name", flat=True)
    }
    official_districts: dict[str, dict[str, Any]] = {}
    for record in payload["records"]:
        if not record.get("has_geometry"):
            continue
        key = district_canonical(record["district_name"])
        official_districts.setdefault(key, record)

    pending = []
    for key, record in sorted(official_districts.items()):
        if key in existing_keys:
            stats["already_present"] += 1
            continue
        region_name = REGION_NAME_BY_CODE.get(str(record.get("region_code")))
        region = regions_by_key.get(
            normalize_uganda_admin_name(region_name) if region_name else ""
        )
        if region is None:
            stats["missing_parent_region"] += 1
            continue
        pending.append(
            District(
                name=str(record["district_name"]).title(),
                region=region,
                code=str(record["district_code"]),
                source=SOURCE_NAME,
            )
        )
        existing_keys.add(key)

    stats["planned_create"] = len(pending)
    if dry_run or not pending:
        return stats

    with transaction.atomic():
        before = District.objects.count()
        District.objects.bulk_create(
            pending,
            batch_size=200,
            ignore_conflicts=True,
        )
        stats["created"] = District.objects.count() - before
    return stats


def ensure_ubos_subcounties(
    *,
    path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Create missing official spatial identities without rewriting user data."""

    from django.db import transaction

    from apps.core.geography import normalize_uganda_admin_name
    from apps.geography.models import District, SubCounty

    districts = list(District.objects.only("id", "name"))
    stats = {
        "official_spatial_records": 0,
        "already_coded": 0,
        "matched_by_name": 0,
        "created": 0,
        "planned_create": 0,
        "missing_parent_district": 0,
        "ambiguous_existing_name": 0,
        "non_spatial_excluded": 0,
    }
    if not districts:
        return stats

    payload = load_registry(path)
    spatial_records = [
        record for record in payload["records"] if record.get("has_geometry")
    ]
    stats["official_spatial_records"] = len(spatial_records)
    stats["non_spatial_excluded"] = len(payload["records"]) - len(spatial_records)

    districts_by_key = {
        district_canonical(district.name): district for district in districts
    }
    existing_rows = list(SubCounty.objects.only("id", "district_id", "name", "pcode"))
    existing_codes = {str(row.pcode): row for row in existing_rows if row.pcode}
    existing_names: dict[tuple[str, str], list] = defaultdict(list)
    district_keys_by_id = {
        str(district.id): district_canonical(district.name) for district in districts
    }
    for row in existing_rows:
        existing_names[
            (
                district_keys_by_id.get(str(row.district_id), ""),
                normalize_uganda_admin_name(row.name),
            )
        ].append(row)

    duplicate_official_names = Counter(
        (
            district_canonical(record["district_name"]),
            canonical(record["name"]),
        )
        for record in spatial_records
    )
    pending = []
    for record in sorted(spatial_records, key=lambda item: str(item["code"])):
        code = str(record["code"])
        if code in existing_codes:
            stats["already_coded"] += 1
            continue

        district_key = district_canonical(record["district_name"])
        district = districts_by_key.get(district_key)
        if district is None:
            stats["missing_parent_district"] += 1
            continue

        official_name = _display_name(record, duplicate_official_names)
        name_key = (
            district_key,
            normalize_uganda_admin_name(official_name),
        )
        name_matches = existing_names.get(name_key, [])
        if len(name_matches) == 1:
            stats["matched_by_name"] += 1
            continue
        if len(name_matches) > 1:
            stats["ambiguous_existing_name"] += 1
            continue

        row = SubCounty(
            name=official_name,
            district=district,
            pcode=code,
            source=SOURCE_NAME,
            seeded=True,
        )
        pending.append(row)
        existing_names[name_key].append(row)
        existing_codes[code] = row

    stats["planned_create"] = len(pending)
    if dry_run or not pending:
        return stats

    with transaction.atomic():
        before = SubCounty.objects.count()
        SubCounty.objects.bulk_create(
            pending,
            batch_size=500,
            ignore_conflicts=True,
        )
        stats["created"] = SubCounty.objects.count() - before
    return stats


def ensure_geography_reference() -> dict[str, Any]:
    """One registered geography ensure function for all durable rows."""

    from apps.geography.subregions import sync

    districts = ensure_ubos_districts()
    return {
        "districts": districts,
        "subregions": sync(),
        "subcounties": ensure_ubos_subcounties(),
    }


__all__ = [
    "CURRENT_CITY_PARENTS",
    "DISTRICT_ALIASES",
    "LEGACY_BOUNDARY_PARENTS",
    "SOURCE_NAME",
    "boundary_district_canonical",
    "canonical",
    "district_canonical",
    "ensure_geography_reference",
    "ensure_ubos_districts",
    "ensure_ubos_subcounties",
    "load_registry",
]
