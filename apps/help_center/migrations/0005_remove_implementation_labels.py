from django.db import migrations
from django.utils import timezone


def friendly_text(value):
    replacements = (
        ("ActivityScheduleCostLine snapshots", "a saved copy of the cost"),
        ("ActivityScheduleCostLine", "saved activity cost"),
        ("returned_by_ia", "a returned flag"),
        ("RBAC matrix", "roles and permissions list"),
        (
            "manual price invention is not supported",
            "you cannot type in a made-up price",
        ),
        ("participant requirements", "required number of participants"),
        ("validates", "checks"),
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


def remove_implementation_labels(apps, schema_editor):
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
            change_summary="Plain-language terminology review.",
            reviewer_name="Edify plain-language review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0004_everyday_language_steps")]
    operations = [
        migrations.RunPython(remove_implementation_labels, migrations.RunPython.noop)
    ]
