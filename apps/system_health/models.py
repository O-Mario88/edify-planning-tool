from django.db import models


class EnvironmentStamp(models.Model):
    """Singleton identity card of THIS database.

    Written once at migrate time with the running process's ENVIRONMENT.
    The startup guard (environment_guard.validate_environment) compares the
    stamp against settings.ENVIRONMENT: a production server connected to a
    database stamped 'local' (restored dev dump) or a local process connected
    to a database stamped 'production' (mispointed DATABASE_URL) refuses to
    run. Re-stamping requires the explicit stamp_environment command with a
    typed confirmation phrase.

    seeded_demo_at records when demo/sample data was last seeded into this
    database — a non-null value on a production-stamped database is a
    critical System Health blocker.
    """

    SINGLETON_ID = 1
    ENVIRONMENTS = ("local", "staging", "production")

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_ID)
    environment = models.CharField(max_length=16, default="local")
    stamped_at = models.DateTimeField(auto_now_add=True)
    stamped_by = models.CharField(max_length=128, default="migration")
    seeded_demo_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "environment_stamp"

    def __str__(self) -> str:  # pragma: no cover
        return f"EnvironmentStamp({self.environment})"
