from django.db import migrations


def seed_project_rules(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    CatalogueItem = apps.get_model(
        "activity_catalogue", "ActivityCatalogueItem"
    )
    ProjectMapping = apps.get_model(
        "activity_catalogue", "ActivityProjectMapping"
    )
    ReviewQueue = apps.get_model(
        "activity_catalogue", "ActivityCatalogueReviewQueue"
    )
    project_code_rules = {
        "SP-EDTECH": [
            "EDTECH_FOUNDATIONS",
            "EDTECH_INTEGRATION",
            "LEARNER_CENTERED_APPROACHES",
            "TECH_SKILLS_EMPLOYABLE_FUTURE",
        ],
        "SP-CCSEL": ["CC_SEL"],
    }
    for project in Project.objects.filter(deleted_at__isnull=True):
        codes = project_code_rules.get(project.code)
        if codes is None:
            ReviewQueue.objects.get_or_create(
                review_kind="project_allowed_activity_definition",
                source_model="projects.Project",
                source_record_id=project.id,
                defaults={
                    "source_value": f"{project.code or ''} · {project.name}",
                    "candidate_codes": [],
                },
            )
            continue
        items = {
            item.stable_code: item
            for item in CatalogueItem.objects.filter(stable_code__in=codes)
        }
        for code in codes:
            item = items.get(code)
            if item is None:
                ReviewQueue.objects.get_or_create(
                    review_kind="missing_project_catalogue_item",
                    source_model="projects.Project",
                    source_record_id=f"{project.id}:{code}",
                    defaults={
                        "source_value": project.code or project.name,
                        "candidate_codes": [code],
                    },
                )
                continue
            ProjectMapping.objects.update_or_create(
                project=project,
                catalogue_item=item,
                defaults={
                    "required_or_optional": "optional",
                    "staff_delivery_allowed": item.staff_delivery_allowed,
                    "partner_delivery_allowed": item.partner_delivery_allowed,
                    "active": True,
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0002_seed_edify_catalogue"),
        ("projects", "0008_project_budget_ceiling_ugx_project_status_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_project_rules, migrations.RunPython.noop),
    ]
