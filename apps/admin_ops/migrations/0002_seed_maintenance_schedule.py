from datetime import date

from django.db import migrations


TEMPLATES = (
    (
        "Weekly backup verification",
        "backup",
        "Confirm the latest managed PostgreSQL backup is visible and recent.",
        7,
        date(2026, 9, 4),
        30,
        [
            "Open the managed database backup list",
            "Record the newest restore point",
            "Escalate any gap immediately",
        ],
    ),
    (
        "Quarterly production restore rehearsal",
        "preventive_maintenance",
        "Restore production into an isolated cluster, validate it, record evidence, then remove the rehearsal cluster.",
        90,
        date(2026, 11, 26),
        240,
        [
            "Restore to an isolated cluster",
            "Run migration and smoke validation",
            "Commit redacted evidence",
            "Delete the rehearsal cluster",
        ],
    ),
    (
        "Monthly dependency and container review",
        "preventive_maintenance",
        "Review dependency, CodeQL and production-container findings and patch supported fixes.",
        30,
        date(2026, 9, 28),
        90,
        [
            "Review dependency alerts",
            "Review container scan",
            "Open or apply supported upgrades",
        ],
    ),
    (
        "Quarterly access and incident-owner review",
        "security",
        "Verify privileged accounts, the configured incident owner and unresolved critical incidents.",
        90,
        date(2026, 11, 26),
        120,
        [
            "Review Admin accounts",
            "Verify incident owner",
            "Review unresolved critical incidents",
            "Record approvals and removals",
        ],
    ),
)


def seed(apps, schema_editor):
    template = apps.get_model("admin_ops", "MaintenanceTemplate")
    for name, category, description, days, due, minutes, steps in TEMPLATES:
        template.objects.get_or_create(
            name=name,
            defaults={
                "category": category,
                "description": description,
                "frequency_days": days,
                "next_due_date": due,
                "estimated_minutes": minutes,
                "steps": steps,
                "active": True,
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("admin_ops", "MaintenanceTemplate").objects.filter(
        name__in=[row[0] for row in TEMPLATES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("admin_ops", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
