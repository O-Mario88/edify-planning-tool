from django.apps import AppConfig


class ActivitiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.activities"
    label = "activities"
    verbose_name = "Edify Activities"

    def ready(self):
        # Every move of a plan's day, recorded as it is saved.
        from . import schedule_trail  # noqa: F401

        # Every change of the plan, told to the pages that show it.
        from . import live

        live.connect()
