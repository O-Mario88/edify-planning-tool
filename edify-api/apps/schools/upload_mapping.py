"""
Canonical upload header mapping (schools + SSA).

This is the SINGLE source of truth for normalizing free-text spreadsheet
headers into model fields. Both the school-upload and SSA-upload endpoints map
their incoming columns through here, so the same header variations are accepted
everywhere and there is exactly one place to extend when a new variation shows up.

Normalization rules (applied to every header before lookup):
  - strip a leading UTF-8 BOM
  - lowercase
  - replace "&" with "and"
  - collapse any run of whitespace / underscores / hyphens into a single space
  - strip leading/trailing whitespace
"""
from __future__ import annotations

import re

from apps.core.enums import SchoolType, SsaIntervention


def normalize_header(raw: str) -> str:
    """Normalize a single header cell to its canonical comparison form."""
    if raw is None:
        return ""
    h = str(raw).replace("\ufeff", "")
    h = h.strip().lower()
    h = h.replace("&", " and ")
    h = re.sub(r"[\s_\-]+", " ", h)
    return h.strip()


# ── School upload header → School model field ────────────────────────────────
# Keys are NORMALIZED header forms (run through normalize_header). Values are the
# canonical field names used by the upload service.
SCHOOL_HEADER_MAP: dict[str, str] = {
    # School ID
    "school id": "school_id",
    "schoolid": "school_id",
    # School Name
    "school name": "name",
    "name": "name",
    # District
    "district": "district",
    # Current Partner Type → school_type
    "current partner type": "school_type",
    "partner type": "school_type",
    "school type": "school_type",
    # Account Owner / Staff Name (preferred column is "Staff Name"; "Account
    # Owner" kept for backward compatibility). When both exist, Staff Name wins
    # because build_field_index records the first mapped column for a field.
    "staff name": "account_owner_name_raw",
    "staff": "account_owner_name_raw",
    "ccoe": "account_owner_name_raw",
    "pl": "account_owner_name_raw",
    "staff_name": "account_owner_name_raw",
    "account owner": "account_owner_name_raw",
    "account_owner": "account_owner_name_raw",
    # Enrolment
    "enrolment": "enrollment",
    "enrollment": "enrollment",
    # Last Date of Enrolment
    "last date of enrolment": "last_enrollment_date",
    "last date of enrollment": "last_enrollment_date",
    "last enrolment date": "last_enrollment_date",
    "last enrollment date": "last_enrollment_date",
    # Phone
    "phone": "school_phone",
    "school phone": "school_phone",
    # Primary Contact
    "primary contact": "primary_contact_name",
    "primary contact name": "primary_contact_name",
    # School Shipping Address
    "school shipping address": "shipping_address",
    "shipping address": "shipping_address",
    "address": "shipping_address",
}

SCHOOL_REQUIRED_FIELDS = ("school_id", "name", "district")

# Human-friendly expected headers (for error messages). "Staff Name" is the
# preferred owner column; "Account Owner" remains accepted as a fallback.
SCHOOL_EXPECTED_HEADERS = [
    "Staff Name",
    "School ID",
    "School Name",
    "District",
    "Current Partner Type",
    "Enrolment",
    "Last Date of Enrolment",
    "Phone",
    "Primary Contact",
    "School Shipping Address",
]


# Current Partner Type label → SchoolType enum value. Normalized for matching.
SCHOOL_TYPE_MAP: dict[str, str] = {
    "client": SchoolType.CLIENT.value,
    "core": SchoolType.CORE.value,
    "potential core": SchoolType.POTENTIAL_CORE.value,
    "champion": SchoolType.CHAMPION.value,
    "potential champion": SchoolType.POTENTIAL_CHAMPION.value,
    "other": SchoolType.OTHER.value,
}


def map_school_type(raw: str) -> tuple[str, bool]:
    """Map a Current Partner Type cell → (school_type, recognized).

    Unknown / blank values default to `client` with recognized=False so the
    caller can record a warning (type is not a required field)."""
    key = normalize_header(raw)
    if not key:
        return SchoolType.CLIENT.value, False
    if key in SCHOOL_TYPE_MAP:
        return SCHOOL_TYPE_MAP[key], True
    return SchoolType.CLIENT.value, False


# ── SSA upload header → SsaIntervention enum value (or meta field) ───────────
SSA_HEADER_MAP: dict[str, str] = {
    # Identity
    "school id": "school_id",
    "schoolid": "school_id",
    # Date
    "assessment date": "date_of_ssa",
    "ssa date": "date_of_ssa",
    "date of ssa": "date_of_ssa",
    "assessment ssa date": "date_of_ssa",
    "date": "date_of_ssa",
    # Optional enrolment
    "enrolment": "new_enrollment",
    "enrollment": "new_enrollment",
    "new enrolment": "new_enrollment",
    "new enrollment": "new_enrollment",
    # 8 interventions
    "teaching and learning": SsaIntervention.TEACHING_AND_LEARNING.value,
    "financial health": SsaIntervention.FINANCIAL_HEALTH.value,
    "christlike behaviour": SsaIntervention.CHRISTLIKE_BEHAVIOUR.value,
    "christlike behavior": SsaIntervention.CHRISTLIKE_BEHAVIOUR.value,
    "exposure to the word of god": SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value,
    "exposure to word of god": SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value,
    "government requirements and compliance": SsaIntervention.GOVERNMENT_REQUIREMENTS.value,
    "government requirements compliance": SsaIntervention.GOVERNMENT_REQUIREMENTS.value,
    "government requirements": SsaIntervention.GOVERNMENT_REQUIREMENTS.value,
    "leadership": SsaIntervention.LEADERSHIP.value,
    "education technology": SsaIntervention.EDUCATION_TECHNOLOGY.value,
    "learning environment": SsaIntervention.LEARNING_ENVIRONMENT.value,
}

ALL_INTERVENTIONS = [i.value for i in SsaIntervention]
SSA_REQUIRED_FIELDS = ("school_id", "date_of_ssa")

SSA_EXPECTED_HEADERS = [
    "School ID",
    "Assessment Date",
    "Teaching & Learning",
    "Financial Health",
    "Christlike Behaviour",
    "Exposure to the Word of God",
    "Government Requirements & Compliance",
    "Leadership",
    "Education Technology",
    "Learning Environment",
]


def build_field_index(raw_headers: list[str], header_map: dict[str, str]) -> dict[str, int]:
    """Map canonical field → column index using a header map. First match wins."""
    index: dict[str, int] = {}
    for col, raw in enumerate(raw_headers):
        field = header_map.get(normalize_header(raw))
        if field and field not in index:
            index[field] = col
    return index


def missing_required(field_index: dict[str, int], required: tuple[str, ...]) -> list[str]:
    return [f for f in required if f not in field_index]


__all__ = [
    "normalize_header",
    "SCHOOL_HEADER_MAP",
    "SCHOOL_REQUIRED_FIELDS",
    "SCHOOL_EXPECTED_HEADERS",
    "SCHOOL_TYPE_MAP",
    "map_school_type",
    "SSA_HEADER_MAP",
    "SSA_REQUIRED_FIELDS",
    "SSA_EXPECTED_HEADERS",
    "ALL_INTERVENTIONS",
    "build_field_index",
    "missing_required",
]
