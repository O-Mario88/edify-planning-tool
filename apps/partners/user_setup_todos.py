"""Configure Partner Users — the user administrators' To-Do (owner, 2026-09-15).

Impact Assessment may add a partner organisation but never sets up the logins
its people use. The organisation waits with ``user_setup_status = pending``
until an Admin or Country Director links, invites or waives a login
(``partners.services.configure_partner_user``).

One row for the whole queue, not one per organisation: the directory lists
them, and a queue of near-identical rows is noise. The row disappears the
moment no organisation is pending.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def partner_user_setup_todos(principal, role, today) -> list[dict]:
    from apps.command_center.derived_rows import todo_row
    from apps.partners.models import Partner, PartnerUserSetupStatus
    from apps.partners.services import may_manage_partner_users

    try:
        if not may_manage_partner_users(principal):
            return []
        pending = list(
            Partner.objects.filter(
                deleted_at__isnull=True,
                user_setup_status=PartnerUserSetupStatus.PENDING,
            )
            .order_by("created_at")
            .values_list("name", flat=True)[:4]
        )
        if not pending:
            return []
        total = Partner.objects.filter(
            deleted_at__isnull=True,
            user_setup_status=PartnerUserSetupStatus.PENDING,
        ).count()
        names = ", ".join(pending[:3]) + (" and more" if total > 3 else "")
        return [
            todo_row(
                "partner-user-setup",
                title="Configure Partner Users",
                description=(
                    f"{total} partner organisation{'s' if total != 1 else ''} "
                    f"without a login set up: {names}."
                ),
                category="Partners",
                priority="high",
                url="/admin-panel/users#partner-directory-title",
                action="Set up logins",
                linked=f"{total} organisation{'s' if total != 1 else ''}",
                today=today,
                source="Partner organisations",
            )
        ]
    except Exception:  # noqa: BLE001 - one source never breaks the queue
        logger.exception("Partner user setup To-Dos failed")
        return []
