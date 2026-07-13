"""
Abstract model bases shared by every domain app.

Mirrors the legacy Prisma conventions:
- `id String @id @default(cuid())` → CUID PK (CuidModel).
- `createdAt`/`updatedAt` everywhere → TimeStampedModel.
- `deletedAt` soft-delete on the operational tables → SoftDeleteModel.
- Many tables also keep a soft-delete manager that auto-excludes tombstoned rows.

Prisma applied `deletedAt` filters manually in queries (no middleware). We
replicate that with a default manager that hides soft-deleted rows, plus a
`all_objects` (include-deleted) manager for audit/admin/cron that needs them.
"""

from __future__ import annotations

from django.db import models

from .cuid import cuid


class CuidField(models.CharField):
    """A primary-key field defaulting to a fresh CUID — the `@default(cuid())`
    semantics. Max length 30 matches the legacy schema's `String` ids."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 30)
        kwargs.setdefault("primary_key", True)
        kwargs.setdefault("default", cuid)
        super().__init__(*args, **kwargs)


class TimeStampedModel(models.Model):
    """`createdAt` + `updatedAt` on every table (Prisma convention)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DataSource(models.TextChoices):
    """Provenance for an operational record — how it entered the database.
    Used for audit + cleanup (purge_local_test_data targets source=local_test_upload)."""

    MANUAL_UPLOAD = "manual_upload", "Manual Upload"
    ADMIN_CREATED = "admin_created", "Admin Created"
    API_IMPORT = "api_import", "API Import"
    LOCAL_TEST_UPLOAD = "local_test_upload", "Local Test Upload"
    PRODUCTION_UPLOAD = "production_upload", "Production Upload"


class DataEnvironment(models.TextChoices):
    LOCAL = "local", "Local"
    STAGING = "staging", "Staging"
    PRODUCTION = "production", "Production"


class SourcedModel(TimeStampedModel):
    """Operational records carry provenance: how + where they were created. This
    lets `purge_local_test_data` clean up local test records without touching
    production data, and lets audits distinguish real uploads from test data.

    Security note: source is for audit/cleanup only — NEVER the sole gate for
    authorization (the RBAC + scope layer is authoritative)."""

    source = models.CharField(
        max_length=32,
        choices=DataSource.choices,
        default=DataSource.MANUAL_UPLOAD,
        db_index=True,
    )
    environment = models.CharField(
        max_length=16,
        choices=DataEnvironment.choices,
        default=DataEnvironment.PRODUCTION,
        db_index=True,
    )

    class Meta:
        abstract = True


class SoftDeleteManager(models.Manager):
    """Default manager that excludes soft-deleted rows. Use
    `SoftDeleteManager(include_deleted=True)` (or the `all_objects` alias) for
    queries that must see tombstoned records (audit, admin, cron recompute)."""

    def __init__(self, *args, include_deleted: bool = False, **kwargs):
        self._include_deleted = include_deleted
        super().__init__(*args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        if self._include_deleted:
            return qs
        return qs.filter(deleted_at__isnull=True)


class SoftDeleteModel(SourcedModel):
    """Adds a nullable `deletedAt` + source/environment provenance. Tombstones
    are never hard-removed for the operational tables (schools, staff,
    activities, SSA, evidence, partners, projects, debriefs, …).
    Reference/lookup tables (geography, RBAC) don't use this."""

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Hides soft-deleted rows by default.
    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager(include_deleted=True)

    class Meta:
        abstract = True

    def soft_delete(self, using=None):
        """Tombstone the row without a hard DELETE."""
        from django.utils import timezone

        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at", "updated_at"])


__all__ = [
    "CuidField",
    "TimeStampedModel",
    "SourcedModel",
    "DataSource",
    "DataEnvironment",
    "SoftDeleteModel",
    "SoftDeleteManager",
]
