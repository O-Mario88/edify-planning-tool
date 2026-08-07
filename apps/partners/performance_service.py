"""What a partner's record actually says, and what it is not allowed to say.

A withdrawal rate that counts every ended assignment is a measure of a
partner's luck. Schools close, we hand over the wrong school, a road floods —
none of that is the partner's doing, and a number that cannot tell the
difference will eventually be used to end a contract.

So there is one rule here, and everything else follows from it: **only
partner-attributable withdrawals reach performance.** The attribution is set
from the reason in code (`REASON_ATTRIBUTION`), never chosen by the person
withdrawing, because somebody under pressure to explain a delay should not
also decide whether it counts against the partner.

The counts that are excluded are still reported — separately, and labelled.
A partner who has had four schools closed on them has a real problem worth
seeing; it is just not a performance problem.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PartnerRecord:
    """One partner's withdrawal history, with blame kept apart from bad luck."""

    partner_id: str
    partner_name: str = ""

    total_assignments: int = 0
    # Withdrawals this partner is answerable for.
    attributable: int = 0
    # Withdrawals that ended their work but were not their doing.
    not_attributable: int = 0
    by_reason: dict = field(default_factory=dict)
    by_attribution: dict = field(default_factory=dict)

    @property
    def withdrawal_rate(self) -> float | None:
        """Share of this partner's assignments they lost through their own doing.

        None rather than 0.0 when they have held no assignments: a partner with
        nothing to deliver has not achieved a perfect record, and a page that
        prints 0% invites exactly that reading.
        """
        if not self.total_assignments:
            return None
        return round(self.attributable * 100 / self.total_assignments, 1)

    @property
    def has_pattern(self) -> bool:
        """Enough attributable withdrawals to be worth a conversation.

        Deliberately a pattern rather than an event. One withdrawal is a bad
        week; the spec is explicit that a partner must not be terminated on the
        strength of one, and a flag that fires on the first is a flag that gets
        ignored by the third.
        """
        return self.attributable >= PATTERN_THRESHOLD


#: Three attributable withdrawals is where a pattern starts. Chosen rather
#: than derived: two is a coincidence often enough that flagging it would
#: train reviewers to dismiss the flag.
PATTERN_THRESHOLD = 3


def build_records(partner_ids=None, *, fy: str | None = None) -> list[PartnerRecord]:
    """Withdrawal history per partner, folded from the withdrawal records.

    One query over withdrawals and one over assignments, then folded in Python
    — the same shape the oversight pages use, so a partner's number here and
    the rows behind it cannot drift apart.
    """
    from apps.partners.models import Partner, PartnerAssignment
    from apps.partners.withdrawal_models import (
        PartnerAssignmentWithdrawal,
        WithdrawalAttribution,
        WithdrawalState,
    )

    partners = Partner.objects.filter(deleted_at__isnull=True)
    if partner_ids is not None:
        partners = partners.filter(id__in=list(partner_ids))
    records = {
        p.id: PartnerRecord(partner_id=p.id, partner_name=p.name) for p in partners
    }
    if not records:
        return []

    assignments = PartnerAssignment.objects.filter(partner_id__in=records)
    for partner_id, count in _counted(assignments, "partner_id"):
        if partner_id in records:
            records[partner_id].total_assignments = count

    withdrawals = PartnerAssignmentWithdrawal.objects.filter(
        partner_id__in=records
    ).exclude(
        # A rejected or cancelled request never took effect, so it is not a
        # thing that happened to the partner.
        state__in=(WithdrawalState.REJECTED, WithdrawalState.CANCELLED)
    )
    for w in withdrawals.values("partner_id", "attribution", "reason_category"):
        record = records.get(w["partner_id"])
        if record is None:
            continue
        if w["attribution"] == WithdrawalAttribution.PARTNER:
            record.attributable += 1
        else:
            record.not_attributable += 1
        record.by_attribution[w["attribution"]] = (
            record.by_attribution.get(w["attribution"], 0) + 1
        )
        record.by_reason[w["reason_category"]] = (
            record.by_reason.get(w["reason_category"], 0) + 1
        )

    return sorted(records.values(), key=lambda r: r.partner_name)


def _counted(queryset, field_name):
    from django.db.models import Count

    return (
        queryset.values(field_name).annotate(n=Count("id")).values_list(field_name, "n")
    )


def partners_needing_review(records=None) -> list[PartnerRecord]:
    """Partners whose attributable pattern is worth a human looking at.

    Returns candidates for a conversation, not a verdict. Nothing here
    suspends, offboards or blocks anybody — those are decisions with a
    person's name on them, and this only says where to look.
    """
    records = records if records is not None else build_records()
    return [r for r in records if r.has_pattern]
