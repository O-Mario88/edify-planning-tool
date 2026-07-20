import logging

logger = logging.getLogger(__name__)


class InterventionSeverityClassifier:
    """Classifies school average SSA score (0.0 to 10.0 scale) into severity bands."""

    @staticmethod
    def classify_severity(score: float | None) -> str:
        # Single source of truth for the 0-10 bands
        # (apps.core.enums.ssa_score_band): Critical 0-4.9 / Warning 5-6.9 /
        # Improving 7-7.9 / Strong 8-10. Those band labels are identical to
        # this classifier's historical vocabulary, so delegating removes a
        # duplicate threshold definition without changing any classification.
        # None (no SSA) now yields the honest canonical "No SSA" instead of
        # the old "Critical", which fabricated an urgent need out of missing
        # data (callers that face a no-SSA school handle it explicitly before
        # reaching here — see get_recommendation).
        from apps.core.enums import ssa_score_band

        return ssa_score_band(score)[0]

    @staticmethod
    def get_color(score: float | None) -> str:
        if score is None:
            return "red"
        if score < 5.0:
            return "red"
        elif score < 7.0:
            return "yellow"
        elif score < 8.0:
            return "light-green"
        else:
            return "green"

    @staticmethod
    def get_owner_type(score: float | None) -> str:
        if score is None:
            return "partner"
        if score < 5.0:
            return "partner"
        elif score < 7.0:
            return "staff"
        elif score < 8.0:
            return "monitor"
        else:
            return "maintain"


class OwnerRecommendationService:
    """Provides recommendations on who should own or support the school based on severity classification."""

    @staticmethod
    def recommend_owner(score: float | None) -> str:
        severity = InterventionSeverityClassifier.classify_severity(score)
        if severity == "Critical":
            return "Partner (In-school coaching)"
        elif severity == "Warning":
            return "Staff (Visit/training support)"
        elif severity == "Improving":
            return "Monitor"
        else:
            return "Maintain/consider champion pathway"


class PlanningRecommendationService:
    """Generates planning readiness states, recommended actions, and reasons for schools."""

    @staticmethod
    def get_recommendation(
        school, has_catalogue=True, has_scheduled=False, partner_assignment=None
    ) -> dict:
        # 1. Cluster check
        if not school.cluster_id:
            return {
                "planningReadiness": "Cluster Required",
                "recommendedAction": "Add to Cluster",
                "reason": "Unclustered schools block activity scheduling.",
                "availableActions": ["Add to Cluster"],
                "blockedActions": [
                    "Schedule visit",
                    "Schedule training",
                ],
            }

        # 2. SSA check
        # Latest *confirmed* SSA — an unverified upload must never drive an
        # official planning recommendation (this used to read any latest
        # record regardless of verification_status; see
        # apps.ssa.services.latest_applicable_record).
        from apps.ssa.services import latest_applicable_record

        latest_ssa = latest_applicable_record(school)
        if not latest_ssa:
            return {
                "planningReadiness": "SSA Required",
                "recommendedAction": "Complete SSA",
                "reason": "Complete SSA first so intervention impact can be measured.",
                "availableActions": [
                    "Schedule",
                    "Schedule",
                    "Assign",
                    "Schedule",
                ],
                "blockedActions": [],
            }

        # 3. Band classification check
        score_val = latest_ssa.average_score
        if score_val is None:
            scores_qs = latest_ssa.scores.all()
            if scores_qs.exists():
                from django.db.models import Avg

                score_val = scores_qs.aggregate(Avg("score"))["score__avg"]
            if score_val is None:
                score_val = 0.0
        severity = InterventionSeverityClassifier.classify_severity(score_val)

        # Weakest area — the single most urgent intervention from the
        # canonical analytics engine (deterministic; this used to sort by
        # score alone over an unordered list, so tied scores picked the
        # weakest area non-deterministically).
        from apps.ssa.recommendation_engine import prioritized_interventions

        ranked = prioritized_interventions(school, n=1)
        weakest_area = ranked[0]["label"] if ranked else "general"

        if severity == "Critical":
            return {
                "planningReadiness": "Ready for Support",
                "recommendedAction": "Recommend Partner (In-school coaching)",
                "reason": f"Critical score ({score_val:.1f}/10.0) requires intensive in-school coaching. Weakest: {weakest_area}.",
                "availableActions": ["Assign", "Schedule"],
                "blockedActions": [],
            }
        elif severity == "Warning":
            return {
                "planningReadiness": "Ready for Support",
                "recommendedAction": "Recommend Staff (Visit/training support)",
                "reason": f"Warning score ({score_val:.1f}/10.0) requires targeted staff visits/trainings. Weakest: {weakest_area}.",
                "availableActions": ["Schedule visit", "Schedule training"],
                "blockedActions": [],
            }
        elif severity == "Improving":
            return {
                "planningReadiness": "Ready for Support",
                "recommendedAction": "Monitor",
                "reason": f"Stable/improving score ({score_val:.1f}/10.0). Continue light-touch monitoring. Weakest: {weakest_area}.",
                "availableActions": ["Schedule visit", "Schedule training"],
                "blockedActions": [],
            }
        else:
            return {
                "planningReadiness": "Ready for Support",
                "recommendedAction": "Maintain/consider champion pathway",
                "reason": f"Strong score ({score_val:.1f}/10.0). Maintain standards or nominate as Champion candidate.",
                "availableActions": ["Schedule visit", "Schedule training"],
                "blockedActions": [],
            }


# NOTE: a `CoreInterventionRecommendationService` used to live here too, with
# a get_weakest_interventions() that (a) read unverified SSA, (b) sorted by
# score with no tie-break, and (c) fabricated the first four enum
# interventions when a school had no SSA at all. It had zero callers — the
# real, used one is apps.core_schools.core_planning_services
# .CoreInterventionRecommendationService.recommend(), which is verified-only
# and now delegates its ranking to apps.ssa.recommendation_engine. The dead
# duplicate was removed to eliminate the fabrication trap and the confusing
# name collision.
