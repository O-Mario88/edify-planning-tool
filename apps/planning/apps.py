from django.apps import AppConfig


class PlanningConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.planning"
    label = "planning"
    verbose_name = "Edify Planning"

    def ready(self):
        from apps.core import reference_data

        from .reference import (
            ensure_planning_reference,
            planning_reference_is_complete,
        )

        reference_data.register(
            "planning",
            ensure_planning_reference,
            planning_reference_is_complete,
        )
