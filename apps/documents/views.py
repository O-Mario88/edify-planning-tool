"""Upload Center, secure document viewer and Policy Agreement Center."""

from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import require_page_permission
from apps.documents.gate import PolicyGateService
from apps.documents.models import (
    AcknowledgementState,
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentType,
    DocumentVersion,
    PreviewStatus,
    READABLE_STATUSES,
)
from apps.documents.services import (
    AcknowledgementService,
    administers,
    CommentService,
    DocumentService,
    EngagementService,
    audience_matches,
    has_permission,
)
from apps.core.private_storage import file_exists, open_file
from apps.documents.storage import DOCUMENT_NAMESPACE
from apps.documents.upload_center import UploadCenterService


def _user_id(request) -> str:
    return getattr(request.user, "id", "") or ""


# ── Upload Center ────────────────────────────────────────────────────────────


@require_page_permission("uploads")
def upload_center_view(request):
    try:
        context = UploadCenterService.get(
            request.user,
            {
                "tab": request.GET.get("tab", "all"),
                "status": request.GET.get("status", ""),
                "type": request.GET.get("type", ""),
                "q": request.GET.get("q", ""),
                "page": request.GET.get("page", "1"),
            },
        )
    except Forbidden as exc:
        messages.error(request, str(exc))
        return redirect("/dashboard")

    context["can_create_document"] = has_permission(request.user, "documents.create")
    context["can_create_training"] = has_permission(
        request.user, "training_resources.create"
    )
    context["upload_actions"] = UploadCenterService.launch_actions(request.user)
    context["show_admin_upload_menu"] = request.user.active_role == "Admin"
    context["topbar_search"] = {
        "placeholder": "Search uploads…",
        "label": "Search uploads by title, context or uploader",
        "name": "q",
        "value": request.GET.get("q", ""),
    }
    if request.headers.get("HX-Request"):
        return render(request, "partials/documents/upload_table.html", context)
    return render(request, "pages/documents/upload_center.html", context)


# ── Document authoring ───────────────────────────────────────────────────────


@require_page_permission("uploads")
def new_document_view(request):
    is_training = request.GET.get("kind") == "training"
    permission = "training_resources.create" if is_training else "documents.create"
    if not has_permission(request.user, permission):
        messages.error(request, "You cannot create this kind of document.")
        return redirect("/uploads")

    if request.method == "GET":
        return render(
            request,
            "pages/documents/new_document.html",
            {
                "is_training": is_training,
                "document_types": [
                    (value, label)
                    for value, label in DocumentType.choices
                    if (value.startswith("training_") if is_training else True)
                    and (not value.startswith("training_") or is_training)
                ],
                "roles": _role_choices(),
            },
        )

    data = request.POST.dict()
    data["acknowledgement_required"] = "acknowledgement_required" in request.POST
    data["agreement_required"] = "agreement_required" in request.POST
    data["comment_required"] = "comment_required" in request.POST
    data["blocks_application_access"] = "blocks_application_access" in request.POST
    data["download_allowed"] = "download_allowed" in request.POST
    data["print_allowed"] = "print_allowed" in request.POST
    data["required_reading_minutes"] = request.POST.get("required_reading_minutes", "")
    data["help_keywords"] = [
        k.strip()
        for k in (request.POST.get("help_keywords") or "").split(",")
        if k.strip()
    ]
    try:
        document = DocumentService.create(request.user, data)
        DocumentService.set_audience(
            request.user,
            document,
            [{"role": role} for role in request.POST.getlist("target_roles")],
        )
        DocumentService.add_version(
            request.user, document, request.FILES.get("file"), data
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        # Back to this form's own route, written out, rather than echoing the
        # submitted URL back into a Location header. `kind` is the only state
        # the form carries in its query string, and it is already parsed.
        return redirect("/uploads/new?kind=training" if is_training else "/uploads/new")

    messages.success(
        request,
        f"“{document.title}” saved as a draft. Submit it for review when it is ready.",
    )
    return redirect(f"/documents/{document.slug}/manage")


def _role_choices():
    from apps.core.rbac import EdifyRole

    return [(r.value, r.value) for r in EdifyRole]


@require_page_permission("uploads")
def manage_document_view(request, slug):
    document = get_object_or_404(DocumentAsset, slug=slug)
    if not administers(request.user, document):
        raise Http404
    return render(
        request,
        "pages/documents/manage_document.html",
        {
            "document": document,
            "versions": list(document.versions.all()),
            "audience": list(document.audience_rules.all()),
            "can_review": has_permission(request.user, "documents.review"),
            "can_publish": has_permission(
                request.user,
                "training_resources.publish"
                if document.is_training_resource
                else "documents.publish",
            ),
            "acknowledgements": list(
                document.acknowledgements.select_related("version")[:100]
            ),
        },
    )


@require_POST
@require_page_permission("uploads")
def new_version_view(request, slug):
    """Upload a revision of an existing document.

    `DocumentService.add_version` existed and was correct, but its only caller
    was new-document creation — so there was no way to publish v2 of anything.
    Correcting a live safeguarding policy meant creating a whole new asset
    under a new slug, orphaning its audience rules, its Help article and its
    entire acknowledgement history (2026-08-20 HR audit, Critical).
    """
    document = get_object_or_404(DocumentAsset, slug=slug)
    if not administers(request.user, document):
        raise Http404
    data = {
        "effective_date": request.POST.get("effective_date") or None,
        "review_date": request.POST.get("review_date") or None,
        "expiry_date": request.POST.get("expiry_date") or None,
        "change_summary": request.POST.get("change_summary", ""),
        # A material change re-asks everyone; a typo fix should not. The
        # uploader states which this is, because only they know.
        "material_change": "material_change" in request.POST,
    }
    try:
        version = DocumentService.add_version(
            request.user, document, request.FILES.get("file"), data
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect(f"/documents/{slug}/manage")
    messages.success(
        request,
        f"Version {version.version_number} uploaded. Submit it for review when "
        f"it is ready — the published version stays live until this one is "
        f"published.",
    )
    return redirect(f"/documents/{slug}/manage")


@require_POST
@require_page_permission("uploads")
def document_action_view(request, slug, action):
    document = get_object_or_404(DocumentAsset, slug=slug)
    if not administers(request.user, document):
        raise Http404
    # Act on the version the reviewer actually read. `versions.first()` is the
    # highest-numbered row, so once revisions exist, approving the v2 on
    # screen would have approved whatever v3 was uploaded in the meantime.
    version_id = request.POST.get("version_id")
    if version_id:
        version = document.versions.filter(id=version_id).first()
    else:
        version = document.versions.filter(published_at__isnull=True).first()
    if version is None and action in ("approve", "return", "publish"):
        messages.error(request, "That version no longer exists.")
        return redirect(f"/documents/{slug}/manage")
    try:
        if action == "submit":
            DocumentService.submit_for_review(request.user, document)
            messages.success(request, "Submitted for review.")
        elif action == "approve":
            DocumentService.review(
                request.user, version, True, request.POST.get("note", "")
            )
            messages.success(request, "Approved — ready to publish.")
        elif action == "return":
            DocumentService.review(
                request.user, version, False, request.POST.get("note", "")
            )
            messages.success(request, "Returned for correction.")
        elif action == "publish":
            DocumentService.publish(request.user, version)
            messages.success(request, "Published.")
        elif action == "archive":
            DocumentService.archive(
                request.user, document, request.POST.get("note", "")
            )
            messages.success(request, "Archived.")
        else:
            messages.error(request, "Unknown action.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(f"/documents/{document.slug}/manage")


# ── Secure viewer ────────────────────────────────────────────────────────────


def _readable_or_404(request, slug) -> DocumentAsset:
    """A document the caller may actually open.

    Administrators see drafts; everyone else sees a published document only if
    they are in its audience. 404 rather than 403 on an audience miss: whether
    a confidential policy exists is itself information.
    """
    document = get_object_or_404(DocumentAsset, slug=slug)
    if administers(request.user, document):
        return document
    if document.status not in READABLE_STATUSES:
        raise Http404
    if not audience_matches(document, request.user):
        raise Http404
    return document


def document_viewer_view(request, slug):
    document = _readable_or_404(request, slug)
    version = document.current_version or document.versions.first()
    ack = None
    if document.is_mandatory and version:
        ack = document.acknowledgements.filter(
            version=version, user_id=_user_id(request)
        ).first()
    audit_log(
        action="documents.opened",
        subject_kind="document",
        subject_id=document.id,
        actor_id=_user_id(request),
        actor_role=getattr(request.user, "active_role", None),
        payload={"version": version.version_number if version else None},
    )
    from apps.documents.canonical_documents import context_for

    canonical = context_for(slug)
    if canonical:
        return render(
            request,
            "pages/documents/canonical_document.html",
            {
                "document": document,
                "version": version,
                "acknowledgement": ack,
                "canonical": canonical,
            },
        )
    return render(
        request,
        "pages/documents/viewer.html",
        {
            "document": document,
            "version": version,
            "acknowledgement": ack,
            "can_download": document.download_allowed,
            "can_print": document.print_allowed,
            "preview_ready": bool(
                version and version.preview_status == PreviewStatus.READY
            ),
        },
    )


def document_preview_view(request, slug):
    """Stream the PDF rendition. Never a storage URL."""
    document = _readable_or_404(request, slug)
    version = document.current_version or document.versions.first()
    if not version or version.preview_status != PreviewStatus.READY:
        raise Http404
    if not file_exists(DOCUMENT_NAMESPACE, version.preview_uri):
        raise Http404
    response = FileResponse(
        open_file(DOCUMENT_NAMESPACE, version.preview_uri),
        content_type="application/pdf",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


def document_download_view(request, slug):
    document = _readable_or_404(request, slug)
    if not document.download_allowed:
        raise Http404
    version = document.current_version or document.versions.first()
    if not version:
        raise Http404
    if not file_exists(DOCUMENT_NAMESPACE, version.uri):
        raise Http404
    audit_log(
        action="documents.download_initiated",
        subject_kind="document_version",
        subject_id=version.id,
        actor_id=_user_id(request),
        actor_role=getattr(request.user, "active_role", None),
    )
    _mark_delivery(document, version, request, "download")
    content_type = (
        version.mime_type or mimetypes.guess_type(version.original_filename)[0]
    )
    return FileResponse(
        open_file(DOCUMENT_NAMESPACE, version.uri),
        as_attachment=True,
        filename=version.original_filename,
        content_type=content_type or "application/octet-stream",
    )


@require_POST
def document_print_view(request, slug):
    """Record that printing was *started*.

    Deliberately not "printed": the platform cannot see a printer, and a record
    that claims otherwise is a record that will be believed.
    """
    document = _readable_or_404(request, slug)
    if not document.print_allowed:
        raise Http404
    version = document.current_version
    audit_log(
        action="documents.print_initiated",
        subject_kind="document_version",
        subject_id=version.id if version else None,
        actor_id=_user_id(request),
        actor_role=getattr(request.user, "active_role", None),
    )
    if version:
        _mark_delivery(document, version, request, "print")
    return JsonResponse({"recorded": "print_initiated"})


def _mark_delivery(document, version, request, kind: str) -> None:
    ack = document.acknowledgements.filter(
        version=version, user_id=_user_id(request)
    ).first()
    if not ack:
        return
    if kind == "download":
        ack.download_initiated = True
        ack.save(update_fields=["download_initiated", "updated_at"])
    else:
        ack.print_initiated = True
        ack.save(update_fields=["print_initiated", "updated_at"])


@require_POST
def engagement_heartbeat_view(request, version_id):
    """Record a bounded foreground/focused reading delta for this reader."""
    if not getattr(request.user, "is_authenticated", False):
        raise Http404
    try:
        page = int(request.POST.get("page") or 0) or None
    except ValueError:
        page = None
    try:
        active_delta = int(request.POST.get("active_delta_seconds") or 0)
    except ValueError:
        active_delta = 0
    try:
        version = DocumentVersion.objects.select_related("document").get(id=version_id)
    except DocumentVersion.DoesNotExist:
        raise Http404 from None
    if not administers(request.user, version.document) and (
        version.document.status not in READABLE_STATUSES
        or not audience_matches(version.document, request.user)
    ):
        raise Http404
    session = EngagementService.heartbeat(
        request.user, version_id, page, active_delta_seconds=active_delta
    )
    acknowledgement = version.document.acknowledgements.filter(
        version=version, user_id=_user_id(request)
    ).first()
    return JsonResponse(
        {
            "active_seconds": (
                acknowledgement.active_reading_seconds
                if acknowledgement
                else session.active_seconds
            ),
            "reading_completion": (
                acknowledgement.reading_completion_key if acknowledgement else ""
            ),
            "last_page": session.last_page,
        }
    )


# ── Policy Agreement Center ──────────────────────────────────────────────────


def agreement_center_view(request):
    if not getattr(request.user, "is_authenticated", False):
        return redirect("/login")
    from apps.documents.models import DocumentAcknowledgement

    pending = AcknowledgementService.pending_for(request.user)
    if pending:
        # The two onboarding commitments are read in sequence. Opening the
        # Agreement Center therefore opens the actual document, rather than
        # making a first-time user discover it behind a second button.
        priority = {"edify-safeguarding-policy": 0, "edify-apostles-creed": 1}
        canonical_pending = sorted(
            (ack for ack in pending if ack.document.slug in priority),
            key=lambda ack: priority[ack.document.slug],
        )
        if canonical_pending:
            return redirect(f"/documents/{canonical_pending[0].document.slug}/")
    done = list(
        DocumentAcknowledgement.objects.filter(
            user_id=_user_id(request),
            state__in=[AcknowledgementState.AGREED, AcknowledgementState.DISAGREED],
        ).select_related("document", "version")[:50]
    )
    return render(
        request,
        "pages/documents/agreement_center.html",
        {"pending": pending, "completed": done},
    )


def _next_blocking_destination(user) -> str:
    """The next required document, or the workspace when onboarding is done."""
    pending = PolicyGateService.blocking_acknowledgements(user)
    if not pending:
        return "/dashboard"
    priority = {"edify-safeguarding-policy": 0, "edify-apostles-creed": 1}
    canonical_pending = sorted(
        (ack for ack in pending if ack.document.slug in priority),
        key=lambda ack: priority[ack.document.slug],
    )
    if canonical_pending:
        return f"/documents/{canonical_pending[0].document.slug}/"
    return "/policy-agreement"


def restricted_view(request):
    """Where a person who disagreed lands until HR resolves it."""
    # As `agreement_center_view` does. Without it this answered 200 to an
    # anonymous caller — an empty page rather than a leak, but a signed-out
    # reader landing here saw "no outstanding policies" instead of the login
    # form, which reads as the gate having let them through.
    if not getattr(request.user, "is_authenticated", False):
        return redirect("/login")
    declined = PolicyGateService.disagreements(request.user)
    return render(
        request,
        "pages/documents/restricted.html",
        {
            "declined": declined,
            "pending": AcknowledgementService.pending_for(request.user),
        },
    )


@require_POST
def submit_acknowledgement_view(request, acknowledgement_id):
    try:
        ack = AcknowledgementService.respond(
            request.user,
            acknowledgement_id,
            request.POST.get("choice", ""),
            request.POST.get("comment", ""),
            request.POST.get("typed_full_name", ""),
        )
    except DocumentAcknowledgement.DoesNotExist:
        # A superseded or withdrawn acknowledgement leaves live deep links
        # behind it — in the reminder mail, in a To-Do, in a bookmark. The
        # service fetches by id with no guard, so following one answered 500.
        messages.error(
            request,
            "That acknowledgement is no longer open — it may have been "
            "replaced by a newer version of the document.",
        )
        return redirect("/policy-agreement")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect("/policy-agreement")

    if ack.state == AcknowledgementState.DISAGREED:
        messages.warning(
            request,
            "Your disagreement has been recorded and sent to HR. You can change "
            "your answer at any time.",
        )
        return redirect("/policy-agreement/restricted")
    messages.success(request, f"Thank you — “{ack.document.title}” is recorded.")
    return redirect(_next_blocking_destination(request.user))


@require_POST
def attest_offline_view(request, acknowledgement_id):
    try:
        AcknowledgementService.attest_offline(
            request.user, acknowledgement_id, request.POST.get("note", "")
        )
        messages.success(request, "Recorded that you reviewed this outside the viewer.")
    except DocumentAcknowledgement.DoesNotExist:
        messages.error(
            request,
            "That acknowledgement is no longer open — it may have been "
            "replaced by a newer version of the document.",
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/policy-agreement")


# ── Compliance reporting ─────────────────────────────────────────────────────


@require_page_permission("policy_compliance")
def compliance_view(request):
    from apps.documents.compliance import PolicyComplianceService

    context = PolicyComplianceService.report(
        request.user,
        {
            "document": request.GET.get("document", ""),
            "state": request.GET.get("state", ""),
            "role": request.GET.get("role", ""),
        },
    )
    context["can_read_comments"] = has_permission(
        request.user, "policies.review_comments"
    )
    if context["can_read_comments"]:
        context["comments"] = CommentService.queue(request.user)
    return render(request, "pages/documents/compliance.html", context)


@require_POST
@require_page_permission("policy_compliance")
def respond_comment_view(request, comment_id):
    try:
        CommentService.respond(
            request.user,
            comment_id,
            request.POST.get("response", ""),
            resolve="resolve" in request.POST,
        )
        messages.success(request, "Response sent.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/policy-compliance")
