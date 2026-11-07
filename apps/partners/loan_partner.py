"""Loan Partners: partner organisations that lend through the loan workflow.

Owner, 2026-11-06: "Add loan partner as another partner role ... The loan
feature is different from the school visits and training. It will follow the
loan workflow."

The loan workflow already has its lenders: ``MfiOrganization`` rows, which
referrals, loan applications ("Preferred lending partner") and the loan
ledger offer. A Loan Partner is one of them. Saving an organisation as a Loan
Partner links it to the lender of the same name, or adds that lender, so the
loan workflow offers it from then on with nothing typed in twice.

Turning a Loan Partner back into a Delivery Partner leaves the lender and its
link alone: its referrals and loans belong to the loan workflow, which is
where a lender is retired.
"""

from __future__ import annotations

import re

from apps.core.exceptions import BadRequest

from .models import Partner, PartnerRole

#: Room left in ``MfiOrganization.code`` (32) for a "-NN" suffix.
_CODE_STEM_LENGTH = 28


def partner_role_from(value, *, default: str | None = None) -> str | None:
    """The posted role as a stored value; ``default`` when none was posted."""
    role = str(value or "").strip()
    if not role:
        return default
    if role not in PartnerRole.values:
        raise BadRequest("Choose Delivery Partner or Loan Partner.")
    return role


def _lender_code(name: str) -> str:
    from apps.business_transformation.models import MfiOrganization

    stem = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:_CODE_STEM_LENGTH]
    stem = stem.strip("-") or "LOAN-PARTNER"
    code, suffix = stem, 2
    while MfiOrganization.all_objects.filter(code=code).exists():
        code, suffix = f"{stem}-{suffix}", suffix + 1
    return code


def link_loan_lender(partner: Partner, actor_id: str | None = None) -> None:
    """Give a Loan Partner its lender in the loan workflow, once.

    A lender of the same name that no other partner holds is linked rather
    than copied; otherwise a new, active lender is added with the partner's
    contact details. Nothing happens to a Delivery Partner or to a Loan
    Partner that already has its lender.
    """
    if partner.partner_role != PartnerRole.LOAN or partner.loan_lender_id:
        return
    from django.utils import timezone

    from apps.business_transformation.models import MfiOrganization

    lender = MfiOrganization.objects.filter(
        name__iexact=partner.name, partner__isnull=True
    ).first()
    if lender is None:
        if MfiOrganization.all_objects.filter(name__iexact=partner.name).exists():
            raise BadRequest(
                f"The loan workflow already has a lender named '{partner.name}' "
                "that cannot be linked: it belongs to another partner or was "
                "removed. Rename the partner or the lender first."
            )
        lender = MfiOrganization.objects.create(
            code=_lender_code(partner.name),
            name=partner.name,
            contact_name=partner.contact_person or "",
            contact_email=partner.email or "",
            contact_phone=partner.phone or "",
            onboarded_by=actor_id,
            onboarded_at=timezone.now(),
        )
    partner.loan_lender = lender
    partner.save(update_fields=["loan_lender", "updated_at"])


def takes_school_work(partner) -> bool:
    """Whether school visits and trainings may be handed to ``partner``."""
    return getattr(partner, "partner_role", PartnerRole.DELIVERY) != PartnerRole.LOAN


def assert_takes_school_work(partner) -> None:
    if partner is not None and not takes_school_work(partner):
        raise BadRequest(
            f"{partner.name} is a Loan Partner. Its work goes through the loan "
            "workflow, not school visits or trainings — choose a Delivery "
            "Partner."
        )
