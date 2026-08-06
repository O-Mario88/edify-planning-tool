from django.db import migrations
from django.utils import timezone


def rebuild_search_document(article):
    fragments = [article.title, article.summary, article.feature, article.workflow]
    fragments.extend(article.keywords or [])
    for section in article.content or []:
        fragments.extend([section.get("heading", ""), section.get("body", "")])
        fragments.extend(section.get("items", []) or [])
    return "\n".join(str(part) for part in fragments if part)


def expand_guides_for_learning(apps, schema_editor):
    # This is a pure content helper: it does not import Django models or make
    # database decisions, so the historical migration remains deterministic.
    from apps.help_center.learning import build_learning_sections

    HelpArticle = apps.get_model("help_center", "HelpArticle")
    HelpArticleVersion = apps.get_model("help_center", "HelpArticleVersion")
    now = timezone.now()

    for article in HelpArticle.objects.filter(
        state__in=["published", "review_due"]
    ).select_related("category"):
        old_content = article.content or []
        steps = []
        for section in old_content:
            if section.get("heading") in {"Step-by-step", "What you do"}:
                steps = section.get("items", []) or []
                break
        if not steps:
            steps = [
                "Open the main Edify page and check the current status.",
                "Complete the action available to you and fill in the information it asks for.",
                "Check the notification or To-Do to see who needs to act next.",
                "If it is returned, fix the named problem on the same record and submit it again.",
            ]
        roles = list(article.role_accesses.values_list("role", flat=True))
        content = build_learning_sections(
            title=article.title,
            category=article.category.name,
            roles=roles,
            purpose=article.summary,
            steps=steps,
        )
        article.content = content
        article.version += 1
        article.reviewer_name = "Edify learning-guide review"
        article.last_reviewed_at = now
        article.estimated_reading_minutes = max(
            4, min(14, (len(str(content)) + len(article.summary)) // 420 + 2)
        )
        article.search_document = rebuild_search_document(article)
        article.save(
            update_fields=[
                "content",
                "version",
                "reviewer_name",
                "last_reviewed_at",
                "estimated_reading_minutes",
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
            change_summary="Expanded guide with practical learning detail.",
            reviewer_name="Edify learning-guide review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0006_polish_everyday_language")]
    operations = [
        migrations.RunPython(expand_guides_for_learning, migrations.RunPython.noop)
    ]
