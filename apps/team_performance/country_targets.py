"""Country targets on the Team Performance report: IA or Admin set them.

Owner, 2026-10-20: "All country target should be set by either IA or Admin",
on the Team Performance page; the Country Director reads them and does not
set them ("No, IA and Admin only"). Region and CCEO targets stay the PLs' and
Project Coordinators' allocations.

A target is one report row's annual figure for the year, with an optional
month-by-month split that must add up to it. A row with no target here falls
back to the Uganda Master Priority Plan (`targets.TargetBook`). Every change
is audited with who made it, in which role.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole

SETTERS = {
    EdifyRole.IMPACT_ASSESSMENT.value: "Impact Assessment",
    EdifyRole.ADMIN.value: "Admin",
}
MONTHS = tuple(range(1, 13))
CENTS = Decimal("0.01")


def may_set(user) -> bool:
    return getattr(user, "active_role", "") in SETTERS


def parse(value) -> Decimal | None:
    """A typed figure: blank is no target, anything else a number."""
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise BadRequest(f"“{value}” is not a number.") from exc


def load(fy: str) -> dict[str, dict]:
    """key -> {"annual", "months", "source"} for the year."""
    from apps.targets.models import CountryReportTarget

    out = {}
    for row in CountryReportTarget.objects.filter(fy=str(fy)):
        months = None
        if row.monthly_targets:
            months = {int(m): float(v) for m, v in row.monthly_targets.items()}
        setter = SETTERS.get(row.set_by_role, row.set_by_role)
        out[row.key] = {
            "annual": float(row.annual_target),
            "months": months,
            "source": f"Country target ({setter})",
        }
    return out


def _clean(key: str, annual, months) -> tuple[Decimal | None, dict | None]:
    if annual is not None and annual < 0:
        raise BadRequest(f"{key}: a target cannot be negative.")
    if not months or all(v is None for v in months.values()):
        return annual, None
    values = {m: (months.get(m) or Decimal(0)) for m in MONTHS}
    if any(v < 0 for v in values.values()):
        raise BadRequest(f"{key}: a month's target cannot be negative.")
    total = sum(values.values())
    if annual is None:
        annual = total
    elif total != annual:
        raise BadRequest(
            f"{key}: the months add up to {total:g}, not the annual {annual:g}."
        )
    return annual, {str(m): str(v.quantize(CENTS)) for m, v in values.items()}


@transaction.atomic
def save(user, fy: str, rows: dict) -> int:
    """Save {key: (annual, months)}; a blank annual with no months clears the
    row. Returns how many rows changed."""
    from apps.audit.services import log
    from apps.targets.models import CountryReportTarget

    role = getattr(user, "active_role", "")
    if role not in SETTERS:
        raise Forbidden("Country targets are set by Impact Assessment or Admin.")
    fy = str(fy)
    existing = {t.key: t for t in CountryReportTarget.objects.filter(fy=fy)}
    changed = 0
    for key, (annual, months) in rows.items():
        annual, months = _clean(key, annual, months)
        current = existing.get(key)
        before = (
            (str(current.annual_target), current.monthly_targets) if current else None
        )
        if annual is None:
            if current is None:
                continue
            current.delete()
            after = None
        else:
            after = (str(Decimal(annual).quantize(CENTS)), months)
            if before == after:
                continue
            CountryReportTarget.objects.update_or_create(
                fy=fy,
                key=key,
                defaults={
                    "annual_target": annual,
                    "monthly_targets": months,
                    "set_by_user_id": str(user.id),
                    "set_by_role": role,
                },
            )
        changed += 1
        log(
            action="team_performance.country_target_set",
            subject_kind="CountryReportTarget",
            subject_id=f"{fy}:{key}",
            actor_id=str(user.id),
            actor_role=role,
            payload={"before": before, "after": after},
        )
    return changed
