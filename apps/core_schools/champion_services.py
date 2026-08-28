import logging
from django.db import transaction
from django.db.models import Count, Q

from apps.core.fy import get_operational_fy
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.core_schools.models import CorePlan, CoreSchoolProfile
from apps.core.scoping import assert_may_write_school
from apps.core_schools.services import (
    CORE_PLAN_CLOSED_STATUSES,
    CORE_SLOT_DONE_STATUSES,
    EXPECTED_CORE_SLOTS,
    get_live_core_plan,
)

logger = logging.getLogger(__name__)


class ChampionEligibilityService:
    @staticmethod
    def calculate_score(school: School) -> dict:
        """Calculates the Champion Score and check items using the official formula."""
        # Retrieve CorePlan. Asking for status="Active" made the act that
        # QUALIFIES a school disqualify it: upload_follow_up_ssa — the
        # follow-up assessment that makes a school a candidate — moves the
        # plan to "Champion Candidate"/"Impact Measured", and this lookup then
        # found nothing and scored the school 0.0 / "No active Core Plan", on
        # the candidates page and in the review drawer alike. Those statuses
        # record how far through the year the package is and are worth
        # keeping; it is the reader that was wrong. get_live_core_plan()
        # holds the one definition of "this school's live package", FY
        # included — see apps.core_schools.services.
        plan = get_live_core_plan(school.school_id)
        if not plan:
            return {"score": 0.0, "eligible": False, "reason": "No active Core Plan"}

        confirmed_ssas = list(
            school.ssa_records.filter(
                deleted_at__isnull=True, verification_status="confirmed"
            )
            .prefetch_related("scores")
            .order_by("date_of_ssa", "created_at")
        )
        slot_statuses = list(plan.slots.values_list("status", flat=True))
        activity_counts = school.activities.filter(deleted_at__isnull=True).aggregate(
            closed=Count("id", filter=Q(status="closed")),
            clean=Count("id", filter=Q(status="closed", evidence_status="accepted")),
        )
        return ChampionEligibilityService._score_loaded(
            confirmed_ssas=confirmed_ssas,
            slot_statuses=slot_statuses,
            total_closed=activity_counts["closed"],
            clean_evidence=activity_counts["clean"],
        )

    @staticmethod
    def _score_loaded(
        *,
        confirmed_ssas: list[SsaRecord],
        slot_statuses: list[str],
        total_closed: int,
        clean_evidence: int,
    ) -> dict:
        """Apply the official formula to already-loaded records.

        Keeping the arithmetic here lets the review drawer score one school
        while the candidates queue scores the whole estate in a constant
        number of queries.  The two readers cannot drift into different
        definitions of champion eligibility.
        """
        if not confirmed_ssas:
            return {"score": 0.0, "eligible": False, "reason": "No SSA recorded"}

        earliest_ssa = confirmed_ssas[0]
        latest_ssa = confirmed_ssas[-1]
        return ChampionEligibilityService._score_values(
            earliest_avg=earliest_ssa.average_score or 0.0,
            latest_avg=latest_ssa.average_score or 0.0,
            latest_scores=[
                (score.score, score.intervention) for score in latest_ssa.scores.all()
            ],
            slot_count=len(slot_statuses),
            completed_slots=sum(
                status in CORE_SLOT_DONE_STATUSES for status in slot_statuses
            ),
            total_closed=total_closed,
            clean_evidence=clean_evidence,
            all_ssas=len(confirmed_ssas),
        )

    @staticmethod
    def _score_values(
        *,
        earliest_avg: float,
        latest_avg: float,
        latest_scores: list[tuple[float, str]],
        slot_count: int,
        completed_slots: int,
        total_closed: int,
        clean_evidence: int,
        all_ssas: int,
    ) -> dict:
        """Pure scoring kernel shared by single-school and estate readers."""
        latest_score_weighted = (latest_avg / 10.0) * 40.0

        # 2. Improvement Delta (25%)
        delta = latest_avg - earliest_avg
        # Score scales up to +3.0 points improvement
        delta_score = min(max(delta / 3.0, 0.0), 1.0) * 25.0

        # 3. Intervention Balance (15%)
        # No major intervention below 7.0
        lowest = (
            min(latest_scores, key=lambda score: score[0]) if latest_scores else None
        )
        lowest_score = lowest[0] if lowest else 0.0
        # If lowest is 7.0 or above, full points. Otherwise scale down.
        balance_score = (min(lowest_score, 7.0) / 7.0) * 15.0

        # 4. Core Package Completion (10%)
        # Total required slots come from CORE_PACKAGE_SPEC (9: 1 assessment +
        # 4 visits + 4 trainings). Uses the same canonical "done" status
        # set the real completion path writes (CORE_SLOT_DONE_STATUSES —
        # see apps.core_schools.services.resync_plan_completion) rather than
        # a hand-duplicated list of status spellings that can drift out of
        # sync with what Activity.save() actually mirrors onto the slot.
        pkg_pct = (completed_slots / slot_count) if slot_count > 0 else 0.0
        package_score = pkg_pct * 10.0

        # 5. Evidence & IA Quality (5%)
        # Evidence completion rate on completed activities
        evidence_pct = (clean_evidence / total_closed) if total_closed > 0 else 1.0
        evidence_score = evidence_pct * 5.0

        # 6. Repeat Performance / Sustainability (5%)
        # At least two SSA records over time
        sustain_score = 5.0 if all_ssas >= 2 else 2.5

        # Total Champion Score
        total_score = (
            latest_score_weighted
            + delta_score
            + balance_score
            + package_score
            + evidence_score
            + sustain_score
        )

        # Eligibility Checks
        eligible = (
            latest_avg >= 8.0
            and lowest_score >= 7.0
            and completed_slots >= EXPECTED_CORE_SLOTS
        )

        return {
            "score": round(total_score, 1),
            "eligible": eligible,
            "latest_avg": latest_avg,
            "lowest_score": lowest_score,
            "delta": round(delta, 1),
            "completed_slots": completed_slots,
            "total_slots": slot_count,
            "all_ssas": all_ssas,
            "evidence_pct": round(evidence_pct * 100, 1),
            "evidence_score": round(evidence_score, 1),
            "lowest_intervention": lowest[1] if lowest else "None",
        }

    @staticmethod
    def evaluate_all() -> list[dict]:
        """Scan the estate without issuing queries per school.

        This endpoint previously executed more than 9,000 queries against the
        development dataset and blocked the page for over 23 seconds.  Load
        every input in bounded batches, score in memory, and persist status
        transitions with one bulk update.
        """
        candidates = []
        profiles = list(CoreSchoolProfile.objects.all())
        if not profiles:
            return candidates

        school_ids = [profile.school_id for profile in profiles]
        operational_fy = get_operational_fy()

        plans_by_school: dict[str, dict] = {}
        plans = (
            CorePlan.objects.filter(school_id__in=school_ids)
            .exclude(status__in=CORE_PLAN_CLOSED_STATUSES)
            .annotate(
                champion_total_slots=Count("slots"),
                champion_completed_slots=Count(
                    "slots", filter=Q(slots__status__in=CORE_SLOT_DONE_STATUSES)
                ),
            )
            .values(
                "school_id",
                "fy",
                "champion_total_slots",
                "champion_completed_slots",
            )
            .order_by("school_id", "-fy")
        )
        for plan in plans:
            selected = plans_by_school.get(plan["school_id"])
            if selected is None or (
                plan["fy"] == operational_fy and selected["fy"] != operational_fy
            ):
                plans_by_school[plan["school_id"]] = plan

        ssa_rows_by_school: dict[str, list[dict]] = {}
        ssa_rows = (
            SsaRecord.objects.filter(
                school__school_id__in=school_ids,
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .values("id", "school__school_id", "date_of_ssa", "average_score")
            .order_by("school__school_id", "date_of_ssa", "created_at")
        )
        for row in ssa_rows:
            ssa_rows_by_school.setdefault(row["school__school_id"], []).append(row)

        latest_ssa_ids = [rows[-1]["id"] for rows in ssa_rows_by_school.values()]
        scores_by_ssa: dict[str, list[tuple[float, str]]] = {}
        for row in SsaScore.objects.filter(ssa_record_id__in=latest_ssa_ids).values(
            "ssa_record_id", "score", "intervention"
        ):
            scores_by_ssa.setdefault(row["ssa_record_id"], []).append(
                (row["score"], row["intervention"])
            )

        schools = (
            School.objects.filter(school_id__in=school_ids)
            .select_related("district")
            .annotate(
                champion_closed_count=Count(
                    "activities",
                    filter=Q(
                        activities__deleted_at__isnull=True,
                        activities__status="closed",
                    ),
                    distinct=True,
                ),
                champion_clean_evidence_count=Count(
                    "activities",
                    filter=Q(
                        activities__deleted_at__isnull=True,
                        activities__status="closed",
                        activities__evidence_status="accepted",
                    ),
                    distinct=True,
                ),
            )
        )
        schools_by_id = {school.school_id: school for school in schools}
        profiles_to_update = []

        for profile in profiles:
            school = schools_by_id.get(profile.school_id)
            plan = plans_by_school.get(profile.school_id)
            confirmed = ssa_rows_by_school.get(profile.school_id, [])
            if not school or not plan or not confirmed:
                continue

            latest = confirmed[-1]
            metrics = ChampionEligibilityService._score_values(
                earliest_avg=confirmed[0]["average_score"] or 0.0,
                latest_avg=latest["average_score"] or 0.0,
                latest_scores=scores_by_ssa.get(latest["id"], []),
                slot_count=plan["champion_total_slots"],
                completed_slots=plan["champion_completed_slots"],
                total_closed=school.champion_closed_count,
                clean_evidence=school.champion_clean_evidence_count,
                all_ssas=len(confirmed),
            )
            if metrics["eligible"]:
                if profile.champion_status not in ["Champion", "Approved Champion"]:
                    profile.champion_status = "Potential Champion"
                    profiles_to_update.append(profile)
                candidates.append(
                    {"school": school, "profile": profile, "metrics": metrics}
                )
        if profiles_to_update:
            CoreSchoolProfile.objects.bulk_update(
                profiles_to_update, ["champion_status"]
            )
        return candidates

    @staticmethod
    @transaction.atomic
    def approve(school_id: str, principal) -> bool:
        """Approves a Potential Champion school to official Champion School status.

        Takes the acting principal rather than a bare user id. Graduation
        rewrites `School.school_type`, and an id carries no authority to do
        that: both this and :meth:`reject` accepted any school in the country
        from any of the four roles holding the `core_schools` page permission.
        The review drawer that leads here scoped its lookup and the POST behind
        it did not — a hidden button, not a rule.
        """
        school = School.objects.filter(school_id=school_id).first()
        if not school:
            return False

        assert_may_write_school(principal, school, action="graduate")

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
            AuditTrailService.log_event(
                dummy_act,
                "Champion School Approved",
                principal.user_id,
                "Admin",
            )

        return True

    @staticmethod
    def reject(school_id: str, principal) -> bool:
        """Rejects a champion proposal and resets candidate status.

        Scoped for the same reason as :meth:`approve` — rejecting somebody
        else's candidate is as much a write into their portfolio as approving
        it, and costs the school its graduation.
        """
        school = School.objects.filter(school_id=school_id).first()
        if not school:
            return False

        assert_may_write_school(principal, school, action="review the candidacy of")

        profile = CoreSchoolProfile.objects.filter(school_id=school_id).first()
        if not profile:
            return False

        profile.champion_status = "Not Eligible"
        profile.save(update_fields=["champion_status"])
        return True
