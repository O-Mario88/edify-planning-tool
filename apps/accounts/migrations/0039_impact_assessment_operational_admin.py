"""Impact Assessment holds the Admin's operational permissions (owner,
2026-11-02), less user management and system settings
(apps.core.rbac.IA_EXCLUDED_ADMIN_PERMISSIONS).

Checks read the matrix in code; the stored grants are what the Roles &
Permissions page shows, so they are brought in line here. The key list is
frozen as it stood when the rule was made: `manage.py seed` keeps later keys
in step from the matrix.
"""

from django.db import migrations

ROLE = "ImpactAssessment"

IA_KEYS = (
    "activity.assign",
    "activity.bulkComplete",
    "activity.complete",
    "activity.ownershipTransfer",
    "activityCatalogue.manageProjectRules",
    "activityCatalogue.mapInterventions",
    "activityCatalogue.view",
    "activityCost.operational.view",
    "analytics.view",
    "budget.viewDetail",
    "budget.viewSummary",
    "budgetDecision.review",
    "budgetIntelligence.view",
    "businessTransformation.export",
    "businessTransformation.ia.validate",
    "businessTransformation.portfolio.view",
    "businessTransformation.purpose.define",
    "businessTransformation.sensitive.view",
    "businessTransformation.view",
    "cluster.assign",
    "cluster.catchmentManage",
    "cluster.override",
    "cluster.view",
    "costAmendment.request",
    "dailyDebrief.view",
    "data.export",
    "district.portfolioTransfer",
    "documents.archive",
    "documents.create",
    "documents.manage_audience",
    "documents.publish",
    "documents.review",
    "evidence.review",
    "ia.verify",
    "leadership.review",
    "leadership.view",
    "leavePlanner.view",
    "milestones.allocate",
    "milestones.define",
    "milestones.viewProgress",
    "partner.hold",
    "partner.manage",
    "partner.view",
    "partnerAssignment.reassign",
    "partnerAssignment.resolveReturn",
    "partnerAssignment.withdraw",
    "partnerMonitoring.country",
    "partnerMonitoring.view",
    "partnerOrganisation.create",
    "partnerOrganisation.edit",
    "partnerSchool.planCluster",
    "partnerSchool.planDirect",
    "partnerSupport.view",
    "partnerWithdrawal.review",
    "planning.create",
    "planning.manualActivity.create",
    "planning.view",
    "planningPolicy.manage",
    "policies.manage_acknowledgements",
    "policies.review_comments",
    "project.assignSchool",
    "project.configurePriorities",
    "project.manage",
    "rateCard.operational.view",
    "recruitment.view",
    "school.close",
    "school.createSingle",
    "school.edit",
    "school.ownershipTransfer",
    "school.resolveDuplicate",
    "school.upload",
    "school.view",
    "schoolDirectory.view",
    "ssa.upload",
    "ssa.view",
    "ssaActivityMapping.manage",
    "ssaActivityMapping.view",
    "staff.manage",
    "staffPerformance.view",
    "strategicPriorities.allocate",
    "strategicPriorities.edit",
    "strategicPriorities.import",
    "strategicPriorities.view",
    "training_resources.create",
    "training_resources.publish",
    "uploads.view",
)


def grant(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    for key in IA_KEYS:
        permission, _ = Permission.objects.get_or_create(
            key=key, defaults={"description": key}
        )
        RolePermission.objects.get_or_create(role=ROLE, permission=permission)
    RolePermission.objects.filter(role=ROLE).exclude(
        permission__key__in=IA_KEYS
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0038_user_acting_until"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
