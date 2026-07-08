import logging
from django.db import transaction
from apps.schools.models import School
from apps.core_schools.models import CoreSchoolProfile, CorePlan

logger = logging.getLogger(__name__)

class ChampionEligibilityService:
    @staticmethod
    def calculate_score(school: School) -> dict:
        """Calculates the Champion Score and check items using the official formula."""
        # Retrieve CorePlan
        plan = CorePlan.objects.filter(school_id=school.school_id, status="Active").first()
        if not plan:
            return {"score": 0.0, "eligible": False, "reason": "No active Core Plan"}

        # 1. Latest SSA (40%)
        latest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("-date_of_ssa").first()
        if not latest_ssa:
            return {"score": 0.0, "eligible": False, "reason": "No SSA recorded"}
        latest_avg = latest_ssa.average_score or 0.0
        latest_score_weighted = (latest_avg / 10.0) * 40.0

        # 2. Improvement Delta (25%)
        # Compare latest with earliest SSA
        earliest_ssa = school.ssa_records.filter(deleted_at__isnull=True).order_by("date_of_ssa").first()
        delta = latest_avg - (earliest_ssa.average_score or 0.0) if earliest_ssa else 0.0
        # Score scales up to +3.0 points improvement
        delta_score = min(max(delta / 3.0, 0.0), 1.0) * 25.0

        # 3. Intervention Balance (15%)
        # No major intervention below 7.0
        scores = list(latest_ssa.scores.all().values_list("score", flat=True))
        lowest_score = min(scores) if scores else 0.0
        # If lowest is 7.0 or above, full points. Otherwise scale down.
        balance_score = (min(lowest_score, 7.0) / 7.0) * 15.0

        # 4. Core Package Completion (10%)
        # Total required slots are 8
        total_slots = plan.slots.count()
        completed_slots = plan.slots.filter(status__in=["Completed", "Closed", "ia_verified", "IA Verified"]).count()
        pkg_pct = (completed_slots / total_slots) if total_slots > 0 else 0.0
        package_score = pkg_pct * 10.0

        # 5. Evidence & IA Quality (5%)
        # Evidence completion rate on completed activities
        completed_activities = school.activities.filter(status="closed")
        total_closed = completed_activities.count()
        clean_evidence = completed_activities.filter(evidence_status="accepted").count()
        evidence_pct = (clean_evidence / total_closed) if total_closed > 0 else 1.0
        evidence_score = evidence_pct * 5.0

        # 6. Repeat Performance / Sustainability (5%)
        # At least two SSA records over time
        all_ssas = school.ssa_records.filter(deleted_at__isnull=True).count()
        sustain_score = 5.0 if all_ssas >= 2 else 2.5

        # Total Champion Score
        total_score = latest_score_weighted + delta_score + balance_score + package_score + evidence_score + sustain_score
        
        # Eligibility Checks
        eligible = (
            latest_avg >= 8.0 and 
            lowest_score >= 7.0 and 
            completed_slots >= 8
        )

        return {
            "score": round(total_score, 1),
            "eligible": eligible,
            "latest_avg": latest_avg,
            "lowest_score": lowest_score,
            "delta": round(delta, 1),
            "completed_slots": completed_slots,
            "total_slots": total_slots,
            "all_ssas": all_ssas,
            "evidence_pct": round(evidence_pct * 100, 1),
            "evidence_score": round(evidence_score, 1),
            "lowest_intervention": latest_ssa.scores.order_by("score").first().intervention if latest_ssa and latest_ssa.scores.exists() else "None"
        }

    @staticmethod
    def evaluate_all() -> list[dict]:
        """Scans all Core School Profiles and updates system proposed candidate statuses."""
        candidates = []
        profiles = CoreSchoolProfile.objects.all().select_related("core_plan")
        for profile in profiles:
            school = School.objects.filter(school_id=profile.school_id).first()
            if not school:
                continue
            
            metrics = ChampionEligibilityService.calculate_score(school)
            if metrics["eligible"]:
                if profile.champion_status not in ["Champion", "Approved Champion"]:
                    profile.champion_status = "Potential Champion"
                    profile.save(update_fields=["champion_status"])
                candidates.append({
                    "school": school,
                    "profile": profile,
                    "metrics": metrics
                })
        return candidates

    @staticmethod
    @transaction.atomic
    def approve(school_id: str, user_id: str) -> bool:
        """Approves a Potential Champion school to official Champion School status."""
        school = School.objects.filter(school_id=school_id).first()
        if not school:
            return False
        
        profile = CoreSchoolProfile.objects.filter(school_id=school_id).first()
        if not profile:
            return False
            
        profile.champion_status = "Champion"
        profile.save(update_fields=["champion_status"])
        
        school.school_type = "champion"
        school.save(update_fields=["school_type"])
        
        # Log audit trail event
        from apps.activities.closure_services import AuditTrailService
        dummy_act = school.activities.first()
        if dummy_act:
            AuditTrailService.log_event(dummy_act, "Champion School Approved", user_id, "Admin")
        
        return True

    @staticmethod
    def reject(school_id: str) -> bool:
        """Rejects a champion proposal and resets candidate status."""
        profile = CoreSchoolProfile.objects.filter(school_id=school_id).first()
        if not profile:
            return False
            
        profile.champion_status = "Not Eligible"
        profile.save(update_fields=["champion_status"])
        return True
