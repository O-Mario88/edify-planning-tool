# Edify — Official Uganda Geography Backbone (COD-AB Import) — 2026-06-17

Built the geography source of truth from the real **HDX/OCHA COD-AB** geodatabase.
Core rule honoured: **import only what exists in the boundary file; never
fabricate parishes or sub-regions.** Original uploaded school text is preserved;
uncertain matches go to a review queue, never silently accepted.

## A. Source

| | |
|---|---|
| Dataset | Uganda – Subnational Administrative Boundaries (COD-AB) |
| File | `uga_admin_boundaries.gdb.zip` (15.5 MB), Geodatabase |
| Source URL | https://data.humdata.org/dataset/6d6d1495-196b-49d0-86b9-dc9022cde8e7 |
| Resource id | ca93a625-4749-4bb0-a6c4-7eec58c2ca84 |
| Source last modified | 2026-01-26 |
| Download checksum (sha256) | `abe3fbeb5e65e29c…69593450` |
| Parser | pyogrio 0.11.1 / **GDAL 3.10.3** (in a venv; no system GDAL needed) |
| CRS | EPSG:4326 |

## B. Layers Inspected (no assumptions)

The actual layers + feature counts + fields were inspected before importing:

| Layer | Admin level | Meaning | Features | pcode field | Example |
|---|---|---|---:|---|---|
| uga_admin0 | 0 | Country | 1 | adm0_pcode | UG (Uganda) |
| uga_admin1 | 1 | **Region** | 4 | adm1_pcode | UG3 (Northern) |
| uga_admin2 | 2 | **District** | 135 | adm2_pcode | UG3083 (Lira) |
| uga_admin3 | 3 | **County** | 208 | adm3_pcode | UG306601 |
| uga_admin4 | 4 | **Sub-county** | 1520 | adm4_pcode | UG30830101 |

Each level carries `admN_name`, `admN_ref_name`, `admN_pcode`, the parent pcode,
`center_lat`/`center_lon`, and `area_sqkm`.

## C. Critical Findings

- **NO PARISHES in COD-AB.** ADM4 is the **sub-county** level (1520 features,
  matching Uganda's sub-county count) — not parish. The Parish table is created
  but **left empty** (`confidence = NOT_IN_BOUNDARY_SOURCE`); uploaded parish text
  is preserved on the school for a future verified parish source. No parish was
  invented.
- **NO SUB-REGIONS in COD-AB.** ADM1 is the **4 macro-regions**, not the ~15
  sub-regions (Lango, Acholi, …). Sub-regions are a **controlled mapping layer**
  (`SubRegion`, source=CONTROLLED) with confidence + audit, never confused with
  the boundary source.
- **County dedupe:** 208 county features → **203 unique counties**. The 5 dropped
  are **duplicate-pcode source rows** (e.g. Ibanda/Ibanda appears 3× with the same
  pcode UG410701) — correctly collapsed, not data loss.

## D. Imported (verified in Postgres)

| Level | Records | Notes |
|---|---:|---|
| Region | 4 | pcode + centroid + source=COD-AB |
| District | 135 | all with COD-AB pcode; existing 16 seeded districts upserted (kept ids, gained pcodes) |
| County | 203 | new level (COD-AB admin3), 5 dup rows deduped |
| Sub-county | 1546 | 1520 official (COD-AB) + 26 pre-existing seed fixtures |
| Parish | 210 | pre-existing **seed fixtures only** — none from COD-AB |
| Sub-region | 1 | **Lango** (CONTROLLED, **VERIFIED**) |

**Lango sub-region:** all 8 required districts verified present in COD-AB and
linked — Lira, Apac, Oyam, Dokolo, Kole, Alebtong, Otuke, Kwania (all Northern).
Other sub-regions are **not invented** (would be REVIEW_REQUIRED).

`BoundaryImportRun` audit row recorded (source, url, last-modified, checksum,
level counts, status=SUCCESS, warnings). **700 schools untouched** (additive).

## E. School Auto-Mapping (geo:map-schools)

The deterministic matcher (`normalizeUgandaAdminName` → EXACT / ALIAS / FUZZY_HIGH
/ FUZZY_LOW_REVIEW_REQUIRED / UNMATCHED) ran over all 700 schools, preserving the
original uploaded text:

| Result | Schools |
|---|---:|
| EXACT (district + sub-county) | 450 |
| FUZZY_LOW_REVIEW_REQUIRED → **review queue** | 250 |

All 700 districts matched EXACT; the 250 in review are schools whose **seeded**
sub-county fixture names don't exactly match an official COD-AB sub-county within
the district — correctly **flagged for review rather than silently accepted**
(the core safety promise). Once real school uploads carry official sub-county
names, these resolve EXACT.

## F. Commands

- `npm run geo:import` — load official records + Lango + BoundaryImportRun (idempotent, non-destructive).
- `npm run geo:map-schools` — resolve schools to official ids, preserve uploaded text, route low-confidence to review.
- `npm run geo:verify` — structural validation; **all checks pass, exit 0**.
- `geo-data/extract-codab.py` — re-parse the .gdb → geography.json (re-download from the HDX URL; binaries are gitignored).

## G. Tests

`src/common/geography/normalize.spec.ts` (13): normalization (suffix stripping,
sub-county spellings, apostrophes, "Moyo" ≠ "Moyo Town Council"), and the matcher
(EXACT/ALIAS, low-confidence → review, "Lusaka" → UNMATCHED no silent guess).
api suite **149 green**.

## H. Remaining (honest scope)

The backbone (data + schema + import + matcher + audit + review-status) is **done
and verified**. Still to wire (documented next phase, large): the **frontend
GeographyFilter cascade** (Region→SubRegion→District→Sub-county) + the
`/data-quality/geography` **review-queue UI**, repointing the school-upload
endpoint to call the matcher at ingest, and migrating cluster/partner/cost
coverage to official ids. The current filter dropdowns already source live
districts (those 16 now carry official pcodes); the 119 school-less official
districts correctly don't appear until schools are uploaded there.

**Verdict:** the official COD-AB geography is the live source of truth — real
data, faithfully imported, parishes/sub-regions never faked, schools mapped
safely with a review queue for anything uncertain.
