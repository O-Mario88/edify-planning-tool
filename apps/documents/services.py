"""Canonical services for the Document Library and policy compliance.

Every path — page, HTMX, API, background job, migration — goes through these.
No view sets a document status or writes an acknowledgement directly.

The rules that shape this module:

* **A published version is immutable.** Corrections create a new version, so an
  acknowledgement always points at exactly the bytes the person agreed to.
* **An empty audience means nobody.** A document with no audience rule reaches
  no one; it is a System Health defect, never an accidental broadcast.
* **Engagement is engagement.** Reading time is recorded and shown, and is
  never described as proof that anyone read or understood anything.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.text import slugify

from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden
from apps.documents.models import (
    AcknowledgementChoice,
    AcknowledgementState,
    CommentStatus,
    DocumentAcknowledgement,
    DocumentAsset,
    DocumentAudienceRule,
    DocumentComment,
    DocumentEngagementSession,
    DocumentStatus,
    DocumentType,
    DocumentVersion,
    PreviewStatus,
    READABLE_STATUSES,
    TRAINING_TYPES,
)

DEFAULT_AGREEMENT_STATEMENT = (
    "I confirm that I have had access to this document, have reviewed it, and "
    "agree to comply with the requirements applicable to my role."
)

# A viewer session with no heartbeat for this long is treated as abandoned:
# an open tab in a locked laptop is not reading.
ENGAGEMENT_IDLE_SECONDS = 120


# ── Permissions ──────────────────────────────────────────────────────────────


def _permissions(principal) -> set[str]:
    from apps.core.rbac import permissions_for_role

    return set(permissions_for_role(getattr(principal, "active_role", "") or ""))


def has_permission(principal, key: str) -> bool:
    return key in _permissions(principal)


def require(principal, key: str, message: str | None = None) -> None:
    if not has_permission(principal, key):
        raise Forbidden(message or f"You do not hold {key}.")


def _user_id(principal) -> str:
    return getattr(principal, "user_id", None) or getattr(principal, "id", "") or ""


# ── Audience ─────────────────────────────────────────────────────────────────


def _role_slug(user) -> str:
    from apps.core.navigation import get_user_role_slug

    return get_user_role_slug(user)


def country_of(user) -> str:
    """A person's country lives on their StaffProfile, not on User.

    Reading it straight off the user silently returned "" for everyone, which
    would have made every country-scoped audience rule match nobody -- a
    policy aimed at Uganda reaching no one, with no error to show for it.
    """
    profile = getattr(user, "staff_profile", None)
    return (
        (getattr(profile, "country", "") if profile else "")
        or getattr(user, "country", "")
        or ""
    )


def audience_matches(document: DocumentAsset, user) -> bool:
    """Does this user fall inside the document's audience?

    Rules union: matching any one rule is enough. Within a rule, every field
    that is set must match — a rule saying "CCEO in Uganda" means both.
    """
    rules = list(document.audience_rules.all())
    if not rules:
        return False  # no audience means nobody, never everybody

    today = timezone.localdate()
    role = getattr(user, "active_role", "") or ""
    role_slug = _role_slug(user)
    user_id = getattr(user, "id", "") or ""
    country = country_of(user)
    partner_ids, project_ids = _partner_and_project_ids(user)

    for rule in rules:
        if rule.effective_from and rule.effective_from > today:
            continue
        if rule.role and rule.role not in (role, role_slug):
            continue
        if rule.country and rule.country != country:
            continue
        if rule.user_id and rule.user_id != user_id:
            continue
        if rule.partner_id and rule.partner_id not in partner_ids:
            continue
        if rule.project_id and rule.project_id not in project_ids:
            continue
        return True
    return False


def _partner_and_project_ids(user) -> tuple[set[str], set[str]]:
    try:
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(user)
        return set(scope.partner_ids or []), set(
            getattr(scope, "project_ids", []) or []
        )
    except Exception:  # noqa: BLE001 — audience must never 500 a page
        return set(), set()


def administers(user, document) -> bool:
    """May this person administer *this* document?

    Scoped by type, not by "holds any document permission". Impact Assessment
    owns training manuals and presentations; it does not own organisational
    policy, and a blanket administrator bypass would have shown IA every draft
    safeguarding policy in the platform.
    """
    if document.is_training_resource:
        return has_permission(user, "training_resources.create")
    return has_permission(user, "documents.create")


def administers_any(user) -> bool:
    return has_permission(user, "documents.create") or has_permission(
        user, "training_resources.create"
    )


def readable_documents(user, document_type: str | None = None):
    """Every published document this user's audience covers."""
    qs = DocumentAsset.objects.filter(status__in=READABLE_STATUSES).prefetch_related(
        "audience_rules"
    )
    if document_type:
        qs = qs.filter(document_type=document_type)
    return [d for d in qs if audience_matches(d, user)]


def targeted_users(document: DocumentAsset):
    """Active users the document's audience covers.

    Walks users rather than translating rules into a query: the rule set is
    small, the user table is not enormous, and an audience predicate expressed
    twice (once as ORM filters, once as `audience_matches`) is a predicate that
    will eventually disagree with itself about who was required to sign.
    """
    from apps.accounts.models import User

    candidates = User.objects.filter(is_active=True, deleted_at__isnull=True)
    return [u for u in candidates if audience_matches(document, u)]


# ── Document lifecycle ───────────────────────────────────────────────────────


class DocumentService:
    @staticmethod
    def create(principal, data: dict) -> DocumentAsset:
        document_type = data.get("document_type")
        if document_type not in DocumentType.values:
            raise BadRequest("Choose a document type.")
        require(
            principal,
            "training_resources.create"
            if document_type in TRAINING_TYPES
            else "documents.create",
            "You cannot create this kind of document.",
        )
        title = (data.get("title") or "").strip()
        if not title:
            raise BadRequest("A title is required.")
        description = (data.get("description") or "").strip()
        if not description:
            raise BadRequest(
                "A description is required — it is what readers see in the "
                "Help Center and on the agreement page."
            )

        base_slug = slugify(title)[:200] or "document"
        slug, suffix = base_slug, 1
        while DocumentAsset.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        document = DocumentAsset.objects.create(
            title=title[:255],
            slug=slug,
            description=description,
            document_type=document_type,
            category=(data.get("category") or "")[:96],
            owner_id=data.get("owner_id") or _user_id(principal),
            country=(data.get("country") or "")[:96],
            confidentiality=data.get("confidentiality")
            or DocumentAsset._meta.get_field("confidentiality").default,
            acknowledgement_required=bool(data.get("acknowledgement_required")),
            agreement_required=bool(data.get("agreement_required")),
            comment_required=bool(data.get("comment_required")),
            agreement_statement=(data.get("agreement_statement") or "").strip()
            or DEFAULT_AGREEMENT_STATEMENT,
            acknowledgement_reason=(data.get("acknowledgement_reason") or "")[:512],
            blocks_application_access=bool(data.get("blocks_application_access")),
            require_reacknowledgement_on_new_version=bool(
                data.get("require_reacknowledgement_on_new_version", True)
            ),
            acknowledgement_due_days=data.get("acknowledgement_due_days") or None,
            download_allowed=bool(data.get("download_allowed", True)),
            print_allowed=bool(data.get("print_allowed", True)),
            help_visible=bool(data.get("help_visible", True)),
            help_category=(data.get("help_category") or "")[:96],
            help_keywords=data.get("help_keywords") or [],
            created_by=_user_id(principal),
        )
        audit_log(
            action="documents.created",
            subject_kind="document",
            subject_id=document.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"title": title, "type": document_type},
        )
        return document

    @staticmethod
    def set_audience(principal, document: DocumentAsset, rules: list[dict]) -> int:
        require(principal, "documents.manage_audience")
        with transaction.atomic():
            document.audience_rules.all().delete()
            created = [
                DocumentAudienceRule.objects.create(
                    document=document,
                    role=(rule.get("role") or "")[:64],
                    country=(rule.get("country") or "")[:96],
                    region_id=(rule.get("region_id") or "")[:30],
                    team_lead_staff_id=(rule.get("team_lead_staff_id") or "")[:30],
                    partner_id=(rule.get("partner_id") or "")[:30],
                    project_id=(rule.get("project_id") or "")[:30],
                    user_id=(rule.get("user_id") or "")[:30],
                    effective_from=rule.get("effective_from"),
                )
                for rule in rules
                if any(rule.values())
            ]
        audit_log(
            action="documents.audience_changed",
            subject_kind="document",
            subject_id=document.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"rules": len(created)},
        )
        return len(created)

    @staticmethod
    def add_version(
        principal, document: DocumentAsset, file_obj, data: dict
    ) -> DocumentVersion:
        """Upload a new revision. Never overwrites a published one."""
        require(
            principal,
            "training_resources.create"
            if document.is_training_resource
            else "documents.create",
        )
        from apps.core.private_storage import best_effort_delete
        from apps.documents.storage import DOCUMENT_NAMESPACE, store_upload

        stored = store_upload(file_obj)
        next_number = (
            document.versions.aggregate(highest=Max("version_number"))["highest"] or 0
        ) + 1

        try:
            version = DocumentVersion.objects.create(
                document=document,
                version_number=next_number,
                effective_date=data.get("effective_date"),
                review_date=data.get("review_date"),
                expiry_date=data.get("expiry_date"),
                change_summary=(data.get("change_summary") or "").strip(),
                material_change=bool(data.get("material_change", True)),
                uploaded_by=_user_id(principal),
                **stored,
            )
        except Exception:
            best_effort_delete(DOCUMENT_NAMESPACE, stored["uri"])
            raise
        audit_log(
            action="documents.version_uploaded",
            subject_kind="document_version",
            subject_id=version.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={
                "document": document.id,
                "version": next_number,
                "scan_status": stored["scan_status"],
            },
        )
        return version

    @staticmethod
    def submit_for_review(principal, document: DocumentAsset) -> DocumentAsset:
        """Send the newest unpublished version for review.

        A document that is already published stays published while its
        successor is reviewed. Moving the *asset* to "under review" would take
        the live policy off every reader's screen for as long as the next
        draft sat in a queue -- which is exactly when people are most likely
        to need it.
        """
        pending = document.versions.filter(published_at__isnull=True).first()
        if pending is None:
            raise BadRequest("Upload a file before submitting for review.")
        if document.status in (DocumentStatus.DRAFT, DocumentStatus.RETURNED):
            document.status = DocumentStatus.UNDER_REVIEW
        elif document.status not in (
            DocumentStatus.PUBLISHED,
            DocumentStatus.EFFECTIVE,
        ):
            raise BadRequest(
                f"A document in '{document.get_status_display()}' cannot be "
                "submitted for review."
            )
        document.save(update_fields=["status", "updated_at"])
        audit_log(
            action="documents.review_requested",
            subject_kind="document",
            subject_id=document.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
        )
        return document

    @staticmethod
    def review(
        principal, version: DocumentVersion, approve: bool, note: str = ""
    ) -> DocumentAsset:
        require(principal, "documents.review")
        document = version.document
        if version.published_at is not None:
            raise BadRequest("A published version cannot be reviewed again.")
        if document.status not in (
            DocumentStatus.UNDER_REVIEW,
            DocumentStatus.PUBLISHED,
            DocumentStatus.EFFECTIVE,
        ):
            raise BadRequest("This document is not awaiting review.")
        version.reviewed_by = _user_id(principal)
        version.reviewed_at = timezone.now()
        version.review_decision = "approved" if approve else "returned"
        version.review_note = note[:512]
        version.save(
            update_fields=[
                "reviewed_by",
                "reviewed_at",
                "review_decision",
                "review_note",
                "updated_at",
            ]
        )
        # A live document keeps its published status: the decision recorded
        # above belongs to the version, not to the asset the readers see.
        if document.status not in (DocumentStatus.PUBLISHED, DocumentStatus.EFFECTIVE):
            document.status = (
                DocumentStatus.APPROVED if approve else DocumentStatus.RETURNED
            )
            document.save(update_fields=["status", "updated_at"])
        audit_log(
            action="documents.review_completed",
            subject_kind="document_version",
            subject_id=version.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            reason=note or None,
            payload={"approved": approve},
        )
        return document

    @staticmethod
    def publish(principal, version: DocumentVersion) -> DocumentAsset:
        """Publish a reviewed version. The gate every requirement lands on."""
        document = version.document
        require(
            principal,
            "training_resources.publish"
            if document.is_training_resource
            else "documents.publish",
            "You cannot publish documents.",
        )
        if version.published_at is not None:
            raise BadRequest("That version is already published.")
        _assert_publishable(document, version)

        with transaction.atomic():
            previous = document.current_version
            if previous and previous.id != version.id:
                previous.superseded_at = timezone.now()
                previous.save(update_fields=["superseded_at", "updated_at"])

            version.published_by = _user_id(principal)
            version.published_at = timezone.now()
            version.save(update_fields=["published_by", "published_at", "updated_at"])

            document.current_version = version
            document.status = DocumentStatus.PUBLISHED
            document.save(update_fields=["current_version", "status", "updated_at"])

        # Preview is best-effort and must never block publication: a manual
        # that will not convert is still a manual people need.
        from apps.documents.storage import build_preview

        build_preview(version)

        from apps.documents.help_sync import sync_help_mapping

        sync_help_mapping(document)

        if document.is_mandatory:
            AcknowledgementService.generate_pending(document, version, previous)

        audit_log(
            action="documents.published",
            subject_kind="document_version",
            subject_id=version.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"document": document.id, "version": version.version_number},
        )
        _notify_published(document, version)
        return document

    @staticmethod
    def archive(principal, document: DocumentAsset, reason: str = "") -> DocumentAsset:
        require(principal, "documents.archive")
        document.status = DocumentStatus.ARCHIVED
        document.archived_at = timezone.now()
        document.save(update_fields=["status", "archived_at", "updated_at"])
        audit_log(
            action="documents.archived",
            subject_kind="document",
            subject_id=document.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            reason=reason or None,
        )
        return document


def _assert_publishable(document: DocumentAsset, version: DocumentVersion) -> None:
    """Everything a published document must have. Stated in one place, so the
    list cannot quietly shrink."""
    missing = []
    if not document.title.strip():
        missing.append("title")
    if not document.description.strip():
        missing.append("description")
    if not document.owner_id:
        missing.append("owner")
    if not document.audience_rules.exists():
        missing.append("audience")
    if not version.uri:
        missing.append("file")
    if not version.effective_date:
        missing.append("effective date")
    if version.review_decision != "approved":
        missing.append("review decision")
    if document.is_mandatory:
        if not document.agreement_statement.strip():
            missing.append("agreement wording")
        if not document.acknowledgement_reason.strip():
            missing.append("reason acknowledgement is required")
    if missing:
        raise BadRequest("Cannot publish — still missing: " + ", ".join(missing))

    # A sensitive organisational document must not go out while a configured
    # scanner says it is infected. "skipped" is honest and permitted; "infected"
    # is not.
    if version.scan_status == "infected":
        raise BadRequest("Publication blocked: the malware scan flagged this file.")


def _notify_published(document: DocumentAsset, version: DocumentVersion) -> None:
    from apps.notifications.services import WorkflowNotificationService

    recipients = [u.id for u in targeted_users(document)]
    if not recipients:
        return
    mandatory = document.is_mandatory
    WorkflowNotificationService.trigger(
        event_type="documents.policy_published"
        if mandatory
        else "documents.resource_published",
        category="policy" if mandatory else "training",
        priority="high" if mandatory else "normal",
        title=f"{'Action required: ' if mandatory else ''}{document.title}",
        body=document.description[:400],
        context_type="document",
        context_id=document.id,
        recipients=recipients,
    )


# ── Acknowledgement ──────────────────────────────────────────────────────────


class AcknowledgementService:
    @staticmethod
    def ensure_pending_for(user) -> int:
        """Give a newly onboarded user every live mandatory agreement.

        Publication creates acknowledgements for the users who exist at that
        moment. This lazy reconciliation closes the future-user gap: on first
        authenticated access, any current blocking document whose audience
        matches the user receives a version-specific pending record.

        A person with any acknowledgement for a document is not synthesized a
        second one here. Material new versions are handled by ``publish``;
        non-material versions intentionally carry the earlier response.
        """
        if not getattr(user, "is_authenticated", False):
            return 0
        existing_document_ids = set(
            DocumentAcknowledgement.objects.filter(user_id=_user_id(user)).values_list(
                "document_id", flat=True
            )
        )
        candidates = (
            DocumentAsset.objects.filter(
                status__in=READABLE_STATUSES,
                acknowledgement_required=True,
                blocks_application_access=True,
                current_version__isnull=False,
            )
            .select_related("current_version")
            .prefetch_related("audience_rules")
        )
        created = 0
        for document in candidates:
            if document.id in existing_document_ids or not audience_matches(
                document, user
            ):
                continue
            _, was_created = DocumentAcknowledgement.objects.get_or_create(
                version=document.current_version,
                user_id=_user_id(user),
                defaults={
                    "document": document,
                    "state": AcknowledgementState.PENDING,
                    "role_at_acknowledgement": getattr(user, "active_role", "") or "",
                    "country_at_acknowledgement": country_of(user),
                },
            )
            created += int(was_created)
        return created

    @staticmethod
    def generate_pending(
        document: DocumentAsset,
        version: DocumentVersion,
        previous: DocumentVersion | None = None,
    ) -> int:
        """Create a pending acknowledgement per targeted user for this version.

        A non-material change on a document configured not to require
        re-acknowledgement carries the previous answers forward rather than
        asking everyone again for a typo fix.
        """
        if previous is not None and not (
            version.material_change
            and document.require_reacknowledgement_on_new_version
        ):
            return 0

        due = None
        if document.acknowledgement_due_days:
            due = timezone.localdate() + timedelta(
                days=document.acknowledgement_due_days
            )

        created = 0
        for user in targeted_users(document):
            _, was_created = DocumentAcknowledgement.objects.get_or_create(
                version=version,
                user_id=user.id,
                defaults={
                    "document": document,
                    "state": AcknowledgementState.PENDING,
                    "due_date": due,
                    "role_at_acknowledgement": getattr(user, "active_role", "") or "",
                    "country_at_acknowledgement": country_of(user),
                },
            )
            created += 1 if was_created else 0

        # Earlier answers are preserved, never rewritten — they are the record
        # of what that person agreed to at the time. They are only marked as
        # belonging to a superseded version.
        if previous is not None:
            DocumentAcknowledgement.objects.filter(
                version=previous, state=AcknowledgementState.AGREED
            ).update(state=AcknowledgementState.SUPERSEDED, updated_at=timezone.now())

        return created

    @staticmethod
    def pending_for(user) -> list[DocumentAcknowledgement]:
        """Outstanding mandatory acknowledgements for this user, current
        versions only."""
        AcknowledgementService.ensure_pending_for(user)
        return list(
            DocumentAcknowledgement.objects.filter(
                user_id=getattr(user, "id", ""),
                state=AcknowledgementState.PENDING,
                document__status__in=READABLE_STATUSES,
            )
            .select_related("document", "version")
            .order_by("due_date", "created_at")
        )

    @staticmethod
    def blocking_for(user) -> list[DocumentAcknowledgement]:
        """The subset that withholds the application until answered."""
        return [
            ack
            for ack in AcknowledgementService.pending_for(user)
            if ack.document.blocks_application_access
        ]

    @staticmethod
    def disagreed_for(user) -> list[DocumentAcknowledgement]:
        return list(
            DocumentAcknowledgement.objects.filter(
                user_id=getattr(user, "id", ""),
                state=AcknowledgementState.DISAGREED,
                document__status__in=READABLE_STATUSES,
                document__blocks_application_access=True,
            ).select_related("document", "version")
        )

    @staticmethod
    @transaction.atomic
    def respond(
        principal,
        acknowledgement_id: str,
        choice: str,
        comment: str = "",
        typed_name: str = "",
    ) -> DocumentAcknowledgement:
        ack = DocumentAcknowledgement.objects.select_for_update().get(
            id=acknowledgement_id
        )
        if ack.user_id != _user_id(principal) and ack.user_id != getattr(
            principal, "id", None
        ):
            raise Forbidden("You can only answer your own acknowledgement.")
        if choice not in AcknowledgementChoice.values:
            raise BadRequest("Choose either I Agree or I Disagree.")

        document = ack.document
        comment = (comment or "").strip()
        if document.comment_required and not comment:
            raise BadRequest("A comment is required for this document.")
        if choice == AcknowledgementChoice.DISAGREE and not comment:
            raise BadRequest("Please tell us why you disagree.")

        ack.choice = choice
        ack.state = (
            AcknowledgementState.AGREED
            if choice == AcknowledgementChoice.AGREE
            else AcknowledgementState.DISAGREED
        )
        ack.statement = document.agreement_statement
        ack.comment = comment
        ack.typed_full_name = (typed_name or "")[:160]
        ack.responded_at = timezone.now()
        ack.role_at_acknowledgement = getattr(principal, "active_role", "") or ""
        ack.save()

        AcknowledgementService._roll_up_engagement(ack)

        audit_log(
            action=f"documents.policy_{choice}d",
            subject_kind="document_acknowledgement",
            subject_id=ack.id,
            actor_id=ack.user_id,
            actor_role=ack.role_at_acknowledgement,
            payload={
                "document": document.id,
                "version": ack.version.version_number,
                "active_reading_seconds": ack.active_reading_seconds,
            },
        )

        if comment:
            CommentService.record(principal, ack, comment)
        if choice == AcknowledgementChoice.DISAGREE:
            _notify_disagreement(ack)
        return ack

    @staticmethod
    def attest_offline(
        principal, acknowledgement_id: str, note: str
    ) -> DocumentAcknowledgement:
        """A reader who reviewed the document outside the viewer.

        Screen readers, downloaded copies and printed copies are legitimate
        ways to read a policy. Completion must never depend on scrolling a
        mouse to the last page.
        """
        ack = DocumentAcknowledgement.objects.get(id=acknowledgement_id)
        if ack.user_id != _user_id(principal) and ack.user_id != getattr(
            principal, "id", None
        ):
            raise Forbidden("You can only attest for your own acknowledgement.")
        ack.offline_attestation = True
        ack.offline_attestation_note = (note or "")[:512]
        ack.save(
            update_fields=[
                "offline_attestation",
                "offline_attestation_note",
                "updated_at",
            ]
        )
        return ack

    @staticmethod
    def _roll_up_engagement(ack: DocumentAcknowledgement) -> None:
        sessions = DocumentEngagementSession.objects.filter(
            version=ack.version, user_id=ack.user_id
        )
        total = sum(s.active_seconds for s in sessions)
        last_page = max((s.last_page or 0) for s in sessions) if sessions else 0
        ack.active_reading_seconds = total
        ack.session_count = sessions.count()
        ack.last_page_reached = last_page or None
        pages = ack.version.page_count
        ack.viewer_completed = bool(pages and last_page and last_page >= pages)
        ack.save(
            update_fields=[
                "active_reading_seconds",
                "session_count",
                "last_page_reached",
                "viewer_completed",
                "updated_at",
            ]
        )


def _notify_disagreement(ack: DocumentAcknowledgement) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    reviewers = User.objects.filter(
        active_role__in=["HumanResources", "CountryDirector"],
        is_active=True,
        deleted_at__isnull=True,
    )
    if not reviewers:
        return
    WorkflowNotificationService.trigger(
        event_type="documents.policy_disagreed",
        category="policy",
        priority="high",
        title=f"Disagreement recorded: {ack.document.title}",
        body=f"A {ack.role_at_acknowledgement or 'user'} disagreed and gave a reason.",
        context_type="document_acknowledgement",
        context_id=ack.id,
        recipients=list(reviewers),
    )


# ── Engagement ───────────────────────────────────────────────────────────────


class EngagementService:
    """Active reading time, honestly measured.

    Time only accrues while the viewer reports itself visible, and a gap longer
    than the idle threshold is discarded rather than counted -- an open tab on a
    locked laptop is not reading. What this produces is labelled Active Reading
    Time, never proof of reading.
    """

    @staticmethod
    def heartbeat(
        principal, version_id: str, page: int | None = None
    ) -> DocumentEngagementSession:
        user_id = _user_id(principal) or getattr(principal, "id", "")
        now = timezone.now()
        version = DocumentVersion.objects.get(id=version_id)

        session = (
            DocumentEngagementSession.objects.filter(
                version=version, user_id=user_id, finalised=False
            )
            .order_by("-last_heartbeat_at")
            .first()
        )
        if (
            session is None
            or (now - session.last_heartbeat_at).total_seconds()
            > ENGAGEMENT_IDLE_SECONDS
        ):
            if session is not None:
                session.finalised = True
                session.save(update_fields=["finalised", "updated_at"])
            session = DocumentEngagementSession.objects.create(
                document=version.document,
                version=version,
                user_id=user_id,
                started_at=now,
                last_heartbeat_at=now,
                pages_viewed=[page] if page else [],
                last_page=page,
            )
            return session

        elapsed = int((now - session.last_heartbeat_at).total_seconds())
        session.active_seconds += max(0, min(elapsed, ENGAGEMENT_IDLE_SECONDS))
        session.last_heartbeat_at = now
        if page:
            session.last_page = max(page, session.last_page or 0)
            if page not in session.pages_viewed:
                session.pages_viewed = sorted({*session.pages_viewed, page})
        session.save(
            update_fields=[
                "active_seconds",
                "last_heartbeat_at",
                "last_page",
                "pages_viewed",
                "updated_at",
            ]
        )
        return session


# ── Comments ─────────────────────────────────────────────────────────────────


class CommentService:
    @staticmethod
    def record(principal, ack: DocumentAcknowledgement, body: str) -> DocumentComment:
        comment = DocumentComment.objects.create(
            document=ack.document,
            version=ack.version,
            acknowledgement=ack,
            author_id=ack.user_id,
            author_role=ack.role_at_acknowledgement,
            author_country=ack.country_at_acknowledgement,
            body=body,
        )
        audit_log(
            action="documents.comment_submitted",
            subject_kind="document_comment",
            subject_id=comment.id,
            actor_id=ack.user_id,
            actor_role=ack.role_at_acknowledgement,
            payload={"document": ack.document_id},
        )
        _notify_comment(comment)
        return comment

    @staticmethod
    def queue(principal):
        """Comments this reviewer may see.

        Private by default: only roles holding `policies.review_comments` read
        the body at all, and a Country Director sees their own country. A
        Program Lead sees acknowledgement *status* for their team through the
        compliance report, and never the private text.
        """
        require(principal, "policies.review_comments", "Policy comments are private.")
        qs = DocumentComment.objects.select_related("document", "version").exclude(
            status=CommentStatus.ARCHIVED
        )
        role = getattr(principal, "active_role", "")
        if role == "CountryDirector":
            country = getattr(principal, "country", "") or ""
            qs = qs.filter(author_country=country)
        return list(qs[:200])

    @staticmethod
    def respond(
        principal, comment_id: str, response: str, resolve: bool = False
    ) -> DocumentComment:
        require(principal, "policies.review_comments")
        comment = DocumentComment.objects.get(id=comment_id)
        comment.response = (response or "").strip()
        comment.responded_by = _user_id(principal)
        comment.responded_at = timezone.now()
        comment.status = CommentStatus.RESOLVED if resolve else CommentStatus.RESPONDED
        comment.owner_id = comment.owner_id or _user_id(principal)
        if resolve:
            comment.resolved_at = timezone.now()
        comment.save()
        audit_log(
            action="documents.comment_reviewed",
            subject_kind="document_comment",
            subject_id=comment.id,
            actor_id=_user_id(principal),
            actor_role=getattr(principal, "active_role", None),
            payload={"resolved": resolve},
        )
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="documents.comment_response",
            category="policy",
            priority="normal",
            title=f"Response on {comment.document.title}",
            body=comment.response[:400],
            context_type="document_comment",
            context_id=comment.id,
            recipients=[comment.author_id],
        )
        return comment


def _notify_comment(comment: DocumentComment) -> None:
    from apps.accounts.models import User
    from apps.notifications.services import WorkflowNotificationService

    reviewers = User.objects.filter(
        active_role__in=["HumanResources", "CountryDirector"],
        is_active=True,
        deleted_at__isnull=True,
    )
    if not reviewers:
        return
    WorkflowNotificationService.trigger(
        event_type="documents.comment_submitted",
        category="policy",
        priority="normal",
        title=f"Policy comment: {comment.document.title}",
        body="A comment was submitted with an acknowledgement.",
        context_type="document_comment",
        context_id=comment.id,
        recipients=list(reviewers),
    )


__all__ = [
    "AcknowledgementService",
    "CommentService",
    "DocumentService",
    "EngagementService",
    "audience_matches",
    "has_permission",
    "readable_documents",
    "require",
    "targeted_users",
    "PreviewStatus",
]
