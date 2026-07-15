"""PeerSolutionService — CCEO-to-CCEO collaborative problem-solving on
same-team debriefs (§16). Endorsing/proposing is only possible on a debrief
the principal can already read — `FieldDebriefService.scoped_queryset()`
already restricts a CCEO to their own-team peers and excludes restricted
incidents, so peer solutions can never leak into another team's debrief or
a safeguarding/fraud incident.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from .field_debrief_service import FieldDebriefService
from .models import DailyDebriefPeerSolution, PeerSolutionStatus

PL_CLASSIFIER_ROLES = ("Program Lead", "CountryDirector", "Admin")


class PeerSolutionService:
    @staticmethod
    def propose(
        principal, debrief_id: str, *, suggestion: str, related_experience: str = ""
    ) -> DailyDebriefPeerSolution:
        if not suggestion or not suggestion.strip():
            raise BadRequest("A suggestion is required.")
        debrief = FieldDebriefService.get_one(principal, debrief_id)
        if debrief.submitted_by_user_id == principal.user_id:
            raise BadRequest("You cannot propose a peer solution on your own debrief.")
        solution = DailyDebriefPeerSolution.objects.create(
            debrief=debrief,
            author_user_id=principal.user_id,
            suggestion=suggestion.strip(),
            related_experience=related_experience or None,
        )
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="field_debrief_peer_solution",
            category="field_debrief",
            priority="normal",
            title="A peer proposed a solution on your debrief",
            body=suggestion.strip()[:200],
            context_type="field_debrief",
            context_id=debrief.id,
            recipients=[debrief.submitted_by_user_id],
        )
        return solution

    @staticmethod
    def endorse(principal, solution_id: str) -> DailyDebriefPeerSolution:
        solution = (
            DailyDebriefPeerSolution.objects.select_related("debrief")
            .filter(id=solution_id)
            .first()
        )
        if not solution:
            raise BadRequest("Peer solution not found.")
        if not FieldDebriefService.can_read(principal, solution.debrief):
            raise Forbidden("You cannot view this debrief.")
        if principal.user_id not in solution.endorsed_by_user_ids:
            solution.endorsed_by_user_ids = [
                *solution.endorsed_by_user_ids,
                principal.user_id,
            ]
            if solution.status == PeerSolutionStatus.PROPOSED:
                solution.status = PeerSolutionStatus.UNDER_DISCUSSION
            solution.save(update_fields=["endorsed_by_user_ids", "status"])
            if solution.author_user_id and solution.author_user_id != principal.user_id:
                from apps.notifications.services import WorkflowNotificationService

                WorkflowNotificationService.trigger(
                    event_type="field_debrief_peer_solution_endorsed",
                    category="field_debrief",
                    priority="normal",
                    title="Your peer solution was endorsed",
                    body=solution.suggestion[:200],
                    context_type="field_debrief",
                    context_id=solution.debrief_id,
                    recipients=[solution.author_user_id],
                )
        return solution

    @staticmethod
    def pl_classify(
        principal, solution_id: str, *, classification: str
    ) -> DailyDebriefPeerSolution:
        role = getattr(principal, "active_role", "")
        if role not in PL_CLASSIFIER_ROLES:
            raise Forbidden("Only a Program Lead may classify a peer solution.")
        solution = (
            DailyDebriefPeerSolution.objects.select_related("debrief")
            .filter(id=solution_id)
            .first()
        )
        if not solution:
            raise BadRequest("Peer solution not found.")
        if not FieldDebriefService.can_read(principal, solution.debrief):
            raise Forbidden("You cannot view this debrief.")

        solution.pl_classification = classification
        solution.pl_classified_by_user_id = principal.user_id
        solution.pl_classified_at = timezone.now()
        status_map = {
            "adopt_for_team": PeerSolutionStatus.ADOPTED,
            "pilot": PeerSolutionStatus.PILOTING,
            "not_applicable": PeerSolutionStatus.REJECTED,
        }
        solution.status = status_map.get(classification, solution.status)
        solution.save(
            update_fields=[
                "pl_classification",
                "pl_classified_by_user_id",
                "pl_classified_at",
                "status",
            ]
        )
        if solution.author_user_id and solution.author_user_id != principal.user_id:
            from apps.notifications.services import WorkflowNotificationService

            WorkflowNotificationService.trigger(
                event_type="field_debrief_peer_solution_classified",
                category="field_debrief",
                priority="normal",
                title=f"Your peer solution was classified: {solution.get_pl_classification_display()}",
                body=solution.suggestion[:200],
                context_type="field_debrief",
                context_id=solution.debrief_id,
                recipients=[solution.author_user_id],
            )
        return solution
