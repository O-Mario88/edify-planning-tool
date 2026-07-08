import logging
from django.db.models import Avg
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.ssa.models import SsaRecord

logger = logging.getLogger(__name__)

class InterventionSeverityClassifier:
    """Classifies school average SSA score (0.0 to 10.0 scale) into severity bands."""
    @staticmethod
    def classify_severity(score: float | None) -> str:
        if score is None:
            return "Critical"  # Treat unassessed/no SSA as critical/high priority by default
        if score < 5.0:
            return "Critical"
        elif score < 7.0:
            return "Warning"
        elif score < 8.0:
            return "Improving"
        else:
            return "Strong"

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
    def get_recommendation(school, has_catalogue=True, has_scheduled=False, partner_assignment=None) -> dict:
        # 1. Cluster check
        if not school.cluster_id:
            return {
                "planningReadiness": "Cluster Required",
                "recommendedAction": "Add to Cluster",
                "reason": "Unclustered schools block activity scheduling.",
                "availableActions": ["Add to Cluster"],
                "blockedActions": ["Schedule visit", "Schedule training", "Assign to Partner"],
            }

        # 2. SSA check
        # Fetch latest SSA record
        latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if not latest_ssa:
            return {
                "planningReadiness": "SSA Required",
                "recommendedAction": "Schedule Baseline SSA Visit",
                "reason": "Complete SSA first so intervention impact can be measured.",
                "availableActions": ["Schedule SSA Visit", "Schedule School Visit + SSA", "Assign Partner SSA Collection", "Schedule Activity Anyway"],
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
        
        # Get weakest area
        scores = sorted(list(latest_ssa.scores.all().values("intervention", "score")), key=lambda x: x["score"])
        weakest_area = "general"
        if scores:
            code = scores[0]["intervention"]
            weakest_area = dict(SsaIntervention.choices).get(code, code)

        if severity == "Critical":
            return {
                "planningReadiness": "Ready for Support",
                "recommendedAction": "Recommend Partner (In-school coaching)",
                "reason": f"Critical score ({score_val:.1f}/10.0) requires intensive in-school coaching. Weakest: {weakest_area}.",
                "availableActions": ["Assign to Partner", "Schedule visit"],
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


class CoreInterventionRecommendationService:
    """Selects the four weakest SSA interventions (2 for partner, 2 for staff)."""
    @staticmethod
    def get_weakest_interventions(school_id, fy=None) -> dict:
        if not fy:
            fy = get_operational_fy()
            
        latest_ssa = SsaRecord.objects.filter(
            school_id=school_id, deleted_at__isnull=True
        ).order_by("-date_of_ssa").first()
        
        # All choices from SsaIntervention
        all_interventions = [choice[0] for choice in SsaIntervention.choices]
        
        if not latest_ssa:
            return {
                "partner": all_interventions[:2],
                "staff": all_interventions[2:4],
            }
            
        # Get sorted scores
        scores = list(latest_ssa.scores.all().order_by("score"))
        scored_interventions = [s.intervention for s in scores]
        
        # Fill in missing interventions
        remaining = [i for i in all_interventions if i not in scored_interventions]
        
        weakest_4 = scored_interventions[:4]
        while len(weakest_4) < 4 and remaining:
            weakest_4.append(remaining.pop(0))
            
        # 2 weakest to partner, next 2 to staff
        return {
            "partner": weakest_4[:2],
            "staff": weakest_4[2:4],
        }
