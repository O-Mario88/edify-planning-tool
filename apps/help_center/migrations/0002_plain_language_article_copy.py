from django.db import migrations
from django.utils import timezone


def make_plain_language(apps, schema_editor):
    HelpArticle = apps.get_model("help_center", "HelpArticle")
    HelpArticleVersion = apps.get_model("help_center", "HelpArticleVersion")
    now = timezone.now()
    replacements = {
        "Where to find it": ("Open the relevant Edify page. The Help for this page button opens this same guide.", []),
        "Before you begin": ("Make sure you are using the right role and looking at the right record. Edify only shows actions that are available to you.", []),
        "What Edify does automatically": ("Edify checks the information you enter, keeps a history of the record and sends the next person a task or notification when they need to act.", []),
        "What happens after submission": ("If somebody else needs to check, approve, verify or pay the record, Edify sends it to the next person.", []),
        "Statuses and their meaning": ("The status tells you where the record is and what needs to happen next. Read the words beside the status; do not rely on colour alone.", []),
        "Notifications and To-Dos": ("When a record moves to another person, Edify gives that person a notification or To-Do. You will see one when it is your turn.", []),
        "Permissions and restrictions": ("Reading this guide does not give you extra access. If a button is missing or unavailable, another person or condition may need to act first.", []),
        "How to correct a returned or blocked record": ("Open the same record. Read the reason shown on screen, fix only that problem, then use the available submit or resubmit button. Do not make a second record to work around the problem.", []),
        "Canonical sources": ("Before this guide is published or changed, the Edify team checks it against the live way the system works.", []),
    }
    for article in HelpArticle.objects.filter(state__in=["published", "review_due"]):
        content = article.content or []
        changed = False
        for section in content:
            heading = section.get("heading")
            if heading in replacements:
                body, items = replacements[heading]
                section["body"] = body
                section["items"] = items
                if heading == "Canonical sources":
                    section["heading"] = "How this guide stays correct"
                changed = True
        if not changed:
            continue
        article.content = content
        article.version += 1
        article.reviewer_name = "Edify plain-language review"
        article.last_reviewed_at = now
        article.save(update_fields=["content", "version", "reviewer_name", "last_reviewed_at", "updated_at"])
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
            change_summary="Plain-language user guidance review.",
            reviewer_name="Edify plain-language review",
            reviewed_at=now,
        )


class Migration(migrations.Migration):
    dependencies = [("help_center", "0001_initial")]
    operations = [migrations.RunPython(make_plain_language, migrations.RunPython.noop)]
