from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class SystemHealthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.system_health"
    label = "system_health"
    verbose_name = "Edify SystemHealth"

    def ready(self):
        # Database environment-stamp guard: refuse to run a production
        # process against a local-stamped database (restored dev dump) or a
        # local process against a production-stamped database (mispointed
        # DATABASE_URL). See apps/system_health/environment_guard.py.
        from apps.system_health.environment_guard import (
            EnvironmentMismatch,
            validate_environment,
        )

        try:
            validate_environment()
        except EnvironmentMismatch as exc:
            raise ImproperlyConfigured(str(exc)) from exc
