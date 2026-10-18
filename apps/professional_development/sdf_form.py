"""The Staff Development Fund request form — on screen and as its PDF.

Owner, 2026-10-18: "The application form is attached. Build that form exactly
the way it is ... a completed form should be rendered in PDF exactly the way
it is in the attachment first page." One sheet of figures (``sheet``) feeds
both the drawer and the PDF (``render_pdf``), so the two cannot disagree.

Where each box comes from:

* Full Name, Position, Manager — the request's own copy of the employee's
  details, taken when it was written.
* Details — purpose, start and end dates, duration, title, and "How will this
  course impact your work in Edify?" (``relevance_to_role``).
* Budget — approximate cost (the total cost, in the allocation's currency),
  amount requested (in the currency it is paid in, when that is another one)
  and the fiscal year.
* Authorization — the manager's decision, comment, name and date.
* Office Use Only — the staff member's SDF entitlement and balance, and the
  Regional HRD's and Country Director's names and dates.
* Accounting Authorization — whoever disbursed the funds, and when.

A signature box holds the signer's name, written as a signature, once they
have signed in the platform; it stays empty until then. The platform records
who decided and when (the audit chain), which is what the paper signature
stood for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from django.conf import settings

from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentAllocation,
    ProfessionalDevelopmentRequest,
)

#: Accents the form uses: the title's slate blue and the margin's grey band.
TITLE_RGB = (72, 108, 140)
BAND_RGB = (165, 180, 195)
INK_RGB = (25, 25, 25)
SIGNATURE_RGB = (40, 60, 110)
LINE_RGB = (90, 90, 90)

CURRENCY_SYMBOLS = {"USD": "$"}


def money(cents: int | None, currency: str | None) -> str:
    """ "$219.12" for dollars, "UGX 943,688.50" for anything else; "" for none."""
    if cents in (None, 0):
        return ""
    amount = f"{cents / 100:,.2f}"
    code = (currency or "USD").upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    return f"{symbol}{amount}" if symbol else f"{code} {amount}"


def _day(moment) -> str:
    if not moment:
        return ""
    from django.utils import timezone

    if hasattr(moment, "hour"):
        moment = timezone.localtime(moment).date()
    return moment.isoformat()


@dataclass(frozen=True)
class Signature:
    name: str = ""
    signed: bool = False
    date: str = ""


def _names(user_ids) -> dict[str, str]:
    from apps.accounts.models import User

    ids = [i for i in user_ids if i]
    return dict(User.objects.filter(id__in=ids).values_list("id", "name"))


def _manager_decision(req: ProfessionalDevelopmentRequest) -> str:
    """ "approved" | "denied" | "" — the form's two radio buttons."""
    if req.status == PDStatus.REJECTED:
        return "denied"
    if req.supervisor_reviewed_at and req.status not in (
        PDStatus.RETURNED_BY_SUPERVISOR,
        PDStatus.DRAFT,
    ):
        return "approved"
    return ""


def _authorization_note(req: ProfessionalDevelopmentRequest) -> str:
    """The comment under the radio buttons: the reason a request was denied,
    by whoever denied it, else the manager's own comment."""
    if req.status == PDStatus.REJECTED:
        return req.cd_note or req.hr_note or req.supervisor_note or ""
    return req.supervisor_note or ""


def sheet(req: ProfessionalDevelopmentRequest) -> dict:
    """Every box of the form, as text."""
    from apps.professional_development.services import StaffPDService

    disbursement = None
    fund = getattr(req, "fund_request", None) if req.pk else None
    if fund is not None:
        disbursement = fund.disbursements.order_by("disbursed_at").first()
    names = _names(
        (
            req.supervisor_reviewed_by,
            req.hr_reviewed_by,
            req.cd_reviewed_by,
            getattr(disbursement, "disbursed_by", None),
        )
    )

    def signed(user_id, moment) -> Signature:
        name = names.get(user_id or "", "")
        return Signature(name=name, signed=bool(name and moment), date=_day(moment))

    allocation = ProfessionalDevelopmentAllocation.objects.filter(
        staff_id=req.staff_id, fy=req.fy
    ).first()
    entitlement = allocation.annual_allocation if allocation else 0
    used = StaffPDService.committed_and_accounted_cents(req.staff_id, req.fy)
    # Office use is filled once HR has decided, as the form's office would.
    office = req.hr_reviewed_at is not None and req.status not in (
        PDStatus.RETURNED_BY_HR,
        PDStatus.REJECTED,
    )
    manager = signed(req.supervisor_reviewed_by, req.supervisor_reviewed_at)
    if not manager.name and req.supervisor_name:
        manager = Signature(name=req.supervisor_name)
    requested_local = money(
        req.requested_local_amount_cents, req.requested_local_currency
    )
    return {
        "full_name": req.staff_name or "",
        "position": req.position or "",
        "manager": req.supervisor_name or "",
        "purpose": req.purpose or "",
        "start_date": _day(req.start_date),
        "end_date": _day(req.end_date),
        "duration": req.duration or "",
        "title": req.course_name or "",
        "impact": req.relevance_to_role or "",
        "approximate_cost": money(req.total_cost_cents, req.currency),
        "amount_requested": requested_local
        or money(req.requested_amount_cents, req.currency),
        "fiscal_year": req.fy or "",
        "decision": _manager_decision(req),
        "authorization_note": _authorization_note(req),
        "manager_signature": manager,
        "entitlement": f"{entitlement / 100:,.0f}" if office and entitlement else "",
        "balance_due": f"{max(0, entitlement - used) / 100:,.0f}"
        if office and entitlement
        else "",
        "hr_signature": signed(req.hr_reviewed_by, req.hr_reviewed_at),
        "cd_signature": signed(req.cd_reviewed_by, req.cd_reviewed_at),
        "accounting_signature": signed(
            getattr(disbursement, "disbursed_by", None),
            getattr(disbursement, "disbursed_at", None),
        ),
    }


# ── The PDF ──────────────────────────────────────────────────────────────────
def _latin1(text: str) -> str:
    """The PDF's core fonts are Latin-1: typographic punctuation is written
    plainly and anything else is replaced, never dropped silently."""
    table = {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
        " ": " ",
    }
    for old, new in table.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def _logo():
    """The Edify wordmark in the form's slate blue. The platform's logo is
    white (it sits on the dark sidebar), so its shape is kept and recoloured,
    which keeps one source of the mark rather than a second image file."""
    from io import BytesIO

    from PIL import Image

    path = os.path.join(str(settings.BASE_DIR), "static", "images", "logo.png")
    if not os.path.exists(path):
        return None
    with Image.open(path) as source:
        alpha = source.convert("RGBA").getchannel("A")
    tinted = Image.new("RGBA", alpha.size, (*TITLE_RGB, 255))
    tinted.putalpha(alpha)
    out = BytesIO()
    tinted.save(out, format="PNG")
    out.seek(0)
    return out


class _Form:
    """Draws the form in points on an A4 page, at the attachment's places."""

    def __init__(self):
        from fpdf import FPDF

        self.pdf = FPDF(orientation="P", unit="pt", format="A4")
        self.pdf.set_auto_page_break(auto=False)
        self.pdf.set_margins(0, 0, 0)
        self.pdf.add_page()
        self.pdf.set_draw_color(*LINE_RGB)

    def text(self, x, y, value, *, font="Times", style="", size=11.5, rgb=INK_RGB):
        self.pdf.set_font(font, style, size)
        self.pdf.set_text_color(*rgb)
        self.pdf.text(x, y, _latin1(value))

    def rule(self, x1, y, x2):
        self.pdf.set_line_width(0.6)
        self.pdf.line(x1, y, x2, y)

    def heading(self, x, y, value):
        self.text(x, y, value, style="BU", size=12)

    def _frame(self, x, y, w, h):
        self.pdf.set_line_width(0.5)
        self.pdf.rect(x, y, w, h, style="D", round_corners=True, corner_radius=1.5)

    def _fit(self, value, w, size, font="Helvetica", style=""):
        self.pdf.set_font(font, style, size)
        while size > 5 and self.pdf.get_string_width(value) > w - 4:
            size -= 0.5
            self.pdf.set_font(font, style, size)
        return size

    def box(self, x, y, w, h, value="", *, size=9.5):
        """A field: a thin rounded box with its value written inside, shrunk
        to fit as the attachment's long title is."""
        self._frame(x, y, w, h)
        if not value:
            return
        value = _latin1(value)
        size = self._fit(value, w, size)
        self.pdf.set_text_color(*INK_RGB)
        self.pdf.text(x + 2.5, y + h / 2 + size * 0.35, value)

    def area(self, x, y, w, h, value="", *, size=8.5):
        """A box of several lines (the impact and authorization boxes)."""
        self._frame(x, y, w, h)
        if not value:
            return
        self.pdf.set_font("Helvetica", "", size)
        self.pdf.set_text_color(*INK_RGB)
        self.pdf.set_xy(x + 1.5, y + 2)
        self.pdf.multi_cell(w - 3, size * 1.35, _latin1(value), align="L")

    def signature(self, x, y, w, h, sig: Signature):
        self._frame(x, y, w, h)
        if not sig.signed:
            return
        value = _latin1(sig.name)
        size = self._fit(value, w, 10.5, font="Times", style="I")
        self.pdf.set_text_color(*SIGNATURE_RGB)
        self.pdf.text(x + 2, y + h / 2 + size * 0.35, value)

    def radio(self, x, y, checked):
        self.pdf.set_line_width(0.6)
        self.pdf.circle(x + 5, y + 5, 5, style="D")
        if checked:
            self.pdf.set_fill_color(*INK_RGB)
            self.pdf.circle(x + 5, y + 5, 2.6, style="F")


def render_pdf(req: ProfessionalDevelopmentRequest) -> bytes:
    """The completed form, drawn where the attachment's first page has it."""
    s = sheet(req)
    f = _Form()
    pdf = f.pdf

    # The grey band down the left margin, the title and the logo.
    pdf.set_fill_color(*BAND_RGB)
    pdf.rect(0, 0, 15, 842, style="F")
    f.text(
        61,
        90,
        "STAFF DEVELOPMENT FUND REQUEST FORM",
        font="Helvetica",
        style="B",
        size=13,
        rgb=TITLE_RGB,
    )
    logo = _logo()
    if logo:
        pdf.image(logo, x=437, y=52, w=96)
    f.rule(61, 103, 534)
    f.text(
        75,
        118,
        "Please refer to the Staff Development Fund Policy before completing "
        "this form.",
        size=9.5,
    )

    # Who is asking.
    for label, value, y in (
        ("Full Name", s["full_name"], 139),
        ("Position", s["position"], 167),
        ("Manager", s["manager"], 199),
    ):
        f.text(41, y + 14, label)
        f.box(133, y, 166, 20, value)
    for line, y in (
        ("Please attach a copy of:", 151),
        ("a) the conference and/or training course programme", 167),
        ("and registration forms (including dates, location,", 181),
        ("registration fees etc.)", 194),
        ("b) your abstract (optional)", 211),
    ):
        f.text(317, y, line, size=9.5)
    f.rule(59, 227, 534)

    # Details.
    f.heading(59, 241, "Details")
    for label, value, y in (
        ("Purpose for Which Funding is Sought", s["purpose"], 253),
        ("Start Date of Proposed Activity", s["start_date"], 274),
        ("End Date of Proposed Activity", s["end_date"], 294),
        ("Duration of Activity", s["duration"], 315),
        ("Title of Course, Conference, Paper", s["title"], 336),
    ):
        f.text(59, y + 12, label, size=9.5)
        f.box(362, y, 150, 18, value)
    for line, y in (
        ("How will this", 381),
        ("course impact your", 395),
        ("work in Edify?", 408),
    ):
        f.text(62, y, line, size=9.5)
    f.area(157, 361, 358, 63, s["impact"])
    f.rule(61, 427, 534)

    # Budget.
    f.heading(61, 446, "Budget")
    for label, value, y in (
        ("Approximate cost of Activity", s["approximate_cost"], 450),
        ("Amount Requested", s["amount_requested"], 473),
        ("What Fiscal Year are the Funds budgeted for?", s["fiscal_year"], 496),
    ):
        f.text(61, y + 12, label, size=9.5)
        f.box(379, y, 137, 19, value, size=11)
    f.rule(61, 515, 534)

    # Authorization.
    f.heading(61, 534, "Authorization")
    f.radio(61, 545, s["decision"] == "approved")
    f.text(
        80,
        554,
        "Approved, the source of funding is available and I fully support "
        "this request form.",
        size=10.5,
    )
    f.radio(61, 562, s["decision"] == "denied")
    f.text(
        80,
        571,
        "Denied, the source of funding is not available. If No, further "
        "reasons provided below",
        size=10.5,
    )
    f.area(82, 582, 398, 50, s["authorization_note"], size=10)
    manager = s["manager_signature"]
    f.text(62, 657, "Manager Name:", size=10.5)
    f.box(159, 645, 97, 16, manager.name)
    f.text(262, 656, "Manager Signature:", size=10.5)
    f.signature(373, 645, 69, 16, manager)
    f.text(453, 657, "Date:", size=10.5)
    f.box(490, 645, 45, 16, manager.date, size=7.5)
    f.rule(61, 682, 534)

    # Office use only.
    f.heading(63, 701, "Office Use Only")
    f.text(63, 722, "Staff SDF Entitlement:", size=10.5)
    f.box(180, 711, 66, 16, s["entitlement"])
    f.text(286, 721, "Balance Due:", size=10.5)
    f.box(379, 711, 54, 16, s["balance_due"])
    hr = s["hr_signature"]
    f.text(63, 745, "Regional HRD Name:", size=10.5)
    f.box(176, 734, 90, 16, hr.name)
    f.text(272, 745, "Regional HRD Signature:", size=10.5)
    f.signature(401, 734, 73, 16, hr)
    f.text(480, 745, "Date:", size=10.5)
    f.box(509, 735, 29, 14, hr.date, size=5)
    cd = s["cd_signature"]
    f.text(52, 775, "Country Director Name:", size=10.5)
    f.box(178, 764, 90, 16, cd.name)
    f.text(276, 773, "Country Director Signature:", size=10.5)
    f.signature(418, 763, 72, 16, cd)
    f.text(495, 775, "Date:", size=10.5)
    f.box(524, 764, 29, 14, cd.date, size=5)
    f.rule(61, 797, 534)

    # Accounting.
    accounting = s["accounting_signature"]
    f.text(63, 818, "Accounting Autorization:", size=10.5)
    f.signature(176, 807, 165, 17, accounting)
    f.text(421, 818, "Date:", size=10.5)
    f.box(457, 807, 84, 17, accounting.date)

    return bytes(pdf.output())


def certificate_pdf(image_bytes: bytes) -> bytes:
    """A photographed or scanned certificate on one A4 page, as large as the
    page allows with a 10mm margin, turned to landscape when it is wider than
    tall (most certificates are)."""
    from io import BytesIO

    from fpdf import FPDF
    from PIL import Image, ImageOps

    with Image.open(BytesIO(image_bytes)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    landscape = image.width > image.height
    pdf = FPDF(orientation="L" if landscape else "P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    margin = 10
    room_w, room_h = pdf.w - 2 * margin, pdf.h - 2 * margin
    scale = min(room_w / image.width, room_h / image.height)
    w, h = image.width * scale, image.height * scale
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    buffer.seek(0)
    pdf.image(buffer, x=(pdf.w - w) / 2, y=(pdf.h - h) / 2, w=w, h=h)
    return bytes(pdf.output())
