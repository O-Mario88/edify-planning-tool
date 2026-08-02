from django.apps import AppConfig


def ensure_catalogue_reference():
    """Restore the governed source catalogue after a flush.

    The seeder is stable-code idempotent: it creates missing items, repairs
    source-owned metadata and mappings, and preserves governance-owned
    lifecycle (a retired item is never reactivated) — so a rerun never walks
    back an administrator's lifecycle decision.
    """
    from apps.activity_catalogue.project_seeding import (
        seed_known_project_activity_rules,
    )
    from apps.activity_catalogue.seeding import seed_activity_catalogue

    seed_activity_catalogue(actor_id="reference_data")
    seed_known_project_activity_rules(actor_id="reference_data")


def catalogue_reference_is_complete() -> bool:
    """Read-only counterpart to ``ensure_catalogue_reference``."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.activity_catalogue.seed_data import CATALOGUE_ITEMS

    expected = {row["stable_code"] for row in CATALOGUE_ITEMS}
    present = set(
        ActivityCatalogueItem.objects.filter(stable_code__in=expected).values_list(
            "stable_code", flat=True
        )
    )
    return present == expected


class ActivityCatalogueConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.activity_catalogue"
    verbose_name = "Activity Catalogue"

    def ready(self):
        from apps.core import reference_data

        reference_data.register(
            "activity_catalogue",
            ensure_catalogue_reference,
            catalogue_reference_is_complete,
        )
