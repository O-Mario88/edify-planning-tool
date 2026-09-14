"""Record a new starter's policy obligations when they sign in.

Publication gives an acknowledgement to everyone who exists at that moment;
people who join later were given theirs by the blocking policy gate, which ran
`AcknowledgementService.ensure_pending_for` on their first request. The owner
removed that gate on 2026-09-14, so the reconciliation moves here: signing in
never waits on a policy, but HR's compliance register still lists what a new
starter owes.
"""

from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in, dispatch_uid="documents_policy_obligations_on_login")
def _record_policy_obligations(sender, request, user, **kwargs):
    from apps.documents.services import AcknowledgementService

    try:
        AcknowledgementService.ensure_pending_for(user)
    except Exception:  # a policy record must never stop someone signing in
        logger.exception("Could not record policy obligations for %s", user.pk)
