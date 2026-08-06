#!/usr/bin/env python3
"""Build lazy, district-sized sub-county boundary assets for the dashboard.

The current UBOS Map Explorer export is a display layer whose independently
generalised features overlap along shared borders. The dashboard must never
use those polygons to assign schools. For visual drill-down only, this compiler
clips each feature to the existing topology-safe district outline and removes
positive-area overlaps deterministically in UBOS-code order.

Run after installing ``requirements/dev.txt``:

    python scripts/build_uganda_subcounty_assets.py

The generated files are committed static assets. Production request handling
does not need Shapely and loads only the selected district's file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import shapely
from shapely.geometry import GeometryCollection, mapping, shape

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.geography.ubos_registry import (  # noqa: E402
    boundary_district_canonical,
    canonical,
)


DEFAULT_SOURCE = ROOT / "data/geography/uganda_subcounties_ubos_nphc2024_live.geojson"
DEFAULT_DISTRICTS = ROOT / "static/geo/uganda_districts.geojson"
DEFAULT_OUTPUT = ROOT / "static/geo/subcounties"
DEFAULT_INDEX = ROOT / "static/geo/uganda_subcounty_index.json"

ADMIN_TERMS = (
    "SUB COUNTY",
    "SUBCOUNTY",
    "TOWN COUNCIL",
    "MUNICIPALITY",
    "DIVISION",
    "CITY",
    "URBAN COUNCIL",
)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def polygonal(geometry):
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        parts = [
            part
            for part in geometry.geoms
            if part.geom_type in {"Polygon", "MultiPolygon"}
        ]
        return shapely.union_all(parts) if parts else GeometryCollection()
    return GeometryCollection()


def aliases(name: str, district: str) -> list[str]:
    """Conservative historical-name aliases used only for pin aggregation.

    Aliases never write geography back to the database. The browser accepts an
    alias only within the already selected district and combines all matching
    legacy labels, so no school can cross a district boundary through fuzzy
    matching.
    """

    upper = re.sub(r"\s+", " ", name.upper()).strip()
    values = {canonical(upper)}
    simplified = upper
    for term in ADMIN_TERMS:
        simplified = re.sub(rf"\b{re.escape(term)}\b", " ", simplified)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    if simplified:
        values.add(canonical(simplified))
    values.add(canonical(upper.replace("ISLANDS", "ISLAND")))

    district_key = canonical(district)
    for value in tuple(values):
        if value.startswith(district_key) and len(value) > len(district_key):
            values.add(value[len(district_key) :])

    # Compound council names frequently preserve both historical sub-county
    # names (for example NAKIFUMA-NAGGALAMA). Each segment is a useful alias
    # only inside the same selected district.
    stem = upper
    for term in ADMIN_TERMS:
        stem = re.sub(rf"\b{re.escape(term)}\b", " ", stem)
    for part in re.split(r"\s*[-/]\s*", stem):
        key = canonical(part)
        if key:
            values.add(key)

    # "Mukono" and "Central Division" are both legacy directory labels for
    # the current MUKONO CENTRAL DIVISION boundary. Retain the non-central
    # component as an alias without applying that rule to unrelated words.
    central_removed = canonical(re.sub(r"\bCENTRAL\b", " ", simplified))
    if central_removed:
        values.add(central_removed)

    return sorted(value for value in values if value)


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    )


def build(source: Path, district_source: Path, output: Path, index_path: Path) -> dict:
    source_payload = load_json(source)
    district_payload = load_json(district_source)

    source_by_district = defaultdict(list)
    for feature in source_payload["features"]:
        source_by_district[
            boundary_district_canonical(feature["properties"]["district_name"])
        ].append(feature)

    index = {
        "version": date.today().isoformat(),
        "source": "Uganda Bureau of Statistics NPHC 2024 Map Explorer",
        "source_url": "https://statistics.ubos.org/nphc/map",
        "usage": "visualization_only_school_assignment_uses_saved_geography",
        "districts": {},
    }
    audit = {
        "districts": 0,
        "features": 0,
        "source_features_clipped": 0,
        "overlap_area_removed_coordinate_units": 0.0,
        "districts_with_source_gap": 0,
        "missing_districts": [],
    }

    for district_feature in sorted(
        district_payload["features"], key=lambda feature: feature["properties"]["d"]
    ):
        district_name = district_feature["properties"]["d"]
        district_key = boundary_district_canonical(district_name)
        source_features = sorted(
            source_by_district.get(district_key, []),
            key=lambda feature: str(feature["properties"]["code"]),
        )
        if not source_features:
            audit["missing_districts"].append(district_name)
            continue

        district_geometry = polygonal(
            shapely.make_valid(shape(district_feature["geometry"]))
        )
        assigned = GeometryCollection()
        prepared = []
        removed = 0.0
        for feature in source_features:
            geometry = polygonal(
                shapely.make_valid(shape(feature["geometry"]))
            ).intersection(district_geometry)
            geometry = polygonal(geometry)
            if geometry.is_empty:
                continue
            non_overlapping = polygonal(geometry.difference(assigned))
            removed += max(0.0, geometry.area - non_overlapping.area)
            if non_overlapping.is_empty:
                continue
            if not non_overlapping.is_valid:
                raise RuntimeError(
                    f"Invalid compiled geometry for {district_name} / "
                    f"{feature['properties']['name']}"
                )
            assigned = shapely.union_all([assigned, non_overlapping])
            point = non_overlapping.representative_point()
            props = feature["properties"]
            prepared.append(
                {
                    "type": "Feature",
                    "properties": {
                        "n": props["name"].title(),
                        "c": str(props["code"]),
                        "d": props["district_name"].title(),
                        "od": district_name,
                        "dc": str(props["district_code"]),
                        "k": canonical(props["name"]),
                        "a": aliases(props["name"], district_name),
                        "lat": round(point.y, 6),
                        "lon": round(point.x, 6),
                    },
                    "geometry": mapping(non_overlapping),
                }
            )

        uncovered = polygonal(district_geometry.difference(assigned))
        gap_ratio = (
            uncovered.area / district_geometry.area if district_geometry.area else 0
        )
        if gap_ratio > 0.000001:
            audit["districts_with_source_gap"] += 1

        filename = f"{slug(district_name)}.geojson"
        write_json(
            output / filename,
            {
                "type": "FeatureCollection",
                "name": f"{district_name} sub-counties",
                "metadata": {
                    "source": index["source"],
                    "retrieved": source_payload.get("metadata", {}).get("retrieved"),
                    "display_only": True,
                    "clipped_to_dashboard_district": True,
                    "positive_area_overlaps_removed": True,
                    "source_gap_ratio": round(gap_ratio, 8),
                },
                "features": prepared,
            },
        )
        index["districts"][district_key] = {
            "name": district_name,
            "file": f"subcounties/{filename}",
            "features": len(prepared),
        }
        audit["districts"] += 1
        audit["features"] += len(prepared)
        audit["source_features_clipped"] += len(source_features)
        audit["overlap_area_removed_coordinate_units"] += removed

    if audit["missing_districts"]:
        raise RuntimeError(
            "No current UBOS sub-county source features for dashboard districts: "
            + ", ".join(audit["missing_districts"])
        )

    index["audit"] = {
        **audit,
        "overlap_area_removed_coordinate_units": round(
            audit["overlap_area_removed_coordinate_units"], 10
        ),
    }
    write_json(index_path, index)
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--districts", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()
    result = build(args.source, args.districts, args.output, args.index)
    print(json.dumps(result["audit"], indent=2))


if __name__ == "__main__":
    main()
