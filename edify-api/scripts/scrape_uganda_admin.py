#!/usr/bin/env python3
"""
scrape_uganda_admin.py
======================
Downloads the official Uganda COD-AB dataset from UN HDX, extracts
Region / District / Sub-County at admin levels 1-3 (and admin4 for
additional sub-county coverage), cleans the data with pandas, saves
the canonical CSV, then seeds the Edify geography database.

Source: OCHA / Uganda Bureau of Statistics
URL:    https://data.humdata.org/dataset/cod-ab-uga
File:   uga_admin_boundaries.xlsx (XLSX, ~380 KB)
"""

import io
import sys
import urllib.request
import ssl
import os
import django
import pandas as pd
from pathlib import Path

# ── Django setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
DJANGO_ROOT = SCRIPT_DIR.parent  # edify-api/
sys.path.insert(0, str(DJANGO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
# Load .env so DB credentials are available
env_file = DJANGO_ROOT.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
django.setup()

from django.db import transaction
from apps.geography.models import Region, District, SubCounty, GeographyAlias

# ── Download ──────────────────────────────────────────────────────────────────
XLSX_URL = (
    "https://data.humdata.org/dataset/"
    "6d6d1495-196b-49d0-86b9-dc9022cde8e7/resource/"
    "e8f918a3-c16f-4a9f-a688-0760adcb2003/download/uga_admin_boundaries.xlsx"
)

OUTPUT_CSV = DJANGO_ROOT.parent / "uganda_complete_administrative_mapping.csv"


def download_xlsx(url: str) -> bytes:
    print(f"Downloading: {url}")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        data = r.read()
    print(f"  Downloaded {len(data):,} bytes")
    return data


def build_combined_df(xlsx_bytes: bytes) -> pd.DataFrame:
    """
    Reads uga_admin2, uga_admin3 and uga_admin4 sheets.
    - admin3 rows → sub-counties (adm3_name)
    - admin4 rows → parishes used as additional sub-counties (adm4_name)
    Deduplicates and returns a clean DataFrame.
    """
    xf = pd.ExcelFile(io.BytesIO(xlsx_bytes))

    # ── Admin2 — districts ───────────────────────────────────────────────────
    admin2 = xf.parse("uga_admin2", usecols=["adm1_name", "adm2_name"])
    admin2 = admin2.rename(columns={"adm1_name": "Region", "adm2_name": "District"})
    admin2 = admin2.dropna(subset=["Region", "District"])
    admin2["Region"] = admin2["Region"].str.strip()
    admin2["District"] = admin2["District"].str.strip()

    # ── Admin3 — sub-counties (adm3_name) ───────────────────────────────────
    admin3 = xf.parse("uga_admin3", usecols=["adm1_name", "adm2_name", "adm3_name"])
    admin3 = admin3.rename(
        columns={"adm1_name": "Region", "adm2_name": "District", "adm3_name": "Sub_County"}
    )
    admin3 = admin3.dropna(subset=["Region", "District", "Sub_County"])
    admin3[["Region", "District", "Sub_County"]] = admin3[["Region", "District", "Sub_County"]].apply(
        lambda c: c.str.strip()
    )

    # ── Admin4 — parishes → also used as sub-counties for full coverage ──────
    # adm3_name = sub-county parent (already in admin3)
    # adm4_name = parish = the granular unit Uganda calls "sub-county" in common use
    admin4_sc = xf.parse("uga_admin4", usecols=["adm1_name", "adm2_name", "adm3_name"])
    admin4_sc = admin4_sc.rename(
        columns={"adm1_name": "Region", "adm2_name": "District", "adm3_name": "Sub_County"}
    )
    admin4_sc = admin4_sc.dropna(subset=["Region", "District", "Sub_County"])
    admin4_sc[["Region", "District", "Sub_County"]] = admin4_sc[["Region", "District", "Sub_County"]].apply(
        lambda c: c.str.strip()
    )
    admin4_sc = admin4_sc.drop_duplicates()

    # Also pull the actual admin4 names (parishes) as sub-county entries
    admin4_parish = xf.parse("uga_admin4", usecols=["adm1_name", "adm2_name", "adm4_name"])
    admin4_parish = admin4_parish.rename(
        columns={"adm1_name": "Region", "adm2_name": "District", "adm4_name": "Sub_County"}
    )
    admin4_parish = admin4_parish.dropna(subset=["Region", "District", "Sub_County"])
    admin4_parish[["Region", "District", "Sub_County"]] = admin4_parish[["Region", "District", "Sub_County"]].apply(
        lambda c: c.str.strip()
    )
    admin4_parish = admin4_parish.drop_duplicates()

    # Region normalisation
    REGION_MAP = {
        "Central": "Central Region",
        "Eastern": "Eastern Region",
        "Northern": "Northern Region",
        "Western": "Western Region",
    }

    def normalize_region(name: str) -> str:
        for k, v in REGION_MAP.items():
            if name.strip().lower() in (k.lower(), v.lower()):
                return v
        return name.strip()

    for df in (admin2, admin3, admin4_sc, admin4_parish):
        df["Region"] = df["Region"].apply(normalize_region)

    # Union all sub-county sources
    combined = pd.concat([admin3, admin4_sc, admin4_parish], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Region", "District", "Sub_County"])
    combined = combined.sort_values(["Region", "District", "Sub_County"]).reset_index(drop=True)

    return combined, admin2


def save_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)
    print(f"  Saved CSV: {path} ({len(df):,} rows)")


def seed_db(admin2: pd.DataFrame, combined: pd.DataFrame) -> dict:
    regions = {r.name: r for r in Region.objects.all()}
    stats = {
        "district_created": 0, "district_updated": 0,
        "subcounty_created": 0, "subcounty_skipped": 0,
        "alias_created": 0, "region_missing": [],
    }

    with transaction.atomic():
        # ── Seed districts ───────────────────────────────────────────────────
        district_cache: dict[tuple, District] = {}
        for _, row in admin2.iterrows():
            rname = row["Region"]
            dname = row["District"]
            region = regions.get(rname)
            if not region:
                if rname not in stats["region_missing"]:
                    stats["region_missing"].append(rname)
                continue

            district, created = District.objects.get_or_create(
                name=dname, region=region
            )
            if created:
                stats["district_created"] += 1
            district_cache[(rname, dname)] = district

            # Alias: lower-cased name for tolerant matching
            norm = dname.lower().strip()
            _, a_created = GeographyAlias.objects.get_or_create(
                admin_level="district",
                normalized_alias=norm,
                defaults={"admin_id": district.id, "alias": dname, "source": "HDX-COD-AB", "confidence": "HIGH"},
            )
            if a_created:
                stats["alias_created"] += 1

        # ── Seed sub-counties ────────────────────────────────────────────────
        for _, row in combined.iterrows():
            rname = row["Region"]
            dname = row["District"]
            scname = row["Sub_County"]

            district = district_cache.get((rname, dname))
            if not district:
                region = regions.get(rname)
                if not region:
                    continue
                district, _ = District.objects.get_or_create(name=dname, region=region)
                district_cache[(rname, dname)] = district

            _, sc_created = SubCounty.objects.get_or_create(
                name=scname, district=district,
                defaults={"seeded": True}
            )
            if sc_created:
                stats["subcounty_created"] += 1
            else:
                stats["subcounty_skipped"] += 1

    return stats


def validate(df: pd.DataFrame) -> None:
    districts = df["District"].nunique()
    sub_counties = df["Sub_County"].nunique()
    print(f"\n{'─'*50}")
    print(f"  Distinct Regions    : {df['Region'].nunique()}")
    print(f"  Distinct Districts  : {districts}")
    print(f"  Distinct Sub-Counties: {sub_counties}")
    print(f"  Total rows          : {len(df):,}")
    if districts < 100:
        print(f"  ⚠ WARNING: Only {districts} districts found (expected ≥ 100)")
    if sub_counties < 500:
        print(f"  ⚠ WARNING: Only {sub_counties} sub-counties found (expected ≥ 500)")
    print(f"{'─'*50}\n")


def main():
    xlsx_bytes = download_xlsx(XLSX_URL)
    combined, admin2 = build_combined_df(xlsx_bytes)

    validate(combined)
    save_csv(combined, OUTPUT_CSV)

    print("Seeding database …")
    stats = seed_db(admin2, combined)

    print(f"\n✅ Districts  created : {stats['district_created']}")
    print(f"✅ SubCounties created: {stats['subcounty_created']}")
    print(f"✅ SubCounties exist  : {stats['subcounty_skipped']}")
    print(f"✅ Aliases    created : {stats['alias_created']}")
    if stats["region_missing"]:
        print(f"⚠  Regions not found : {stats['region_missing']}")

    print(f"\n── Final DB counts ──────────────────────────────────")
    print(f"  Regions    : {Region.objects.count()}")
    print(f"  Districts  : {District.objects.count()}")
    print(f"  SubCounties: {SubCounty.objects.count()}")
    print(f"  Aliases    : {GeographyAlias.objects.filter(admin_level='district').count()}")
    print(f"\nOutput CSV : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
