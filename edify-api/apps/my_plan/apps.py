from django.apps import AppConfig


class MyPlanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.my_plan"
    label = "my_plan"
    verbose_name = "Edify MyPlan"
