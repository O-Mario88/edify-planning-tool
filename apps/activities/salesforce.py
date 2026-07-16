"""
Activity Salesforce ID: format validation, normalization, and the atomic
duplicate-prevention reservation service (2026-07-15 preventive-verification
mandate — this is proof a completed field activity, visit or training, was
entered into Salesforce; never to be confused with the platform School ID
used for SSA CSV matching, a School's own Salesforce ID, or the NetSuite
Expense ID used for financial accountability).

Canonical prefixes (2026-07-15 clarification, supersedes the earlier
SV-/SVE- dual-acceptance design): Training activities require TS-; School
Visit activities require SVE-. Historical data entered under the older bare
SV- prefix remains valid for READS (never silently rewritten) but is no
longer accepted for a NEW entry — see is_valid_new_entry().

Uniqueness scope: the platform integrates with a single Salesforce
organization (no multi-org/country partition exists anywhere in the
codebase today), so normalized_value is globally unique — enforced by a
database constraint on ActivitySalesforceReference, not merely application
logic, so a concurrent double-submit can never create two reservations.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, NotFoundError

if TYPE_CHECKING:
    from .models import ActivitySalesforceReference

_TS_RE = re.compile(r"^TS-[A-Z0-9-]{3,}$")
_SVE_RE = re.compile(r"^SVE-[A-Z0-9-]{3,}$")
# Legacy visits stored before the SVE- clarification may carry the older
# bare SV- prefix — accepted for reads of historical data only.
_LEGACY_SV_RE = re.compile(r"^SV-[A-Z0-9-]{3,}$")

# Roles allowed to enter an Activity Salesforce ID as themselves (staff
# self-entry) or on behalf of a partner they manage (managing-staff entry).
# Partners are deliberately excluded — they submit evidence, but the final
# Salesforce entry belongs to the staff member who verifies it.
ENTRY_AUTHORIZED_ROLES = ("CCEO", "Program Lead", "ImpactAssessment", "Admin")

ENTRY_SOURCE_STAFF_SELF = "staff_self_entry"
ENTRY_SOURCE_MANAGING_STAFF = "managing_staff_for_partner"
ENTRY_SOURCE_LEGACY_IMPORT = "legacy_import"
ENTRY_SOURCE_ADMIN_EXCEPTION = "admin_exception"


def normalize_salesforce_id(raw: str) -> str:
    """Trim, uppercase, drop invisible/control Unicode characters, and
    collapse accidental whitespace around hyphens — so "sve - abc123 " and
    "SVE-ABC123" are recognized as the same value for duplicate detection."""
    if not raw:
        return ""
    cleaned = "".join(ch for ch in raw if unicodedata.category(ch) not in ("Cc", "Cf"))
    cleaned = cleaned.strip().upper()
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def is_valid_salesforce_id(id_value: str, kind: str) -> bool:
    """kind: 'visit' | 'training'. Accepts the legacy bare SV- prefix for
    visits (backward-compatible reads of historical data) — use
    is_valid_new_entry to enforce the canonical prefix on new submissions."""
    v = normalize_salesforce_id(id_value)
    if kind == "training":
        return bool(_TS_RE.match(v))
    return bool(_SVE_RE.match(v)) or bool(_LEGACY_SV_RE.match(v))


def is_valid_new_entry(id_value: str, kind: str) -> bool:
    """The canonical prefix required for any NEW submission — TS- for
    training, SVE- for visits. The legacy bare SV- prefix is grandfathered
    for historical data only (is_valid_salesforce_id), never accepted here."""
    v = normalize_salesforce_id(id_value)
    return bool(_TS_RE.match(v)) if kind == "training" else bool(_SVE_RE.match(v))


def salesforce_prefix_for(kind: str) -> str:
    return "TS-" if kind == "training" else "SVE-"


class DuplicateSalesforceId(ConflictError):
    """Raised when a normalized Salesforce ID is already reserved by another
    activity. A ConflictError so the DRF exception handler renders HTTP 409
    automatically, with a stable error code for API consumers."""

    default_detail = (
        "This Salesforce Activity ID has already been used. Check the ID in "
        "Salesforce and enter the correct record."
    )
    code = "duplicate_salesforce_activity_id"


def reserve_salesforce_id(
    *,
    activity,
    raw_value: str,
    kind: str,
    principal,
    entry_source: str,
) -> "ActivitySalesforceReference":
    """Atomically validate, normalize and reserve a Salesforce Activity ID
    for one activity — the single canonical entry point every write surface
    (My Plan completion, the standalone SF-ID drawer, partner managing-staff
    review, admin correction) must call. Never assign
    Activity.salesforce_activity_id directly outside this function.

    Sequence (mandate §3): normalize -> validate prefix -> lock the Activity
    row -> attempt to reserve the normalized value -> rely on the database
    uniqueness constraint as the final concurrency guard -> save the
    Activity's own denormalized copy -> return the reservation.

    Raises DuplicateSalesforceId if the normalized value is already reserved
    by a DIFFERENT activity (re-submitting the same activity's own current
    value is idempotent, not a duplicate).

    entry_source is recorded for audit/duplicate-investigation purposes.
    This function does NOT itself enforce ENTRY_AUTHORIZED_ROLES — who may
    submit which entry_source is a caller-level authorization decision
    (today's callers inherit their existing, per-endpoint role checks; a
    dedicated managing-staff-for-partner review step, where a partner is
    structurally prevented from supplying entry_source=staff_self_entry, is
    part of the larger partner-workflow rebuild, not this dedup fix)."""
    from .models import Activity, ActivitySalesforceReference

    normalized = normalize_salesforce_id(raw_value)
    if not is_valid_new_entry(normalized, kind):
        prefix = salesforce_prefix_for(kind)
        raise BadRequest(f"A valid {prefix} Salesforce Activity ID is required.")

    with transaction.atomic():
        locked = Activity.objects.select_for_update().filter(id=activity.id).first()
        if not locked:
            raise NotFoundError("Activity not found.")

        existing_ref = ActivitySalesforceReference.objects.filter(
            activity=locked
        ).first()
        conflict = (
            ActivitySalesforceReference.objects.filter(normalized_value=normalized)
            .exclude(activity=locked)
            .exists()
        )
        if conflict:
            raise DuplicateSalesforceId(
                "This Salesforce Activity ID has already been used. Check the "
                "ID in Salesforce and enter the correct record."
            )

        try:
            if existing_ref:
                existing_ref.raw_value = raw_value
                existing_ref.normalized_value = normalized
                existing_ref.activity_type = locked.activity_type
                existing_ref.expected_prefix = salesforce_prefix_for(kind)
                existing_ref.entry_source = entry_source
                existing_ref.entered_by = principal.user_id
                existing_ref.entered_at = timezone.now()
                existing_ref.save(
                    update_fields=[
                        "raw_value",
                        "normalized_value",
                        "activity_type",
                        "expected_prefix",
                        "entry_source",
                        "entered_by",
                        "entered_at",
                        "updated_at",
                    ]
                )
                ref = existing_ref
            else:
                ref = ActivitySalesforceReference.objects.create(
                    activity=locked,
                    raw_value=raw_value,
                    normalized_value=normalized,
                    activity_type=locked.activity_type,
                    expected_prefix=salesforce_prefix_for(kind),
                    entry_source=entry_source,
                    entered_by=principal.user_id,
                    entered_at=timezone.now(),
                )
        except IntegrityError as exc:
            # Final concurrency guard: two near-simultaneous requests both
            # passed the pre-check above and raced to INSERT — the database
            # constraint lets exactly one through; the loser lands here.
            raise DuplicateSalesforceId(
                "This Salesforce Activity ID has already been used. Check the "
                "ID in Salesforce and enter the correct record."
            ) from exc

        locked.salesforce_activity_id = normalized
        locked.salesforce_activity_type = kind
        locked.save(
            update_fields=[
                "salesforce_activity_id",
                "salesforce_activity_type",
                "updated_at",
            ]
        )

    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="activity.salesforce_id_entered",
            subject_kind="Activity",
            subject_id=str(locked.id),
            actor_id=str(principal.user_id),
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"normalized_value": normalized, "entry_source": entry_source},
        )
    except Exception:  # noqa: BLE001 — audit must never block the reservation
        pass

    return ref


__all__ = [
    "normalize_salesforce_id",
    "is_valid_salesforce_id",
    "is_valid_new_entry",
    "salesforce_prefix_for",
    "reserve_salesforce_id",
    "DuplicateSalesforceId",
    "ENTRY_AUTHORIZED_ROLES",
    "ENTRY_SOURCE_STAFF_SELF",
    "ENTRY_SOURCE_MANAGING_STAFF",
    "ENTRY_SOURCE_LEGACY_IMPORT",
    "ENTRY_SOURCE_ADMIN_EXCEPTION",
]
