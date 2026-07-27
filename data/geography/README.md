# Uganda sub-county boundaries

This directory deliberately separates **current administrative identity** from
**production-safe topology**. The current UBOS NPHC platform has more than
2,000 sub-county-level records, while the older 2020 COD layer is the only
public nationwide source found here whose shared borders form a clean polygon
coverage.

## Current UBOS NPHC 2024/live source

The following files were retrieved from the official
[UBOS NPHC 2024 Map Explorer](https://statistics.ubos.org/nphc/map) and its
public hierarchy and geospatial APIs on 2026-07-26:

- `uganda_subcounty_registry_ubos_nphc2024_live.json`: 2,208 unique coded
  records and their parent relationships.
- `uganda_subcounties_ubos_nphc2024_live.geojson`: 2,205 unique territorial
  polygon features.
- `uganda_districts_ubos_nphc2024_live.geojson`: 146 unique district/city
  polygon features.
- `uganda_nphc2024_boundary_audit.json`: provenance, checksums, repairs,
  duplicate-code handling, missing geometry classification, and topology
  measurements.

The other three live hierarchy records are Bidi Bidi refugee-camp statistical
reporting entries under three Yumbe counties. UBOS does not publish a separate
polygon for those records. They remain in the registry with
`has_geometry: false`; no boundary was fabricated for them.

The official counts describe different reference dates:

- The NPHC 2024 census report records 2,191
  Sub-county/Division/Town Council units at census time.
- The current [UBOS Uganda profile](https://www.ubos.org/uganda-profile/)
  reports 2,197 sub-counties.
- The live NPHC hierarchy APIs returned 2,208 coded records during this
  retrieval, including the three non-spatial refugee-camp reporting entries.

Do not treat those three values as interchangeable.

### Current-layer quality decision

Six malformed polygon components were structure-repaired and the two map rows
for Rubaga Division were merged into one multipart feature. Every resulting
feature is individually valid.

The layer is **not approved for production spatial assignment yet**. The public
Map Explorer polygons are independently generalised display geometry, not a
topological coverage:

- 6,222 adjacent sub-county pairs have positive-area overlap.
- The aggregate overlap overcount is 250.569 km².
- All 2,205 features have at least one inconsistent shared edge.

The live registry codes and hierarchy can be used to reconcile the application
directory. Keep the live geometry as a staging/reference layer until UBOS
provides a topology-grade current shapefile or a documented border-conflict
resolution is approved. School-to-sub-county assignment should use stored UBOS
codes rather than point-in-polygon inference against this display layer.

UBOS's statistical metadata says its administrative Geo Maps are available in
soft copy on request from UBOS servers/archives and also records administrative
boundary conflicts as a known limitation. The official data-request contact is
`ubos@ubos.org` ([UBOS contact page](https://www.ubos.org/contact-us/)).

## Topology-safe 2020 reference

`uganda_subcounties_2020.geojson` is the topology-checked extraction of the
Uganda admin-level 4 polygon layer from the Uganda Common Operational Dataset.
It is a historical topology reference, not the current administrative
registry.

### Provenance

- Dataset: Uganda - Subnational Administrative Boundaries
- Source: Uganda Bureau of Statistics (UBOS), with support from WHO
- Contributor: OCHA Regional Office for Southern and Eastern Africa
- Publisher: Humanitarian Data Exchange (HDX)
- Catalogue: https://data.humdata.org/dataset/cod-ab-uga
- GeoJSON resource: https://data.humdata.org/dataset/6d6d1495-196b-49d0-86b9-dc9022cde8e7/resource/8080f36a-a86b-475c-a960-9a63900ae8ad/download/uga_admin_boundaries.geojson.zip
- Resource last modified: 2026-01-26
- Boundary validity date: 2020-08-24; all records have no `valid_to` date
- Licence: Creative Commons Attribution for Intergovernmental Organisations
  (CC BY-IGO)
- Retrieved: 2026-07-26

Attribution for any map that uses the file should read:
`Source: Uganda Bureau of Statistics (UBOS), WHO and OCHA/HDX.`

### Extraction

The file was extracted from `uga_admin4.geojson` in the official GeoJSON
archive. It retains the full-precision polygon geometry, administrative names
and stable P-codes, district/county/region parents, centre coordinates, area,
and validity dates. The JSON was minified, but the source geometry was not
rounded or simplified.

- Features: 1,520
- Districts represented: 135
- Unique sub-county P-codes: 1,520
- Geometry: Polygon and MultiPolygon, CRS84/WGS84
- Prepared file SHA-256:
  `479e349ef1e7d056ccf2eebb1755f273f055e7ff4f84732df4bbda763c570a05`

The source contained one self-intersecting ring in Nyimbwa
(`UG10140207`). It was repaired with a structure-preserving geometry repair;
the resulting area change is below `0.000001 m²`. Validation after repair found
no invalid geometry, missing geometry, overlapping polygon area, invalid shared
edges, or duplicate P-codes.

`uganda_subcounties_merged_outline.geojson` is the dissolved national outline
made from all 1,520 repaired sub-counties. It exists as an independent
whole-coverage check; the master file retains all internal sub-county
boundaries.

`uganda_subcounty_topology_audit.json` records the machine-readable validation
results and file checksums.

### Directory reconciliation

All 1,520 source `(district, sub-county)` pairs match the current application
directory exactly after case and punctuation normalisation.

The directory has 171 additional records. Every one is an admin-level 3 county
that was also inserted into the `SubCounty` table. The existing
`scripts/scrape_uganda_admin.py` combines admin-level 3 counties with
admin-level 4 sub-counties; this should be corrected before P-codes are written
back to the database.

The 41 MB full-country master is a source artifact. Before using it in the
dashboard, generate district-specific browser assets with a topology-preserving
process and lazy-load only the selected district. Do not round each polygon's
vertices independently: doing so introduced invalid rings and microscopic
overlaps during the extraction audit.
