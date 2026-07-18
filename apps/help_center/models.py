"""Versioned, role-aware in-product documentation.

Published help is deliberately stored separately from code comments and old
documents.  Each version keeps the reviewed snapshot that users saw, while
route contexts make contextual help an explicit, auditable mapping.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import CuidField, TimeStampedModel
from apps.core.rbac import EdifyRole


ROLE_CHOICES = [(role.value, role.value) for role in EdifyRole]


class HelpArticleState(models.TextChoices):
    DRAFT = "draft", "Draft"
    TECHNICAL_REVIEW = "technical_review", "Technical review"
    PRODUCT_REVIEW = "product_review", "Product review"
    APPROVED = "approved", "Approved"
    PUBLISHED = "published", "Published"
    REVIEW_DUE = "review_due", "Review due"
    ARCHIVED = "archived", "Archived"


class HelpCategory(TimeStampedModel):
    id = CuidField()
    name = models.CharField(max_length=96, unique=True)
    slug = models.SlugField(max_length=96, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=32, blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Help categories"

    def __str__(self) -> str:
        return self.name


class HelpArticle(TimeStampedModel):
    """The current working copy; immutable publication snapshots live below."""

    id = CuidField()
    title = models.CharField(max_length=180)
    slug = models.SlugField(max_length=180, unique=True)
    summary = models.TextField()
    # Structured, plain-language sections.  Keeping this JSON makes rendered
    # headings, print exports and context panels consume the same source.
    content = models.JSONField(default=list)
    search_document = models.TextField(blank=True)
    category = models.ForeignKey(
        HelpCategory, on_delete=models.PROTECT, related_name="articles"
    )
    feature = models.CharField(max_length=96, blank=True)
    workflow = models.CharField(max_length=96, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    source_paths = models.JSONField(default=list, blank=True)
    state = models.CharField(
        max_length=32, choices=HelpArticleState.choices, default=HelpArticleState.DRAFT
    )
    version = models.PositiveIntegerField(default=1)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="help_articles_authored",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="help_articles_reviewed",
    )
    # Bootstrap content is independently reviewed against canonical services
    # before shipment and may predate an account in a newly provisioned DB.
    reviewer_name = models.CharField(max_length=160, blank=True)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    review_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    related_articles = models.ManyToManyField("self", blank=True, symmetrical=False)
    estimated_reading_minutes = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["state", "category"]),
            models.Index(fields=["state", "slug"]),
            models.Index(fields=["feature"]),
            models.Index(fields=["workflow"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_published(self) -> bool:
        return self.state in {HelpArticleState.PUBLISHED, HelpArticleState.REVIEW_DUE}

    def clean(self):
        if self.is_published:
            missing = []
            if not self.category_id:
                missing.append("category")
            if not self.last_reviewed_at:
                missing.append("last reviewed date")
            if not (self.reviewer_id or self.reviewer_name):
                missing.append("reviewer")
            if missing:
                raise ValidationError(
                    "Published documentation requires " + ", ".join(missing) + "."
                )

    def rebuild_search_document(self, *, save: bool = True) -> str:
        fragments = [self.title, self.summary, self.feature, self.workflow]
        fragments.extend(self.keywords or [])
        for section in self.content or []:
            fragments.extend([section.get("heading", ""), section.get("body", "")])
            fragments.extend(section.get("items", []) or [])
        self.search_document = "\n".join(str(part) for part in fragments if part)
        if save and self.pk:
            type(self).objects.filter(pk=self.pk).update(search_document=self.search_document)
        return self.search_document


class HelpArticleVersion(TimeStampedModel):
    id = CuidField()
    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="versions"
    )
    version = models.PositiveIntegerField()
    state = models.CharField(max_length=32, choices=HelpArticleState.choices)
    snapshot = models.JSONField(default=dict)
    change_summary = models.CharField(max_length=512, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="help_article_versions_authored",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="help_article_versions_reviewed",
    )
    reviewer_name = models.CharField(max_length=160, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "version"], name="unique_help_article_version"
            )
        ]


class HelpArticleRoleAccess(TimeStampedModel):
    id = CuidField()
    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="role_accesses"
    )
    role = models.CharField(max_length=64, choices=ROLE_CHOICES)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["article", "role"], name="unique_help_article_role"
            )
        ]


class HelpArticleRouteContext(TimeStampedModel):
    id = CuidField()
    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="route_contexts"
    )
    route_pattern = models.CharField(max_length=255, db_index=True)
    route_name = models.CharField(max_length=128, blank=True)
    workflow_status = models.CharField(max_length=96, blank=True)
    priority = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["priority", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "route_pattern", "workflow_status"],
                name="unique_help_route_context",
            )
        ]


class HelpArticleFeedback(TimeStampedModel):
    id = CuidField()
    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="feedback"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    user_role = models.CharField(max_length=64, blank=True)
    page_context = models.CharField(max_length=255, blank=True)
    helpful = models.BooleanField(null=True, blank=True)
    feedback_type = models.CharField(
        max_length=32,
        choices=[
            ("helpful", "Helpful"),
            ("outdated", "Report outdated information"),
            ("missing", "Report missing instructions"),
        ],
        default="helpful",
    )
    comment = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_help_feedback",
    )


class HelpSearchKeyword(TimeStampedModel):
    id = CuidField()
    article = models.ForeignKey(
        HelpArticle, on_delete=models.CASCADE, related_name="search_keywords"
    )
    term = models.CharField(max_length=120)
    synonym_for = models.CharField(max_length=120, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["article", "term"], name="unique_help_search_keyword"
            )
        ]
        indexes = [models.Index(fields=["term"])]


class HelpReleaseNote(TimeStampedModel):
    id = CuidField()
    title = models.CharField(max_length=180)
    version_label = models.CharField(max_length=48)
    summary = models.TextField()
    published_at = models.DateTimeField(default=timezone.now)
    related_articles = models.ManyToManyField(HelpArticle, blank=True)

    class Meta:
        ordering = ["-published_at"]


class HelpGlossaryTerm(TimeStampedModel):
    id = CuidField()
    term = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    definition = models.TextField()
    used_in = models.CharField(max_length=255, blank=True)
    related_terms = models.JSONField(default=list, blank=True)
    article = models.ForeignKey(
        HelpArticle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="glossary_terms",
    )

    class Meta:
        ordering = ["term"]


class HelpWalkthrough(TimeStampedModel):
    """Optional non-blocking tour mapped only to a working, named route."""

    id = CuidField()
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    article = models.ForeignKey(HelpArticle, on_delete=models.CASCADE, related_name="walkthroughs")
    route_pattern = models.CharField(max_length=255)
    steps = models.JSONField(default=list)
    roles = models.JSONField(default=list)
    active = models.BooleanField(default=True)


def article_snapshot(article: HelpArticle) -> dict:
    return {
        "title": article.title,
        "slug": article.slug,
        "summary": article.summary,
        "content": article.content,
        "keywords": article.keywords,
        "source_paths": article.source_paths,
        "category": article.category.slug if article.category_id else "",
        "feature": article.feature,
        "workflow": article.workflow,
        "state": article.state,
        "version": article.version,
        "reviewed_at": article.last_reviewed_at.isoformat() if article.last_reviewed_at else None,
    }
