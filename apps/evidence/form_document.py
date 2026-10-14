"""One uploaded form per partner activity, opened as one PDF.

Owner, 2026-10-14: "Only staff dont need to upload. partners HAVE to upload
because that is how we verify their work." Staff work is completed with its
visit ID or training ID alone (the day before's rule, marked UPLOAD-OFF
across the apps); a partner's work is verified from the form it uploads: the
Visit Form for a school visit, the Training Attendance for a training or a
cluster meeting.

The same message, on what the verifier saw: "it displays list of all the
uploads even if the same document is uploaded 3 times it will display all
the 3. can you fix it to show only one upload. if the document has many
pages, from the upload drawer, ask the partner if it is a different page
from the one they have uploaded if they say yes then allow if they say no
then reject the second upload. if many pages, combine them all into one
single PDF file with many pages. and from the verifiers side, no need to
show the uploaded image, just use the link "View Uploaded {visit form} or
{Training attendance}" in a beautiful button which allow them to click and
open the upload in PDF which can be downloaded."

So an activity holds ONE document for its form:

* the first upload is stored as before (one file, or the pages chosen
  together joined into one PDF: apps.evidence.services.record_pages_upload);
* a later upload is taken only as another page of that document, and only
  when the partner says it is one (`another_page`); it is joined to the pages
  already held and the one PDF replaces what was stored. A file that is
  byte for byte one already held is refused whatever the answer;
* a reader opens it through one address, `/api/evidence/activity/<id>/form`,
  which answers one PDF. Work that gathered several records before this rule
  is read the same way: the records that differ, joined in the order they
  were uploaded.
"""

from __future__ import annotations

import hashlib
import io

from django.db import transaction
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.private_storage import best_effort_delete, file_exists, open_file

from . import pages
from .models import EvidenceRecord

#: The two governed forms (the two-form law, owner 2026-08-19).
FORM_KINDS = ("visit_form", "attendance_form")
#: What a reader calls each: "View Uploaded Visit Form", "View Uploaded
#: Training Attendance" (owner, 2026-10-14).
FORM_NAMES = {"visit_form": "Visit Form", "attendance_form": "Training Attendance"}

#: What a page of a form may be; anything else cannot be drawn into the PDF.
_PAGE_TYPES = (".pdf", ".jpg", ".jpeg", ".png", ".webp")
#: A document opened for reading may be longer than one upload may add:
#: work from before this rule can hold several full uploads.
_READ_MAX_PAGES = 200

STAFF_TAKES_NO_UPLOAD = (
    "Staff work is completed with its Salesforce visit ID or training ID. "
    "No form is uploaded for it."
)


def takes_upload(activity) -> bool:
    """Whether this activity is verified from an uploaded form: partner work
    is, staff work is not.

    UPLOAD-OFF: the one switch. The rules that asked staff for a file (the
    completion gates, IA's checks, closure, payment clearance, the Evidence
    column) all ask this first, so returning True for staff work brings their
    upload back ("just comment the code out, we may need it later")."""
    return (getattr(activity, "delivery_type", "") or "") == "partner"


def assert_takes_upload(activity) -> None:
    if not takes_upload(activity):
        raise BadRequest(STAFF_TAKES_NO_UPLOAD)


def form_kind(activity) -> str:
    """The form this activity is verified from."""
    from apps.activities.completion_columns import expected_evidence
    from apps.evidence.requirements import required_kinds_for_activity

    for kind in required_kinds_for_activity(activity):
        if kind in FORM_KINDS:
            return kind
    return expected_evidence(activity.activity_type)[0]


def form_name(activity) -> str:
    return FORM_NAMES[form_kind(activity)]


def form_records(activity, kind: str | None = None) -> list[EvidenceRecord]:
    """The records that make up the activity's form, oldest first.

    The records of the form's own kind; where an activity holds none of that
    kind but does hold files (older uploads filed as a photo or a PDF), those
    files are its form: a file that is there is never reported missing."""
    records = list(
        EvidenceRecord.objects.filter(activity_id=activity.id, quarantined=False)
        .order_by("created_at", "id")
        .only(
            "id",
            "activity_id",
            "kind",
            "uri",
            "original_name",
            "mime_type",
            "file_extension",
            "file_size",
            "created_at",
            "pdf_rendition_storage_key",
            "view_count",
        )
    )
    wanted = kind or form_kind(activity)
    own = [r for r in records if r.kind == wanted]
    if own or kind:
        return own
    return records


def uploaded_form(activity) -> dict | None:
    """What a page needs to offer the one button: the form's name, the
    button's words and the address that opens it. None when nothing is
    uploaded."""
    if not form_records(activity):
        return None
    name = form_name(activity)
    return {
        "kind": form_kind(activity),
        "name": name,
        "label": f"View Uploaded {name}",
        "url": f"/api/evidence/activity/{activity.id}/form",
    }


def _stored_bytes(record: EvidenceRecord) -> bytes | None:
    """The record's stored file, or None when the store no longer holds it."""
    from .services import EVIDENCE_NAMESPACE

    if not file_exists(EVIDENCE_NAMESPACE, record.uri):
        return None
    with open_file(EVIDENCE_NAMESPACE, record.uri) as handle:
        return handle.read()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _as_page_source(data: bytes, name: str) -> io.BytesIO:
    """Bytes as the file-like object apps.evidence.pages reads."""
    source = io.BytesIO(data)
    source.name = name
    return source


def _is_page(record: EvidenceRecord) -> bool:
    extension = (record.file_extension or "").lower()
    return extension in _PAGE_TYPES or (record.mime_type or "").startswith("image/")


def _distinct_sources(records) -> list[tuple[EvidenceRecord, bytes]]:
    """Each record with its bytes, a file held twice kept once."""
    seen: set[str] = set()
    kept = []
    for record in records:
        data = _stored_bytes(record)
        if data is None:
            continue
        digest = _digest(data)
        if digest in seen:
            continue
        seen.add(digest)
        kept.append((record, data))
    return kept


def _upload_bytes(upload) -> bytes:
    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    return data


def add_form_pages(
    *, principal, activity_id: str, kind: str, files, another_page: bool = False
) -> dict:
    """The one door a governed form is uploaded through.

    The first upload is the form. A later one is taken only as another page
    of it, when the uploader says it is one; it is joined to the pages held
    and the one PDF replaces them."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from . import services

    files = [f for f in (files or []) if f]
    if not files:
        raise BadRequest("A file is required.")
    activity = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not activity:
        raise NotFoundError("Activity not found")
    services._assert_activity_in_scope(activity, principal)
    assert_takes_upload(activity)
    name = FORM_NAMES.get(kind, kind.replace("_", " ").title())

    existing = form_records(activity, kind)
    if not existing:
        return services.record_pages_upload(
            principal=principal, activity_id=activity_id, kind=kind, files=files
        )
    if not another_page:
        raise BadRequest(
            f"The {name} is already uploaded. Add a file only if it is a "
            "different page of that form; the same page is not uploaded twice."
        )

    held = _distinct_sources(existing)
    held_digests = {_digest(data) for _record, data in held}
    fresh_digests: set[str] = set()
    for upload in files:
        digest = _digest(_upload_bytes(upload))
        label = getattr(upload, "name", "") or "This file"
        if digest in held_digests:
            raise BadRequest(
                f"{label} is already in the uploaded {name}. Only a "
                "different page is added."
            )
        if digest in fresh_digests:
            raise BadRequest(f"{label} was chosen twice. Add each page once.")
        fresh_digests.add(digest)

    # Each new page is checked and scanned like any upload before it is
    # joined to the pages already held.
    services.check_pages(files)
    sources = [
        _as_page_source(data, record.original_name or record.uri)
        for record, data in held
        if _is_page(record)
    ]
    merged, count = pages.merge_pages([*sources, *files])
    with transaction.atomic():
        record = services.record_upload(
            principal=principal,
            activity_id=activity_id,
            kind=kind,
            file_obj=SimpleUploadedFile(
                f"{name} ({count} pages).pdf", merged, content_type="application/pdf"
            ),
            max_size=pages.MERGED_MAX_SIZE,
        )
        retired = [
            (r.uri, r.pdf_rendition_storage_key)
            for r in existing
            if _is_page(r) and r.id != record["id"]
        ]
        EvidenceRecord.objects.filter(
            id__in=[r.id for r in existing if _is_page(r) and r.id != record["id"]]
        ).delete()
    # Their pages are in the new document; the files they were are let go
    # once the change is safely made.
    for uri, rendition in retired:
        best_effort_delete(services.EVIDENCE_NAMESPACE, uri)
        if rendition:
            best_effort_delete(services.EVIDENCE_NAMESPACE, rendition)
    return {**record, "pages": count, "addedTo": [r.id for r in existing]}


def document_response(activity_id: str, principal, *, download: bool = False):
    """The activity's uploaded form as one PDF.

    One record that is a PDF is sent as it is. A photo, or several records
    from before one document was the rule, are drawn into one PDF: the
    records that differ, in the order they were uploaded."""
    from . import services

    activity = (
        Activity.objects.filter(id=activity_id, deleted_at__isnull=True)
        .select_related("school", "cluster")
        .first()
    )
    if not activity:
        raise NotFoundError("Activity not found.")
    services._assert_activity_readable(activity, principal)
    records = form_records(activity)
    held = _distinct_sources(records)
    if not held:
        raise NotFoundError("No form has been uploaded for this activity.")

    place = (
        activity.school.name
        if activity.school_id
        else (activity.cluster.name if activity.cluster_id else "")
    )
    filename = (
        " - ".join(part for part in (form_name(activity), place) if part) + ".pdf"
    )
    drawable = [(record, data) for record, data in held if _is_page(record)]
    if not drawable:
        # A file that cannot be drawn as pages (an old Word document): it is
        # handed over as it is rather than reported missing.
        record, data = held[0]
        response = HttpResponse(
            data, content_type=record.mime_type or "application/octet-stream"
        )
        response["Content-Disposition"] = content_disposition_header(
            True, record.original_name or record.uri
        )
    else:
        first, first_data = drawable[0]
        if len(drawable) == 1 and (first.file_extension or "").lower() == ".pdf":
            body = first_data
        else:
            body, _count = pages.merge_pages(
                [
                    _as_page_source(data, record.original_name or record.uri)
                    for record, data in drawable
                ],
                max_pages=_READ_MAX_PAGES,
            )
        response = HttpResponse(body, content_type="application/pdf")
        response["Content-Disposition"] = content_disposition_header(
            bool(download), filename
        )
    response["X-Content-Type-Options"] = "nosniff"
    # The form is read in a popup on the page that offers it (owner,
    # 2026-10-14: "make the pdf upload view a popup with download button"), so
    # this one address may be framed, by this site and no other. Every other
    # evidence address stays unframeable.
    response["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'self'"
    response["X-Frame-Options"] = "SAMEORIGIN"
    for record, _data in held:
        EvidenceRecord.objects.filter(id=record.id).update(
            view_count=record.view_count + 1
        )
    return response
