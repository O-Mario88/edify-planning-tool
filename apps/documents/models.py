"""The Document Library — organisational policies, manuals and training resources.

This is the one file category Edify had no home for. School and SSA imports have
``SchoolImportBatch`` / ``SSAImportBatch``; activity evidence has
``EvidenceRecord``; PD certificates have ``ProfessionalDevelopmentCertificate``.
Policies, manuals and training resources had nothing, so they are what these
models carry — and *only* what they carry. The Upload Center indexes the other
four through adapters that read their authoritative records; nothing is copied
here to make it appear in a list.

Five models, not nine. Three of the pieces the specification names separately
are one-to-one with a record that already exists, and a table per concept would
buy nothing but joins:

* the **acknowledgement rule** is per-asset configuration, so it lives on
  ``DocumentAsset``;
* the **review decision** is per-version and single-valued, so it lives on
  ``DocumentVersion``;
* the **Help mapping** is one article per asset, so it is a foreign key.

Audience rules, acknowledgements, engagement sessions and comments are each
genuinely many-per-document and keep their own tables.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class DocumentType(models.TextChoices):
    POLICY = "policy", "Organisational Policy"
    MANUAL = "manual", "Organisational Manual"
    TRAINING_MANUAL = "training_manual", "Training Manual"
    TRAINING_PRESENTATION = "training_presentation", "Training Presentation"


#: Types that belong to the Training Resource Library rather than the
#: organisational document set. Used for routing, audience defaults and the
#: Upload Center's tabs.
TRAINING_TYPES = frozenset(
    {DocumentType.TRAINING_MANUAL, DocumentType.TRAINING_PRESENTATION}
)


class DocumentStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under Review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"
    EFFECTIVE = "effective", "Effective"
    SUPERSEDED = "superseded", "Superseded"
    ARCHIVED = "archived", "Archived"
    # Exception states.
    RETURNED = "returned", "Returned for Correction"
    BLOCKED = "blocked", "Publication Blocked"
    EXPIRED = "expired", "Expired"


#: A reader may only see an asset in these states.
READABLE_STATUSES = frozenset({DocumentStatus.PUBLISHED, DocumentStatus.EFFECTIVE})


class PreviewStatus(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not Required"
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"
    NOT_SUPPORTED = "not_supported", "Preview Unavailable"


class Confidentiality(models.TextChoices):
    INTERNAL = "internal", "Public within Edify"
    ROLE_RESTRICTED = "role_restricted", "Role Restricted"
    COUNTRY_RESTRICTED = "country_restricted", "Country Restricted"
    TEAM_RESTRICTED = "team_restricted", "Team Restricted"
    PARTNER_RESTRICTED = "partner_restricted", "Partner Restricted"
    CONFIDENTIAL = "confidential", "Confidential"
    HIGHLY_RESTRICTED = "highly_restricted", "Highly Restricted"


class AcknowledgementChoice(models.TextChoices):
    AGREE = "agree", "I Agree"
    DISAGREE = "disagree", "I Disagree"


class AcknowledgementState(models.TextChoices):
    PENDING = "pending", "Pending"
    AGREED = "agreed", "Agreed"
    DISAGREED = "disagreed", "Disagreed"
    SUPERSEDED = "superseded", "Superseded"


class CommentStatus(models.TextChoices):
    NEW = "new", "New"
    UNDER_REVIEW = "under_review", "Under Review"
    RESPONSE_REQUIRED = "response_required", "Response Required"
    RESPONDED = "responded", "Responded"
    RESOLVED = "resolved", "Resolved"
    ARCHIVED = "archived", "Archived"


class DocumentAsset(TimeStampedModel):
    """One organisational document, across all its versions."""

    id = CuidField()
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(
        help_text="Shown in the Help Center and on the agreement page."
    )
    document_type = models.CharField(max_length=32, choices=DocumentType.choices)
    category = models.CharField(max_length=96, blank=True, default="")

    owner_id = models.CharField(max_length=30, null=True, blank=True, db_index=True)
    country = models.CharField(max_length=96, blank=True, default="")
    confidentiality = models.CharField(
        max_length=32,
        choices=Confidentiality.choices,
        default=Confidentiality.ROLE_RESTRICTED,
    )

    status = models.CharField(
        max_length=24,
        choices=DocumentStatus.choices,
        default=DocumentStatus.DRAFT,
        db_index=True,
    )
    current_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for",
    )

    # ── Acknowledgement configuration (the "rule", inlined) ──────────────────
    acknowledgement_required = models.BooleanField(default=False)
    agreement_required = models.BooleanField(default=False)
    comment_required = models.BooleanField(default=False)
    agreement_statement = models.TextField(blank=True, default="")
    acknowledgement_reason = models.CharField(max_length=512, blank=True, default="")
    # Withholding the application until the policy is accepted is a serious
    # step, so it is opt-in per document rather than implied by "mandatory".
    blocks_application_access = models.BooleanField(default=False)
    require_reacknowledgement_on_new_version = models.BooleanField(default=True)
    acknowledgement_due_days = models.PositiveIntegerField(null=True, blank=True)

    # ── Delivery permissions ─────────────────────────────────────────────────
    download_allowed = models.BooleanField(default=True)
    print_allowed = models.BooleanField(default=True)

    # ── Help Center (one article per asset, so a FK rather than a table) ─────
    help_visible = models.BooleanField(default=True)
    help_category = models.CharField(max_length=96, blank=True, default="")
    help_keywords = models.JSONField(default=list, blank=True)
    help_article = models.ForeignKey(
        "help_center.HelpArticle",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="document_assets",
    )

    created_by = models.CharField(max_length=30, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document_asset"
        ordering = ["title"]
        indexes = [
            models.Index(fields=["document_type", "status"]),
            models.Index(fields=["acknowledgement_required", "status"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_training_resource(self) -> bool:
        return self.document_type in TRAINING_TYPES

    @property
    def is_mandatory(self) -> bool:
        """Mandatory means the reader must answer, not merely that it exists."""
        return self.acknowledgement_required or self.agreement_required


class DocumentVersion(TimeStampedModel):
    """One immutable published revision of a document.

    A published version is never edited: a correction is a new version. That is
    what makes an acknowledgement meaningful — it points at exactly the bytes
    the person agreed to.
    """

    id = CuidField()
    document = models.ForeignKey(
        DocumentAsset, on_delete=models.CASCADE, related_name="versions"
    )
    version_number = models.PositiveIntegerField()

    # Stored name inside the document store, never a public URL.
    uri = models.CharField(max_length=512)
    original_filename = models.CharField(max_length=512)
    mime_type = models.CharField(max_length=128, blank=True, default="")
    file_extension = models.CharField(max_length=16, blank=True, default="")
    file_size = models.BigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default="")

    effective_date = models.DateField(null=True, blank=True)
    review_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    change_summary = models.TextField(blank=True, default="")
    # Whether the change is big enough to require people to read it again.
    material_change = models.BooleanField(default=True)

    uploaded_by = models.CharField(max_length=30, null=True, blank=True)

    # ── Review decision (single-valued per version, so inlined) ──────────────
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_decision = models.CharField(max_length=24, blank=True, default="")
    review_note = models.CharField(max_length=512, blank=True, default="")

    published_by = models.CharField(max_length=30, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    # ── Preview pipeline ─────────────────────────────────────────────────────
    preview_status = models.CharField(
        max_length=24, choices=PreviewStatus.choices, default=PreviewStatus.PENDING
    )
    preview_uri = models.CharField(max_length=512, blank=True, default="")
    preview_error = models.CharField(max_length=512, blank=True, default="")
    preview_generated_at = models.DateTimeField(null=True, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)

    # clean | infected | skipped | pending. "skipped" is the honest state when
    # no scanner is configured -- never relabelled as clean.
    scan_status = models.CharField(max_length=16, default="pending")
    scan_detail = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "document_version"
        ordering = ["-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "version_number"],
                name="uniq_document_version_number",
            )
        ]

    def __str__(self) -> str:
        return f"{self.document.title} v{self.version_number}"

    @property
    def is_published(self) -> bool:
        return self.published_at is not None and self.superseded_at is None


class DocumentAudienceRule(TimeStampedModel):
    """Who a document is for. Several rules union together.

    An empty rule set means nobody, not everybody — a published document with
    no audience is a System Health defect, never an accidental broadcast.
    """

    id = CuidField()
    document = models.ForeignKey(
        DocumentAsset, on_delete=models.CASCADE, related_name="audience_rules"
    )
    role = models.CharField(max_length=64, blank=True, default="")
    country = models.CharField(max_length=96, blank=True, default="")
    region_id = models.CharField(max_length=30, blank=True, default="")
    team_lead_staff_id = models.CharField(max_length=30, blank=True, default="")
    partner_id = models.CharField(max_length=30, blank=True, default="")
    project_id = models.CharField(max_length=30, blank=True, default="")
    user_id = models.CharField(max_length=30, blank=True, default="")
    effective_from = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "document_audience_rule"

    def __str__(self) -> str:
        parts = [
            f"{field}={value}"
            for field, value in (
                ("role", self.role),
                ("country", self.country),
                ("partner", self.partner_id),
                ("user", self.user_id),
            )
            if value
        ]
        return " ".join(parts) or "everyone"


class DocumentAcknowledgement(TimeStampedModel):
    """One person's answer to one exact version.

    Keyed on the version, never the document: that is what makes "they agreed"
    a statement about specific content rather than about a title.
    """

    id = CuidField()
    document = models.ForeignKey(
        DocumentAsset, on_delete=models.CASCADE, related_name="acknowledgements"
    )
    version = models.ForeignKey(
        DocumentVersion, on_delete=models.CASCADE, related_name="acknowledgements"
    )
    user_id = models.CharField(max_length=30, db_index=True)

    state = models.CharField(
        max_length=16,
        choices=AcknowledgementState.choices,
        default=AcknowledgementState.PENDING,
        db_index=True,
    )
    choice = models.CharField(
        max_length=16, choices=AcknowledgementChoice.choices, blank=True, default=""
    )
    statement = models.TextField(blank=True, default="")
    comment = models.TextField(blank=True, default="")
    responded_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    # Scope captured at the moment of answering: a person's role and country
    # change, and a compliance record has to say what was true at the time.
    role_at_acknowledgement = models.CharField(max_length=64, blank=True, default="")
    country_at_acknowledgement = models.CharField(max_length=96, blank=True, default="")

    # Engagement roll-up, for the reviewer's context. Never described as proof.
    active_reading_seconds = models.PositiveIntegerField(default=0)
    session_count = models.PositiveIntegerField(default=0)
    last_page_reached = models.PositiveIntegerField(null=True, blank=True)
    viewer_completed = models.BooleanField(default=False)
    download_initiated = models.BooleanField(default=False)
    print_initiated = models.BooleanField(default=False)
    # For readers who reviewed the document outside the viewer -- a screen
    # reader, a downloaded copy, a printed copy. Completion must not depend on
    # scrolling a mouse to the last page.
    offline_attestation = models.BooleanField(default=False)
    offline_attestation_note = models.CharField(max_length=512, blank=True, default="")

    typed_full_name = models.CharField(max_length=160, blank=True, default="")
    reminder_count = models.PositiveIntegerField(default=0)
    last_reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document_acknowledgement"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["version", "user_id"], name="uniq_ack_per_user_version"
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "state"]),
            models.Index(fields=["document", "state"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.document_id} v{self.version_id} · {self.state}"


class DocumentEngagementSession(TimeStampedModel):
    """One stretch of time a document was actually open and visible.

    Sessions are recorded rather than one running total so a reviewer can see
    *how* a document was read -- four short visits and one long one are
    different behaviours -- and so an abandoned tab cannot inflate the number.
    """

    id = CuidField()
    document = models.ForeignKey(
        DocumentAsset, on_delete=models.CASCADE, related_name="engagement_sessions"
    )
    version = models.ForeignKey(
        DocumentVersion, on_delete=models.CASCADE, related_name="engagement_sessions"
    )
    user_id = models.CharField(max_length=30, db_index=True)
    started_at = models.DateTimeField()
    last_heartbeat_at = models.DateTimeField()
    active_seconds = models.PositiveIntegerField(default=0)
    pages_viewed = models.JSONField(default=list, blank=True)
    last_page = models.PositiveIntegerField(null=True, blank=True)
    finalised = models.BooleanField(default=False)

    class Meta:
        db_table = "document_engagement_session"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["user_id", "version"])]


class DocumentComment(TimeStampedModel):
    """A private note attached to an acknowledgement.

    Private by construction: it is routed to HR and the Country Director and is
    never a discussion thread other readers can see.
    """

    id = CuidField()
    document = models.ForeignKey(
        DocumentAsset, on_delete=models.CASCADE, related_name="comments"
    )
    version = models.ForeignKey(
        DocumentVersion, on_delete=models.CASCADE, related_name="comments"
    )
    acknowledgement = models.ForeignKey(
        DocumentAcknowledgement,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="comment_records",
    )
    author_id = models.CharField(max_length=30, db_index=True)
    author_role = models.CharField(max_length=64, blank=True, default="")
    author_country = models.CharField(max_length=96, blank=True, default="")
    body = models.TextField()

    status = models.CharField(
        max_length=24,
        choices=CommentStatus.choices,
        default=CommentStatus.NEW,
        db_index=True,
    )
    owner_id = models.CharField(max_length=30, null=True, blank=True)
    response = models.TextField(blank=True, default="")
    responded_by = models.CharField(max_length=30, null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "document_comment"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "document"])]

    def __str__(self) -> str:
        return f"Comment by {self.author_id} on {self.document_id}"
