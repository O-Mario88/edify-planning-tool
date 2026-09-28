"""Which schools a Partner supports, for the cluster drawers.

Owner rule, 2026-09-23: at a Partner-supported school, staff could plan only
Data Gathering, Content Gathering or a Donor Visit directly; everything else
was the Partner's, and only roles holding ``partnerSchool.planDirect`` /
``partnerSchool.planCluster`` could plan there or invite the school to a
cluster session. The drawer greyed the other purposes out and the create
service refused them ("This school is currently supported by …").

Owner, 2026-09-28, lifted it: "lift all restrictions. the only restriction is
for client schools to have one visit from the staff", and "yes remove the
partner-supported school lock too". A Partner-supported school is planned
like any other school. The drawer still names the Partner and its live plans
there, so nobody schedules on top of them without seeing them.

What remains is the cluster drawers' default: a Partner-supported member is
left unticked on first open, and joins a session because a planner ticked it.
"""

from __future__ import annotations


def partner_supported_members(school_ids, principal=None) -> dict[str, str]:
    """Which of these cluster members a Partner supports, and by whom.

    One query. The cluster drawers use it to leave those schools unticked on
    first open: a Partner-supported school joins a Cluster Meeting or Group
    Training because a planner ticked it by name, never because it is in the
    cluster (owner, 2026-09-23).
    """
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import (
        active_assignment_q,
        visibility_enabled,
    )

    ids = [i for i in school_ids if i]
    if not ids or not visibility_enabled(principal):
        return {}
    out: dict[str, str] = {}
    for school_id, name in (
        PartnerAssignment.objects.filter(school_id__in=ids)
        .filter(active_assignment_q())
        .order_by("created_at")
        .values_list("school_id", "partner__name")
    ):
        if school_id in out and out[school_id] != name:
            out[school_id] = "Multiple Partners"
        else:
            out.setdefault(school_id, name)
    return out


__all__ = ["partner_supported_members"]
