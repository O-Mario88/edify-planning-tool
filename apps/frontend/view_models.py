from __future__ import annotations

from typing import TYPE_CHECKING
from apps.core.permissions import has_permission

if TYPE_CHECKING:
    from apps.schools.models import School
    from apps.accounts.jwt import AuthPrincipal


class SchoolDirectoryViewModel:
    @staticmethod
    def bulk_progress(school_ids: list[str], fy: str | None = None) -> dict[str, dict]:
        """Batch-compute the SSA/visit/training progress counters that
        from_school() needs for a page of schools, in a handful of queries
        instead of ~5-7 queries per school (avoids N+1 on the directory list).

        When a financial year is supplied, score groups come from each
        school's latest confirmed assessment in that selected year. Returns
        {school_id: {"has_ssa": bool, "visits_count": int,
        "trainings_count": int, "ssa_groups": list}}. Pass the result as
        ``progress`` to from_school() for each school on the page.
        """
        from django.db.models import Count
        from apps.ssa.models import SsaRecord
        from apps.activities.models import Activity
        from apps.ssa.presentation import build_ssa_score_summary

        school_ids = list(school_ids)
        if not school_ids:
            return {}

        ssa_records = SsaRecord.objects.filter(
            school_id__in=school_ids,
            verification_status="confirmed",
            deleted_at__isnull=True,
        )
        if fy:
            ssa_records = ssa_records.filter(fy=fy)

        latest_ssa_by_school = {}
        for record in ssa_records.prefetch_related("scores").order_by(
            "school_id", "-date_of_ssa", "-created_at"
        ):
            latest_ssa_by_school.setdefault(record.school_id, record)

        ssa_by_school = {
            school_id: build_ssa_score_summary(
                [
                    {"intervention": score.intervention, "score": score.score}
                    for score in record.scores.all()
                ]
            )
            for school_id, record in latest_ssa_by_school.items()
        }

        visits_by_school: dict[str, int] = dict(
            Activity.objects.filter(
                school_id__in=school_ids,
                activity_type__in=["school_visit", "core_visit", "baseline_ssa_visit"],
                status="completed",
                deleted_at__isnull=True,
            )
            .values("school_id")
            .annotate(c=Count("id"))
            .values_list("school_id", "c")
        )

        trainings_by_school: dict[str, int] = dict(
            Activity.objects.filter(
                school_id__in=school_ids,
                activity_type__in=["training", "core_training"],
                status="completed",
                deleted_at__isnull=True,
            )
            .values("school_id")
            .annotate(c=Count("id"))
            .values_list("school_id", "c")
        )

        # Cluster-wide trainings/meetings record attendance via a JSON array
        # of school ids rather than a school FK, so they can't be grouped
        # with a values().annotate() the way the two querysets above are.
        # Fetch the (bounded) set of qualifying activities once and tally
        # attendance in Python instead of re-querying per school.
        wanted = set(school_ids)
        cluster_attended = Activity.objects.filter(
            activity_type__in=["cluster_training", "cluster_meeting"],
            status="completed",
            deleted_at__isnull=True,
            attended_school_ids__overlap=list(wanted),
        ).values_list("attended_school_ids", flat=True)
        for attended in cluster_attended:
            for sid in attended or []:
                if sid in wanted:
                    trainings_by_school[sid] = trainings_by_school.get(sid, 0) + 1

        return {
            sid: {
                "has_ssa": sid in latest_ssa_by_school,
                "visits_count": visits_by_school.get(sid, 0),
                "trainings_count": trainings_by_school.get(sid, 0),
                "has_ssa_scores": ssa_by_school.get(sid, {}).get("has_scores", False),
                "ssa_average": ssa_by_school.get(sid, {}).get("average_score"),
                "ssa_average_tone": ssa_by_school.get(sid, {}).get("average_tone", "neutral"),
                "ssa_groups": ssa_by_school.get(sid, {}).get("groups", []),
            }
            for sid in school_ids
        }

    @staticmethod
    def from_school(
        school: School,
        user: AuthPrincipal,
        clusters_dict: dict[str, str],
        active_projects_exist: bool,
        progress: dict | None = None,
        staff_names_by_owner_id: dict[str, str] | None = None,
    ) -> dict:
        is_clustered = (
            school.cluster_id is not None or school.cluster_status == "clustered"
        )

        # Project assignments count
        project_count = getattr(school, "_project_count", None)
        if project_count is None:
            project_count = school.project_assignments.count()

        # Determine available actions & disabled reasons
        can_assign_cluster = has_permission(user, "cluster.assign")
        can_assign_project = has_permission(user, "project.assignSchool")

        available_actions = []
        disabled_reasons = {}

        # Add to Cluster action
        if not is_clustered:
            if can_assign_cluster:
                available_actions.append("add_to_cluster")
            else:
                disabled_reasons["add_to_cluster"] = (
                    "You do not have permission to assign clusters."
                )

        # Assign to Project action
        if not active_projects_exist:
            disabled_reasons["assign_to_project"] = "No active project available."
        elif not can_assign_project:
            disabled_reasons["assign_to_project"] = (
                "You do not have permission to assign projects."
            )
        else:
            available_actions.append("assign_to_project")

        # Resolve cluster name from pre-loaded dict
        cluster_name = "—"
        if is_clustered and school.cluster_id:
            cluster_name = clusters_dict.get(school.cluster_id, "—")

        staff_name = (
            (staff_names_by_owner_id or {}).get(school.account_owner_id)
            or school.account_owner_name_raw
            or "Unassigned"
        )

        is_core_school = school.school_type == "core"

        # Calculate dynamic planning gaps for cards. Callers rendering a
        # page of schools should batch-compute this once via
        # SchoolDirectoryViewModel.bulk_progress(school_ids) and pass the
        # per-school entry as `progress` — falling back here (single
        # per-school query batch) keeps single-school callers (e.g. the
        # school detail drawer, tests) working without a page-level
        # precompute step.
        if progress is None:
            progress = SchoolDirectoryViewModel.bulk_progress([school.id]).get(
                school.id,
                {
                    "has_ssa": False,
                    "visits_count": 0,
                    "trainings_count": 0,
                    "has_ssa_scores": False,
                    "ssa_average": None,
                    "ssa_average_tone": "neutral",
                    "ssa_groups": [],
                },
            )

        has_ssa = progress["has_ssa"]
        visits_count_raw = progress["visits_count"]
        trainings_count_raw = progress["trainings_count"]
        has_visit = visits_count_raw > 0
        has_training = trainings_count_raw > 0

        # Core School Progressive Status Calculation
        visit_status_label = ""
        visit_status_type = ""
        training_status_label = ""
        training_status_type = ""
        assessment_status_label = ""
        assessment_status_type = ""
        core_support_complete = False

        if is_core_school:
            # 1. Assessment Status
            if has_ssa:
                assessment_status_label = "Assessed"
                assessment_status_type = "success"
            else:
                assessment_status_label = "No Assessment"
                assessment_status_type = "danger"

            # 2. Support Visits Count
            visits_count = min(4, visits_count_raw)

            if visits_count == 0:
                visit_status_label = "No 1st Visit"
                visit_status_type = "danger"
            elif visits_count == 1:
                visit_status_label = "No 2nd Visit"
                visit_status_type = "warning"
            elif visits_count == 2:
                visit_status_label = "No 3rd Visit"
                visit_status_type = "warning"
            elif visits_count == 3:
                visit_status_label = "No 4th Visit"
                visit_status_type = "warning"
            else:
                visit_status_label = "Support Visits Complete"
                visit_status_type = "success"

            # 3. Trainings Count (Individual + Cluster Attendances)
            trainings_count = min(4, trainings_count_raw)

            if trainings_count == 0:
                training_status_label = "No 1st Training"
                training_status_type = "danger"
            elif trainings_count == 1:
                training_status_label = "No 2nd Training"
                training_status_type = "warning"
            elif trainings_count == 2:
                training_status_label = "No 3rd Training"
                training_status_type = "warning"
            elif trainings_count == 3:
                training_status_label = "No 4th Training"
                training_status_type = "warning"
            else:
                training_status_label = "Training Package Complete"
                training_status_type = "success"

            core_support_complete = visits_count >= 4 and trainings_count >= 4

        is_high_priority = (
            (school.data_quality_score or 0) < 70 or not is_clustered or not has_ssa
        )

        return {
            "id": school.id,
            "school_id": school.school_id,
            "school_name": school.name,
            "school_type": school.get_school_type_display(),
            "district": school.district.name if school.district else "—",
            "sub_county": school.sub_county.name if school.sub_county else "—",
            "shipping_address": school.shipping_address or "—",
            "enrolment": school.enrollment or 0,
            "phone": school.school_phone or "—",
            "school_contact": school.primary_contact_name or "—",
            "staff_name": staff_name,
            "is_clustered": is_clustered,
            "cluster_id": school.cluster_id,
            "cluster_name": cluster_name,
            "project_assignment_count": project_count,
            "available_actions": available_actions,
            "disabled_reasons": disabled_reasons,
            "data_quality_status": school.data_quality_status,
            "data_quality_score": school.data_quality_score,
            "has_ssa": has_ssa,
            "has_visit": has_visit,
            "has_training": has_training,
            "visit_count": visits_count_raw,
            "training_count": trainings_count_raw,
            "has_ssa_scores": progress.get("has_ssa_scores", False),
            "ssa_average": progress.get("ssa_average"),
            "ssa_average_tone": progress.get("ssa_average_tone", "neutral"),
            "ssa_groups": progress.get("ssa_groups", []),
            "is_high_priority": is_high_priority,
            "is_core_school": is_core_school,
            "visit_status_label": visit_status_label,
            "visit_status_type": visit_status_type,
            "training_status_label": training_status_label,
            "training_status_type": training_status_type,
            "assessment_status_label": assessment_status_label,
            "assessment_status_type": assessment_status_type,
            "core_support_complete": core_support_complete,
        }
