from django.db import transaction

from apps.projects.models import Project

from .models import (
    ActivityCatalogueItem,
    ActivityCatalogueReviewQueue,
    ActivityProjectMapping,
)


PROJECT_CODE_RULES = {
    "SP-EDTECH": [
        "EDTECH_FOUNDATIONS",
        "EDTECH_INTEGRATION",
        "LEARNER_CENTERED_APPROACHES",
        "TECH_SKILLS_EMPLOYABLE_FUTURE",
    ],
    "SP-CCSEL": ["CC_SEL"],
}


@transaction.atomic
def seed_known_project_activity_rules(*, actor_id="system", dry_run=False):
    result = {"projects": 0, "mappings": 0, "review": 0}
    for project in Project.objects.filter(deleted_at__isnull=True):
        codes = PROJECT_CODE_RULES.get(project.code)
        if codes is None:
            ActivityCatalogueReviewQueue.objects.get_or_create(
                review_kind="project_allowed_activity_definition",
                source_model="projects.Project",
                source_record_id=project.id,
                defaults={
                    "source_value": f"{project.code or ''} · {project.name}",
                    "candidate_codes": [],
                },
            )
            result["review"] += 1
            continue
        items = {
            item.stable_code: item
            for item in ActivityCatalogueItem.objects.filter(stable_code__in=codes)
        }
        for code in codes:
            item = items.get(code)
            if item is None:
                ActivityCatalogueReviewQueue.objects.get_or_create(
                    review_kind="missing_project_catalogue_item",
                    source_model="projects.Project",
                    source_record_id=f"{project.id}:{code}",
                    defaults={
                        "source_value": project.code or project.name,
                        "candidate_codes": [code],
                    },
                )
                result["review"] += 1
                continue
            ActivityProjectMapping.objects.update_or_create(
                project=project,
                catalogue_item=item,
                defaults={
                    "required_or_optional": "optional",
                    "staff_delivery_allowed": item.staff_delivery_allowed,
                    "partner_delivery_allowed": item.partner_delivery_allowed,
                    "active": True,
                },
            )
            result["mappings"] += 1
        result["projects"] += 1
    if dry_run:
        transaction.set_rollback(True)
    return result
