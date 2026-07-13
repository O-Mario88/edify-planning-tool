"""School location intelligence — structured-first, coordinates-strongest,
text parsing only as fallback.

SchoolLocationParserService — resolves each school's best location source in
strict priority order and extracts meaningful location *phrases* (never bare
most-common words: generic tokens like "school", "central", "trading centre",
"division" are stripped before anything is compared across schools).

SchoolCoordinateService — haversine distance, nearest-neighbour visit
sequencing and travel-time estimation from whatever coordinates genuinely
exist (SchoolGeoPoint override → School.latitude/longitude → SubCounty
centroid → District centroid). No coordinates are ever invented.
"""

from __future__ import annotations

import math
import re

from apps.routes.models import (
    LocationConfidence,
    LocationSource,
    SchoolGeoPoint,
    SchoolLocationConfidence,
)

# Words that appear constantly in school names/addresses but prove nothing
# about location. Never use these to group schools.
GENERIC_WORDS = {
    "school", "schools", "primary", "junior", "senior", "secondary", "nursery",
    "academy", "college", "education", "centre", "center", "central", "trading",
    "division", "road", "street", "village", "parish", "sub-county", "subcounty",
    "county", "district", "town", "council", "city", "ward", "zone", "area",
    "p/s", "p.s", "ps", "s.s", "ss", "uganda", "the", "and", "of", "st", "saint",
}

AVG_SPEED_KMH = 30  # rural murram-road planning speed


def _clean_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,;/\-]+", (text or "").strip()) if t]


def extract_location_phrases(text: str, district_name: str | None = None) -> list[str]:
    """Extract meaningful location phrases from free address text.

    Rules from the route mandate: look after the district name, keep multi-word
    place phrases together (comma-separated segments), drop generic words, and
    never return a bare generic token. "Mukono, Goma Division, Nakifuma Hill"
    → ["Goma", "Nakifuma Hill"].
    """
    if not text:
        return []
    segments = [s.strip() for s in re.split(r"[,;/]", text) if s.strip()]
    district_l = (district_name or "").strip().lower()
    phrases: list[str] = []
    for seg in segments:
        if district_l and seg.lower() == district_l:
            continue  # the district itself is not a local grouping
        kept = [t for t in _clean_tokens(seg) if t.lower() not in GENERIC_WORDS]
        if not kept:
            continue
        phrase = " ".join(kept)
        if phrase.lower() != district_l and phrase not in phrases:
            phrases.append(phrase)
    return phrases


class SchoolCoordinateService:
    """Real-distance math over whatever coordinates genuinely exist."""

    @staticmethod
    def coords_for(school) -> tuple[float, float, str] | None:
        """Best available (lat, lng, source) for a school, in priority order:
        verified SchoolGeoPoint → school upload lat/lng → sub-county centroid
        → district centroid. Returns None when nothing real exists."""
        gp = SchoolGeoPoint.objects.filter(school_id=school.id).first()
        if gp:
            return (gp.latitude, gp.longitude, "geo_point")
        if school.latitude is not None and school.longitude is not None:
            return (school.latitude, school.longitude, "school")
        sc = getattr(school, "sub_county", None) if school.sub_county_id else None
        if sc and sc.latitude is not None and sc.longitude is not None:
            return (sc.latitude, sc.longitude, "sub_county_centroid")
        d = getattr(school, "district", None) if school.district_id else None
        if d and d.latitude is not None and d.longitude is not None:
            return (d.latitude, d.longitude, "district_centroid")
        return None

    @staticmethod
    def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
        lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * 6371.0 * math.asin(math.sqrt(h))

    @staticmethod
    def best_sequence(points: dict[str, tuple[float, float]]) -> tuple[list[str], float]:
        """Nearest-neighbour ordering over {school_id: (lat, lng)} → (ordered
        ids, total leg distance km). Good enough for ≤ CD-target-sized days."""
        remaining = dict(points)
        if not remaining:
            return [], 0.0
        # Start from the school closest to the centroid edge (western-most is a
        # stable, deterministic pick; the day is a loop so the start matters little).
        current = min(remaining, key=lambda k: remaining[k][1])
        order = [current]
        total = 0.0
        pos = remaining.pop(current)
        while remaining:
            nxt = min(
                remaining,
                key=lambda k: SchoolCoordinateService.haversine_km(pos, remaining[k]),
            )
            total += SchoolCoordinateService.haversine_km(pos, remaining[nxt])
            pos = remaining.pop(nxt)
            order.append(nxt)
        return order, round(total, 1)

    @staticmethod
    def travel_minutes_for_km(km: float) -> int:
        return round(km / AVG_SPEED_KMH * 60)


class SchoolLocationParserService:
    """Resolve one school's location in strict source-priority order and cache
    the result (+ confidence) on SchoolLocationConfidence."""

    @staticmethod
    def resolve(school) -> dict:
        district_name = school.district.name if school.district_id else None
        coords = SchoolCoordinateService.coords_for(school)

        # 1. Coordinates — strongest (only own coords count as HIGH; a
        #    sub-county/district centroid is structured data, not a real point).
        if coords and coords[2] in ("geo_point", "school"):
            source, confidence = LocationSource.COORDINATES, LocationConfidence.HIGH
            tokens = [school.sub_county.name] if school.sub_county_id else []
            area = tokens[0] if tokens else district_name
        # 2. District + Sub-county (structured upload fields).
        elif school.district_id and school.sub_county_id:
            source, confidence = LocationSource.DISTRICT_SUBCOUNTY, LocationConfidence.HIGH
            tokens = [school.sub_county.name]
            area = school.sub_county.name
        # 3. District + Parish.
        elif school.district_id and school.parish_id:
            source, confidence = LocationSource.DISTRICT_PARISH, LocationConfidence.MEDIUM
            tokens = [school.parish.name]
            area = school.parish.name
        # 4. Shipping-address / uploaded text parsing (careful, phrase-based).
        else:
            text = school.shipping_address or school.uploaded_sub_county_text or school.uploaded_parish_text
            phrases = extract_location_phrases(text or "", district_name)
            if phrases:
                source, confidence = LocationSource.ADDRESS_TEXT, LocationConfidence.LOW
                tokens, area = phrases, phrases[0]
            else:
                # 5. Manual review — flag, never reject the school.
                source, confidence = LocationSource.NONE, LocationConfidence.NEEDS_CLEANUP
                tokens, area = [], None

        SchoolLocationConfidence.objects.update_or_create(
            school_id=school.id,
            defaults={
                "source_used": source, "confidence": confidence,
                "tokens": tokens, "area_label": area,
            },
        )
        return {
            "school_id": school.id, "source": source, "confidence": confidence,
            "tokens": tokens, "area_label": area, "coords": coords,
        }


__all__ = [
    "GENERIC_WORDS",
    "AVG_SPEED_KMH",
    "extract_location_phrases",
    "SchoolCoordinateService",
    "SchoolLocationParserService",
]
