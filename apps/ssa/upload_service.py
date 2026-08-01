"""
File-based SSA upload (CSV + XLSX) — mirrors the school upload path.

`POST /api/ssa/upload` flows through `upload_ssa_file`. Headers are normalized
through the single canonical mapping module; each row must reference an existing
School and carry all 8 numeric intervention scores. Valid rows retain the
canonical FY/quarter, verification-provenance, school-status and planning-
readiness rules while being persisted in bounded bulk writes. Reporting reuses
UploadBatch + UploadBatchRowResult with upload_type="ssa".
"""

from __future__ import annotations

import logging

import time
from datetime import datetime

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.schools import upload_mapping as M
from apps.schools.upload_service import _parse_date, _read_rows, _value

logger = logging.getLogger(__name__)


def upload_ssa_file(file, principal) -> dict:
    from apps.schools.models import SSAImportBatch, SSAImportRow, School

    started_at = time.perf_counter()
    raw_headers, data_rows = _read_rows(file)
    if not raw_headers:
        raise BadRequest("The uploaded file is empty — no header row found.")

    normalized_headers = {M.normalize_header(header) for header in raw_headers}
    legacy_headcount_headers = {
        "new enrolment",
        "new enrollment",
        "enrolment count",
        "enrollment count",
    }
    if normalized_headers & legacy_headcount_headers:
        raise BadRequest(
            "Pupil enrolment is not part of the SSA upload. In SSA, Enrolment "
            "is a score from 0 to 10. Update pupil headcount through the School "
            "Upload file or the School Profile."
        )

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
    uploaded_school_ids = {
        _value(field_index, "school_id", cells)
        for _row_number, cells in data_rows
        if _value(field_index, "school_id", cells)
    }
    schools_by_id = School.objects.filter(
        school_id__in=uploaded_school_ids,
        deleted_at__isnull=True,
    ).in_bulk(field_name="school_id")
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord as _SR

    current_fy = get_operational_fy()
    prev_fy = str(int(current_fy) - 1)
    existing_fys = {
        (school_pk, fy)
        for school_pk, fy in _SR.objects.filter(
            school_id__in=[school.id for school in schools_by_id.values()],
            deleted_at__isnull=True,
        ).values_list("school_id", "fy")
    }
    staged_fys: set[tuple[str, str]] = set()

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
            school = schools_by_id.get(school_id)
            if school:
                try:
                    date_parsed = _parse_date(date_raw)

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
                    existing_this_fy = (school.id, row_fy) in existing_fys or (
                        school.id,
                        row_fy,
                    ) in staged_fys
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
                        has_prev_db = (school.id, prev_fy) in existing_fys
                        has_prev_batch = (school.id, prev_fy) in staged_fys
                        if not has_prev_db and not has_prev_batch:
                            validation_errors.append(
                                f"Cannot upload current FY ({current_fy}) SSA — "
                                f"upload the last FY ({prev_fy}) SSA score first "
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
                    staged_fys.add((school.id, row_fy))
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

    # Legacy parallel write to keep REST endpoints and unit tests 100% green.
    # status starts "uploaded" (not "imported") and is only flipped to
    # "imported" once import_ssa_batch actually succeeds below — it used to
    # be stamped "imported" here unconditionally, so a failed import left the
    # batch history permanently showing false success counts. Same defect,
    # and same fix, as the school-upload path (SCH-03).
    from apps.schools.models import UploadBatch, UploadBatchRowResult

    legacy_batch = UploadBatch.objects.create(
        source="csv_upload",
        upload_type="ssa",
        file_name=getattr(file, "name", "ssa_import.xlsx"),
        original_file_name=getattr(file, "name", "ssa_import.xlsx"),
        uploaded_by=principal.user_id,
        status="uploaded",
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
        try:
            import_ssa_batch(batch, principal)
        except Exception as exc:
            legacy_batch.status = "failed"
            legacy_batch.error_summary = str(exc)
            legacy_batch.save(update_fields=["status", "error_summary", "updated_at"])
            logger.error("SSA import failed", exc_info=exc)
            raise BadRequest(
                "SSA import failed. The batch is marked failed and the reason "
                "has been recorded for support."
            ) from exc
        legacy_batch.status = "imported"
        legacy_batch.save(update_fields=["status", "updated_at"])

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

    processing_seconds = round(time.perf_counter() - started_at, 3)
    logger.info(
        "SSA upload completed batch=%s rows=%s created=%s unmatched=%s "
        "failed=%s duration_seconds=%s",
        batch.id,
        len(data_rows),
        counts["created"],
        counts["unmatched"],
        counts["failed"],
        processing_seconds,
    )
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
        "processing_seconds": processing_seconds,
    }


def import_ssa_batch(batch, user) -> dict:
    from apps.schools.models import (
        School,
        UnmatchedSSARecord,
        UploadBatch,
        SSAImportBatch,
    )
    from django.utils import timezone
    from apps.core.fy import get_operational_fy, get_quarter_for_date
    from apps.ssa.models import SsaRecord, SsaScore

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

    if batch is None:
        raise BadRequest("The authoritative SSA import batch could not be found.")
    if batch.status == "imported":
        return {"created": 0, "unmatched": 0, "already_imported": True}

    rows = list(batch.rows.exclude(status="blocked"))
    schools_by_id = School.objects.filter(
        school_id__in=[row.school_id for row in rows],
        deleted_at__isnull=True,
    ).in_bulk(field_name="school_id")
    current_fy = get_operational_fy()
    affected_school_pks = {school.id for school in schools_by_id.values()}
    current_states: dict[str, set[str]] = {}
    for school_pk, verification_status in SsaRecord.objects.filter(
        school_id__in=affected_school_pks,
        fy=current_fy,
        deleted_at__isnull=True,
    ).values_list("school_id", "verification_status"):
        current_states.setdefault(school_pk, set()).add(verification_status)

    records = []
    scores = []
    unmatched_records = []
    now = timezone.now()

    with transaction.atomic():
        for r in rows:
            school = schools_by_id.get(r.school_id)
            if school:
                ssa_date = _parse_date(r.date_of_ssa)
                aware = timezone.make_aware(
                    datetime.combine(ssa_date, timezone.datetime.min.time()),
                    timezone.get_current_timezone(),
                )
                row_scores = [
                    (intervention, score)
                    for intervention, score in r.scores.items()
                    if not intervention.startswith("_")
                ]
                record = SsaRecord(
                    school=school,
                    date_of_ssa=aware,
                    fy=get_operational_fy(aware),
                    quarter=get_quarter_for_date(aware),
                    average_score=round(
                        sum(float(score) for _intervention, score in row_scores)
                        / len(row_scores),
                        1,
                    ),
                    uploaded_by=user.user_id,
                    collector_type="staff",
                    collected_by_user_id=user.user_id,
                    verification_status="confirmed",
                    verification_source="staff_self_verified",
                    verified_by_user_id=user.user_id,
                    verified_at=now,
                )
                records.append(record)
                scores.extend(
                    SsaScore(
                        ssa_record=record,
                        intervention=intervention,
                        score=score,
                    )
                    for intervention, score in row_scores
                )
                current_states.setdefault(school.id, set())
                if record.fy == current_fy:
                    current_states[school.id].add("confirmed")
                continue

            # Create UnmatchedSSARecord. Pop the pass-through-only keys
            # (school_name/district ride in `scores` because
            # SSAImportRow has no columns for them — see the comment where
            # they're written above) before storing `scores`: the "match" /
            # "create_school" actions later average every value in it, and a
            # a raw name string there would TypeError.
            row_scores = dict(r.scores or {})
            school_name_raw = row_scores.pop("_school_name_raw", None)
            district_raw = row_scores.pop("_district_raw", None)
            suggested_id, confidence = unmatched_service.compute_suggested_match(
                school_name_raw, district_raw
            )
            unmatched_records.append(
                UnmatchedSSARecord(
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
            )

        if records:
            SsaRecord.objects.bulk_create(records, batch_size=1000)
            SsaScore.objects.bulk_create(scores, batch_size=2000)
        if unmatched_records:
            UnmatchedSSARecord.objects.bulk_create(
                unmatched_records,
                batch_size=1000,
            )

        affected_schools = list(School.objects.filter(id__in=affected_school_pks))
        completed_school_ids = []
        full_quality_refresh = []
        for school in affected_schools:
            previous_status = school.current_fy_ssa_status
            states = current_states.get(school.id, set())
            if "confirmed" in states:
                school.current_fy_ssa_status = "done"
                completed_school_ids.append(school.id)
            elif "pending" in states:
                school.current_fy_ssa_status = "partner_assigned"
            elif school.current_fy_ssa_status in ("done", "partner_assigned"):
                school.current_fy_ssa_status = "not_done"
            if (
                previous_status != school.current_fy_ssa_status
                and school.current_fy_ssa_status != "done"
            ):
                full_quality_refresh.append(school)
            school.recompute_quality_and_readiness()
            school.updated_at = now
        if affected_schools:
            School.objects.bulk_update(
                affected_schools,
                [
                    "current_fy_ssa_status",
                    "planning_readiness",
                    "data_quality_score",
                    "data_quality_status",
                    "updated_at",
                ],
                batch_size=1000,
            )
            from apps.schools.models import DataQualityIssue

            if completed_school_ids:
                DataQualityIssue.objects.filter(
                    school_id__in=completed_school_ids,
                    status="open",
                    issue_type="no_ssa",
                ).delete()
            if full_quality_refresh:
                from apps.schools.upload_service import _bulk_refresh_quality_issues

                _bulk_refresh_quality_issues(full_quality_refresh)

        if records or unmatched_records:
            batch.status = "imported"
            batch.save(update_fields=["status", "updated_at"])

    return {
        "created": len(records),
        "unmatched": len(unmatched_records),
    }


__all__ = ["upload_ssa_file", "import_ssa_batch"]
