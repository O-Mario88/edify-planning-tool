from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Edify Notifications"

    def ready(self):
        # Registration only: importing the module binds the outbox handler
        # and the post-save hook, and touches no database.
        from . import push  # noqa: F401
