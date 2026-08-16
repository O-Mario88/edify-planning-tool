"""Validated IA upload pipeline for the governed country priority master."""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import zipfile
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.permissions import has_permission
from apps.core.rbac import Permission

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_IMPORT_ROWS = 5000
REQUIRED_HEADERS = {
    "priority_code",
    "priority_title",
    "milestone_code",
    "milestone_title",
    "allocation_method",
}
HEADER_ALIASES = {
    "priority_group": "group_title",
    "group": "group_title",
    "target": "target_value",
    "unit": "target_unit",
    "activity_code": "activity_codes",
}
TEMPLATE_HEADERS = [
    "group_code",
    "group_title",
    "priority_code",
    "priority_title",
    "milestone_code",
    "milestone_title",
    "target_value",
    "target_unit",
    "core_target",
    "client_target",
    "measurement_type",
    "metric_key",
    "allocation_method",
    "responsible_role",
    "needs_confirmation",
    "confirmation_note",
    "quality_gate",
    "counting_basis",
    "activity_codes",
]


def _actor_id(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def _assert_importer(principal) -> None:
    if not has_permission(principal, Permission.STRATEGIC_PRIORITIES_IMPORT.value):
        raise Forbidden(
            "Only Impact Assessment may import the country priority master."
        )


def _header(value) -> str:
    key = "_".join(str(value or "").strip().casefold().replace("-", " ").split())
    return HEADER_ALIASES.get(key, key)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_file(name: str, raw: bytes) -> tuple[list[str], list[tuple[int, dict]]]:
    if name.casefold().endswith((".xlsx", ".xlsm")):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                if (
                    len(members) > 2000
                    or sum(member.file_size for member in members)
                    > MAX_XLSX_UNCOMPRESSED_BYTES
                ):
                    raise BadRequest("The XLSX expands beyond the safe import limit.")
            import openpyxl

            workbook = openpyxl.load_workbook(
                io.BytesIO(raw), read_only=True, data_only=True
            )
            iterator = workbook.worksheets[0].iter_rows(values_only=True)
            headers = [_header(value) for value in next(iterator)]
            records = [
                (number, dict(zip(headers, (_cell(value) for value in values))))
                for number, values in enumerate(iterator, start=2)
                if any(_cell(value) for value in values)
            ]
            return headers, records
        except StopIteration:
            return [], []
        except BadRequest:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Priority XLSX parse failed", exc_info=exc)
            raise BadRequest(
                "The spreadsheet could not be read. Check that it opens and is not password-protected."
            ) from exc

    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise BadRequest("The CSV must be a valid UTF-8 comma-separated file.") from exc
    if not rows:
        return [], []
    headers = [_header(value) for value in rows[0]]
    records = [
        (number, dict(zip(headers, (_cell(value) for value in values))))
        for number, values in enumerate(rows[1:], start=2)
        if any(_cell(value) for value in values)
    ]
    return headers, records


def _decimal(value: str, field: str, errors: list[str]) -> Decimal | None:
    if not value:
        return None
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation:
        errors.append(f"{field} must be a number.")
        return None
    if parsed < 0:
        errors.append(f"{field} cannot be negative.")
    return parsed


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y"}


def stage_priority_file(*, file, fy: str, principal, country_id="Uganda"):
    """Parse once, persist every row, and return an idempotent staging batch."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.hr.models import (
        MilestoneAllocationMethod,
        MilestoneMeasurementType,
        MilestoneMetricDefinition,
        PriorityImportBatch,
        PriorityImportRow,
        PriorityImportRowStatus,
        PriorityImportStatus,
    )

    _assert_importer(principal)
    fy = (fy or "").strip()
    if not fy or len(fy) > 16:
        raise BadRequest("Choose a valid financial year.")
    name = (getattr(file, "name", "") or "priorities.csv")[:255]
    if getattr(file, "size", 0) > MAX_UPLOAD_BYTES:
        raise BadRequest("Priority uploads may not exceed 5 MB.")
    raw = file.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw:
        raise BadRequest("Choose a non-empty CSV or XLSX file.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BadRequest("Priority uploads may not exceed 5 MB.")
    if not name.casefold().endswith((".csv", ".xlsx", ".xlsm")):
        raise BadRequest("Upload a CSV or XLSX file.")

    digest = hashlib.sha256(raw).hexdigest()
    existing = PriorityImportBatch.objects.filter(
        fy=fy, country_id=country_id, file_sha256=digest
    ).first()
    if existing:
        return existing, False

    headers, source_rows = _parse_file(name, raw)
    missing = sorted(REQUIRED_HEADERS - set(headers))
    if missing:
        raise BadRequest("Missing required columns: " + ", ".join(missing) + ".")
    if not source_rows:
        raise BadRequest("The upload contains no priority rows.")
    if len(source_rows) > MAX_IMPORT_ROWS:
        raise BadRequest(
            f"A priority upload may contain at most {MAX_IMPORT_ROWS} rows."
        )

    metric_keys = {row.get("metric_key", "") for _, row in source_rows}
    known_metrics = set(
        MilestoneMetricDefinition.objects.filter(
            metric_key__in=metric_keys
        ).values_list("metric_key", flat=True)
    )
    activity_codes = {
        code.strip()
        for _, row in source_rows
        for code in row.get("activity_codes", "").replace(";", ",").split(",")
        if code.strip()
    }
    known_activities = set(
        ActivityCatalogueItem.objects.filter(
            stable_code__in=activity_codes
        ).values_list("stable_code", flat=True)
    )
    allowed_methods = set(MilestoneAllocationMethod.values)
    allowed_measurements = set(MilestoneMeasurementType.values)
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    staged = []

    for row_number, raw_row in source_rows:
        errors: list[str] = []
        for required in REQUIRED_HEADERS:
            if not raw_row.get(required, "").strip():
                errors.append(f"{required} is required.")
        method = raw_row.get("allocation_method", "").strip()
        measurement = raw_row.get("measurement_type", "count").strip() or "count"
        metric_key = raw_row.get("metric_key", "").strip()
        if method and method not in allowed_methods:
            errors.append("allocation_method is not recognized.")
        if measurement not in allowed_measurements:
            errors.append("measurement_type is not recognized.")
        if metric_key and metric_key not in known_metrics:
            errors.append(f"metric_key '{metric_key}' is not configured.")

        target = _decimal(raw_row.get("target_value", ""), "target_value", errors)
        core = _decimal(raw_row.get("core_target", ""), "core_target", errors)
        client = _decimal(raw_row.get("client_target", ""), "client_target", errors)
        if method == MilestoneAllocationMethod.FIELD_CASCADE and target is None:
            errors.append("field_cascade rows require target_value.")
        if target is not None and core is not None and core > target:
            errors.append("core_target cannot exceed target_value.")
        if target is not None and client is not None and client > target:
            errors.append("client_target cannot exceed target_value.")
        if (
            target is not None
            and core is not None
            and client is not None
            and core + client > target
        ):
            errors.append("core_target plus client_target cannot exceed target_value.")

        codes = [
            code.strip()
            for code in raw_row.get("activity_codes", "").replace(";", ",").split(",")
            if code.strip()
        ]
        unknown_codes = sorted(set(codes) - known_activities)
        if unknown_codes:
            errors.append("Unknown activity codes: " + ", ".join(unknown_codes) + ".")
        key = (
            raw_row.get("priority_code", "").strip().casefold(),
            raw_row.get("milestone_code", "").strip().casefold(),
        )
        duplicate = key in seen
        seen.add(key)
        if duplicate:
            duplicate_count += 1
            errors.append("Duplicate priority_code and milestone_code in this file.")

        needs_confirmation = _truthy(raw_row.get("needs_confirmation", ""))
        status = (
            PriorityImportRowStatus.BLOCKED
            if errors
            else (
                PriorityImportRowStatus.REVIEW
                if needs_confirmation
                else PriorityImportRowStatus.READY
            )
        )
        staged.append(
            PriorityImportRow(
                row_number=row_number,
                group_code=(
                    raw_row.get("group_code") or raw_row.get("priority_code", "")
                ).strip(),
                group_title=(
                    raw_row.get("group_title") or raw_row.get("priority_title", "")
                ).strip(),
                priority_code=raw_row.get("priority_code", "").strip(),
                priority_title=raw_row.get("priority_title", "").strip(),
                milestone_code=raw_row.get("milestone_code", "").strip(),
                milestone_title=raw_row.get("milestone_title", "").strip(),
                target_value=target,
                target_unit=raw_row.get("target_unit", "").strip(),
                core_target=core,
                client_target=client,
                measurement_type=measurement,
                metric_key=metric_key,
                allocation_method=method,
                responsible_role=raw_row.get("responsible_role", "").strip(),
                needs_confirmation=needs_confirmation,
                confirmation_note=raw_row.get("confirmation_note", "").strip(),
                quality_gate=raw_row.get("quality_gate", "").strip(),
                counting_basis=raw_row.get("counting_basis", "").strip(),
                activity_codes=codes,
                status=status,
                validation_errors=errors,
                raw_data=raw_row,
            )
        )

    invalid_count = sum(row.status == PriorityImportRowStatus.BLOCKED for row in staged)
    batch_status = (
        PriorityImportStatus.NEEDS_CORRECTION
        if invalid_count
        else PriorityImportStatus.VALIDATED
    )
    try:
        with transaction.atomic():
            batch = PriorityImportBatch.objects.create(
                fy=fy,
                country_id=country_id,
                original_file_name=name,
                file_sha256=digest,
                uploaded_by=_actor_id(principal),
                status=batch_status,
                total_rows=len(staged),
                valid_rows=len(staged) - invalid_count,
                invalid_rows=invalid_count,
                duplicate_rows=duplicate_count,
                validation_summary={
                    "ready": sum(
                        row.status == PriorityImportRowStatus.READY for row in staged
                    ),
                    "review": sum(
                        row.status == PriorityImportRowStatus.REVIEW for row in staged
                    ),
                    "blocked": invalid_count,
                },
            )
            for row in staged:
                row.batch = batch
            PriorityImportRow.objects.bulk_create(staged)
    except IntegrityError:
        return PriorityImportBatch.objects.get(
            fy=fy, country_id=country_id, file_sha256=digest
        ), False

    _audit("hr.priority_import_staged", batch, principal)
    return batch, True


@transaction.atomic
def commit_priority_batch(*, batch_id: str, principal):
    """Turn a clean staging batch into an inactive country draft master."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.hr.models import (
        MilestoneActivityRule,
        MilestoneDefinitionStatus,
        MilestoneMetricDefinition,
        MilestoneType,
        PriorityImportBatch,
        PriorityImportRow,
        PriorityImportRowStatus,
        PriorityImportStatus,
        PriorityMilestone,
        StrategicPriority,
        StrategicPriorityCycle,
        StrategicPriorityLevel,
        StrategicPriorityStatus,
    )

    _assert_importer(principal)
    batch = PriorityImportBatch.objects.select_for_update().get(id=batch_id)
    if batch.status == PriorityImportStatus.COMMITTED:
        return batch
    if batch.invalid_rows or batch.status != PriorityImportStatus.VALIDATED:
        raise BadRequest("Correct every blocked row before committing this upload.")
    rows = list(batch.rows.order_by("row_number"))
    published_codes = list(
        StrategicPriority.objects.filter(
            fy=batch.fy,
            country_id=batch.country_id,
            level=StrategicPriorityLevel.COUNTRY,
            code__in={row.priority_code for row in rows},
            status=StrategicPriorityStatus.PUBLISHED,
        ).values_list("code", flat=True)
    )
    if published_codes:
        raise ConflictError(
            "This upload includes already-published priorities: "
            + ", ".join(sorted(published_codes))
            + ". Archive or version them through the governed amendment flow first."
        )

    actor = _actor_id(principal)
    cycle, _ = StrategicPriorityCycle.objects.get_or_create(
        financial_year=batch.fy,
        defaults={
            "title": f"Uganda Master Priority Plan FY{batch.fy}",
            "scope_type": "country",
            "country_id": batch.country_id,
            "status": "draft",
            "created_by": actor,
            "updated_by": actor,
        },
    )
    metric_map = {
        metric.metric_key: metric
        for metric in MilestoneMetricDefinition.objects.filter(
            metric_key__in={row.metric_key for row in rows if row.metric_key}
        )
    }
    catalogue_map = {
        item.stable_code: item
        for item in ActivityCatalogueItem.objects.filter(
            stable_code__in={code for row in rows for code in row.activity_codes}
        )
    }
    priorities = {}
    for row in rows:
        priority = priorities.get(row.priority_code)
        if priority is None:
            parent = StrategicPriority.objects.filter(
                fy=batch.fy,
                level=StrategicPriorityLevel.REGIONAL,
                code=row.priority_code,
                status=StrategicPriorityStatus.PUBLISHED,
            ).first()
            priority, _ = StrategicPriority.objects.update_or_create(
                fy=batch.fy,
                level=StrategicPriorityLevel.COUNTRY,
                country_id=batch.country_id,
                code=row.priority_code,
                status=StrategicPriorityStatus.DRAFT,
                defaults={
                    "cycle": cycle,
                    "parent": parent,
                    "title": row.priority_title,
                    "source_title": row.group_title,
                    "source_document": batch.original_file_name,
                    "source_reference": f"Priority import {batch.id}",
                    "strategic_purpose": row.priority_title,
                    "sequence": len(priorities) + 1,
                    "author_id": actor,
                },
            )
            priorities[row.priority_code] = priority
        metric = metric_map.get(row.metric_key)
        milestone, _ = PriorityMilestone.objects.update_or_create(
            priority=priority,
            code=row.milestone_code,
            defaults={
                "title": row.milestone_title,
                "source_text": row.milestone_title,
                "milestone_type": MilestoneType.OUTPUT,
                "measurement_type": row.measurement_type,
                "progress_source": row.metric_key or "manual_assessment",
                "metric_definition": metric,
                "target_value": row.target_value,
                "target_unit": row.target_unit,
                "target_source_text": f"{batch.original_file_name}, row {row.row_number}",
                "core_target": row.core_target,
                "client_target": row.client_target,
                "allocation_method": row.allocation_method,
                "responsible_role": row.responsible_role,
                "needs_confirmation": row.needs_confirmation,
                "confirmation_note": row.confirmation_note,
                "quality_gate": row.quality_gate,
                "requires_definition": metric is None,
                "definition_status": (
                    MilestoneDefinitionStatus.DEFINED
                    if metric is not None
                    else MilestoneDefinitionStatus.NEEDS_DEFINITION
                ),
                "active": False,
                "source_order": row.row_number,
            },
        )
        for code in row.activity_codes:
            item = catalogue_map.get(code)
            if item:
                MilestoneActivityRule.objects.update_or_create(
                    milestone=milestone,
                    catalogue_item=item,
                    project=None,
                    defaults={
                        "counting_basis": row.counting_basis or "activity",
                        "active": True,
                    },
                )
        row.imported_milestone = milestone
        row.status = PriorityImportRowStatus.IMPORTED
        row.updated_at = timezone.now()

    PriorityImportRow.objects.bulk_update(
        rows, ["imported_milestone", "status", "updated_at"]
    )

    batch.status = PriorityImportStatus.COMMITTED
    batch.committed_at = timezone.now()
    batch.committed_by = actor
    batch.save(update_fields=["status", "committed_at", "committed_by", "updated_at"])
    _audit("hr.priority_import_committed", batch, principal)
    return batch


def csv_template() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerow(
        [
            "P1",
            "School growth",
            "P1",
            "Strengthen school growth",
            "P1-M1",
            "Complete verified school support visits",
            "120",
            "visits",
            "80",
            "40",
            "count",
            "verified_activity_catalogue_progress",
            "field_cascade",
            "CCEO",
            "no",
            "",
            "IA verified",
            "distinct_activity",
            "STANDARD_SCHOOL_VISIT",
        ]
    )
    return buffer.getvalue()


def _audit(action, batch, principal) -> None:
    try:
        from apps.audit.services import log

        log(
            action=action,
            subject_kind="PriorityImportBatch",
            subject_id=str(batch.id),
            actor_id=_actor_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"fy": batch.fy, "countryId": batch.country_id},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Priority import audit failed")
