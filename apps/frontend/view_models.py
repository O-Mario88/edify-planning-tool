from __future__ import annotations

from typing import TYPE_CHECKING
from apps.core.permissions import has_permission

if TYPE_CHECKING:
    from apps.schools.models import School
    from apps.accounts.jwt import AuthPrincipal


class SchoolDirectoryViewModel:
    @staticmethod
    def from_school(school: School, user: AuthPrincipal, clusters_dict: dict[str, str], active_projects_exist: bool) -> dict:
        is_clustered = school.cluster_id is not None or school.cluster_status == "clustered"
        
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
                disabled_reasons["add_to_cluster"] = "You do not have permission to assign clusters."
                
        # Assign to Project action
        if not active_projects_exist:
            disabled_reasons["assign_to_project"] = "No active project available."
        elif not can_assign_project:
            disabled_reasons["assign_to_project"] = "You do not have permission to assign projects."
        else:
            available_actions.append("assign_to_project")
            
        # Resolve cluster name from pre-loaded dict
        cluster_name = "—"
        if is_clustered and school.cluster_id:
            cluster_name = clusters_dict.get(school.cluster_id, "—")
            
        is_core_school = (school.school_type == "core")
        
        # Calculate dynamic planning gaps for cards
        from apps.ssa.models import SsaRecord
        from apps.activities.models import Activity
        
        has_ssa = SsaRecord.objects.filter(school=school, verification_status="confirmed", deleted_at__isnull=True).exists()
        has_visit = Activity.objects.filter(school=school, activity_type__in=["school_visit", "core_visit", "baseline_ssa_visit"], status="completed", deleted_at__isnull=True).exists()
        has_training = Activity.objects.filter(school=school, activity_type__in=["training", "core_training"], status="completed", deleted_at__isnull=True).exists()
        if not has_training:
            has_training = Activity.objects.filter(
                activity_type__in=["cluster_training", "cluster_meeting"],
                status="completed",
                deleted_at__isnull=True,
                attended_school_ids__contains=[str(school.id)]
            ).exists()
            
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
            visits_count = Activity.objects.filter(
                school=school, 
                activity_type__in=["school_visit", "core_visit", "baseline_ssa_visit"], 
                status="completed", 
                deleted_at__isnull=True
            ).count()
            visits_count = min(4, visits_count)
            
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
            trainings_count = Activity.objects.filter(
                school=school, 
                activity_type__in=["training", "core_training"], 
                status="completed", 
                deleted_at__isnull=True
            ).count()
            
            cluster_trainings_attended = Activity.objects.filter(
                activity_type__in=["cluster_training", "cluster_meeting"],
                status="completed",
                deleted_at__isnull=True,
                attended_school_ids__contains=[str(school.id)]
            ).count()
            
            trainings_count = min(4, trainings_count + cluster_trainings_attended)
            
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
                
            core_support_complete = (visits_count >= 4 and trainings_count >= 4)
            
        is_high_priority = (school.data_quality_score or 0) < 70 or not is_clustered or not has_ssa

        return {
            "id": school.id,
            "school_id": school.school_id,
            "school_name": school.name,
            "school_type": school.get_school_type_display(),
            "district": school.district.name if school.district else "—",
            "sub_county": school.sub_county.name if school.sub_county else "—",
            "enrolment": school.enrollment or 0,
            "phone": school.school_phone or "—",
            "school_contact": school.primary_contact_name or "—",
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
