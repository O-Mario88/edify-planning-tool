"""Publish a document into the Help Center — as a pointer, never a copy.

A published policy, manual or training resource has to be findable where people
look for help. What it must not become is a second, separately maintained copy
of its own text: two sources drift, and the one nobody updated is the one
somebody reads.

So the Help article carries the document's title, description and metadata, and
a single link into the viewer. The file itself stays in the Document Library,
behind the same permission checks. Superseding a version updates the article in
place, so Help always points at the current version and never at bytes that
have been replaced.
"""

from __future__ import annotations

from django.utils import timezone

from apps.audit.services import log as audit_log

HELP_CATEGORY_NAME = "Policies and Resources"

#: Document type → the wording the Help entry uses for its open action.
OPEN_LABELS = {
    "policy": "Read Policy in Detail",
    "manual": "Read Manual",
    "training_manual": "Open Training Resource",
    "training_presentation": "View Presentation",
}


def _category():
    from django.utils.text import slugify

    from apps.help_center.models import HelpCategory

    category, _ = HelpCategory.objects.get_or_create(
        slug=slugify(HELP_CATEGORY_NAME),
        defaults={
            "name": HELP_CATEGORY_NAME,
            "description": (
                "Organisational policies, manuals and approved training "
                "resources, published from the Document Library."
            ),
            "sort_order": 50,
        },
    )
    return category


def _audience_roles(document) -> list[str]:
    """The roles the document is for, so Help cannot widen its reach.

    A document whose audience is expressed only by country, partner or named
    user yields no role rows — Help then shows it to nobody by role, which is
    the safe direction to fail.
    """
    return sorted({rule.role for rule in document.audience_rules.all() if rule.role})


def sync_help_mapping(document):
    """Create or refresh the Help entry for a published document."""
    from apps.documents.models import READABLE_STATUSES
    from apps.help_center.models import (
        HelpArticle,
        HelpArticleRoleAccess,
        HelpArticleState,
    )

    if not document.help_visible or document.status not in READABLE_STATUSES:
        return None

    version = document.current_version
    if version is None:
        return None

    body = [
        {
            "heading": "What this is",
            "body": document.description,
        },
        {
            "heading": "Current version",
            "body": (
                f"Version {version.version_number}"
                + (
                    f", effective {version.effective_date:%d %B %Y}"
                    if version.effective_date
                    else ""
                )
                + (
                    f". Last reviewed {version.reviewed_at:%d %B %Y}."
                    if version.reviewed_at
                    else "."
                )
            ),
        },
        {
            "heading": OPEN_LABELS.get(document.document_type, "Open document"),
            # A link into the viewer, which re-checks permission and audience.
            # Never a storage URL.
            "body": f"/documents/{document.slug}/",
        },
    ]
    if document.is_mandatory:
        body.append(
            {
                "heading": "Acknowledgement",
                "body": (
                    document.acknowledgement_reason
                    or "This document requires your acknowledgement."
                ),
            }
        )

    article = document.help_article
    fields = {
        "title": document.title[:180],
        "summary": document.description[:2000],
        "content": body,
        "category": _category(),
        "keywords": list(document.help_keywords or []),
        "state": HelpArticleState.PUBLISHED,
        "published_at": timezone.now(),
        "last_reviewed_at": version.reviewed_at,
        "feature": "document_library",
        "workflow": document.document_type,
    }

    if article is None:
        from django.utils.text import slugify

        slug = f"doc-{slugify(document.title)[:160]}"
        suffix = 1
        while HelpArticle.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"doc-{slugify(document.title)[:150]}-{suffix}"
        article = HelpArticle.objects.create(slug=slug, **fields)
        document.help_article = article
        document.save(update_fields=["help_article", "updated_at"])
        created = True
    else:
        for key, value in fields.items():
            setattr(article, key, value)
        article.version = (article.version or 1) + 1
        article.save()
        created = False

    # Help visibility must never be wider than the document's own audience.
    roles = _audience_roles(document)
    HelpArticleRoleAccess.objects.filter(article=article).exclude(
        role__in=roles
    ).delete()
    for role in roles:
        HelpArticleRoleAccess.objects.get_or_create(article=article, role=role)

    audit_log(
        action="documents.help_mapping_created"
        if created
        else "documents.help_mapping_updated",
        subject_kind="document",
        subject_id=document.id,
        payload={"article": article.id, "roles": roles},
    )
    return article


def retire_help_mapping(document):
    """Take an archived document out of Help without deleting its history."""
    from apps.help_center.models import HelpArticleState

    article = document.help_article
    if article is None:
        return None
    article.state = HelpArticleState.ARCHIVED
    article.save(update_fields=["state", "updated_at"])
    return article
