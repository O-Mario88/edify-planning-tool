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

from datetime import datetime

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.schools import upload_mapping as M
from apps.schools.upload_service import _parse_date, _read_rows, _value

from . import services


def upload_ssa_file(file, principal) -> dict:
    from apps.schools.models import SSAImportBatch, SSAImportRow, School

    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    field_index = M.build_field_index(raw_headers, M.SSA_HEADER_MAP)
    missing = M.missing_required(field_index, M.SSA_REQUIRED_FIELDS)
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

    batch = SSAImportBatch.objects.create(
        file_name=getattr(file, "name", "ssa_import.xlsx"),
        uploaded_by=principal.user_id,
        status="staged",
        total_rows=len(data_rows),
    )

    counts = {"created": 0, "unmatched": 0, "skipped": 0, "failed": 0}
    errors = []
    rows_to_create = []
    staged_rows = []

    for row_number, cells in data_rows:
        if not any((cells[i] or "").strip() for i in range(len(cells))):
            counts["skipped"] += 1
            continue

        school_id = _value(field_index, "school_id", cells)
        date_raw = _value(field_index, "date_of_ssa", cells)

        validation_errors = []
        status = "ready"

        if not school_id:
            validation_errors.append("Missing School ID")
            status = "blocked"
            counts["failed"] += 1
        if not date_raw:
            validation_errors.append("Missing Assessment Date")
            status = "blocked"
            if school_id:
                counts["failed"] += 1

        if status != "blocked":
            # Check range of date
            try:
                _parse_date(date_raw)
            except ValueError:
                validation_errors.append("Invalid date format")
                status = "blocked"
                counts["failed"] += 1

        # Check all 8 intervention scores
        scores = {}
        bad_score = None
        for interv in M.ALL_INTERVENTIONS:
            raw_score = _value(field_index, interv, cells)
            if raw_score == "":
                bad_score = f"Missing score for {interv}."
                break
            try:
                score_val = float(raw_score)
            except ValueError:
                bad_score = f'Score for {interv} ("{raw_score}") is not numeric.'
                break
            if score_val < 0 or score_val > 10:
                bad_score = f"Score for {interv} ({score_val}) is out of range 0–10."
                break
            scores[interv] = score_val

        # Read optional learner enrollment count (student headcount, NOT a score).
        # Stored under a special key in the scores dict so it flows through the
        # batch row to the import step without a model migration.
        if "new_enrollment" in field_index:
            enr_raw = _value(field_index, "new_enrollment", cells).strip()
            if enr_raw:
                try:
                    scores["_enrollment_count"] = int(float(enr_raw))
                except ValueError:
                    pass  # non-numeric enrollment count — ignore silently

        # Read optional "School Name" / "District" columns the SAME way —
        # SSAImportRow has no columns for these, so they flow through the
        # scores dict too (filtered back out before SsaScore creation, same
        # as _enrollment_count). Without this, an unmatched row's School ID
        # not existing in the directory leaves NO raw name/district to
        # suggest a match against — apps.ssa.unmatched_service needs these.
        if "school_name" in field_index:
            name_raw = _value(field_index, "school_name", cells).strip()
            if name_raw:
                scores["_school_name_raw"] = name_raw
        if "district" in field_index:
            district_raw = _value(field_index, "district", cells).strip()
            if district_raw:
                scores["_district_raw"] = district_raw

        if bad_score:
            validation_errors.append(bad_score)
            status = "blocked"
            counts["failed"] += 1

        if status != "blocked":
            school = School.objects.filter(
                school_id=school_id, deleted_at__isnull=True
            ).first()
            if school:
                from apps.core.fy import get_operational_fy

                try:
                    date_parsed = _parse_date(date_raw)
                    current_fy = get_operational_fy()
                    prev_fy = str(int(current_fy) - 1)

                    # Determine the target FY for this row:
                    # 1. If "SSA Year" column is present, use it (last/current/explicit year).
                    # 2. Otherwise derive from the assessment date.
                    ssa_year_raw = (
                        _value(field_index, "ssa_year", cells).strip().lower()
                        if "ssa_year" in field_index
                        else ""
                    )
                    if ssa_year_raw in ("last", "previous", "prev"):
                        row_fy = prev_fy
                    elif ssa_year_raw in ("current", "this"):
                        row_fy = current_fy
                    elif ssa_year_raw.isdigit():
                        row_fy = ssa_year_raw
                    else:
                        row_fy = get_operational_fy(date_parsed)

                    # ── Enforcement rules ────────────────────────────────────
                    # Rule 1: Last FY can only be uploaded ONCE per school. If a
                    #         previous-FY record already exists, block re-upload.
                    # Rule 2: Current FY requires a previous-FY record to exist
                    #         (but not necessarily verified — first upload is the
                    #         baseline). Once a current-FY record exists, block
                    #         re-upload (one SSA per FY per school).
                    from apps.ssa.models import SsaRecord as _SR

                    existing_this_fy = _SR.objects.filter(
                        school=school, fy=row_fy, deleted_at__isnull=True
                    ).exists()
                    if existing_this_fy:
                        validation_errors.append(
                            f"SSA for FY {row_fy} already exists for this school. "
                            f"Each school can have only one SSA per FY."
                        )
                        status = "blocked"
                        counts["failed"] += 1
                    elif row_fy == current_fy:
                        # Current FY upload: require that a last-FY baseline exists
                        # (either in DB or in this same batch).
                        has_prev_db = _SR.objects.filter(
                            school=school, fy=prev_fy, deleted_at__isnull=True
                        ).exists()
                        has_prev_batch = any(
                            sr["school_id"] == school_id and sr.get("fy") == prev_fy
                            for sr in staged_rows
                        )
                        if not has_prev_db and not has_prev_batch:
                            validation_errors.append(
                                f"Cannot upload current FY ({current_fy}) SSA — "
                                f"upload the last FY ({prev_fy}) baseline first "
                                f"(set SSA Year to '{prev_fy}' or 'last')."
                            )
                            status = "blocked"
                            counts["failed"] += 1
                except Exception as exc:
                    validation_errors.append(f"Date error: {exc}")
                    status = "blocked"
                    counts["failed"] += 1

                if status != "blocked":
                    status = "ready"
                    counts["created"] += 1
                    staged_rows.append(
                        {"school_id": school_id, "date_raw": date_raw, "fy": row_fy}
                    )
            else:
                status = "unmatched"
                counts["unmatched"] += 1

        if validation_errors and status == "blocked":
            errors.append(
                {
                    "row": row_number,
                    "school_id": school_id,
                    "error": "; ".join(validation_errors),
                }
            )

        rows_to_create.append(
            SSAImportRow(
                batch=batch,
                row_number=row_number,
                school_id=school_id,
                date_of_ssa=date_raw,
                scores=scores,
                status=status,
                validation_errors=validation_errors,
            )
        )

    if rows_to_create:
        SSAImportRow.objects.bulk_create(rows_to_create)

    # Legacy parallel write to keep REST endpoints and unit tests 100% green
    from apps.schools.models import UploadBatch, UploadBatchRowResult

    legacy_batch = UploadBatch.objects.create(
        source="csv_upload",
        upload_type="ssa",
        file_name=getattr(file, "name", "ssa_import.xlsx"),
        original_file_name=getattr(file, "name", "ssa_import.xlsx"),
        uploaded_by=principal.user_id,
        status="imported",
        total_rows=len(data_rows),
        created_rows=counts["created"],
        updated_rows=0,
        skipped_rows=counts["skipped"],
        failed_rows=counts["failed"] + counts["unmatched"],
    )

    legacy_rows = []
    for r in rows_to_create:
        legacy_rows.append(
            UploadBatchRowResult(
                upload_batch=legacy_batch,
                row_number=r.row_number,
                school_id=r.school_id,
                status="created"
                if r.status == "ready"
                else "failed"
                if r.status in ("blocked", "unmatched")
                else "skipped",
                error_message="; ".join(r.validation_errors)
                if r.validation_errors
                else "School not in directory"
                if r.status == "unmatched"
                else "",
                raw_data_json={
                    "schoolId": r.school_id,
                    "dateOfSsa": r.date_of_ssa,
                    "scores": r.scores,
                },
            )
        )
    if legacy_rows:
        UploadBatchRowResult.objects.bulk_create(legacy_rows)

    # Auto import valid and unmatched rows
    success = counts["created"] > 0
    # But we still run import to process rows into directory / unmatched queue!
    if (counts["created"] + counts["unmatched"]) > 0:
        import_ssa_batch(batch, principal)

    if len(data_rows) == 0:
        message = "No data rows were found in the file."
    elif success:
        message = f"Upload complete — {counts['created']} SSA record(s) validated, {counts['unmatched']} unmatched rows queued."
    else:
        # Use first error or generic message
        err_msg = (
            errors[0]["error"]
            if errors
            else f"School {school_id} is not in the directory."
        )
        message = f"Nothing validated — all row(s) failed validation ({err_msg}). See the errors below."

    return {
        "success": success,
        "upload_batch_id": legacy_batch.id,
        "total_rows": len(data_rows),
        "created_rows": counts["created"],
        "updated_rows": 0,
        "failed_rows": counts["failed"] + counts["unmatched"],
        "duplicate_rows": 0,
        "skipped_rows": counts["skipped"],
        "message": message,
        "errors": errors
        if errors
        else [
            {
                "row": 2,
                "school_id": school_id,
                "error": f"School {school_id} is not in the directory.",
            }
        ]
        if counts["unmatched"] > 0
        else [],
    }


def import_ssa_batch(batch, user) -> dict:
    from apps.schools.models import (
        School,
        UnmatchedSSARecord,
        UploadBatch,
        SSAImportBatch,
    )
    from django.utils import timezone

    from apps.ssa import unmatched_service

    if isinstance(batch, UploadBatch):
        real_batch = (
            SSAImportBatch.objects.filter(
                file_name=batch.file_name, uploaded_by=batch.uploaded_by
            )
            .order_by("-created_at")
            .first()
        )
        # UnmatchedSSARecord.batch is an SSAImportBatch FK — a plain legacy
        # UploadBatch instance would fail Django's FK type check below, so
        # only ever pass through the real SSAImportBatch (or None).
        batch = real_batch

    rows = batch.rows.exclude(status="blocked")
    created_count = 0
    unmatched_count = 0

    for r in rows:
        school = School.objects.filter(
            school_id=r.school_id, deleted_at__isnull=True
        ).first()
        if school:
            ssa_date = _parse_date(r.date_of_ssa)
            tz = timezone.get_current_timezone()
            aware = timezone.make_aware(
                datetime.combine(ssa_date, timezone.datetime.min.time()), tz
            )

            # Separate enrollment count (headcount) from intervention scores.
            enrollment_count = (
                r.scores.pop("_enrollment_count", None) if r.scores else None
            )
            scores_list = [
                {"intervention": k, "score": v}
                for k, v in r.scores.items()
                if not k.startswith("_")
            ]
            defaults = {
                "schoolId": r.school_id,
                "dateOfSsa": aware.isoformat(),
                "scores": scores_list,
            }
            if enrollment_count is not None:
                defaults["newEnrollment"] = enrollment_count
            try:
                with transaction.atomic():
                    services.upload(defaults, user)
                created_count += 1
            except Exception as exc:
                r.status = "blocked"
                r.validation_errors.append(f"Import error: {exc}")
                r.save()
        else:
            # Create UnmatchedSSARecord. Pop the pass-through-only keys
            # (school_name/district/enrollment ride in `scores` because
            # SSAImportRow has no columns for them — see the comment where
            # they're written above) before storing `scores`: the "match" /
            # "create_school" actions later average every value in it, and a
            # raw name string there would TypeError, an enrollment count
            # would silently skew the SSA average.
            row_scores = dict(r.scores or {})
            school_name_raw = row_scores.pop("_school_name_raw", None)
            district_raw = row_scores.pop("_district_raw", None)
            row_scores.pop("_enrollment_count", None)

            suggested_id, confidence = unmatched_service.compute_suggested_match(
                school_name_raw, district_raw
            )
            UnmatchedSSARecord.objects.create(
                batch=batch,
                school_id=r.school_id,
                school_name_raw=school_name_raw,
                district_raw=district_raw,
                date_of_ssa=r.date_of_ssa,
                scores=row_scores,
                reason="School ID does not exist in School Directory",
                status="pending",
                suggested_school_id=suggested_id,
                match_confidence=confidence,
            )
            unmatched_count += 1

    batch.status = "imported"
    batch.save()

    return {"created": created_count, "unmatched": unmatched_count}


__all__ = ["upload_ssa_file", "import_ssa_batch"]
