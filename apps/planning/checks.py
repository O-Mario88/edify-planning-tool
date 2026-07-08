from django.core.checks import Error, register, Tags
from apps.schools.models import School
from apps.activities.models import Activity
from apps.core_schools.models import CorePlan

@register(Tags.compatibility)
def check_school_planning_flow(app_configs, **kwargs):
    errors = []
    
    # 1. Unclustered scheduling check
    # Activities that are scheduled but the school has no cluster
    unclustered_activities = Activity.objects.filter(
        deleted_at__isnull=True,
        school__isnull=False,
        school__cluster_id__isnull=True
    ).exclude(status__in=["cancelled", "deferred", "not_planned", "planned"]).select_related("school")
    
    for act in unclustered_activities:
        errors.append(
            Error(
                f"Activity '{act.id}' is scheduled for unclustered school '{act.school.name}'.",
                hint="Assign the school to a cluster before scheduling activities.",
                obj=act,
                id="planning.E001",
            )
        )
        
    # 2. Core school missing package slots check
    # Core schools that don't have exactly 4 visits and 4 trainings slots in their active CorePlan
    core_schools = School.objects.filter(school_type="core", deleted_at__isnull=True)
    for school in core_schools:
        plan = CorePlan.objects.filter(school_id=school.school_id).first()
        if not plan:
            errors.append(
                Error(
                    f"Core school '{school.name}' is missing an active CorePlan.",
                    hint="Initialize the core plan for this school.",
                    obj=school,
                    id="planning.E002",
                )
            )
        else:
            slots = plan.slots.all()
            visits_count = slots.filter(activity_type="visit").count()
            trainings_count = slots.filter(activity_type="training").count()
            if visits_count < 4 or trainings_count < 4:
                errors.append(
                    Error(
                        f"Core school '{school.name}' has incomplete package slots (Visits: {visits_count}, Trainings: {trainings_count}).",
                        hint="Ensure all 4 visits and 4 trainings slots are created for the core plan.",
                        obj=plan,
                        id="planning.E003",
                    )
                )
                
    # 3. Partner scheduling alignment check
    # Detect activities assigned to a partner where no matching active PartnerAssignment exists
    from apps.partners.models import PartnerAssignment
    partner_activities = Activity.objects.filter(
        deleted_at__isnull=True,
        school__isnull=False,
        assigned_partner_id__isnull=False
    ).exclude(status="cancelled").select_related("school")
    
    for act in partner_activities:
        has_assignment = PartnerAssignment.objects.filter(
            school_id=act.school_id,
            partner_id=act.assigned_partner_id
        ).exists()
        if not has_assignment:
            errors.append(
                Error(
                    f"Activity '{act.id}' is assigned to partner '{act.assigned_partner_id}' but no matching PartnerAssignment exists.",
                    hint="Create a PartnerAssignment for this school/partner combo or clear the activity's assigned partner.",
                    obj=act,
                    id="planning.E004",
                )
            )
            
    return errors
