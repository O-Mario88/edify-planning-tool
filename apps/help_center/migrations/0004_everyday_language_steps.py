from django.db import migrations
from django.utils import timezone


def friendly_text(value):
    replacements = (
        ("canonical", "official"),
        ("authoritative", "official"),
        ("authorised", "allowed"),
        ("operational ledger", "main activity record"),
        ("source workspace", "main Edify page"),
        ("source record", "same record"),
        ("source activities", "activities"),
        ("source values", "current values"),
        ("source workflow", "main workflow"),
        ("role- and scope-aware", "based on your role and what you are allowed to see"),
        ("role-specific", "for the right role"),
        ("scoped", "limited"),
        ("scope", "work area"),
        ("persists", "saves"),
        ("immutable-at-schedule", "saved when you schedule"),
        ("immutable", "locked"),
        ("atomicity", "saving the whole upload together"),
        ("gates", "checks"),
        ("handoff", "next step"),
        ("rework state", "sent-back-for-correction state"),
        ("traceable", "easy to follow"),
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


def make_steps_everyday_language(apps, schema_editor):
    HelpArticle = apps.get_model("help_center", "HelpArticle")
    HelpArticleVersion = apps.get_model("help_center", "HelpArticleVersion")
    now = timezone.now()

    for article in HelpArticle.objects.filter(state__in=["published", "review_due"]):
        content = article.content or []
        changed = False
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
            change_summary="Everyday-language steps review.",
            reviewer_name="Edify plain-language review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0003_everyday_language_summaries")]
    operations = [
        migrations.RunPython(make_steps_everyday_language, migrations.RunPython.noop)
    ]
