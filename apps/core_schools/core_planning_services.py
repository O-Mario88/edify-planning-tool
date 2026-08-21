import logging
from datetime import date

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth
from apps.core.logging_filters import escape_control_characters
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
# How many missing CorePlan rows one page load will repair. See the call site.
SELF_HEAL_BATCH = 50

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

    @classmethod
    def commit_schedule(
        cls,
        slot: CoreActivitySlot,
        *,
        activity_id: str,
        scheduled_for,
        scheduled_month: str,
        scheduled_week,
        assigned_staff_id: str,
        partner_id: str | None = None,
    ) -> CoreActivitySlot:
        """Mark a locked slot Scheduled against its created activity.

        The commit half of `assert_can_schedule`. It used to live in the two
        views that call the pair, as identical copy-pasted blocks -- so the
        4 + 4 policy's guard was in this class while the state it protects was
        written elsewhere, and a third caller could lock a slot and then write
        any status it liked. Guard and commit belong to the same owner.
        """
        slot.status = "Scheduled"
        slot.activity_id = activity_id
        slot.scheduled_for = scheduled_for
        slot.scheduled_month = scheduled_month
        slot.scheduled_week = scheduled_week
        slot.assigned_staff_id = assigned_staff_id
        if partner_id:
            slot.assigned_partner_id = partner_id
            slot.owner = "partner"
        else:
            slot.owner = "staff"
        slot.save()
        return slot

    @classmethod
    def commit_assign(
        cls, slot: CoreActivitySlot, *, partner_id: str, partner_name: str
    ) -> CoreActivitySlot:
        """Reserve a locked slot for a partner (the commit half of
        `assert_can_assign`)."""
        slot.status = "Assigned"
        slot.assigned_partner_id = partner_id
        slot.assigned_partner_name = partner_name
        slot.owner = "partner"
        slot.save()
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
    def base_queryset(user, *, lens: str = "direct"):
        """The core schools a lens may show.

        Two lenses, two disjoint sets, and the caller must say which it means:

        * ``direct`` — the core schools assigned to this person. This is the
          operational list: it carries Schedule Visit, Schedule Training,
          Assign Partner and Upload Assessment, so it may only contain schools
          those buttons will actually work on.
        * ``oversight`` — a supervisor's supervisees' core schools, read-only.

        The page used to build its list from `analytics._scoped_schools`, which
        is the aggregate scope — own **plus** team. A Programme Lead therefore
        opened Core Schools onto their CCEOs' packages with every operational
        control live beside them; on this deployment that was 103 core schools
        for a lead who is directly assigned none.
        """
        from apps.core.scoping import (
            direct_portfolio_schools,
            resolve_user_scope,
            team_oversight_schools,
        )
        from apps.schools.models import School

        scope = resolve_user_scope(user)
        base = School.objects.filter(deleted_at__isnull=True)
        if lens == "oversight":
            qs = team_oversight_schools(scope, base=base)
        else:
            qs = direct_portfolio_schools(scope)
        return (qs if qs is not None else School.objects.none()).filter(
            school_type="core"
        ), scope

    @staticmethod
    def get_core_schools(user, filters: dict, *, lens: str = "direct"):
        """Scopes and filters core schools for the page."""
        core_schools_qs, scope = CoreSchoolsService.base_queryset(user, lens=lens)

        # 1. Self-healing check: ensure all core schools have a CorePlan for the current FY
        #
        # Bounded. This runs on every page load over the whole scoped set, and
        # a country role's set is every core school in the deployment — 1,407
        # here — so an unbounded `list()` pulled the entire table into memory
        # to find the handful with no plan. The cap is per request and the work
        # is idempotent, so a large backlog drains over successive loads
        # instead of making one load pay for all of it.
        fy = filters.get("fy") or get_operational_fy()
        uninitialized_schools = list(
            core_schools_qs.exclude(
                school_id__in=CorePlan.objects.filter(fy=fy).values_list(
                    "school_id", flat=True
                )
            )[:SELF_HEAL_BATCH]
        )
        if uninitialized_schools:
            from django.db import transaction

            interventions = [i.value for i in SsaIntervention]
            # One bounded query for the cohort, rather than one reverse-FK
            # lookup per school.  Keep this portable across PostgreSQL and the
            # SQLite test database by selecting the first row per school in
            # Python from an explicitly ordered result set.
            latest_ssa_by_school = {}
            confirmed_records = SsaRecord.objects.filter(
                school_id__in=[school.id for school in uninitialized_schools],
                deleted_at__isnull=True,
                verification_status="confirmed",
            ).order_by("school_id", "-date_of_ssa", "-created_at")
            for record in confirmed_records:
                latest_ssa_by_school.setdefault(record.school_id, record)

            # Provenance for auto-created plans/slots — same shape as the
            # audited onboard() path (created_by_id/created_by_name), so a
            # self-healed record is never indistinguishable from a hand-made
            # one with no author on file.
            actor_id = getattr(user, "user_id", None) or getattr(user, "id", None)
            actor_name = getattr(user, "name", None) or "System (auto-heal)"
            for s in uninitialized_schools:
                latest = latest_ssa_by_school.get(s.id)
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
                        escape_control_characters(str(s.school_id)),
                    )
                    continue
                baseline_avg = latest.average_score
                plan_id = cplan_id(s.school_id, fy=fy)
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
                    # Lazy %-args rather than an f-string: the filter that
                    # escapes line breaks works on the record's arguments, and
                    # a message already formatted has nothing left to clean.
                    logger.error(
                        "Error auto-onboarding core school %s: %s",
                        escape_control_characters(str(s.school_id)),
                        escape_control_characters(str(e)),
                    )

        # 2. Apply filters
        #
        # Search runs last, over the already-scoped and already-filtered set, so
        # a query can only ever narrow what the user could reach anyway. Core
        # Schools shipped with no search at all: the only way to reach one
        # school in a paginated matrix was to page through it.
        search_q = str(filters.get("q") or "").strip()
        if search_q:
            core_schools_qs = core_schools_qs.filter(
                Q(name__icontains=search_q)
                | Q(school_id__icontains=search_q)
                | Q(district__name__icontains=search_q)
                | Q(sub_county__name__icontains=search_q)
                | Q(account_owner_name_raw__icontains=search_q)
            )

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

        # Partner support, as one grouped read. The compact row shows it beside
        # the visit and training counts because "is anyone else carrying part
        # of this package" is one of the nine facts §15 asks a core row for.
        partner_counts_map = {
            item["school_id"]: item["count"]
            for item in PartnerAssignment.objects.filter(school_id__in=db_ids)
            .values("school_id")
            .annotate(count=Count("id"))
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
                    "partner_support_count": partner_counts_map.get(s.id, 0),
                    "score_pct": score_pct,
                    "score_label": score_label,
                    "score_badge_class": badge_class,
                    "has_ssa": latest_ssa is not None,
                    "has_ssa_scores": ssa_summary["has_scores"],
                    "ssa_average": ssa_summary["average_score"],
                    "ssa_average_tone": ssa_summary["average_tone"],
                    "ssa_groups": ssa_summary["groups"],
                    "assessment": assessment_cell,
                    # The plan's own flag, not the slot pill. The slot can
                    # read "Complete" from a scheduling state while the plan
                    # still records no assessment on file, and the oversight
                    # table and the "Send to…" it offers were reading one
                    # each — so a row said Complete and the ask it produced
                    # said Outstanding. One field now answers both.
                    "assessment_completed": bool(plan and plan.assessment_completed),
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
                    # Raw counts drive the segmented progress display; the
                    # formatted strings above stay for any legacy consumer.
                    "visits_done": visits_done,
                    "trainings_done": trainings_done,
                    "assessment_done": assessment_done,
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
                school__in=core_schools_qs,
                deleted_at__isnull=True,
                # Only verified assessments may drive the trend (methodology
                # guardrail) — pending/returned records are not outcomes.
                verification_status="confirmed",
            )
            .annotate(month=TruncMonth("date_of_ssa"))
            .values("month")
            .annotate(avg=Avg("average_score"), n=Count("id"))
            .order_by("month")
        )
        trend = [
            {
                "label": m["month"].strftime("%b %Y"),
                "avg": round(m["avg"], 1),
                "n": m["n"],
            }
            for m in monthly
            if m["avg"] is not None and m["month"] is not None
        ]
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

        active_statuses = [
            "planned",
            "scheduled",
            "partner_scheduled",
            "in_progress",
            "completed",
            "accountant_confirmed",
        ]
        completed_statuses = [
            "Completed",
            "Accountant Confirmed",
            "accountant_confirmed",
            "ia_verified",
            "IA Verified",
            "iaVerify",
        ]

        # Every metric below is batched across all intervention codes. The old
        # implementation repeated the same 8–10 queries once per row.
        activity_base = Activity.objects.filter(
            school__in=core_schools_qs,
            fy=fy,
            deleted_at__isnull=True,
        )
        supported_by_code = {
            row["focus_intervention"]: row["count"]
            for row in activity_base.filter(status__in=active_statuses)
            .values("focus_intervention")
            .annotate(count=Count("school", distinct=True))
        }
        owner_counts = list(
            activity_base.values("focus_intervention", "responsible_staff_id").annotate(
                count=Count("id")
            )
        )
        top_owner_id: dict[str, str | None] = {}
        top_owner_count: dict[str, int] = {}
        for row in owner_counts:
            code = row["focus_intervention"]
            if row["count"] > top_owner_count.get(code, -1):
                top_owner_count[code] = row["count"]
                top_owner_id[code] = row["responsible_staff_id"]
        owner_names = {
            str(row["user_id"]): row["user__name"]
            for row in StaffProfile.objects.filter(
                user_id__in=[value for value in top_owner_id.values() if value]
            ).values("user_id", "user__name")
        }

        slot_rows = list(
            CoreActivitySlot.objects.filter(
                school_id__in=school_ids,
                core_plan__fy=fy,
            ).values("intervention", "school_id", "owner", "status")
        )
        completed_by_code: dict[str, set[str]] = {}
        staff_by_code: dict[str, set[str]] = {}
        partner_by_code: dict[str, set[str]] = {}
        for row in slot_rows:
            code = row["intervention"]
            school_id = row["school_id"]
            if row["status"] in completed_statuses:
                completed_by_code.setdefault(code, set()).add(school_id)
            owner_bucket = (
                partner_by_code if row["owner"] == "partner" else staff_by_code
            )
            owner_bucket.setdefault(code, set()).add(school_id)

        plan_deltas = {
            row["school_id"]: row["follow_up_average"] - row["baseline_average"]
            for row in CorePlan.objects.filter(
                school_id__in=school_ids,
                fy=fy,
                baseline_average__isnull=False,
                follow_up_average__isnull=False,
            ).values("school_id", "baseline_average", "follow_up_average")
        }

        score_totals = {
            (row["intervention"], row["ssa_record__school__school_id"]): (
                row["total"],
                row["count"],
            )
            for row in SsaScore.objects.filter(
                ssa_record__school__school_id__in=school_ids,
                ssa_record__deleted_at__isnull=True,
            )
            .values("intervention", "ssa_record__school__school_id")
            .annotate(total=Sum("score"), count=Count("id"))
        }

        trends_by_code: dict[str, list[float]] = {}
        monthly_rows = (
            SsaScore.objects.filter(
                ssa_record__school__school_id__in=school_ids,
                ssa_record__deleted_at__isnull=True,
            )
            .annotate(month=TruncMonth("ssa_record__date_of_ssa"))
            .values("intervention", "month")
            .annotate(avg=Avg("score"))
            .order_by("intervention", "month")
        )
        for row in monthly_rows:
            if row["avg"] is not None:
                trends_by_code.setdefault(row["intervention"], []).append(
                    round(row["avg"], 2)
                )

        interventions_data = []
        for code, label in SsaIntervention.choices:
            deltas = [
                plan_deltas[school_id]
                for school_id in completed_by_code.get(code, set())
                if school_id in plan_deltas
            ]
            has_improvement_data = bool(deltas)
            avg_improvement = round(sum(deltas) / len(deltas), 1) if deltas else 0

            def group_average(group: set[str]) -> float | None:
                totals = [
                    score_totals[(code, school_id)]
                    for school_id in group
                    if (code, school_id) in score_totals
                ]
                count = sum(item[1] for item in totals)
                return (
                    round(sum(item[0] for item in totals) / count, 1) if count else None
                )

            staff_schools = staff_by_code.get(code, set())
            partner_schools = partner_by_code.get(code, set())
            if staff_schools and partner_schools:
                staff_pct = group_average(staff_schools)
                partner_pct = group_average(partner_schools)
            else:
                staff_pct = partner_pct = None
            if staff_pct is not None and partner_pct is not None:
                diff = staff_pct - partner_pct
                comparison = (
                    f"Staff +{diff}pp" if diff >= 0 else f"Partner +{abs(diff)}pp"
                )
            else:
                comparison = "Insufficient data"

            trend_values = trends_by_code.get(code, [])
            trend = trend_values if len(trend_values) >= 2 else []
            owner_id = top_owner_id.get(code)
            top_owner = owner_names.get(str(owner_id), "Unassigned")

            interventions_data.append(
                {
                    "code": code,
                    "label": label,
                    "supported_count": supported_by_code.get(code, 0),
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
            is_partner = any(slot.owner == "partner" for slot in p.slots.all())
            if is_partner:
                partner_deltas.append(delta)
            else:
                staff_deltas.append(delta)

        # With no paired SSA cycles anywhere in scope there is no comparison to
        # report. A zero here would read as "staff and partners performed
        # identically" — a finding — when the truth is that nothing has been
        # measured yet, so the delta stays None and the KPI says so.
        avg_staff = sum(staff_deltas) / len(staff_deltas) if staff_deltas else 0
        avg_partner = sum(partner_deltas) / len(partner_deltas) if partner_deltas else 0
        delta = (avg_staff - avg_partner) if (staff_deltas or partner_deltas) else None

        # Organization benchmark: the average verified core score across the
        # whole scoped cohort — every row compares against this one number.
        org_average = CoreAssessmentService.get_average_score(core_schools_qs)
        org_average = round(org_average, 1) if org_average else None

        def _vs_avg(score):
            if score is None or org_average is None:
                return None
            return round(score - org_average, 1)

        def _initials(name):
            parts = [w for w in (name or "").split() if w]
            return (
                (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()
                if parts
                else "–"
            )

        # ── One read of the cohort, then group in memory ──────────────────
        #
        # These three blocks used to walk every StaffProfile, every Partner
        # and every Region, running a .count() and a two-query average for
        # each — 101 queries of the page's 258, on a page that then keeps the
        # top FIVE rows of each and discards the rest. The work was real and
        # almost all of it was thrown away.
        #
        # The cohort is core schools only, so it is small enough to group in
        # Python. What must not change is WHICH average each row reports:
        # staff and partner rows use the latest verified-or-not record per
        # school (CoreAssessmentService.get_average_score), while regions
        # deliberately average every confirmed record. Those are different
        # numbers and both are intentional, so they are computed separately
        # below rather than unified into one convenient figure.
        cohort = list(
            core_schools_qs.values_list("id", "account_owner_id", "region_id")
        )
        cohort_ids = [row[0] for row in cohort]

        latest_ids = list(
            SsaRecord.objects.filter(school_id__in=cohort_ids, deleted_at__isnull=True)
            .order_by("school_id", "-date_of_ssa")
            .distinct("school_id")
            .values_list("id", flat=True)
        )
        latest_by_school = dict(
            SsaRecord.objects.filter(id__in=latest_ids).values_list(
                "school_id", "average_score"
            )
        )

        def _grouped_score(school_ids):
            """The latest-record average for a group, or None if unscored."""
            scores = [
                latest_by_school[sid]
                for sid in school_ids
                if latest_by_school.get(sid) is not None
            ]
            if not scores:
                return None
            return round(round(sum(scores) / len(scores), 2), 1) or None

        # account_owner_id holds either a StaffProfile id or a User id
        # depending on how the school was assigned, so both spaces map to the
        # same person — the original `__in=[staff.id, staff.user_id]`.
        owner_schools: dict[str, list[str]] = {}
        for school_id, owner_id, _region_id in cohort:
            if owner_id:
                owner_schools.setdefault(owner_id, []).append(school_id)

        staff_insights = []
        for staff in StaffProfile.objects.all().select_related("user"):
            school_ids = owner_schools.get(staff.id, []) + owner_schools.get(
                staff.user_id, []
            )
            if not school_ids:
                continue
            score = _grouped_score(school_ids)
            staff_insights.append(
                {
                    "name": staff.user.name,
                    "initials": _initials(staff.user.name),
                    "score": score,
                    "school_count": len(school_ids),
                    "vs_avg": _vs_avg(score),
                    "insufficient": score is None,
                }
            )
        staff_insights.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        staff_insights = staff_insights[:5]

        cohort_id_set = set(cohort_ids)
        partner_schools: dict[str, set[str]] = {}
        for partner_id, school_id in PartnerAssignment.objects.filter(
            school__school_type="core"
        ).values_list("partner_id", "school_id"):
            if school_id in cohort_id_set:
                partner_schools.setdefault(partner_id, set()).add(school_id)

        partner_insights = []
        for part in Partner.objects.all():
            school_ids = partner_schools.get(part.id)
            if not school_ids:
                continue
            score = _grouped_score(school_ids)
            partner_insights.append(
                {
                    "name": part.name,
                    "initials": _initials(part.name),
                    "score": score,
                    "school_count": len(school_ids),
                    "vs_avg": _vs_avg(score),
                    "insufficient": score is None,
                }
            )
        partner_insights.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        partner_insights = partner_insights[:5]

        # Regions: scoped to THIS cohort's schools and verified records only
        # (the previous version averaged every SSA in the region, scoped or
        # not). Regions with no scored core schools read as insufficient.
        # Confirmed records only, and EVERY confirmed record rather than the
        # latest per school — different from the staff/partner figure above
        # on purpose, so it is aggregated separately. One grouped query
        # replaces a count plus an average per region.
        region_schools: dict[str, list[str]] = {}
        for school_id, _owner_id, region_id in cohort:
            if region_id:
                region_schools.setdefault(region_id, []).append(school_id)

        region_averages = {
            row["school__region_id"]: row["avg"]
            for row in SsaRecord.objects.filter(
                school_id__in=cohort_ids,
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .values("school__region_id")
            .annotate(avg=Avg("average_score"))
        }

        region_insights = []
        for reg in Region.objects.all():
            school_ids = region_schools.get(reg.id)
            if not school_ids:
                continue
            avg_reg = region_averages.get(reg.id)
            score = round(avg_reg, 1) if avg_reg else None
            region_insights.append(
                {
                    "name": reg.name,
                    "score": score,
                    "school_count": len(school_ids),
                    "vs_avg": _vs_avg(score),
                    "insufficient": score is None,
                }
            )
        region_insights.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
        scored_regions = [r for r in region_insights if r["score"] is not None]
        top_region = scored_regions[0] if scored_regions else None

        return {
            # Score points, not percentage points: this is the gap between two
            # averages of SSA score movement, both measured on the 0–10 scale.
            "delta_points": round(delta, 1) if delta is not None else None,
            "org_average": org_average,
            "staff_insights": staff_insights,
            "partner_insights": partner_insights,
            "region_insights": region_insights,
            "top_region": top_region,
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
                    # Both values are average core scores on the 0-10 scale —
                    # the gap is score points, never percentage points.
                    "gap": round(staff_pct - partner_pct, 1),
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
                "reason": "SSA Required",
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


class CoreTeamOversightService:
    """The read-only lens a supervisor gets over their team's core schools.

    Deliberately a different shape from the operational rows. It answers the
    supervisor's question — *who is answerable, what is stuck, and what can I
    ask for* — rather than offering the CCEO's controls at one remove. Nothing
    in here schedules, assigns or edits: the only action it produces is a
    TeamAction addressed to the person who owns the work.

    Every figure is folded from the same matrix rows the operational list
    builds, plus three bounded lookups (partner support, activity state,
    actions already sent), so the two lenses can never disagree about a
    school's progress.
    """

    # Ordered most- to least-blocking. The first condition that holds is the
    # blocker; the ask attached to it is the one worth sending.
    #
    # The fourth value is the design-system badge variant, resolved here rather
    # than mapped in the template: `edify-status-badge` takes success/warning/
    # danger/info/pending, and a template that translated "critical" into a
    # class name would be a second vocabulary to keep in step with this one.
    _BLOCKERS = (
        (
            "core_assessment_missing",
            "Assessment due",
            "critical",
            "danger",
        ),
        (
            "core_package_behind",
            "Package behind",
            "warning",
            "warning",
        ),
    )

    @staticmethod
    def build_rows(matrix_rows: list[dict], fy: str) -> list[dict]:
        from apps.core.activity_types import COMPLETED_WORK_STATUSES
        from apps.planning.action_models import ACTIVE_STATES, TeamAction

        if not matrix_rows:
            return []

        db_ids = [r["id"] for r in matrix_rows]

        partner_counts = {
            row["school_id"]: row["n"]
            for row in PartnerAssignment.objects.filter(school_id__in=db_ids)
            .values("school_id")
            .annotate(n=Count("id"))
        }

        # One pass for the delivery chain: evidence, Salesforce, IA and
        # finance are four questions about the same activities, so they are
        # four conditional counts over one scan rather than four queries.
        activity_state = {
            row["school_id"]: row
            for row in Activity.objects.filter(
                school_id__in=db_ids,
                fy=fy,
                activity_type__in=("core_visit", "core_training"),
                deleted_at__isnull=True,
            )
            .exclude(status="cancelled")
            .values("school_id")
            .annotate(
                total=Count("id"),
                evidence_outstanding=Count(
                    "id", filter=Q(evidence_status__in=("", "pending", "not_uploaded"))
                ),
                salesforce_missing=Count(
                    "id",
                    filter=Q(status__in=tuple(COMPLETED_WORK_STATUSES))
                    & (
                        Q(salesforce_activity_id__isnull=True)
                        | Q(salesforce_activity_id="")
                    ),
                ),
                ia_pending=Count("id", filter=Q(status="awaiting_ia_verification")),
                finance_pending=Count("id", filter=Q(payment_status="pending")),
            )
        }

        sent = {
            (a.school_id, a.issue_type): a
            for a in TeamAction.objects.filter(
                school_id__in=db_ids, fy=fy, state__in=ACTIVE_STATES
            )
        }

        rows = []
        for r in matrix_rows:
            state = activity_state.get(r["id"], {})
            assessment_done = r["assessment_completed"]
            blocker_key = blocker_label = blocker_severity = blocker_tone = ""
            for key, label, severity, tone in CoreTeamOversightService._BLOCKERS:
                if key == "core_assessment_missing" and assessment_done:
                    continue
                if key == "core_package_behind" and r["package_complete"]:
                    continue
                blocker_key, blocker_label = key, label
                blocker_severity, blocker_tone = severity, tone
                break

            existing = sent.get((r["id"], blocker_key)) if blocker_key else None
            rows.append(
                {
                    **r,
                    "responsible_cceo": r["staff_name"],
                    # "Send to James", not "Send to James Okello" — §7 asks for
                    # the first name, and the button reads as a message to a
                    # colleague rather than a system operation on a record.
                    "responsible_first_name": (r["staff_name"] or "").split(" ")[0]
                    or "the owner",
                    "partner_support": partner_counts.get(r["id"], 0),
                    "evidence_outstanding": state.get("evidence_outstanding", 0),
                    "salesforce_missing": state.get("salesforce_missing", 0),
                    "ia_pending": state.get("ia_pending", 0),
                    "finance_pending": state.get("finance_pending", 0),
                    "assessment_done": assessment_done,
                    "blocker_key": blocker_key,
                    "blocker_label": blocker_label or "No blocker",
                    "blocker_severity": blocker_severity or "ok",
                    "blocker_tone": blocker_tone or "success",
                    "action_id": existing.id if existing else "",
                    "action_state": existing.get_state_display() if existing else "",
                }
            )
        return rows
