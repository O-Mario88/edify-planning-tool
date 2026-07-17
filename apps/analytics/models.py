"""Persisted user-owned analytics presentation and delivery preferences."""

from django.conf import settings
from django.db import models

from apps.core.models import CuidField, TimeStampedModel


DEFAULT_ANALYTICS_CARDS = [
    "targets",
    "training",
    "reach",
    "ssa",
]


class AnalyticsDashboardPreference(TimeStampedModel):
    class Layout(models.TextChoices):
        GRID = "grid", "Standard grid"
        COMPACT = "compact", "Compact"

    id = CuidField()
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analytics_dashboard_preference",
    )
    visible_cards = models.JSONField(default=list)
    layout = models.CharField(
        max_length=16, choices=Layout.choices, default=Layout.GRID
    )

    class Meta:
        db_table = "analytics_dashboard_preference"


class AnalyticsReportSchedule(TimeStampedModel):
    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    class OutputFormat(models.TextChoices):
        CSV = "csv", "CSV"

    id = CuidField()
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analytics_report_schedule",
    )
    frequency = models.CharField(max_length=16, choices=Frequency.choices)
    output_format = models.CharField(
        max_length=8, choices=OutputFormat.choices, default=OutputFormat.CSV
    )
    categories = models.JSONField(default=list)
    is_active = models.BooleanField(default=True, db_index=True)
    next_run_at = models.DateTimeField(db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_delivered_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "analytics_report_schedule"
        indexes = [models.Index(fields=["is_active", "next_run_at"])]


__all__ = [
    "AnalyticsDashboardPreference",
    "AnalyticsReportSchedule",
    "DEFAULT_ANALYTICS_CARDS",
]
