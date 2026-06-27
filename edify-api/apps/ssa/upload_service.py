"""
File-based SSA upload (CSV + XLSX) — mirrors the school upload path.

`POST /api/ssa/upload` flows through `upload_ssa_file`. Headers are normalized
through the single canonical mapping module; each row must reference an existing
School and carry all 8 numeric intervention scores. Valid rows are saved through
the existing `apps.ssa.services.upload` (so FY/quarter derivation, verification
provenance, school SSA-status + planning-readiness recompute all stay identical).
Reporting reuses UploadBatch + UploadBatchRowResult with upload_type="ssa".
"""
from __future__ import annotations

from datetime import datetime, time

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.schools.models import School, UploadBatch, UploadBatchRowResult
from apps.schools import upload_mapping as M
from apps.schools.upload_service import _parse_date, _read_rows, _value

from . import services


def upload_ssa_file(file, principal) -> dict:
    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    field_index = M.build_field_index(raw_headers, M.SSA_HEADER_MAP)
    missing = M.missing_required(field_index, M.SSA_REQUIRED_FIELDS)
    present_interventions = [i for i in M.ALL_INTERVENTIONS if i in field_index]
    missing_interventions = [i for i in M.ALL_INTERVENTIONS if i not in field_index]
    if missing or missing_interventions:
        label = {"school_id": "School ID", "date_of_ssa": "Assessment/SSA Date"}
        missing_labels = [label[m] for m in missing]
        if missing_interventions:
            missing_labels.append(
                f"{len(missing_interventions)} intervention column(s) ({', '.join(missing_interventions)})"
            )
        raise BadRequest(
            "Missing required column(s): "
            + ", ".join(missing_labels)
            + f". Received headers: [{', '.join(h for h in raw_headers if h)}]. "
            + f"Expected headers include: [{', '.join(M.SSA_EXPECTED_HEADERS)}]."
        )

    batch = UploadBatch.objects.create(
        source="csv_upload",
        upload_type="ssa",
        file_name=getattr(file, "name", None),
        original_file_name=getattr(file, "name", None),
        uploaded_by=principal.user_id,
    )

    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "duplicate": 0}
    errors: list[dict] = []
    row_results: list[UploadBatchRowResult] = []

    for row_number, cells in data_rows:
        raw_map = {f: _value(field_index, f, cells) for f in field_index}

        if not any((cells[i] or "").strip() for i in range(len(cells))):
            counts["skipped"] += 1
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=None,
                status="skipped", error_message="Blank row", raw_data_json=raw_map,
            ))
            continue

        school_id = _value(field_index, "school_id", cells)
        date_raw = _value(field_index, "date_of_ssa", cells)

        def fail(msg: str):
            counts["failed"] += 1
            errors.append({"row": row_number, "school_id": school_id, "error": msg})
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=school_id or None,
                status="failed", error_message=msg, raw_data_json=raw_map,
            ))

        if not school_id:
            fail("Missing School ID.")
            continue
        if not School.objects.filter(school_id=school_id).exists():
            fail(f"School {school_id} is not in the directory.")
            continue
        if not date_raw:
            fail("Missing Assessment/SSA Date.")
            continue
        try:
            ssa_date = _parse_date(date_raw)
        except ValueError:
            fail(f'Assessment/SSA Date "{date_raw}" is not a valid date.')
            continue

        # All 8 scores required, numeric, in range.
        scores = []
        bad = None
        for interv in M.ALL_INTERVENTIONS:
            raw = _value(field_index, interv, cells)
            if raw == "":
                bad = f"Missing score for {interv}."
                break
            try:
                score = float(raw)
            except ValueError:
                bad = f'Score for {interv} ("{raw}") is not numeric.'
                break
            if score < 0 or score > 10:
                bad = f"Score for {interv} ({score}) is out of range 0–10."
                break
            scores.append({"intervention": interv, "score": score})
        if bad:
            fail(bad)
            continue

        new_enrollment_raw = _value(field_index, "new_enrollment", cells)
        new_enrollment = None
        if new_enrollment_raw:
            try:
                new_enrollment = int(float(new_enrollment_raw))
            except ValueError:
                fail(f'Enrolment "{new_enrollment_raw}" is not a whole number.')
                continue

        try:
            with transaction.atomic():
                # Attach the project timezone (local noon) so the SSA record's
                # date_of_ssa is timezone-aware (USE_TZ=True) — a bare date string
                # would otherwise produce a naive-datetime RuntimeWarning.
                from django.utils import timezone
                tz = timezone.get_current_timezone()
                aware = timezone.make_aware(datetime.combine(ssa_date, time(12, 0)), tz)
                services.upload(
                    {
                        "schoolId": school_id,
                        "dateOfSsa": aware.isoformat(),
                        "newEnrollment": new_enrollment,
                        "scores": scores,
                    },
                    principal,
                )
            counts["created"] += 1
            row_results.append(UploadBatchRowResult(
                upload_batch=batch, row_number=row_number, school_id=school_id,
                status="created", raw_data_json=raw_map,
            ))
        except Exception as exc:  # noqa: BLE001
            fail(f"Could not save SSA: {exc}")

    if row_results:
        UploadBatchRowResult.objects.bulk_create(row_results)

    total = len(data_rows)
    saved = counts["created"]
    success = saved > 0
    batch.row_count = total
    batch.total_rows = total
    batch.created_rows = counts["created"]
    batch.skipped_rows = counts["skipped"]
    batch.failed_rows = counts["failed"]
    batch.accepted_count = saved
    batch.flagged_count = counts["failed"]
    batch.status = "completed" if not counts["failed"] else "completed_with_errors"
    if errors:
        batch.error_summary = "; ".join(f"row {e['row']}: {e['error']}" for e in errors[:50])
    batch.save()

    if total == 0:
        message = "No data rows were found in the file."
    elif success:
        message = f"Upload complete — {saved} SSA record(s) saved" + (
            f", {counts['failed']} failed." if counts["failed"] else "."
        )
    else:
        message = f"Nothing saved — all {counts['failed']} row(s) failed validation. See the errors below."

    return {
        "success": success,
        "upload_batch_id": batch.id,
        "total_rows": total,
        "created_rows": counts["created"],
        "updated_rows": counts["updated"],
        "failed_rows": counts["failed"],
        "duplicate_rows": counts["duplicate"],
        "skipped_rows": counts["skipped"],
        "message": message,
        "errors": errors,
    }


__all__ = ["upload_ssa_file"]
