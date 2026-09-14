"""What a user still owes on mandatory policies.

This module held the mandatory-policy access gate: middleware that withheld the
whole application from anyone with an unanswered or declined blocking policy
and sent them to the Agreement Center. The owner removed that blocking gate on
2026-09-14. Policies are still published, read and acknowledged at
/policy-agreement, and HR still sees who has and has not answered; an
outstanding answer no longer stands between a person and their work.

What remains is the resolver the Agreement Center and the audit scripts read:
which blocking acknowledgements a person has not answered, which they declined,
and a one-word summary of the two.
"""

from __future__ import annotations


class PolicyGateService:
    """Resolves which blocking policies a user has not answered or declined."""

    @staticmethod
    def any_blocking_policy_exists() -> bool:
        """Is there a live policy marked as blocking at all?

        The common case has to be cheap. Until somebody publishes a policy
        marked as blocking, one EXISTS query answers the whole question and the
        two per-user reads below never happen. Memoised per request, so a page
        that asks several times does not repeat even that.
        """
        from apps.core import request_cache
        from apps.documents.models import DocumentAsset, READABLE_STATUSES

        def compute():
            return DocumentAsset.objects.filter(
                status__in=READABLE_STATUSES,
                blocks_application_access=True,
                acknowledgement_required=True,
            ).exists()

        return request_cache.memoize("documents.blocking_policy_exists", compute)

    @staticmethod
    def blocking_acknowledgements(user):
        from apps.documents.services import AcknowledgementService

        return AcknowledgementService.blocking_for(user)

    @staticmethod
    def disagreements(user):
        from apps.documents.services import AcknowledgementService

        return AcknowledgementService.disagreed_for(user)

    @staticmethod
    def state_for(user) -> tuple[str, list]:
        """('clear' | 'pending' | 'restricted', acknowledgements)."""
        if not PolicyGateService.any_blocking_policy_exists():
            return "clear", []
        declined = PolicyGateService.disagreements(user)
        if declined:
            return "restricted", declined
        pending = PolicyGateService.blocking_acknowledgements(user)
        if pending:
            return "pending", pending
        return "clear", []
