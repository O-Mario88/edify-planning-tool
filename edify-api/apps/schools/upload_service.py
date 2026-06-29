"""
File-based school upload (CSV + XLSX) — the truthful, persisted onboarding path.

`POST /api/schools/upload` flows through `upload_school_file`. The file is parsed
with a real parser (Python `csv` for CSV, `openpyxl` for XLSX — never naive
string splitting), headers are normalized through the single canonical mapping
module, and each row is validated + saved (or skipped/failed/duplicated) with a
per-row audit result. A file-level/header error rolls back everything (nothing is
written); row-level errors never block the valid rows.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.core.enums import AccountOwnerStatus
from apps.geography.models import District
from apps.accounts.models import StaffSchoolAssignment

from . import upload_mapping as M
from .models import School, UploadBatch, UploadBatchRowResult


# ── Parsing ──────────────────────────────────────────────────────────────────
def _read_rows(file) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Parse an uploaded file into (raw_headers, [(row_number, cells)]).

    row_number is the 1-based spreadsheet line including the header (header == 1,
    first data row == 2). Fully-blank rows are dropped here only when they carry
    no cells at all; blank-but-present rows are kept so the caller can mark them
    `skipped` truthfully."""
    name = (getattr(file, "name", "") or "").lower()
    raw = file.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")

    is_xlsx = name.endswith(".xlsx") or name.endswith(".xlsm")
    if is_xlsx:
        return _read_xlsx(raw)
    return _read_csv(raw)


def _read_csv(raw: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    text = raw.decode("utf-8-sig", errors="replace")  # utf-8-sig strips the BOM
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    headers = [c.strip() for c in all_rows[0]]
    data: list[tuple[int, list[str]]] = []
    for i, cells in enumerate(all_rows[1:], start=2):
        # A truly empty line (no cells at all) is not a record — drop it. A row
        # of empty commas (cells present but blank) is a real blank row → kept so
        # the caller can mark it `skipped`.
        if len(cells) == 0:
            continue
        data.append((i, [(c or "").strip() for c in cells]))
    return headers, data


def _read_xlsx(raw: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - openpyxl is a declared dep
        raise BadRequest("XLSX support requires openpyxl on the server.") from exc

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise BadRequest(f"Could not read the XLSX file: {exc}") from exc
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return [], []
    headers = [_cell_to_str(c).strip() for c in header_row]
    data: list[tuple[int, list[str]]] = []
    for i, row in enumerate(rows_iter, start=2):
        data.append((i, [_cell_to_str(c).strip() for c in row]))
    return headers, data


def _cell_to_str(c) -> str:
    if c is None:
        return ""
    if isinstance(c, datetime):
        return c.date().isoformat()
    if isinstance(c, date):
        return c.isoformat()
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c)


def _value(field_index: dict[str, int], field: str, cells: list[str]) -> str:
    col = field_index.get(field)
    if col is None or col >= len(cells):
        return ""
    return (cells[col] or "").strip()


def _parse_date(value: str) -> date:
    """Parse a date cell into a `date`. Accepts ISO + common spreadsheet forms."""
    v = value.strip()
    # ISO first (covers 2026-01-31 and full datetimes).
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date '{value}'")


def _match_account_owner(name: str) -> tuple[str | None, str]:
    """Match a raw staff name via the StaffMatchingService. Returns
    (staff_profile_id | None, status). Replaces the old single-user iexact match
    with role-aware matching + ambiguity detection."""
    from apps.accounts.staff_matching import match as staff_match

    return staff_match(name)


def _upsert_staff_candidate(name: str, batch_id: str, school_pk: str) -> None:
    """Create/update a StaffSetupCandidate for an unmatched/ambiguous staff name.
    One candidate per normalized name (no duplicates across uploads); each new
    school increments the count and is appended to the sample list."""
    from apps.accounts.models import StaffSetupCandidate
    from apps.accounts.staff_matching import normalize_name

    norm = normalize_name(name)
    if not norm:
        return
    cand, created = StaffSetupCandidate.objects.get_or_create(
        normalized_name=norm,
        defaults={"full_name": name.strip(), "source_upload_batch": batch_id},
    )
    if created:
        cand.school_count = 1
        cand.sample_school_ids = [school_pk]
    else:
        cand.school_count = (cand.school_count or 0) + 1
        sample = list(cand.sample_school_ids or [])
        if school_pk not in sample:
            sample.append(school_pk)
            cand.sample_school_ids = sample[:20]  # cap the sample list
    cand.save(update_fields=["school_count", "sample_school_ids"])


# ── Main entry ───────────────────────────────────────────────────────────────
def upload_school_file(file, principal, update_existing: bool = False) -> dict:
    """Parse + validate + persist a school onboarding file. Returns the truthful
    response contract. Raises BadRequest (→ 400) on file/header errors with
    NOTHING saved."""
    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    field_index = M.build_field_index(raw_headers, M.SCHOOL_HEADER_MAP)
    missing = M.missing_required(field_index, M.SCHOOL_REQUIRED_FIELDS)
    if missing:
        label = {"school_id": "School ID", "name": "School Name", "district": "District"}
        raise BadRequest(
            "Missing required column(s): "
            + ", ".join(label[m] for m in missing)
            + f". Received headers: [{', '.join(h for h in raw_headers if h)}]. "
            + f"Expected headers include: [{', '.join(M.SCHOOL_EXPECTED_HEADERS)}]."
        )

    batch = UploadBatch.objects.create(
        source="csv_upload",
        upload_type="schools",
        file_name=getattr(file, "name", None),
        original_file_name=getattr(file, "name", None),
        uploaded_by=principal.user_id,
    )

    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    # Staff-ownership matching tallies (for the upload response summary).
    staff_counts = {"matched": 0, "unmatched": 0, "ambiguous": 0}
    errors: list[dict] = []
    row_results: list[UploadBatchRowResult] = []

    for row_number, cells in data_rows:
        school_id = _value(field_index, "school_id", cells)
        name = _value(field_index, "name", cells)
        district_name = _value(field_index, "district", cells)

        raw_map = {
            f: _value(field_index, f, cells)
            for f in field_index
        }

        # Fully-blank row → skipped.
        if not any((cells[i] or "").strip() for i in range(len(cells))):
            counts["skipped"] += 1
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=None,
                status="skipped", error_message="Blank row", raw_data_json=raw_map,
            ))
            continue

        # Required-field checks.
        blank_required = [
            label for value, label in (
                (school_id, "School ID"), (name, "School Name"), (district_name, "District"),
            ) if not value
        ]
        if blank_required:
            msg = f"Missing required value(s): {', '.join(blank_required)}"
            counts["failed"] += 1
            errors.append({"row": row_number, "school_id": school_id, "error": msg})
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=school_id or None,
                status="failed", error_message=msg, raw_data_json=raw_map,
            ))
            continue

        # Geography — district name → district + region.
        # 3-tier lookup: exact (iexact) → alias table → partial contains.
        district = District.objects.select_related("region").filter(name__iexact=district_name).first()
        if not district:
            from apps.geography.models import GeographyAlias
            norm = district_name.strip().lower()
            alias = GeographyAlias.objects.filter(admin_level="district", normalized_alias=norm).first()
            if alias:
                district = District.objects.select_related("region").filter(id=alias.admin_id).first()
        if not district:
            # Last resort: partial contains (catches "Fort Portal" matching "Fort Portal (Kabarole)")
            district = District.objects.select_related("region").filter(
                name__icontains=district_name.strip()
            ).first() or District.objects.select_related("region").filter(
                name__icontains=district_name.strip().split("(")[0].strip()
            ).first()
        if not district:
            msg = f'District "{district_name}" did not match any district in the geography directory.'
            counts["failed"] += 1
            errors.append({"row": row_number, "school_id": school_id, "error": msg})
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=school_id,
                status="failed", error_message=msg, raw_data_json=raw_map,
            ))
            continue

        # Enrolment — int if present.
        enrollment = None
        enrollment_raw = _value(field_index, "enrollment", cells)
        if enrollment_raw:
            try:
                enrollment = int(float(enrollment_raw))
            except ValueError:
                msg = f'Enrolment "{enrollment_raw}" is not a whole number.'
                counts["failed"] += 1
                errors.append({"row": row_number, "school_id": school_id, "error": msg})
                row_results.append(UploadBatchRowResult(
                    upload_batch=batch, row_number=row_number, school_id=school_id,
                    status="failed", error_message=msg, raw_data_json=raw_map,
                ))
                continue

        # Last enrolment date — parse if present.
        last_enrollment_date = None
        date_raw = _value(field_index, "last_enrollment_date", cells)
        if date_raw:
            try:
                last_enrollment_date = _parse_date(date_raw)
            except ValueError:
                msg = f'Last Date of Enrolment "{date_raw}" is not a valid date.'
                counts["failed"] += 1
                errors.append({"row": row_number, "school_id": school_id, "error": msg})
                row_results.append(UploadBatchRowResult(
                    upload_batch=batch, row_number=row_number, school_id=school_id,
                    status="failed", error_message=msg, raw_data_json=raw_map,
                ))
                continue

        school_type, _recognized = M.map_school_type(_value(field_index, "school_type", cells))
        owner_raw = _value(field_index, "account_owner_name_raw", cells) or None
        # Role-aware matching: only field-staff (CCEO/PL) users auto-link.
        owner_id, owner_status = _match_account_owner(owner_raw) if owner_raw else (None, AccountOwnerStatus.PENDING.value)

        defaults = {
            "name": name,
            "region": district.region,
            "district": district,
            "school_type": school_type,
            "enrollment": enrollment,
            "last_enrollment_date": last_enrollment_date,
            "school_phone": _value(field_index, "school_phone", cells) or None,
            "primary_contact_name": _value(field_index, "primary_contact_name", cells) or None,
            "shipping_address": _value(field_index, "shipping_address", cells) or None,
            "account_owner_name_raw": owner_raw,
            "account_owner_id": owner_id,
            "account_owner_status": owner_status,
            "uploaded_district_text": district_name,
            "upload_batch_id": batch.id,
        }

        try:
            # Store resolved defaults in raw_map for deferred import
            raw_map["_defaults"] = {
                "name": name,
                "region_id": district.region_id,
                "district_id": district.id,
                "school_type": school_type,
                "enrollment": enrollment,
                "last_enrollment_date": last_enrollment_date.isoformat() if last_enrollment_date else None,
                "school_phone": _value(field_index, "school_phone", cells) or None,
                "primary_contact_name": _value(field_index, "primary_contact_name", cells) or None,
                "shipping_address": _value(field_index, "shipping_address", cells) or None,
                "account_owner_name_raw": owner_raw,
                "account_owner_id": owner_id,
                "account_owner_status": owner_status,
                "uploaded_district_text": district_name,
            }

            existing = School.objects.filter(school_id=school_id).first()
            if existing and not update_existing:
                counts["duplicate"] += 1
                row_results.append(UploadBatchRowResult(
                    upload_batch=batch, row_number=row_number, school_id=school_id,
                    status="duplicate",
                    error_message="School ID already exists (update_existing=false).",
                    raw_data_json=raw_map,
                ))
                continue
            if existing and update_existing:
                counts["updated"] += 1
                row_results.append(UploadBatchRowResult(
                    upload_batch=batch, row_number=row_number, school_id=school_id,
                    status="updated", raw_data_json=raw_map,
                ))
                if owner_status == AccountOwnerStatus.MATCHED.value and owner_id:
                    staff_counts["matched"] += 1
                elif owner_status in (AccountOwnerStatus.UNMATCHED.value, AccountOwnerStatus.AMBIGUOUS.value):
                    if owner_status == AccountOwnerStatus.AMBIGUOUS.value:
                        staff_counts["ambiguous"] += 1
                    else:
                        staff_counts["unmatched"] += 1
            else:
                counts["created"] += 1
                row_results.append(UploadBatchRowResult(
                    upload_batch=batch, row_number=row_number, school_id=school_id,
                    status="created", raw_data_json=raw_map,
                ))
                if owner_status == AccountOwnerStatus.MATCHED.value and owner_id:
                    staff_counts["matched"] += 1
                elif owner_status in (AccountOwnerStatus.UNMATCHED.value, AccountOwnerStatus.AMBIGUOUS.value):
                    if owner_status == AccountOwnerStatus.AMBIGUOUS.value:
                        staff_counts["ambiguous"] += 1
                    else:
                        staff_counts["unmatched"] += 1
        except Exception as exc:  # noqa: BLE001 — never let one row break the batch
            msg = f"Could not validate row: {exc}"
            counts["failed"] += 1
            errors.append({"row": row_number, "school_id": school_id, "error": msg})
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=school_id,
                status="failed", error_message=msg, raw_data_json=raw_map,
            ))

    if row_results:
        UploadBatchRowResult.objects.bulk_create(row_results)

    total = len(data_rows)
    saved = counts["created"] + counts["updated"]
    success = saved > 0
    batch.row_count = total
    batch.total_rows = total
    batch.created_rows = counts["created"]
    batch.updated_rows = counts["updated"]
    batch.skipped_rows = counts["skipped"]
    batch.failed_rows = counts["failed"]
    batch.duplicate_rows = counts["duplicate"]
    batch.accepted_count = saved
    batch.flagged_count = counts["failed"] + counts["duplicate"]
    batch.status = "validated" if not counts["failed"] else "completed_with_errors"
    if errors:
        batch.error_summary = "; ".join(f"row {e['row']}: {e['error']}" for e in errors[:50])
    batch.save()

    if success:
        import_school_batch(batch, principal)
        batch.status = "imported"
        batch.save(update_fields=["status"])

    message = _build_message(success, counts, total)
    # Staff-matching summary: which uploaded names matched a field-staff user,
    # and which need Admin setup. Sourced from the candidates touched this batch
    # so the response is truthful (no fabricated rows).
    from apps.accounts.models import StaffSetupCandidate

    pending_candidates = list(
        StaffSetupCandidate.objects.filter(source_upload_batch=batch.id).exclude(status="ignored")
    )
    unmatched_staff = [
        {"staff_name": c.full_name, "school_count": c.school_count, "status": c.status}
        for c in pending_candidates
    ]
    return {
        "success": success,
        "upload_batch_id": batch.id,
        "total_rows": total,
        "created_rows": counts["created"],
        "updated_rows": counts["updated"],
        "failed_rows": counts["failed"],
        "duplicate_rows": counts["duplicate"],
        "skipped_rows": counts["skipped"],
        "matched_staff_count": staff_counts["matched"],
        "unmatched_staff_count": staff_counts["unmatched"],
        "ambiguous_staff_count": staff_counts["ambiguous"],
        "unmatched_staff": unmatched_staff,
        "message": message,
        "errors": errors,
    }


def import_school_batch(batch: UploadBatch, principal) -> None:
    rows = batch.row_results.filter(status__in=("created", "updated"))
    for r in rows:
        defaults = r.raw_data_json.get("_defaults")
        if not defaults:
            continue
        
        school_id = r.school_id
        if defaults.get("last_enrollment_date"):
            defaults["last_enrollment_date"] = date.fromisoformat(defaults["last_enrollment_date"])
        
        # Region and District ForeignKeys must be set to models on import
        region_id = defaults.pop("region_id", None)
        district_id = defaults.pop("district_id", None)
        if region_id:
            defaults["region_id"] = region_id
        if district_id:
            defaults["district_id"] = district_id

        owner_status = defaults.get("account_owner_status")
        owner_id = defaults.get("account_owner_id")
        owner_raw = defaults.get("account_owner_name_raw")

        try:
            with transaction.atomic():
                existing = School.objects.filter(school_id=school_id).first()
                if existing:
                    # Update existing
                    for k, v in defaults.items():
                        setattr(existing, k, v)
                    existing.save()
                    saved_school = existing
                else:
                    saved_school = School.objects.create(school_id=school_id, **defaults)

                # Ownership assignment bridge
                if owner_status == AccountOwnerStatus.MATCHED.value and owner_id:
                    StaffSchoolAssignment.objects.get_or_create(
                        staff_id=owner_id, school_id=saved_school.id,
                    )
                    # remove ghost assignments
                    live_ids = set(School.objects.filter(deleted_at__isnull=True).values_list("id", flat=True))
                    StaffSchoolAssignment.objects.filter(staff_id=owner_id).exclude(
                        school_id__in=live_ids
                    ).delete()
                elif owner_status in (AccountOwnerStatus.UNMATCHED.value, AccountOwnerStatus.AMBIGUOUS.value) and owner_raw:
                    _upsert_staff_candidate(owner_raw, batch.id, saved_school.id)
        except Exception as exc:
            r.status = "failed"
            r.error_message = f"Could not save school: {exc}"
            r.save()


def _build_message(success: bool, counts: dict, total: int) -> str:
    if total == 0:
        return "No data rows were found in the file."
    if success:
        parts = []
        if counts["created"]:
            parts.append(f"{counts['created']} created")
        if counts["updated"]:
            parts.append(f"{counts['updated']} updated")
        if counts["duplicate"]:
            parts.append(f"{counts['duplicate']} duplicate")
        if counts["failed"]:
            parts.append(f"{counts['failed']} failed")
        if counts["skipped"]:
            parts.append(f"{counts['skipped']} skipped")
        return "Upload complete — " + ", ".join(parts) + "."
    if counts["duplicate"] and not counts["failed"]:
        return f"Nothing saved — all {counts['duplicate']} row(s) already exist. Enable 'update existing' to overwrite."
    if counts["failed"] and not counts["duplicate"]:
        return f"Nothing saved — all {counts['failed']} row(s) failed validation. See the errors below."
    return "Nothing was saved — no rows were created or updated."


__all__ = ["upload_school_file", "import_school_batch"]
