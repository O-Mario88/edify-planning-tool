from django.apps import AppConfig


class BusinessTransformationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business_transformation"
    label = "business_transformation"
    verbose_name = "Business Transformation"

    def ready(self):
        # Registration only: handlers and signals do not query the database at
        # import time. Durable events join the surrounding transaction, so the
        # source write and its follow-up either commit or roll back together.
        from . import handlers, signals  # noqa: F401
        from apps.core import reference_data

        from .reference import (
            business_transformation_reference_is_complete,
            ensure_business_transformation_reference,
        )

        reference_data.register(
            "business_transformation",
            ensure_business_transformation_reference,
            business_transformation_reference_is_complete,
        )
