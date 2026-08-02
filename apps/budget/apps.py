from django.apps import AppConfig


class BudgetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.budget"
    label = "budget"
    verbose_name = "Edify Budget"

    def ready(self):
        """Register this app's reference data.

        One receiver in apps.core runs every registration on post_migrate,
        which Django emits after `flush` as well as after `migrate` — so rows a
        data migration created once come back when a TransactionTestCase
        truncates them. See apps/core/reference_data.py for why the wiring
        lives there rather than here.
        """
        from apps.core import reference_data

        from apps.budget.reference import (
            cost_reference_is_complete,
            ensure_cost_reference,
        )

        reference_data.register(
            "budget", ensure_cost_reference, cost_reference_is_complete
        )
