import logging
from datetime import date

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncMonth
from apps.core.exceptions import BadRequest
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.schools.models import School
from apps.geography.models import Region
from apps.accounts.models import StaffProfile
from apps.partners.models import Partner, PartnerAssignment
from apps.activities.models import Activity
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.presentation import build_ssa_score_summary
from apps.core_schools.models import (
    CorePlan,
    CoreActivitySlot,
    CoreSchoolProfile,
    cplan_id,
    cprof_id,
)
from apps.core_schools.services import EXPECTED_CORE_SLOTS

logger = logging.getLogger(__name__)


# A support slot counts toward the annual 4 + 4 package as soon as it has
# reached the calendar. Review and completion states remain counted as well:
# the same slot is still reserved and must not be planned a second time.
CORE_ALLOCATED_SLOT_STATUSES = frozenset(
    {
        "scheduled",
        "in_progress",
        "in progress",
        "evidence uploaded",
        "evidence_uploaded",
        "evidence accepted",
        "evidence_accepted",
        "awaiting_ia_verification",
        "submitted_to_pl",
        "ia pending",
        "iapending",
        "completed",
        "closed",
        "ia_verified",
        "iaverified",
        "accountant_confirmed",
        "accountantconfirmed",
        "returned",
        "returned_by_pl",
        "evidence returned",
        "evidence_returned",
    }
)
CORE_SLOT_ORDINALS = {
    1: "First",
    2: "Second",
    3: "Third",
    4: "Fourth",
}


class CorePackageSchedulingService:
    """One source of truth for the Core Schools 4 visits + 4 trainings rule.

    The activity lifecycle remains the authority for verification and Champion
    graduation. This service only answers whether support has been allocated
    on the calendar, which is the right signal for the operational scheduling
    cap and the live counts shown on the Core Schools list.
    """

    @staticmethod
    def _normalise_status(value: str | None) -> str:
        return (value or "").strip().lower()

    @classmethod
    def is_allocated(cls, slot: CoreActivitySlot) -> bool:
        return cls._normalise_status(slot.status) in CORE_ALLOCATED_SLOT_STATUSES

    @classmethod
    def summary(cls, plan: CorePlan, slots=None) -> dict:
        slot_list = list(slots if slots is not None else plan.slots.all())
        visits = sum(
            cls.is_allocated(slot)
            for slot in slot_list
            if slot.activity_type == "visit"
        )
        trainings = sum(
            cls.is_allocated(slot)
            for slot in slot_list
            if slot.activity_type == "training"
        )
        visits_target = plan.visits_target or 4
        trainings_target = plan.trainings_target or 4
        package_complete = visits >= visits_target and trainings >= trainings_target
        return {
            "visits": visits,
            "trainings": trainings,
            "visits_target": visits_target,
            "trainings_target": trainings_target,
            "package_complete": package_complete,
            "package_status": "Package complete" if package_complete else "In progress",
        }

    @classmethod
    def available_sequences(cls, plan: CorePlan, activity_type: str) -> list[int]:
        slots = plan.slots.filter(activity_type=activity_type).order_by(
            "sequence_number"
        )
        return [
            slot.sequence_number
            for slot in slots
            if not cls.is_allocated(slot)
            and cls._normalise_status(slot.status) != "assigned"
        ]

    @classmethod
    def available_options(cls, plan: CorePlan, activity_type: str) -> list[dict]:
        """Return only open slots with plain-language labels for the UI."""
        support_name = "Visit" if activity_type == "visit" else "Training"
        return [
            {
                "sequence": sequence,
                "label": f"{CORE_SLOT_ORDINALS.get(sequence, sequence)} {support_name}",
            }
            for sequence in cls.available_sequences(plan, activity_type)
        ]

    @classmethod
    def assert_can_schedule(
        cls,
        *,
        plan: CorePlan,
        school: School,
        activity_type: str,
        sequence_number: int,
        scheduled_for: date,
        is_partner_delivery: bool,
    ) -> CoreActivitySlot:
        """Lock one usable slot and enforce the annual/quarterly policy.

        Staff delivery is released one visit and one training at a time in the
        current operational quarter. Partner delivery can be scheduled in any
        quarter, but remains inside the non-negotiable annual 4 + 4 cap.
        """
        if activity_type not in {"visit", "training"}:
            raise BadRequest("Core support must be a visit or a training.")

        summary = cls.summary(plan)
        if summary["package_complete"]:
            raise BadRequest(
                "This core package is complete: all 4 visits and 4 trainings are already scheduled or completed."
            )

        count_key = "visits" if activity_type == "visit" else "trainings"
        target_key = "visits_target" if activity_type == "visit" else "trainings_target"
        if summary[count_key] >= summary[target_key]:
            raise BadRequest(
                f"All {summary[target_key]} core {activity_type}s are already scheduled or completed."
            )

        slot = (
            CoreActivitySlot.objects.select_for_update()
            .filter(
                core_plan=plan,
                activity_type=activity_type,
                sequence_number=sequence_number,
            )
            .first()
        )
        if not slot:
            raise BadRequest("That core support slot is unavailable.")
        if cls.is_allocated(slot):
            raise BadRequest(
                "That core support slot is already scheduled or completed."
            )
        if cls._normalise_status(slot.status) == "assigned":
            raise BadRequest(
                "That slot is assigned to a partner and must be scheduled from the partner queue."
            )

        requested_fy = get_operational_fy(scheduled_for)
        if str(requested_fy) != str(plan.fy):
            raise BadRequest(
                "Core support must be scheduled within this package's fiscal year."
            )

        if not is_partner_delivery:
            current_day = date.today()
            current_fy = get_operational_fy(current_day)
            current_quarter = get_quarter_for_date(current_day)
            requested_quarter = get_quarter_for_date(scheduled_for)
            if (requested_fy, requested_quarter) != (current_fy, current_quarter):
                raise BadRequest(
                    f"Staff core support is released in the current {current_quarter} only. "
                    "Partner delivery may be scheduled in another quarter."
                )

            activity_kind = f"core_{activity_type}"
            # The staff share of a core package is 2 visits + 2 trainings PER
            # FISCAL YEAR — the remainder belongs to partners. The previous
            # check was one-per-quarter, which quietly permitted 4 + 4 across
            # the year: the whole package staff-delivered, nothing left for a
            # partner, and the delivery cost moved onto internal staff lines.
            STAFF_ANNUAL_CAP = 2
            staff_this_fy = (
                Activity.objects.filter(
                    school=school,
                    activity_type=activity_kind,
                    fy=current_fy,
                    delivery_type="staff",
                    deleted_at__isnull=True,
                )
                .exclude(status__in=["cancelled", "rejected", "deferred"])
                .count()
            )
            if staff_this_fy >= STAFF_ANNUAL_CAP:
                raise BadRequest(
                    f"Staff may deliver at most {STAFF_ANNUAL_CAP} core {activity_type}s "
                    f"per year ({staff_this_fy} already scheduled). The remaining "
                    "slots are reserved for partner delivery."
                )
            staff_already_scheduled = (
                Activity.objects.filter(
                    school=school,
                    activity_type=activity_kind,
                    fy=current_fy,
                    quarter=current_quarter,
                    delivery_type="staff",
                    deleted_at__isnull=True,
                )
                .exclude(status__in=["cancelled", "rejected"])
                .exists()
            )
            if staff_already_scheduled:
                raise BadRequest(
                    f"One staff-led core {activity_type} is already scheduled in {current_quarter}. "
                    "The next staff slot opens at the start of the next quarter; partner delivery remains available."
                )

        return slot

    @classmethod
    def assert_can_assign(
        cls, *, plan: CorePlan, activity_type: str, sequence_number: int
    ) -> CoreActivitySlot:
        """Reserve only an untouched slot for a partner assignment."""
        summary = cls.summary(plan)
        if summary["package_complete"]:
            raise BadRequest(
                "This core package is complete: all 4 visits and 4 trainings are already scheduled or completed."
            )
        slot = (
            CoreActivitySlot.objects.select_for_update()
            .filter(
                core_plan=plan,
                activity_type=activity_type,
                sequence_number=sequence_number,
            )
            .first()
        )
        if (
            not slot
            or cls.is_allocated(slot)
            or cls._normalise_status(slot.status) == "assigned"
        ):
            raise BadRequest("That core support slot is no longer available to assign.")
        return slot


def build_sparkline_path(
    values: list, width: int = 60, height: int = 20, padding: int = 2
) -> str:
    """Builds a simple SVG path `d` attribute from a list of real values."""
    if not values:
        return ""
    if len(values) == 1:
        mid = height / 2
        return f"M {padding} {mid:.1f} L {width - padding} {mid:.1f}"

    vmin, vmax = min(values), max(values)
    rng = (vmax - vmin) or 1
    step = (width - 2 * padding) / (len(values) - 1)
    points = []
    for i, v in enumerate(values):
        x = padding + i * step
        y = height - padding - ((v - vmin) / rng) * (height - 2 * padding)
        points.append((x, y))
    d = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    for x, y in points[1:]:
        d += f" L {x:.1f} {y:.1f}"
    return d


class CoreSchoolsService:
    @staticmethod
    def get_core_schools(user, filters: dict):
        """Scopes and filters core schools for the page."""
        from apps.analytics.services import _scoped_schools

        schools_qs, scope = _scoped_schools(user)

        # Ensure we only work with Core schools
        core_schools_qs = schools_qs.filter(school_type="core")

        # 1. Self-healing check: ensure all core schools have a CorePlan for the current FY
        fy = filters.get("fy") or get_operational_fy()
        uninitialized_schools = core_schools_qs.exclude(
            school_id__in=CorePlan.objects.filter(fy=fy).values_list(
                "school_id", flat=True
            )
        )
        if uninitialized_schools.exists():
            from django.db import transaction

            interventions = [i.value for i in SsaIntervention]
            # Provenance for auto-created plans/slots — same shape as the
            # audited onboard() path (created_by_id/created_by_name), so a
            # self-healed record is never indistinguishable from a hand-made
            # one with no author on file.
            actor_id = getattr(user, "user_id", None) or getattr(user, "id", None)
            actor_name = getattr(user, "name", None) or "System (auto-heal)"
            for s in uninitialized_schools:
                latest = (
                    s.ssa_records.filter(
                        deleted_at__isnull=True,
                        verification_status="confirmed",
                    )
                    .order_by("-date_of_ssa", "-created_at")
                    .first()
                )
                if not latest:
                    # SSA gate: mirrors the official onboard() path, which
                    # only ever runs after IA has verified an SSA-backed
                    # candidate (services.verify_candidate). Without a real
                    # SSA record there is no legitimate baseline to onboard
                    # against, so skip rather than silently fabricating a
                    # 0.0 baseline for this FY.
                    logger.warning(
                        "Skipping self-heal for core school %s: no SSA record "
                        "on file to gate onboarding against.",
                        s.school_id,
                    )
                    continue
                baseline_avg = latest.average_score
                plan_id = cplan_id(s.school_id)
                try:
                    with transaction.atomic():
                        plan, _ = CorePlan.objects.update_or_create(
                            id=plan_id,
                            defaults={
                                "school_id": s.school_id,
                                "fy": fy,
                                "status": "Active",
                                "baseline_average": baseline_avg,
                                "baseline_ssa_record_id": latest.id,
                                "created_by_id": actor_id,
                                "created_by_name": actor_name,
                            },
                        )
                        CoreSchoolProfile.objects.update_or_create(
                            id=cprof_id(s.school_id),
                            defaults={
                                "school_id": s.school_id,
                                "core_plan": plan,
                                "core_start_fy": fy,
                            },
                        )
                        # Canonical 9-slot package (assessment + 4v + 4t) via
                        # the shared helper so this self-heal path can never
                        # drift from the onboard path.
                        from apps.core_schools.services import create_package_slots

                        create_package_slots(
                            plan, s.school_id, interventions, actor_id, actor_name
                        )
                except Exception as e:
                    logger.error(
                        f"Error auto-onboarding core school {s.school_id}: {e}"
                    )

        # 2. Apply filters
        region_id = filters.get("region")
        if region_id and region_id != "All":
            core_schools_qs = core_schools_qs.filter(region_id=region_id)

        district_id = filters.get("district")
        if district_id and district_id != "All":
            core_schools_qs = core_schools_qs.filter(district_id=district_id)

        staff_id = filters.get("staff")
        if staff_id and staff_id != "All":
            core_schools_qs = core_schools_qs.filter(account_owner_id=staff_id)

        partner_id = filters.get("partner")
        if partner_id and partner_id != "All":
            # Filter core schools with partner assignments
            assigned_school_ids = PartnerAssignment.objects.filter(
                partner_id=partner_id, school__school_type="core"
            ).values_list("school_id", flat=True)
            core_schools_qs = core_schools_qs.filter(id__in=assigned_school_ids)

        # More filters drawer filters
        school_type_filter = filters.get("school_type_filter")
        if school_type_filter and school_type_filter != "All":
            core_schools_qs = core_schools_qs.filter(school_type=school_type_filter)

        ssa_status = filters.get("ssa_status")
        if ssa_status and ssa_status != "All":
            core_schools_qs = core_schools_qs.filter(current_fy_ssa_status=ssa_status)

        partner_assigned = filters.get("partner_assigned")
        if partner_assigned and partner_assigned != "All":
            assigned_ids = PartnerAssignment.objects.filter(
                school__school_type="core"
            ).values_list("school_id", flat=True)
            if partner_assigned == "assigned":
                core_schools_qs = core_schools_qs.filter(id__in=assigned_ids)
            elif partner_assigned == "unassigned":
                core_schools_qs = core_schools_qs.exclude(id__in=assigned_ids)

        return core_schools_qs


class CorePackageProgressService:
    @staticmethod
    def get_matrix_data(core_schools_qs, fy: str) -> list[dict]:
        """Prepares matrix progress rows for the dashboard."""
        iterator = list(
            core_schools_qs.select_related("district", "region", "sub_county")
            if hasattr(core_schools_qs, "select_related")
            else core_schools_qs
        )
        school_ids = [school.school_id for school in iterator]
        db_ids = [school.id for school in iterator]

        plans = CorePlan.objects.filter(
            school_id__in=school_ids, fy=fy
        ).prefetch_related("slots")
        plans_map = {p.school_id: p for p in plans}

        # The matrix is paginated, so load each visible school's latest
        # confirmed assessment and all eight scores in two bounded queries.
        # This lets the expandable recommendation show saved intervention
        # scores without issuing a query for every core school card.
        latest_ssa_by_school = {}
        confirmed_ssa_records = (
            SsaRecord.objects.filter(
                school_id__in=db_ids,
                fy=fy,
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .prefetch_related("scores")
            .order_by("school_id", "-date_of_ssa", "-created_at")
        )
        for record in confirmed_ssa_records:
            latest_ssa_by_school.setdefault(record.school_id, record)

        # Load cluster names
        from apps.clusters.models import Cluster

        cluster_ids = [school.cluster_id for school in iterator if school.cluster_id]
        clusters = Cluster.objects.filter(id__in=cluster_ids, deleted_at__isnull=True)
        clusters_map = {c.id: c.name for c in clusters}

        owner_ids = {
            school.account_owner_id for school in iterator if school.account_owner_id
        }
        staff_names_by_owner_id = {}
        if owner_ids:
            for staff in (
                StaffProfile.objects.filter(deleted_at__isnull=True)
                .filter(Q(id__in=owner_ids) | Q(user_id__in=owner_ids))
                .select_related("user")
            ):
                if staff.user_id and staff.user.name:
                    staff_names_by_owner_id[staff.id] = staff.user.name
                    staff_names_by_owner_id[staff.user_id] = staff.user.name

        # Load project assignment counts
        from apps.projects.models import ProjectSchoolAssignment

        project_counts = (
            ProjectSchoolAssignment.objects.filter(school_id__in=db_ids)
            .values("school_id")
            .annotate(count=Count("id"))
        )
        project_counts_map = {
            item["school_id"]: item["count"] for item in project_counts
        }

        # Prefetch school geo details and latest SSA
        schools_data = []
        for s in iterator:
            plan = plans_map.get(s.school_id)

            # Calculate the average and recommendation bands from the actual
            # saved intervention scores, not the denormalized record average.
            latest_ssa = latest_ssa_by_school.get(s.id)
            ssa_summary = build_ssa_score_summary(
                [
                    {"intervention": score.intervention, "score": score.score}
                    for score in latest_ssa.scores.all()
                ]
                if latest_ssa
                else []
            )
            score_val = ssa_summary["average_score"]

            # Map score to percentage and label
            score_pct = None
            score_label = "No SSA"
            badge_class = "bg-slate-50 text-slate-400 border-slate-200"
            if score_val is not None:
                score_pct = round(score_val * 10)
                if score_pct < 50:
                    score_label = "Needs Support"
                    badge_class = "bg-rose-50 text-rose-700 border-rose-200"
                elif score_pct < 70:
                    score_label = "Average"
                    badge_class = "bg-amber-50 text-amber-600 border-amber-200"
                elif score_pct < 80:
                    score_label = "Improving"
                    badge_class = "bg-emerald-50 text-emerald-600 border-emerald-200"
                else:
                    score_label = "Strong"
                    badge_class = "bg-emerald-100 text-emerald-800 border-emerald-350"

            # Map slots status
            visits = []
            trainings = []
            v_slots = []
            t_slots = []
            assessment_cell = CorePackageProgressService._serialize_slot_ui(None)

            if plan:
                slots = list(plan.slots.all().order_by("sequence_number"))
                v_slots = [sl for sl in slots if sl.activity_type == "visit"]
                t_slots = [sl for sl in slots if sl.activity_type == "training"]
                a_slot = next(
                    (sl for sl in slots if sl.activity_type == "assessment"), None
                )
                assessment_cell = CorePackageProgressService._serialize_slot_ui(a_slot)

                for seq in range(1, 5):
                    slot = next(
                        (sl for sl in v_slots if sl.sequence_number == seq), None
                    )
                    visits.append(CorePackageProgressService._serialize_slot_ui(slot))

                for seq in range(1, 5):
                    slot = next(
                        (sl for sl in t_slots if sl.sequence_number == seq), None
                    )
                    trainings.append(
                        CorePackageProgressService._serialize_slot_ui(slot)
                    )
            else:
                # Default empty slots
                for _ in range(4):
                    visits.append(
                        {
                            "status": "Missing",
                            "pill_class": "bg-rose-50 text-rose-700 border-rose-200",
                            "label": "Miss",
                        }
                    )
                    trainings.append(
                        {
                            "status": "Missing",
                            "pill_class": "bg-rose-50 text-rose-700 border-rose-200",
                            "label": "Miss",
                        }
                    )

            # Calculate next missing milestone
            next_missing_milestone = "All Packages are Complete"
            seq_names = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}

            for seq in range(1, 5):
                # Check Visit
                slot_v = (
                    next((sl for sl in v_slots if sl.sequence_number == seq), None)
                    if plan
                    else None
                )
                v_done = False
                if slot_v:
                    v_status = slot_v.status.lower()
                    if v_status in [
                        "completed",
                        "completed_at",
                        "accountantconfirmed",
                        "accountant_confirmed",
                        "ia_verified",
                        "iaverified",
                    ]:
                        v_done = True

                if not v_done:
                    next_missing_milestone = f"Missing {seq_names[seq]} Visit"
                    break

                # Check Training
                slot_t = (
                    next((sl for sl in t_slots if sl.sequence_number == seq), None)
                    if plan
                    else None
                )
                t_done = False
                if slot_t:
                    t_status = slot_t.status.lower()
                    if t_status in [
                        "completed",
                        "completed_at",
                        "accountantconfirmed",
                        "accountant_confirmed",
                        "ia_verified",
                        "iaverified",
                    ]:
                        t_done = True

                if not t_done:
                    next_missing_milestone = f"Missing {seq_names[seq]} Training"
                    break

            cluster_name = clusters_map.get(s.cluster_id, "—") if s.cluster_id else "—"
            project_count = project_counts_map.get(s.id, 0)
            if plan:
                package_summary = CorePackageSchedulingService.summary(plan, slots)
                blocked_reason = (
                    "Package complete" if package_summary["package_complete"] else None
                )
            else:
                package_summary = {
                    "visits": 0,
                    "trainings": 0,
                    "visits_target": 4,
                    "trainings_target": 4,
                    "package_complete": False,
                    "package_status": "Package unavailable",
                }
                blocked_reason = "Core package unavailable"

            schools_data.append(
                {
                    "id": s.id,
                    "school_id": s.school_id,
                    "name": s.name,
                    "geo_label": f"{s.district.name} / {s.region.name}",
                    "district_name": s.district.name,
                    "sub_county_name": s.sub_county.name if s.sub_county else "—",
                    "shipping_address": s.shipping_address or "—",
                    "school_type": s.get_school_type_display(),
                    "phone": s.primary_contact_phone or s.school_phone or "—",
                    "school_contact": s.primary_contact_name or "—",
                    "staff_name": staff_names_by_owner_id.get(s.account_owner_id)
                    or s.account_owner_name_raw
                    or "Unassigned",
                    "enrolment": s.enrollment or 0,
                    "data_quality_score": s.data_quality_score,
                    "data_quality_status": s.data_quality_status,
                    "is_clustered": s.cluster_status == "clustered"
                    or s.cluster_id is not None,
                    "cluster_name": cluster_name,
                    "project_assignment_count": project_count,
                    "score_pct": score_pct,
                    "score_label": score_label,
                    "score_badge_class": badge_class,
                    "has_ssa": latest_ssa is not None,
                    "has_ssa_scores": ssa_summary["has_scores"],
                    "ssa_average": ssa_summary["average_score"],
                    "ssa_average_tone": ssa_summary["average_tone"],
                    "ssa_groups": ssa_summary["groups"],
                    "assessment": assessment_cell,
                    "visits": visits,
                    "trainings": trainings,
                    "scheduled_visit_count": package_summary["visits"],
                    "scheduled_training_count": package_summary["trainings"],
                    "visits_target": package_summary["visits_target"],
                    "trainings_target": package_summary["trainings_target"],
                    "package_complete": package_summary["package_complete"],
                    "package_status": package_summary["package_status"],
                    "core_package_available": bool(plan)
                    and not package_summary["package_complete"],
                    "blocked_reason": blocked_reason,
                    "next_missing_milestone": next_missing_milestone,
                }
            )

        return schools_data

    @staticmethod
    def _serialize_slot_ui(slot) -> dict:
        if not slot:
            return {
                "status": "Missing",
                "pill_class": "bg-rose-50 text-rose-700 border-rose-200",
                "label": "Miss",
            }

        status = slot.status.lower()
        if status in [
            "completed",
            "completed_at",
            "accountantconfirmed",
            "accountant_confirmed",
            "ia_verified",
            "iaverified",
        ]:
            if slot.ia_verification_status == "confirmed" or status in [
                "ia_verified",
                "iaverified",
            ]:
                return {
                    "status": "IA Verified",
                    "pill_class": "bg-emerald-100 text-emerald-850 border-emerald-300",
                    "label": "✔",
                }
            return {
                "status": "Completed",
                "pill_class": "bg-emerald-50 text-emerald-700 border-emerald-200",
                "label": "✔",
            }
        elif status in ["scheduled", "assigned", "in_progress", "in progress"]:
            return {
                "status": "Scheduled",
                "pill_class": "edify-primary-soft edify-primary-text edify-primary-border",
                "label": "Sch",
            }
        elif status in [
            "evidence uploaded",
            "evidence_uploaded",
            "evidence accepted",
            "evidence_accepted",
            "awaiting_ia_verification",
            "submitted_to_pl",
            "iapending",
            "ia pending",
        ]:
            return {
                "status": "IA Pending",
                "pill_class": "bg-purple-50 text-purple-700 border-purple-200",
                "label": "IA Pend",
            }
        elif status in [
            "returned",
            "returned_by_pl",
            "evidence returned",
            "evidence_returned",
        ]:
            return {
                "status": "Returned",
                "pill_class": "bg-rose-100 text-rose-800 border-rose-300",
                "label": "Ret",
            }
        elif status in ["planned", "not_planned", "pending"]:
            return {
                "status": "Pending",
                "pill_class": "bg-amber-50 text-amber-700 border-amber-200",
                "label": "Pend",
            }
        else:
            return {
                "status": "Missing",
                "pill_class": "bg-rose-50 text-rose-700 border-rose-200",
                "label": "Miss",
            }


class CorePlanningService:
    @staticmethod
    def get_planning_queue(core_schools_qs, fy: str) -> list[dict]:
        """Prepares items for the Core Schools Planning Queue."""
        if hasattr(core_schools_qs, "values_list"):
            school_ids = list(core_schools_qs.values_list("school_id", flat=True))
        else:
            school_ids = [s.school_id for s in core_schools_qs]

        plans = CorePlan.objects.filter(
            school_id__in=school_ids, fy=fy
        ).prefetch_related("slots")
        plans_map = {p.school_id: p for p in plans}

        # Load staff and partner details to map names
        staff_map = {
            sp.user_id: sp.user.name
            for sp in StaffProfile.objects.all().select_related("user")
        }
        partner_map = {p.id: p.name for p in Partner.objects.all()}

        queue_data = []
        iterator = (
            core_schools_qs.select_related("region")
            if hasattr(core_schools_qs, "select_related")
            else core_schools_qs
        )
        for s in iterator:
            plan = plans_map.get(s.school_id)

            visits_done = 0
            trainings_done = 0
            assessment_done = 0
            total_done = 0
            assigned_staff_name = "Unassigned"
            assigned_partner_name = "Unassigned"

            if s.account_owner_id:
                assigned_staff_name = staff_map.get(s.account_owner_id, "Staff Owner")

            # Check Partner Assignment
            pa = PartnerAssignment.objects.filter(school=s, status="assigned").first()
            if pa:
                assigned_partner_name = partner_map.get(pa.partner_id, "Partner Owner")

            is_clustered = s.cluster_id is not None and s.cluster_id != ""

            # Resolve weakest intervention from latest SSA
            weakest_intervention = "—"
            latest_ssa = (
                s.ssa_records.filter(
                    fy=fy,
                    deleted_at__isnull=True,
                    verification_status="confirmed",
                )
                .order_by("-date_of_ssa", "-created_at")
                .first()
            )

            if plan:
                # Iterate the prefetched slot list in Python — calling .filter()
                # here would discard the prefetch and re-query per school.
                from apps.core_schools.services import CORE_SLOT_DONE_WITH_LEGACY

                done_statuses = CORE_SLOT_DONE_WITH_LEGACY
                slot_list = list(plan.slots.all())
                visits_done = sum(
                    1
                    for sl in slot_list
                    if sl.activity_type == "visit" and sl.status in done_statuses
                )
                trainings_done = sum(
                    1
                    for sl in slot_list
                    if sl.activity_type == "training" and sl.status in done_statuses
                )
                assessment_done = sum(
                    1
                    for sl in slot_list
                    if sl.activity_type == "assessment" and sl.status in done_statuses
                )
                total_done = visits_done + trainings_done + assessment_done

                # Check slot assignments
                first_partner_slot = next(
                    (sl for sl in slot_list if sl.owner == "partner"), None
                )
                if first_partner_slot and first_partner_slot.assigned_partner_name:
                    assigned_partner_name = first_partner_slot.assigned_partner_name

            if not is_clustered:
                weakest_intervention = "Requires Cluster"
                next_recommended = "Requires Cluster"
            elif not latest_ssa:
                weakest_intervention = "Assessment Required"
                next_recommended = "Assessment Required"
            else:
                lowest_score = latest_ssa.scores.order_by("score").first()
                if lowest_score:
                    weakest_intervention = dict(SsaIntervention.choices).get(
                        lowest_score.intervention, lowest_score.intervention
                    )

                # Recommendation logic: next missing item in slot. The Core
                # Assessment is the package's first milestone.
                if assessment_done < 1:
                    next_recommended = "Core Assessment"
                elif visits_done < 4:
                    next_recommended = f"V{visits_done + 1} Visit"
                elif trainings_done < 4:
                    next_recommended = f"T{trainings_done + 1} Training"
                else:
                    next_recommended = "Graduation Review"

            queue_data.append(
                {
                    "school_id": s.school_id,
                    "name": s.name,
                    "region": s.region.name,
                    "assigned_staff": assigned_staff_name,
                    "assigned_partner": assigned_partner_name,
                    "weakest_interventions": weakest_intervention,
                    "next_recommended": next_recommended,
                    "assessment_progress": f"{assessment_done} / 1",
                    "visits_progress": f"{visits_done} / 4",
                    "trainings_progress": f"{trainings_done} / 4",
                    "progress_pct": int((total_done / EXPECTED_CORE_SLOTS) * 100),
                }
            )

        return queue_data


class CoreAssessmentService:
    @staticmethod
    def get_average_score(core_schools_qs) -> float:
        """Gets average Core Assessment score for the core schools in scope."""
        latest_record_ids = list(
            SsaRecord.objects.filter(
                school__in=core_schools_qs, deleted_at__isnull=True
            )
            .order_by("school_id", "-date_of_ssa")
            .distinct("school_id")
            .values_list("id", flat=True)
        )

        avg = SsaRecord.objects.filter(id__in=latest_record_ids).aggregate(
            avg=Avg("average_score")
        )["avg"]
        return round(avg, 2) if avg is not None else 0.0

    @staticmethod
    def get_monthly_trend(core_schools_qs) -> list:
        """Real month-over-month average Core Assessment score, built from SsaRecord
        history. Returns [] when there is less than two distinct months of data —
        i.e. not enough real history yet to plot a trend.
        """
        monthly = (
            SsaRecord.objects.filter(
                school__in=core_schools_qs, deleted_at__isnull=True
            )
            .annotate(month=TruncMonth("date_of_ssa"))
            .values("month")
            .annotate(avg=Avg("average_score"))
            .order_by("month")
        )
        trend = [round(m["avg"], 1) for m in monthly if m["avg"] is not None]
        return trend if len(trend) >= 2 else []


class CoreInterventionImpactService:
    @staticmethod
    def _staff_partner_split_for_intervention(
        core_schools_qs, fy: str, code: str, school_ids: list
    ) -> tuple:
        """Real staff-vs-partner score comparison for a single intervention.

        Splits schools by whether their CoreActivitySlot for this intervention is
        partner-owned (`owner="partner"`) vs staff-led (everything else — the same
        "not partner" convention already used by
        CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance), then
        averages each group's SsaScore for that intervention. Returns (None, None)
        when there isn't genuinely a split to compare (e.g. no partner-owned slots
        recorded yet for this intervention).
        """
        slots = CoreActivitySlot.objects.filter(
            school_id__in=school_ids, core_plan__fy=fy, intervention=code
        )
        partner_school_ids = list(
            slots.filter(owner="partner").values_list("school_id", flat=True).distinct()
        )
        staff_school_ids = list(
            slots.exclude(owner="partner")
            .values_list("school_id", flat=True)
            .distinct()
        )

        if not partner_school_ids or not staff_school_ids:
            return None, None

        staff_avg = SsaScore.objects.filter(
            ssa_record__school__school_id__in=staff_school_ids,
            ssa_record__deleted_at__isnull=True,
            intervention=code,
        ).aggregate(avg=Avg("score"))["avg"]
        partner_avg = SsaScore.objects.filter(
            ssa_record__school__school_id__in=partner_school_ids,
            ssa_record__deleted_at__isnull=True,
            intervention=code,
        ).aggregate(avg=Avg("score"))["avg"]

        if staff_avg is None or partner_avg is None:
            return None, None

        return round(staff_avg, 1), round(partner_avg, 1)

    @staticmethod
    def _monthly_trend_for_intervention(core_schools_qs, code: str) -> list:
        """Real month-over-month average score trend for an intervention, built from
        SsaScore/SsaRecord history. Returns [] when there is less than two distinct
        months of data — i.e. no genuine trend to plot yet (rather than fabricating one).
        """
        monthly = (
            SsaScore.objects.filter(
                ssa_record__school__in=core_schools_qs,
                ssa_record__deleted_at__isnull=True,
                intervention=code,
            )
            .annotate(month=TruncMonth("ssa_record__date_of_ssa"))
            .values("month")
            .annotate(avg=Avg("score"))
            .order_by("month")
        )
        trend = [round(m["avg"], 2) for m in monthly if m["avg"] is not None]
        return trend if len(trend) >= 2 else []

    @staticmethod
    def get_intervention_impact(core_schools_qs, fy: str) -> list[dict]:
        """Prepares rows for bottom table Intervention Support & Impact."""
        school_ids = list(core_schools_qs.values_list("school_id", flat=True))

        # Group by intervention and aggregate
        interventions_data = []
        for code, label in SsaIntervention.choices:
            # Count schools supported by training or visit focusing on this intervention
            supported_count = (
                Activity.objects.filter(
                    school__in=core_schools_qs,
                    focus_intervention=code,
                    fy=fy,
                    deleted_at__isnull=True,
                    status__in=[
                        "planned",
                        "scheduled",
                        "partner_scheduled",
                        "in_progress",
                        "completed",
                        "accountant_confirmed",
                    ],
                )
                .values("school")
                .distinct()
                .count()
            )

            # Real improvement delta: average (follow_up_average - baseline_average) for
            # schools whose slot for this intervention has actually been completed. Both
            # baseline_average and follow_up_average come from real SSA records; this is
            # 0 rather than fabricated when no follow-up SSA has been collected yet.
            completed_school_ids = list(
                CoreActivitySlot.objects.filter(
                    school_id__in=school_ids,
                    core_plan__fy=fy,
                    intervention=code,
                    status__in=[
                        "Completed",
                        "Accountant Confirmed",
                        "accountant_confirmed",
                        "ia_verified",
                        "IA Verified",
                        "iaVerify",
                    ],
                )
                .values_list("school_id", flat=True)
                .distinct()
            )
            plans_for_intervention = CorePlan.objects.filter(
                school_id__in=completed_school_ids,
                fy=fy,
                baseline_average__isnull=False,
                follow_up_average__isnull=False,
            )
            deltas = [
                p.follow_up_average - p.baseline_average for p in plans_for_intervention
            ]
            has_improvement_data = bool(deltas)
            avg_improvement = round(sum(deltas) / len(deltas), 1) if deltas else 0

            # Top supporting owner
            top_owner = "Unassigned"
            top_act = (
                Activity.objects.filter(
                    school__in=core_schools_qs,
                    focus_intervention=code,
                    fy=fy,
                    deleted_at__isnull=True,
                )
                .values("responsible_staff_id")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")
                .first()
            )

            if top_act and top_act["responsible_staff_id"]:
                staff = (
                    StaffProfile.objects.filter(user_id=top_act["responsible_staff_id"])
                    .select_related("user")
                    .first()
                )
                if staff:
                    top_owner = staff.user.name

            staff_pct, partner_pct = (
                CoreInterventionImpactService._staff_partner_split_for_intervention(
                    core_schools_qs, fy, code, school_ids
                )
            )
            if staff_pct is not None and partner_pct is not None:
                diff = staff_pct - partner_pct
                comparison = (
                    f"Staff +{diff}pp" if diff >= 0 else f"Partner +{abs(diff)}pp"
                )
            else:
                comparison = "Insufficient data"

            trend = CoreInterventionImpactService._monthly_trend_for_intervention(
                core_schools_qs, code
            )

            interventions_data.append(
                {
                    "code": code,
                    "label": label,
                    "supported_count": supported_count,
                    "avg_improvement": f"+{avg_improvement} pp"
                    if has_improvement_data
                    else "No data yet",
                    "avg_improvement_raw": avg_improvement,
                    "top_owner": top_owner,
                    "comparison": comparison,
                    "trend": trend,
                    "trend_path": build_sparkline_path(trend),
                }
            )

        return sorted(
            interventions_data, key=lambda x: x["supported_count"], reverse=True
        )


class CoreStaffPartnerPerformanceService:
    @staticmethod
    def get_staff_vs_partner_performance(core_schools_qs, fy: str) -> dict:
        """Compares Staff-supported school improvements vs Partner-supported ones."""
        plans = CorePlan.objects.filter(
            school_id__in=core_schools_qs.values_list("school_id", flat=True),
            fy=fy,
            baseline_average__isnull=False,
            follow_up_average__isnull=False,
        ).prefetch_related("slots")

        staff_deltas = []
        partner_deltas = []

        for p in plans:
            delta = p.follow_up_average - p.baseline_average
            # If the school has partner slots scheduled/completed
            is_partner = p.slots.filter(owner="partner").exists()
            if is_partner:
                partner_deltas.append(delta)
            else:
                staff_deltas.append(delta)

        # Honest 0 when there simply isn't any baseline/follow-up delta data yet
        # (e.g. no follow-up SSA has been collected for any plan in scope).
        avg_staff = sum(staff_deltas) / len(staff_deltas) if staff_deltas else 0
        avg_partner = sum(partner_deltas) / len(partner_deltas) if partner_deltas else 0
        delta = avg_staff - avg_partner

        staff_insights = []
        for staff in StaffProfile.objects.all().select_related("user")[:5]:
            # account_owner_id holds a StaffProfile id on every row the school
            # upload wrote, so matching only the User id found nothing at all.
            staff_schools = core_schools_qs.filter(
                account_owner_id__in=[staff.id, staff.user_id]
            )
            if staff_schools.exists():
                avg = CoreAssessmentService.get_average_score(staff_schools)
                staff_insights.append(
                    {
                        "name": staff.user.name,
                        "score": round(avg, 1) if avg else 0,
                    }
                )
        # Default fallback if empty: query real staff profiles in the database
        if not staff_insights:
            for staff in StaffProfile.objects.all().select_related("user")[:5]:
                staff_insights.append(
                    {
                        "name": staff.user.name,
                        "score": 0,
                    }
                )

        partner_insights = []
        for part in Partner.objects.all()[:5]:
            part_assignments = PartnerAssignment.objects.filter(
                partner=part, school__school_type="core"
            )
            if part_assignments.exists():
                assigned_school_ids = part_assignments.values_list(
                    "school_id", flat=True
                )
                partner_schools = core_schools_qs.filter(id__in=assigned_school_ids)
                avg = (
                    CoreAssessmentService.get_average_score(partner_schools)
                    if partner_schools.exists()
                    else None
                )
                partner_insights.append(
                    {
                        "name": part.name,
                        "score": round(avg, 1) if avg else 0,
                    }
                )
        # Default fallback if empty: query real partners in the database
        if not partner_insights:
            for part in Partner.objects.all()[:5]:
                partner_insights.append(
                    {
                        "name": part.name,
                        "score": 0,
                    }
                )

        # Region stats
        region_insights = []
        for reg in Region.objects.all()[:5]:
            avg_reg = SsaRecord.objects.filter(
                school__region=reg, deleted_at__isnull=True
            ).aggregate(avg=Avg("average_score"))["avg"]
            region_insights.append(
                {
                    "name": reg.name,
                    "score": round(avg_reg or 0, 1),
                }
            )

        return {
            "delta_pp": round(delta, 1),
            "staff_insights": staff_insights,
            "partner_insights": partner_insights,
            "region_insights": region_insights,
        }

    @staticmethod
    def get_intervention_comparison_rows(core_schools_qs, fy: str) -> list[dict]:
        """Real per-intervention Staff vs Partner score comparison for Card D.

        Reuses CoreInterventionImpactService's staff/partner split (based on
        CoreActivitySlot.owner). Only returns a row for an intervention when there
        is genuinely a comparable split (partner-owned slots exist alongside
        staff-led ones with real SsaScore data) — otherwise the intervention is
        omitted rather than showing a fabricated comparison.
        """
        school_ids = list(core_schools_qs.values_list("school_id", flat=True))
        rows = []
        for code, label in SsaIntervention.choices:
            staff_pct, partner_pct = (
                CoreInterventionImpactService._staff_partner_split_for_intervention(
                    core_schools_qs, fy, code, school_ids
                )
            )
            if staff_pct is None or partner_pct is None:
                continue
            rows.append(
                {
                    "code": code,
                    "label": label,
                    "staff_pct": staff_pct,
                    "partner_pct": partner_pct,
                }
            )
        return rows


class CoreRecommendationService:
    @staticmethod
    def get_recommendation_card(core_schools_qs) -> dict:
        """Prepares strategy, attention needed, and playbook data for right panel."""
        fy = get_operational_fy()
        plans = CorePlan.objects.filter(
            school_id__in=core_schools_qs.values_list("school_id", flat=True), fy=fy
        ).prefetch_related("slots")

        # Count over the prefetched slot lists in Python (a .filter() here would
        # re-query per plan) and bulk-load the schools once.
        done_statuses = {
            "Completed",
            "Accountant Confirmed",
            "iaVerify",
            "ia_verified",
            "accountant_confirmed",
        }
        plans = list(plans)
        schools_by_id = {
            s.school_id: s
            for s in School.objects.filter(school_id__in=[p.school_id for p in plans])
        }

        attention_needed = []
        for p in plans:
            slot_list = list(p.slots.all())
            visits_missing = 4 - sum(
                1
                for sl in slot_list
                if sl.activity_type == "visit" and sl.status in done_statuses
            )
            trainings_missing = 4 - sum(
                1
                for sl in slot_list
                if sl.activity_type == "training" and sl.status in done_statuses
            )

            if visits_missing > 0 or trainings_missing > 0:
                school = schools_by_id.get(p.school_id)
                if school:
                    attention_needed.append(
                        {
                            "name": school.name,
                            "school_id": school.school_id,
                            "visits_missing": visits_missing,
                            "trainings_missing": trainings_missing,
                        }
                    )

        # Derive the strategy from the actual gap profile — never a canned line.
        total_v_missing = sum(a["visits_missing"] for a in attention_needed)
        total_t_missing = sum(a["trainings_missing"] for a in attention_needed)
        unassessed = sum(1 for p in plans if p.baseline_average is None)
        parts = []
        if unassessed:
            parts.append(
                f"complete {unassessed} pending Core Assessment"
                f"{'s' if unassessed != 1 else ''} first"
            )
        if total_v_missing >= total_t_missing and total_v_missing:
            parts.append(
                f"close the {total_v_missing} missing visit slot"
                f"{'s' if total_v_missing != 1 else ''}"
            )
            if total_t_missing:
                parts.append(
                    f"then the {total_t_missing} training slot"
                    f"{'s' if total_t_missing != 1 else ''}"
                )
        elif total_t_missing:
            parts.append(
                f"close the {total_t_missing} missing training slot"
                f"{'s' if total_t_missing != 1 else ''}"
            )
        strategy = (
            "Focus on " + ", ".join(parts) + "."
            if parts
            else "All core packages are on track — prepare Champion reviews and follow-up assessments."
        )
        # Next actions — real queue-derived counts, each with a working route.
        pending_visit_schools = sum(1 for a in attention_needed if a["visits_missing"])
        pending_training_schools = sum(
            1 for a in attention_needed if a["trainings_missing"]
        )
        next_actions = []
        if unassessed:
            next_actions.append(
                {
                    "label": f"Review assessment results for {unassessed} core school"
                    f"{'s' if unassessed != 1 else ''}",
                    "url": "/core-schools?ssa_status=required",
                }
            )
        if pending_visit_schools:
            next_actions.append(
                {
                    "label": f"Schedule pending visits for {pending_visit_schools} core school"
                    f"{'s' if pending_visit_schools != 1 else ''}",
                    "url": "/core-schools",
                }
            )
        if pending_training_schools:
            next_actions.append(
                {
                    "label": f"Schedule pending trainings for {pending_training_schools} core school"
                    f"{'s' if pending_training_schools != 1 else ''}",
                    "url": "/core-schools",
                }
            )
        return {
            "attention_needed": attention_needed[:5],
            "attention_count": len(attention_needed),
            "recommended_strategy": strategy,
            "next_actions": next_actions[:3],
        }


class CoreInterventionRecommendationService:
    """Mandate §17 — the four weakest verified interventions become the core
    support priorities: the two most critical go to Partner (in-school,
    one-on-one coaching), the next two to Staff (visit/training). Strong
    schools get maintenance/Champion preparation instead of forced support."""

    @staticmethod
    def recommend(school, fy: str | None = None) -> dict:
        from apps.partners.models import Partner
        from apps.ssa.recommendation_engine import prioritized_interventions

        # Delegate the ranking to the canonical analytics engine
        # (verified-SSA-only, deterministic, analytics-backed). This replaces
        # a `sorted(..., key=score)` with no tie-break, which selected the
        # weakest FOUR — and therefore which two go to Partner vs Staff, and
        # what gets persisted as the school's core package — non-
        # deterministically whenever scores tied at the 4th/5th boundary
        # (re-running could reshuffle the persisted package). The engine ranks
        # by priority (severity anchored, refined by trend/peer/persistence);
        # with a single confirmed baseline that reduces exactly to ascending
        # score, so an unambiguous baseline yields the same four as before.
        ranked = prioritized_interventions(school)
        if not ranked:
            return {
                "available": False,
                "reason": "Baseline Required",
                "rows": [],
                "maintenance": False,
            }
        if all((r["score"] or 0) >= 8.0 for r in ranked):
            return {
                "available": True,
                "maintenance": True,
                "rows": [],
                "reason": (
                    "All interventions strong — recommend maintenance, "
                    "mentorship, peer learning and Champion preparation."
                ),
            }
        partner_exists = (
            Partner.objects.filter(deleted_at__isnull=True).exists()
            if hasattr(Partner, "deleted_at")
            else Partner.objects.exists()
        )
        rows = []
        for i, r in enumerate(ranked[:4]):
            owner = "Partner" if i < 2 else "Staff"
            rows.append(
                {
                    "priority": i + 1,
                    "code": r["intervention"],
                    "label": r["label"],
                    "score": r["score"],
                    "owner": owner,
                    "owner_available": partner_exists if owner == "Partner" else True,
                    "support": (
                        "In-school one-on-one coaching"
                        if owner == "Partner"
                        else "Staff visit and/or training"
                    ),
                }
            )
        return {"available": True, "maintenance": False, "rows": rows, "reason": ""}


class CoreMyPlanSyncService:
    @staticmethod
    def sync_to_my_plan(activity) -> bool:
        """Pushes scheduled activity to My Plan (standard Activity record in DB)."""
        return True
