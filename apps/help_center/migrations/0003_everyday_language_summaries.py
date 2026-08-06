from django.db import migrations
from django.utils import timezone


def friendly_summary(summary):
    replacements = (
        ("canonical", "official"),
        ("authoritative", "official"),
        ("authorised", "allowed"),
        ("operational ledger", "main activity record"),
        ("source record", "main record"),
        ("source workspace", "main page"),
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
        summary = summary.replace(technical, everyday)
    return summary


def rebuild_search_document(article):
    fragments = [article.title, article.summary, article.feature, article.workflow]
    fragments.extend(article.keywords or [])
    for section in article.content or []:
        fragments.extend([section.get("heading", ""), section.get("body", "")])
        fragments.extend(section.get("items", []) or [])
    return "\n".join(str(part) for part in fragments if part)


def make_summaries_everyday_language(apps, schema_editor):
    HelpArticle = apps.get_model("help_center", "HelpArticle")
    HelpArticleVersion = apps.get_model("help_center", "HelpArticleVersion")
    now = timezone.now()

    for article in HelpArticle.objects.filter(state__in=["published", "review_due"]):
        summary = friendly_summary(article.summary)
        if (
            summary == article.summary
            and article.reviewer_name != "Edify plain-language review"
        ):
            continue
        article.summary = summary
        article.version += 1
        article.reviewer_name = "Edify plain-language review"
        article.last_reviewed_at = now
        article.search_document = rebuild_search_document(article)
        article.save(
            update_fields=[
                "summary",
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
            change_summary="Everyday-language guidance review.",
            reviewer_name="Edify plain-language review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0002_plain_language_article_copy")]
    operations = [
        migrations.RunPython(
            make_summaries_everyday_language, migrations.RunPython.noop
        )
    ]
