"""One evidence file from several pages (owner, 2026-09-26).

"Sometimes the attendance form has many pages. Allow multiple uploads and
merge them into one file with those pages, and render as one file with many
pages — only the pages uploaded." A field officer photographs each page of a
form, or chooses several photos or PDFs; this builds the one PDF the form is
stored and opened as, in the order the pages were added.

A photo becomes one A4 page, turned upright from its camera orientation and
fitted with margins (the same page _try_image_to_pdf draws for one photo). A
PDF contributes every page it has. Nothing else is added: no cover, no blank
page.

Validation and the malware scan happen on every page before this is called
(apps.evidence.services.record_pages_upload); this module only assembles.
"""

from __future__ import annotations

import io

from apps.core.exceptions import BadRequest

#: The most pages one upload may carry: a long attendance register fits,
#: an accidental camera roll does not.
MAX_PAGES = 20
#: The merged file's ceiling. Each page is still held to the single-file
#: limit (validation.MAX_FILE_SIZE) before it is merged.
MERGED_MAX_SIZE = 25 * 1024 * 1024

#: A4 at 150 DPI, portrait and landscape.
_A4_PORTRAIT = (1240, 1754)
_A4_LANDSCAPE = (1754, 1240)
_MARGIN = 40
_DPI = 150.0


def a4_page(image):
    """A Pillow image as an upright A4 page, fitted with margins on white."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(image)
    if img.mode != "RGB":
        img = img.convert("RGB")
    width, height = _A4_LANDSCAPE if img.width > img.height else _A4_PORTRAIT
    avail_w = max(100, width - 2 * _MARGIN)
    avail_h = max(100, height - 2 * _MARGIN)
    scale = min(avail_w / img.width, avail_h / img.height)
    size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    resized = img.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), color=(255, 255, 255))
    canvas.paste(resized, ((width - size[0]) // 2, (height - size[1]) // 2))
    return canvas


def _is_pdf(upload) -> bool:
    name = (getattr(upload, "name", "") or "").lower()
    upload.seek(0)
    head = upload.read(5)
    upload.seek(0)
    return name.endswith(".pdf") or head.startswith(b"%PDF")


def merge_pages(uploads) -> tuple[bytes, int]:
    """(PDF bytes, page count) for these uploads, in order."""
    from PIL import Image
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError

    writer = PdfWriter()
    pages = 0
    for upload in uploads:
        name = getattr(upload, "name", "") or "file"
        if _is_pdf(upload):
            try:
                reader = PdfReader(upload)
                if reader.is_encrypted and not reader.decrypt(""):
                    raise BadRequest(
                        f"{name} is password-protected; upload it without a password."
                    )
                for page in reader.pages:
                    pages += 1
                    if pages > MAX_PAGES:
                        break
                    writer.add_page(page)
            except PdfReadError as exc:
                raise BadRequest(f"{name} could not be read as a PDF.") from exc
        else:
            try:
                with Image.open(upload) as raw:
                    page = a4_page(raw)
            except (OSError, ValueError) as exc:
                raise BadRequest(f"{name} could not be read as a photo.") from exc
            buffer = io.BytesIO()
            page.save(buffer, "PDF", resolution=_DPI)
            buffer.seek(0)
            pages += 1
            if pages <= MAX_PAGES:
                writer.add_page(PdfReader(buffer).pages[0])
        if pages > MAX_PAGES:
            raise BadRequest(
                f"One upload holds at most {MAX_PAGES} pages; this one has more."
            )
    if not pages:
        raise BadRequest("None of these files has a page to upload.")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), pages
