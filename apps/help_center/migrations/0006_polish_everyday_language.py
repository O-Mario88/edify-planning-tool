from django.db import migrations
from django.utils import timezone


def friendly_text(value):
    replacements = (
        (
            "When a user schedules work, the canonical costing service validates the date, fiscal period, participant requirements and active rate card. It persists ActivityScheduleCostLine snapshots in whole UGX; manual price invention is not supported.",
            "When you schedule work, Edify checks the date, financial period, required number of participants and current rate card. It saves the cost in whole UGX. You cannot type in a made-up price.",
        ),
        (
            "When a user schedules work, the official costing service checks the date, fiscal period, required number of participants and active rate card. It saves a saved copy of the cost in whole UGX; you cannot type in a made-up price.",
            "When you schedule work, Edify checks the date, financial period, required number of participants and current rate card. It saves the cost in whole UGX. You cannot type in a made-up price.",
        ),
        (
            "Open the main Edify page and confirm the current status.",
            "Open the main Edify page and check the current status.",
        ),
        (
            "Complete only the enabled action and its required data.",
            "Complete the action available to you and fill in the information it asks for.",
        ),
        (
            "Use the recorded transition, notification and linked queue to follow the next step.",
            "Check the notification or To-Do to see who needs to act next.",
        ),
        (
            "If returned, correct the named condition on the same record and resubmit.",
            "If it is returned, fix the named problem on the same record and submit it again.",
        ),
    )
    for technical, everyday in replacements:
        value = value.replace(technical, everyday)
    return value


def rebuild_search_document(article):
    fragments = [article.title, article.summary, article.feature, article.workflow]
    fragments.extend(article.keywords or [])
    for section in article.content or []:
        fragments.extend([section.get("heading", ""), section.get("body", "")])
        fragments.extend(section.get("items", []) or [])
    return "\n".join(str(part) for part in fragments if part)


def polish_everyday_language(apps, schema_editor):
    HelpArticle = apps.get_model("help_center", "HelpArticle")
    HelpArticleVersion = apps.get_model("help_center", "HelpArticleVersion")
    now = timezone.now()

    for article in HelpArticle.objects.filter(state__in=["published", "review_due"]):
        changed = False
        summary = friendly_text(article.summary)
        if summary != article.summary:
            article.summary = summary
            changed = True
        content = article.content or []
        for section in content:
            body = section.get("body", "")
            friendly_body = friendly_text(body)
            if friendly_body != body:
                section["body"] = friendly_body
                changed = True
            items = section.get("items", []) or []
            friendly_items = [friendly_text(item) for item in items]
            if friendly_items != items:
                section["items"] = friendly_items
                changed = True
        if not changed:
            continue
        article.content = content
        article.version += 1
        article.reviewer_name = "Edify plain-language review"
        article.last_reviewed_at = now
        article.search_document = rebuild_search_document(article)
        article.save(
            update_fields=[
                "summary",
                "content",
                "version",
                "reviewer_name",
                "last_reviewed_at",
                "search_document",
                "updated_at",
            ]
        )
        HelpArticleVersion.objects.create(
            article=article,
            version=article.version,
            state=article.state,
            snapshot={
                "title": article.title,
                "slug": article.slug,
                "summary": article.summary,
                "content": article.content,
                "keywords": article.keywords,
                "source_paths": article.source_paths,
                "feature": article.feature,
                "workflow": article.workflow,
                "state": article.state,
                "version": article.version,
            },
            change_summary="Everyday-language readability polish.",
            reviewer_name="Edify plain-language review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0005_remove_implementation_labels")]
    operations = [
        migrations.RunPython(polish_everyday_language, migrations.RunPython.noop)
    ]
