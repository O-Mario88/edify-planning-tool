from django.apps import AppConfig


MAINTENANCE_TEMPLATES = (
    {
        "name": "Weekly backup verification",
        "category": "backup",
        "description": "Confirm the latest managed PostgreSQL backup is visible and recent.",
        "frequency_days": 7,
        "next_due_date": "2026-09-04",
        "estimated_minutes": 30,
        "steps": [
            "Open the managed database backup list",
            "Record the newest restore point",
            "Escalate any gap immediately",
        ],
    },
    {
        "name": "Quarterly production restore rehearsal",
        "category": "preventive_maintenance",
        "description": "Restore production into an isolated cluster, validate it, record evidence, then remove the rehearsal cluster.",
        "frequency_days": 90,
        "next_due_date": "2026-11-26",
        "estimated_minutes": 240,
        "steps": [
            "Restore to an isolated cluster",
            "Run migration and smoke validation",
            "Commit redacted evidence",
            "Delete the rehearsal cluster",
        ],
    },
    {
        "name": "Monthly dependency and container review",
        "category": "preventive_maintenance",
        "description": "Review dependency, CodeQL and production-container findings and patch supported fixes.",
        "frequency_days": 30,
        "next_due_date": "2026-09-28",
        "estimated_minutes": 90,
        "steps": [
            "Review dependency alerts",
            "Review container scan",
            "Open or apply supported upgrades",
        ],
    },
    {
        "name": "Quarterly access and incident-owner review",
        "category": "security",
        "description": "Verify privileged accounts, the configured incident owner and unresolved critical incidents.",
        "frequency_days": 90,
        "next_due_date": "2026-11-26",
        "estimated_minutes": 120,
        "steps": [
            "Review Admin accounts",
            "Verify incident owner",
            "Review unresolved critical incidents",
            "Record approvals and removals",
        ],
    },
)


def ensure_maintenance_reference():
    """Restore missing operational schedules without overwriting admin changes."""
    from apps.admin_ops.models import MaintenanceTemplate

    for row in MAINTENANCE_TEMPLATES:
        MaintenanceTemplate.objects.get_or_create(
            name=row["name"],
            defaults={key: value for key, value in row.items() if key != "name"},
        )


def maintenance_reference_is_complete() -> bool:
    """Return whether every mandatory operational schedule exists."""
    from apps.admin_ops.models import MaintenanceTemplate

    expected = {row["name"] for row in MAINTENANCE_TEMPLATES}
    present = set(
        MaintenanceTemplate.objects.filter(name__in=expected).values_list(
            "name", flat=True
        )
    )
    return present == expected


class AdminOpsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_ops"
    verbose_name = "Admin Platform Operations"

    def ready(self):
        from apps.core import reference_data

        reference_data.register(
            "admin_ops",
            ensure_maintenance_reference,
            maintenance_reference_is_complete,
        )
