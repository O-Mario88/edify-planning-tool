"""document_health() — System Health checks for the Document Library.

Wired into ``apps.system_health.services.report()`` as ``data["documents"]``.
Same check shape as the other health modules.

These watch for the ways a document ecosystem goes quietly wrong: a published
policy nobody is assigned to, a mandatory one with no wording to agree to, a
version whose preview never rendered, an acknowledgement pointing at bytes that
have been replaced, and a person who disagreed with nobody reviewing it.
"""

from __future__ import annotations

from django.utils import timezone

from apps.documents.models import (
    AcknowledgementState,
    CommentStatus,
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentComment,
    DocumentStatus,
    DocumentVersion,
    PreviewStatus,
    READABLE_STATUSES,
)


def _check(key, severity, component, current, expected, now, action, link) -> dict:
    return {
        "key": key,
        "severity": severity,
        "component": component,
        "current_state": current,
        "expected_state": expected,
        "last_check": now,
        "owner": "HR / Platform",
        "recommended_action": action,
        "resolution_link": link,
    }


def document_health() -> dict:
    now = timezone.now()
    return {
        "checks": [
            _published_without_audience(now),
            _published_without_owner(now),
            _mandatory_without_agreement_wording(now),
            _mandatory_without_effective_date(now),
            _published_without_preview(now),
            _mandatory_not_in_help(now),
            _superseded_shown_as_current(now),
            _overdue_acknowledgements(now),
            _disagreement_without_review(now),
            _comment_without_owner(now),
            _expired_still_readable(now),
        ]
    }


def _published_without_audience(now) -> dict:
    """The most dangerous shape: live, and reaching nobody."""
    count = sum(
        1
        for d in DocumentAsset.objects.filter(
            status__in=READABLE_STATUSES
        ).prefetch_related("audience_rules")
        if not d.audience_rules.exists()
    )
    return _check(
        "documents_published_without_audience",
        "critical" if count else "ok",
        "Document Audience",
        f"{count} published document(s) with no audience rule",
        "Every published document names who it is for",
        now,
        "Set an audience, or archive the document.",
        "/uploads?tab=documents",
    )


def _published_without_owner(now) -> dict:
    count = DocumentAsset.objects.filter(
        status__in=READABLE_STATUSES, owner_id__isnull=True
    ).count()
    return _check(
        "documents_published_without_owner",
        "warning" if count else "ok",
        "Document Ownership",
        f"{count} published document(s) with no owner",
        "Every published document has an accountable owner",
        now,
        "Assign an owner in the Upload Center.",
        "/uploads?tab=documents",
    )


def _mandatory_without_agreement_wording(now) -> dict:
    count = (
        DocumentAsset.objects.filter(
            status__in=READABLE_STATUSES, acknowledgement_required=True
        )
        .filter(agreement_statement="")
        .count()
    )
    return _check(
        "documents_mandatory_without_wording",
        "critical" if count else "ok",
        "Agreement Wording",
        f"{count} mandatory document(s) with nothing to agree to",
        "Every mandatory document states what the reader is agreeing to",
        now,
        "Add the agreement statement before it is put in front of anyone.",
        "/uploads?tab=documents",
    )


def _mandatory_without_effective_date(now) -> dict:
    count = DocumentVersion.objects.filter(
        document__acknowledgement_required=True,
        document__status__in=READABLE_STATUSES,
        published_at__isnull=False,
        effective_date__isnull=True,
    ).count()
    return _check(
        "documents_mandatory_without_effective_date",
        "warning" if count else "ok",
        "Effective Dates",
        f"{count} published mandatory version(s) with no effective date",
        "Every mandatory version says when it takes effect",
        now,
        "Set the effective date on the version.",
        "/uploads?tab=documents",
    )


def _published_without_preview(now) -> dict:
    count = DocumentVersion.objects.filter(
        published_at__isnull=False,
        superseded_at__isnull=True,
        preview_status__in=[PreviewStatus.FAILED, PreviewStatus.PENDING],
    ).count()
    return _check(
        "documents_published_without_preview",
        "warning" if count else "ok",
        "Preview Pipeline",
        f"{count} live version(s) with no in-app preview",
        "Every live document can be opened inside Edify",
        now,
        "The daily job retries these; a persistent failure needs the converter "
        "checking on the host.",
        "/system-health",
    )


def _mandatory_not_in_help(now) -> dict:
    count = DocumentAsset.objects.filter(
        status__in=READABLE_STATUSES,
        acknowledgement_required=True,
        help_visible=True,
        help_article__isnull=True,
    ).count()
    return _check(
        "documents_mandatory_not_in_help",
        "warning" if count else "ok",
        "Help Center Mapping",
        f"{count} mandatory document(s) missing their Help entry",
        "Published documents are findable in the Help Center",
        now,
        "Re-publish the document to rebuild its Help mapping.",
        "/help",
    )


def _superseded_shown_as_current(now) -> dict:
    """A pointer at replaced bytes — the failure that makes a library lie."""
    count = DocumentAsset.objects.filter(
        current_version__superseded_at__isnull=False
    ).count()
    return _check(
        "documents_superseded_shown_as_current",
        "critical" if count else "ok",
        "Version Pointer",
        f"{count} document(s) whose current version is superseded",
        "The current version is always the live one",
        now,
        "Re-publish the intended version.",
        "/uploads?tab=documents",
    )


def _overdue_acknowledgements(now) -> dict:
    count = DocumentAcknowledgement.objects.filter(
        state=AcknowledgementState.PENDING, due_date__lt=now.date()
    ).count()
    return _check(
        "documents_overdue_acknowledgements",
        "warning" if count else "ok",
        "Policy Acknowledgement",
        f"{count} acknowledgement(s) past their due date",
        "Everyone answers within the configured window",
        now,
        "Review the compliance report and chase the outstanding people.",
        "/policy-compliance?state=pending",
    )


def _disagreement_without_review(now) -> dict:
    """Somebody said no, and nobody has picked it up."""
    disagreed = DocumentAcknowledgement.objects.filter(
        state=AcknowledgementState.DISAGREED
    ).values_list("id", flat=True)
    reviewed = DocumentComment.objects.filter(
        acknowledgement_id__in=disagreed,
        status__in=[CommentStatus.RESPONDED, CommentStatus.RESOLVED],
    ).values_list("acknowledgement_id", flat=True)
    count = len(set(disagreed) - set(reviewed))
    return _check(
        "documents_disagreement_without_review",
        "warning" if count else "ok",
        "Disagreement Review",
        f"{count} disagreement(s) with no HR response",
        "Every disagreement reaches a person",
        now,
        "Open the comment queue and respond.",
        "/policy-compliance",
    )


def _comment_without_owner(now) -> dict:
    count = DocumentComment.objects.filter(
        status=CommentStatus.NEW, owner_id__isnull=True
    ).count()
    return _check(
        "documents_comment_without_owner",
        "warning" if count else "ok",
        "Comment Ownership",
        f"{count} policy comment(s) with no owner",
        "Every comment has somebody accountable for answering it",
        now,
        "Assign an owner in the comment queue.",
        "/policy-compliance",
    )


def _expired_still_readable(now) -> dict:
    count = DocumentAsset.objects.filter(
        status__in=READABLE_STATUSES,
        current_version__expiry_date__lt=now.date(),
    ).count()
    return _check(
        "documents_expired_still_readable",
        "warning" if count else "ok",
        "Document Expiry",
        f"{count} expired document(s) still shown as current",
        "An expired document is withdrawn or re-published",
        now,
        "Publish a new version, or archive the document.",
        "/uploads?tab=documents",
    )


__all__ = ["document_health", "DocumentStatus"]
