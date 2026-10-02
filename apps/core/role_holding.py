"""Who holds a role, as distinct from the role an account is switched to.

Owner, 2026-10-02: "PL are not seeing all the plans for their cceos". An
account carries every role its person holds (``User.roles``) and the one in
use today (``User.active_role``). The team screens asked for the role in use,
so a CCEO who also coordinates a project and was working in that role lost
their tab on the Programme Lead's Team Plan and left the Lead's week
altogether, while their plans stayed where they were. A team is the people
who HOLD the role, whichever one they are switched to — the reading
``apps.planning.country_oversight.rules.roster`` already takes.

``active_role`` counts as held too, so an account whose role list was never
filled in still belongs where it works.
"""

from __future__ import annotations

from django.db.models import Q


def holds_role_q(role, prefix: str = "user") -> Q:
    """Rows whose user holds ``role``. ``prefix`` is the path to the user
    ("user", "supervisor__user"); blank when filtering users themselves."""
    role = str(getattr(role, "value", role))
    path = f"{prefix}__" if prefix else ""
    return Q(**{f"{path}active_role": role}) | Q(**{f"{path}roles__contains": [role]})


def holds_role(user, role) -> bool:
    """Whether this user holds ``role``, in use today or not."""
    if user is None:
        return False
    role = str(getattr(role, "value", role))
    if (getattr(user, "active_role", "") or "") == role:
        return True
    return role in {str(r) for r in (getattr(user, "roles", None) or [])}


__all__ = ["holds_role", "holds_role_q"]
