"""The Upload Center — one index over every file that enters Edify.

This is a control surface, not a second storage system. Four of its five
categories already have an authoritative home, and the Upload Center reads
those homes rather than copying anything into a table of its own:

    Structured imports    -> schools.SchoolImportBatch / SSAImportBatch
    Activity evidence     -> evidence.EvidenceRecord
    PD certificates       -> professional_development.…Certificate
    Policies and manuals  -> documents.DocumentAsset  (the one new home)
    Training resources    -> documents.DocumentAsset

Every adapter returns the same normalised row, so the page can sort, filter and
paginate a mixed list without knowing what any of it is. What it must never do
is offer a generic "upload a file" button: evidence without an activity, or a
certificate without a PD record, is an orphan the owning workflow cannot act on.
So each category's upload action is a deep link into the workflow that owns it,
and only policies, manuals and training resources — which have no other home —
are uploaded here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from django.utils import timezone

from apps.core.exceptions import Forbidden


@dataclass
class UploadRow:
    """One normalised entry, whatever its underlying record."""

    record_type: str
    record_id: str
    title: str
    workflow_owner: str
    uploaded_by: str = ""
    uploaded_at: datetime | None = None
    context: str = ""  # school / activity / audience — what it relates to
    version: str = ""
    processing_status: str = ""
    publication_status: str = ""
    acknowledgement_status: str = ""
    preview_status: str = ""
    next_action: str = ""
    detail_route: str = ""
    original_format: str = ""
    tab: str = ""
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


TABS = (
    ("all", "All Authorized Uploads"),
    ("imports", "Structured Imports"),
    ("documents", "Policies and Manuals"),
    ("training", "Training Resources"),
    ("evidence", "Activity Evidence"),
    ("pd", "PD Certificates"),
    ("mine", "My Uploads"),
)


def _user_id(principal) -> str:
    return getattr(principal, "id", "") or getattr(principal, "user_id", "") or ""


def _name_index() -> dict[str, str]:
    from apps.accounts.models import User

    return {u.id: u.name for u in User.objects.only("id", "name")}


# ── Adapters ─────────────────────────────────────────────────────────────────


def _structured_imports(principal, names) -> list[UploadRow]:
    """School and SSA import batches.

    Deliberately no preview: a school roster is a spreadsheet to be validated
    row by row, not a document to be read, and rendering it as a PDF would hide
    exactly the per-row detail the importer exists to show.
    """
    from apps.core.rbac import Permission, permissions_for_role

    held = set(permissions_for_role(getattr(principal, "active_role", "") or ""))
    rows: list[UploadRow] = []

    if Permission.SCHOOL_UPLOAD.value in held:
        from apps.schools.models import SchoolImportBatch

        for batch in SchoolImportBatch.objects.all()[:100]:
            rows.append(
                UploadRow(
                    record_type="school_import",
                    record_id=batch.id,
                    title=batch.file_name,
                    workflow_owner="School Import",
                    uploaded_by=names.get(batch.uploaded_by, batch.uploaded_by),
                    uploaded_at=batch.created_at,
                    context=f"{batch.total_rows} rows",
                    processing_status=batch.get_status_display(),
                    preview_status="Structured preview",
                    next_action="Review rows"
                    if batch.status == "staged"
                    else "View import results",
                    detail_route=f"/schools/upload?batch={batch.id}",
                    original_format="CSV / XLSX",
                    tab="imports",
                )
            )

    if Permission.SSA_UPLOAD.value in held:
        from apps.schools.models import SSAImportBatch

        for batch in SSAImportBatch.objects.all()[:100]:
            unmatched = batch.rows.filter(status="unmatched").count()
            rows.append(
                UploadRow(
                    record_type="ssa_import",
                    record_id=batch.id,
                    title=batch.file_name,
                    workflow_owner="SSA Import",
                    uploaded_by=names.get(batch.uploaded_by, batch.uploaded_by),
                    uploaded_at=batch.created_at,
                    context=f"{batch.total_rows} rows"
                    + (f" · {unmatched} unmatched" if unmatched else ""),
                    processing_status=batch.get_status_display(),
                    preview_status="Structured preview",
                    next_action="Resolve unmatched School IDs"
                    if unmatched
                    else "View import results",
                    detail_route=f"/ssa/upload/?batch={batch.id}",
                    original_format="CSV",
                    tab="imports",
                )
            )
    return rows


def _documents(principal, names) -> list[UploadRow]:
    """Policies, manuals and training resources from the Document Library."""
    from apps.documents.models import DocumentAsset, TRAINING_TYPES
    from apps.documents.services import administers, audience_matches

    qs = DocumentAsset.objects.select_related("current_version").prefetch_related(
        "audience_rules"
    )

    rows: list[UploadRow] = []
    for document in qs[:300]:
        # A draft is visible to whoever administers that *kind* of document;
        # everyone else sees it only once it is published and aimed at them.
        # Scoped per document, so Impact Assessment sees its training drafts
        # and none of HR's policy drafts.
        manages = administers(principal, document)
        if not manages and not audience_matches(document, principal):
            continue
        if not manages and document.status not in ("published", "effective"):
            continue

        version = document.current_version
        ack = ""
        if document.is_mandatory:
            from apps.documents.models import AcknowledgementState

            total = document.acknowledgements.filter(version=version).count()
            agreed = document.acknowledgements.filter(
                version=version, state=AcknowledgementState.AGREED
            ).count()
            ack = f"{agreed}/{total} accepted" if total else "Awaiting generation"

        rows.append(
            UploadRow(
                record_type=document.document_type,
                record_id=document.id,
                title=document.title,
                workflow_owner="Training Resource Library"
                if document.document_type in TRAINING_TYPES
                else "Document Library",
                uploaded_by=names.get(document.created_by, document.created_by or ""),
                uploaded_at=document.created_at,
                context=", ".join(str(r) for r in document.audience_rules.all()[:3])
                or "No audience set",
                version=f"v{version.version_number}" if version else "—",
                publication_status=document.get_status_display(),
                acknowledgement_status=ack,
                preview_status=version.get_preview_status_display() if version else "—",
                next_action=_document_next_action(document),
                detail_route=f"/documents/{document.slug}/",
                original_format=(version.file_extension if version else "") or "",
                tab="training"
                if document.document_type in TRAINING_TYPES
                else "documents",
            )
        )
    return rows


def _document_next_action(document) -> str:
    from apps.documents.models import DocumentStatus

    return {
        DocumentStatus.DRAFT: "Submit for review",
        DocumentStatus.UNDER_REVIEW: "Review",
        DocumentStatus.APPROVED: "Publish",
        DocumentStatus.RETURNED: "Correct and resubmit",
        DocumentStatus.PUBLISHED: "Monitor acknowledgements"
        if document.is_mandatory
        else "Published",
        DocumentStatus.EFFECTIVE: "Monitor acknowledgements"
        if document.is_mandatory
        else "In effect",
    }.get(document.status, document.get_status_display())


def _evidence(principal, names) -> list[UploadRow]:
    """Activity evidence, read from its authoritative records.

    Displayed and filtered here; reviewed only in the evidence workflow. A
    second review path would be a second definition of "verified".
    """
    from apps.evidence.models import EvidenceRecord

    qs = EvidenceRecord.objects.select_related(
        "activity", "activity__school", "activity__cluster"
    ).order_by("-created_at")
    qs = _scope_evidence(qs, principal)

    rows = []
    for record in qs[:200]:
        activity = record.activity
        target = (
            activity.school.name
            if activity.school
            else (activity.cluster.name if activity.cluster else "—")
        )
        rows.append(
            UploadRow(
                record_type="evidence",
                record_id=record.id,
                title=record.original_name or record.uri,
                workflow_owner="Activity Evidence",
                uploaded_by=names.get(record.uploaded_by, record.uploaded_by),
                uploaded_at=record.created_at,
                context=f"{activity.activity_type} · {target}",
                version="—",
                processing_status=record.get_status_display(),
                preview_status=(record.preview_status or "").replace("_", " ").title(),
                next_action=_evidence_next_action(record),
                detail_route=f"/my-plan/{activity.id}",
                original_format=record.file_extension or "",
                tab="evidence",
                extra={"ia_status": getattr(activity, "ia_verification_status", "")},
            )
        )
    return rows


def _scope_evidence(qs, principal):
    """Evidence a person may see, using the canonical activity scope."""
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return qs
    if scope.partner_ids:
        return qs.filter(activity__assigned_partner_id__in=scope.partner_ids)
    if scope.staff_ids:
        return qs.filter(activity__responsible_staff_id__in=scope.staff_ids)
    return qs.none()


def _evidence_next_action(record) -> str:
    if record.quarantined:
        return "Quarantined — contact support"
    if record.status == "uploaded":
        return "Awaiting managing-staff review"
    if record.status == "accepted":
        return "Awaiting IA verification"
    return record.get_status_display()


def _pd_certificates(principal, names) -> list[UploadRow]:
    """PD certificates, read from the PD workflow.

    Never uploadable from here: a certificate with no PD record behind it has
    no course, no provider, no approval and nobody to sign it off.
    """
    from apps.professional_development.models import ProfessionalDevelopmentCertificate

    qs = ProfessionalDevelopmentCertificate.objects.select_related("request").order_by(
        "-created_at"
    )
    role = getattr(principal, "active_role", "")
    me = _user_id(principal)
    if role not in ("Admin", "HumanResources", "CountryDirector"):
        # Everyone else sees their own certificates only.
        qs = qs.filter(uploaded_by=me)

    rows = []
    for cert in qs[:200]:
        request = cert.request
        rows.append(
            UploadRow(
                record_type="pd_certificate",
                record_id=cert.id,
                title=cert.certificate_name or cert.original_name,
                workflow_owner="Professional Development",
                uploaded_by=names.get(cert.uploaded_by, cert.uploaded_by),
                uploaded_at=cert.created_at,
                context=getattr(request, "course_name", "") or "PD record",
                version="—",
                processing_status=(cert.status or "").replace("_", " ").title(),
                preview_status="PDF",
                next_action="Awaiting HR verification"
                if cert.status == "uploaded"
                else (cert.status or "").replace("_", " ").title(),
                detail_route=f"/my-professional-development?request={request.id}"
                if request
                else "/my-professional-development",
                original_format=(cert.original_name or "").rsplit(".", 1)[-1],
                tab="pd",
            )
        )
    return rows


ADAPTERS = {
    "imports": _structured_imports,
    "documents": _documents,
    "evidence": _evidence,
    "pd": _pd_certificates,
}


# ── The service ──────────────────────────────────────────────────────────────


class UploadCenterService:
    PAGE_SIZE = 50

    @staticmethod
    def _require_view(principal) -> None:
        from apps.documents.services import has_permission

        if not has_permission(principal, "uploads.view"):
            raise Forbidden("You do not have access to the Upload Center.")

    @staticmethod
    def visible_tabs(principal) -> list[dict]:
        """Only tabs with a real dataset behind them for this role.

        A tab that is always empty for a role is not a feature; it is a promise
        the page cannot keep.
        """
        rows = UploadCenterService.rows(principal)
        present = {row.tab for row in rows}
        # "Policies and Manuals" stays for anyone who can create one, even
        # before the first document exists -- that tab is where they start.
        from apps.documents.services import has_permission

        if has_permission(principal, "documents.create"):
            present.add("documents")
        if has_permission(principal, "training_resources.create"):
            present.add("training")
        out = [{"key": "all", "label": "All Authorized Uploads"}]
        out += [
            {"key": key, "label": label}
            for key, label in TABS
            if key in present and key not in ("all", "mine")
        ]
        out.append({"key": "mine", "label": "My Uploads"})
        return out

    @staticmethod
    def rows(principal) -> list[UploadRow]:
        UploadCenterService._require_view(principal)
        names = _name_index()
        rows: list[UploadRow] = []
        for adapter in ADAPTERS.values():
            try:
                rows.extend(adapter(principal, names))
            except Forbidden:
                continue  # a category this role cannot see is simply absent
        rows.sort(key=lambda r: r.uploaded_at or timezone.now(), reverse=True)
        return rows

    @staticmethod
    def get(principal, query: dict | None = None) -> dict:
        query = query or {}
        tab = (query.get("tab") or "all").strip()
        status = (query.get("status") or "").strip().lower()
        record_type = (query.get("type") or "").strip()
        search = (query.get("q") or "").strip().lower()

        rows = UploadCenterService.rows(principal)
        me = _user_id(principal)
        my_name = _name_index().get(me, "")

        if tab == "mine":
            rows = [r for r in rows if r.uploaded_by in (me, my_name)]
        elif tab in {"imports", "documents", "training", "evidence", "pd"}:
            rows = [r for r in rows if r.tab == tab]
        if record_type:
            rows = [r for r in rows if r.record_type == record_type]
        if status:
            rows = [
                r
                for r in rows
                if status in f"{r.processing_status} {r.publication_status}".lower()
            ]
        if search:
            rows = [
                r
                for r in rows
                if search in f"{r.title} {r.context} {r.uploaded_by}".lower()
            ]

        try:
            page = max(1, int(query.get("page") or 1))
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * UploadCenterService.PAGE_SIZE
        window = rows[start : start + UploadCenterService.PAGE_SIZE]

        return {
            "rows": [r.as_dict() for r in window],
            "total": len(rows),
            "page": page,
            "page_size": UploadCenterService.PAGE_SIZE,
            "has_next": start + UploadCenterService.PAGE_SIZE < len(rows),
            "tab": tab,
            "tabs": UploadCenterService.visible_tabs(principal),
            "filters": query,
            "kpis": UploadCenterService.kpis(principal, rows),
        }

    @staticmethod
    def kpis(principal, rows: list[UploadRow]) -> list[dict]:
        """Only the figures this role can act on.

        Built through `apps.core.metrics.render_metric`, so each tile carries
        its registered key, period and scope -- which is what makes the
        platform's duplication and denominator guards able to see it at all.
        A hand-built tile is invisible to them.
        """
        from apps.core.metrics import MetricValue, render_metric, render_strip
        from apps.documents.models import AcknowledgementState, DocumentAcknowledgement
        from apps.documents.services import has_permission

        awaiting = sum(1 for r in rows if "review" in (r.next_action or "").lower())
        published = sum(
            1 for r in rows if (r.publication_status or "").lower() == "published"
        )

        tiles = [
            render_metric(
                "uploads_awaiting_review",
                MetricValue.measured(awaiting),
                drilldown_url="/uploads",
            ),
            render_metric(
                "uploads_documents_published",
                MetricValue.measured(published),
                drilldown_url="/uploads?tab=documents",
            ),
        ]

        if has_permission(principal, "policies.manage_acknowledgements"):
            # Only "overdue" appears here: pending is the same population
            # seen from the other side, and the compliance page is where the
            # split belongs.
            overdue = DocumentAcknowledgement.objects.filter(
                state=AcknowledgementState.PENDING,
                due_date__lt=timezone.localdate(),
            ).count()
            tiles.append(
                render_metric(
                    "policy_acknowledgements_overdue",
                    MetricValue.measured(overdue),
                    drilldown_url="/policy-compliance?state=pending",
                )
            )

        return render_strip(tiles)
