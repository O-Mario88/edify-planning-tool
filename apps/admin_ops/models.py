"""Platform-operations records: support tickets, incidents, admin work items.

These are deliberately NOT field activities. The Platform Operations doctrine
separates Admin's own work — maintenance, support, incidents, security,
features, releases — from the school-programme workflow. Admin work must never
require a school, an SSA intervention, a Salesforce ID, IA verification or an
ActivityBudgetLine, so forcing it through the Activity model would either
corrupt those chains or demand nullable-everything hacks. Three small models
carry the whole workflow instead, and everything else is reused: notifications
through apps.notifications, audit through apps.audit, To-Dos derived live.

The scheduled/unscheduled split IS the Planning/My Plan split:

    AdminOperationsWorkItem.scheduled_date is NULL   -> Admin Planning backlog
    AdminOperationsWorkItem.scheduled_date is set    -> Admin My Plan
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class TicketCategory(models.TextChoices):
    CANNOT_LOG_IN = "cannot_log_in", "Cannot Log In"
    FORGOT_PASSWORD = "forgot_password", "Forgot Password"
    ACCOUNT_LOCKED = "account_locked", "Account Locked"
    CANNOT_ACCESS_PAGE = "cannot_access_page", "Cannot Access Page"
    INCORRECT_PERMISSION = "incorrect_permission", "Incorrect Permission"
    MISSING_DATA = "missing_data", "Missing School / Activity / Budget"
    UPLOAD_PROBLEM = "upload_problem", "Upload Problem"
    DEAD_BUTTON = "dead_button", "Dead Button"
    BROKEN_LINK = "broken_link", "Broken Link"
    SLOW_PAGE = "slow_page", "Slow Page"
    FROZEN_SCREEN = "frozen_screen", "Frozen Screen"
    INCORRECT_DATA = "incorrect_data", "Incorrect Data or Status"
    NOTIFICATION_PROBLEM = "notification_problem", "Notification Problem"
    MESSAGE_PROBLEM = "message_problem", "Message Problem"
    OTHER = "other", "Other"


class TicketStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    TRIAGED = "triaged", "Triaged"
    MORE_INFO = "more_info", "More Information Required"
    PLANNED = "planned", "Planned"
    IN_PROGRESS = "in_progress", "In Progress"
    WAITING_ON_USER = "waiting_on_user", "Waiting on User"
    FIX_READY = "fix_ready", "Fix Ready"
    VERIFICATION = "verification", "Verification"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    DUPLICATE = "duplicate", "Duplicate"
    INVALID = "invalid", "Rejected as Invalid"
    CANCELLED = "cancelled", "Cancelled"
    REOPENED = "reopened", "Reopened"


class IncidentStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    MITIGATED = "mitigated", "Mitigated"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class Severity(models.TextChoices):
    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


class WorkItemCategory(models.TextChoices):
    SUPPORT = "support", "User Support"
    INCIDENT = "incident", "System Incident"
    SECURITY = "security", "Security"
    PREVENTIVE_MAINTENANCE = "preventive_maintenance", "Preventive Maintenance"
    CORRECTIVE_MAINTENANCE = "corrective_maintenance", "Corrective Maintenance"
    PERFORMANCE = "performance", "Performance"
    DATA_REPAIR = "data_repair", "Data Repair"
    CONFIGURATION = "configuration", "Configuration"
    INTEGRATION = "integration", "Integration"
    JOB_FAILURE = "job_failure", "Background Job"
    FRONTEND_DEFECT = "frontend_defect", "Frontend Defect"
    BACKEND_DEFECT = "backend_defect", "Backend Defect"
    ROUTE_DEFECT = "route_defect", "Route Defect"
    ACCESSIBILITY = "accessibility", "Accessibility"
    FEATURE = "feature", "Feature Development"
    RELEASE = "release", "Release / Deployment"
    MONITORING = "monitoring", "Post-Release Monitoring"
    BACKUP = "backup", "Backup and Restore"
    AUDIT_INTEGRITY = "audit_integrity", "Audit Integrity"


class WorkItemStatus(models.TextChoices):
    BACKLOG = "backlog", "Backlog"
    SCHEDULED = "scheduled", "Scheduled"
    IN_PROGRESS = "in_progress", "In Progress"
    WAITING = "waiting", "Waiting"
    MONITORING = "monitoring", "Monitoring"
    DONE = "done", "Done"
    CANCELLED = "cancelled", "Cancelled"


class SupportTicket(TimeStampedModel):
    """One user request for platform help, with its captured context.

    Context capture is deliberately limited: route, page, object reference,
    browser and request id — never passwords, tokens, form contents or private
    message text.
    """

    id = CuidField()
    reference = models.CharField(max_length=20, unique=True)  # e.g. TCK-000042
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32, choices=TicketCategory.choices, default=TicketCategory.OTHER
    )
    description = models.TextField(blank=True, default="")
    urgency = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.MEDIUM
    )
    status = models.CharField(
        max_length=24,
        choices=TicketStatus.choices,
        default=TicketStatus.SUBMITTED,
        db_index=True,
    )

    reporter_id = models.CharField(max_length=30, db_index=True)
    reporter_role = models.CharField(max_length=64, blank=True, default="")
    owner_id = models.CharField(max_length=30, null=True, blank=True)

    # Auto-captured support context.
    route = models.CharField(max_length=255, blank=True, default="")
    page_title = models.CharField(max_length=255, blank=True, default="")
    object_type = models.CharField(max_length=64, blank=True, default="")
    object_id = models.CharField(max_length=64, blank=True, default="")
    browser = models.CharField(max_length=255, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")

    resolution = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_support_ticket"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference}: {self.title}"


class SystemIncident(TimeStampedModel):
    """One unique platform defect, however many times it fires.

    ``signature`` is the dedupe key (environment + category + route +
    error signature). A repeat updates ``occurrence_count`` and
    ``last_detected_at``; a repeat after resolution reopens the incident —
    never a second row, so one recurring defect cannot flood the queue.
    """

    id = CuidField()
    reference = models.CharField(max_length=20, unique=True)  # e.g. INC-000007
    signature = models.CharField(max_length=64, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32,
        choices=WorkItemCategory.choices,
        default=WorkItemCategory.INCIDENT,
    )
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.HIGH
    )
    status = models.CharField(
        max_length=16,
        choices=IncidentStatus.choices,
        default=IncidentStatus.OPEN,
        db_index=True,
    )

    affected_route = models.CharField(max_length=255, blank=True, default="")
    affected_component = models.CharField(max_length=128, blank=True, default="")
    affected_roles = models.JSONField(default=list, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    # Bounded list of recent request ids / event samples for diagnosis.
    samples = models.JSONField(default=list, blank=True)

    occurrence_count = models.PositiveIntegerField(default=1)
    first_detected_at = models.DateTimeField()
    last_detected_at = models.DateTimeField()
    reopened_count = models.PositiveIntegerField(default=0)

    owner_id = models.CharField(max_length=30, null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_system_incident"
        ordering = ["-last_detected_at"]

    def __str__(self) -> str:
        return f"{self.reference}: {self.title}"


class AdminOperationsWorkItem(TimeStampedModel):
    """One unit of Admin platform work, scheduled or not.

    Unscheduled (``scheduled_date`` NULL) items are the Admin Planning backlog;
    scheduling one moves it into Admin My Plan. Critical work skips the backlog
    by being created already scheduled for today.
    """

    id = CuidField()
    reference = models.CharField(max_length=20, unique=True)  # e.g. OPS-000113
    title = models.CharField(max_length=255)
    category = models.CharField(
        max_length=32, choices=WorkItemCategory.choices, db_index=True
    )
    description = models.TextField(blank=True, default="")
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.MEDIUM
    )
    status = models.CharField(
        max_length=16,
        choices=WorkItemStatus.choices,
        default=WorkItemStatus.BACKLOG,
        db_index=True,
    )

    owner_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    due_date = models.DateField(null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True, db_index=True)
    next_action = models.CharField(max_length=128, blank=True, default="")
    resolution_criteria = models.TextField(blank=True, default="")
    verification_note = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    affected_module = models.CharField(max_length=128, blank=True, default="")
    affected_route = models.CharField(max_length=255, blank=True, default="")

    ticket = models.ForeignKey(
        SupportTicket,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_items",
    )
    incident = models.ForeignKey(
        SystemIncident,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_items",
    )

    class Meta:
        db_table = "admin_ops_work_item"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.reference}: {self.title}"


class MaintenanceTemplate(TimeStampedModel):
    """A recurring platform-maintenance definition.

    When ``next_due_date`` arrives, the maintenance job materialises one
    scheduled AdminOperationsWorkItem and advances the date by ``frequency_days``
    — so routine upkeep appears in Admin My Plan without anyone remembering it.
    """

    id = CuidField()
    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(
        max_length=32,
        choices=WorkItemCategory.choices,
        default=WorkItemCategory.PREVENTIVE_MAINTENANCE,
    )
    description = models.TextField(blank=True, default="")
    frequency_days = models.PositiveIntegerField()
    next_due_date = models.DateField(db_index=True)
    owner_id = models.CharField(max_length=30, null=True, blank=True)
    estimated_minutes = models.PositiveIntegerField(default=60)
    steps = models.JSONField(default=list, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_maintenance_template"
        ordering = ["next_due_date"]

    def __str__(self) -> str:
        return self.name
