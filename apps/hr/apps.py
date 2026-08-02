from django.apps import AppConfig


def ensure_priority_reference():
    """Restore the FY2027 strategic-priority cycle and its milestone rules.

    Registered as reference data rather than left to `hr.0009`, because those
    rules are resolved against the Activity Catalogue by stable code. Catalogue
    seeding moved to `post_migrate` (a data migration cannot select columns a
    later migration adds), so at migration time the catalogue is still empty:
    every rule lookup missed, no MilestoneActivityRule was written, and a
    verified Activity therefore earned no milestone credit. `apps.hr` is
    registered after `apps.activity_catalogue`, so running here guarantees the
    catalogue exists first — and it restores the rules after a flush as well.
    """
    from apps.hr.priority_seeding import seed_fy2027_priorities

    seed_fy2027_priorities(actor_id="reference_data")


def priority_reference_is_complete() -> bool:
    """Read-only counterpart to ``ensure_priority_reference``."""
    from apps.hr.models import StrategicPriority
    from apps.hr.priority_seed import PRIORITIES

    expected = {code for code, _title, _milestones in PRIORITIES}
    present = set(
        StrategicPriority.objects.filter(fy="2027", code__in=expected).values_list(
            "code", flat=True
        )
    )
    return present == expected


class HrConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hr"
    label = "hr"
    verbose_name = "Edify Hr"

    def ready(self):
        from apps.core import reference_data

        reference_data.register(
            "hr", ensure_priority_reference, priority_reference_is_complete
        )
