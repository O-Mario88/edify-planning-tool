from django.conf import settings
from django.db import migrations
from django.utils import timezone


CONTENT_CHECKSUM = "94dd579ed3b498142fde588b0dd45966261f14e5ddedb1474ae1da80962f44d8"


def seed_first_login_agreements(apps, schema_editor):
    # The test suite constructs its own policy fixtures and asserts exact
    # acknowledgement counts. Production and development databases receive
    # the defaults; isolated test databases remain deterministic.
    if getattr(settings, "IS_TESTING", False):
        return
    DocumentAsset = apps.get_model("documents", "DocumentAsset")
    DocumentVersion = apps.get_model("documents", "DocumentVersion")
    DocumentAudienceRule = apps.get_model("documents", "DocumentAudienceRule")

    definitions = (
        {
            "slug": "edify-safeguarding-policy",
            "title": "Safeguarding Policy",
            "description": (
                "How Edify protects children and adults at risk, how concerns "
                "must be reported, and the conduct expected of every user."
            ),
            "category": "Safeguarding",
            "statement": (
                "I confirm that I have read and understood the Edify "
                "Safeguarding Policy and agree to abide by it."
            ),
            "reason": (
                "Every person using Edify must understand and accept the "
                "safeguarding responsibilities that apply to their work."
            ),
        },
        {
            "slug": "edify-apostles-creed",
            "title": "The Apostles’ Creed",
            "description": (
                "Edify’s Christian statement of belief, presented with the "
                "scripture passages that frame the commitment."
            ),
            "category": "Faith and Values",
            "statement": (
                "I affirm: I Believe the Apostles’ Creed as presented by Edify."
            ),
            "reason": (
                "Every person using Edify must read and respond to the "
                "organisation’s shared statement of Christian belief."
            ),
        },
    )

    today = timezone.localdate()
    for definition in definitions:
        document, created = DocumentAsset.objects.get_or_create(
            slug=definition["slug"],
            defaults={
                "title": definition["title"],
                "description": definition["description"],
                "document_type": "policy",
                "category": definition["category"],
                "confidentiality": "internal",
                "status": "effective",
                "acknowledgement_required": True,
                "agreement_required": True,
                "comment_required": False,
                "agreement_statement": definition["statement"],
                "acknowledgement_reason": definition["reason"],
                "blocks_application_access": True,
                "require_reacknowledgement_on_new_version": True,
                "download_allowed": False,
                "print_allowed": True,
                "help_visible": True,
                "help_category": "Policies and agreements",
                "help_keywords": [
                    "first login",
                    "agreement",
                    definition["category"].lower(),
                ],
                "created_by": "system",
            },
        )
        if not created:
            continue

        version = DocumentVersion.objects.create(
            document=document,
            version_number=1,
            uri=f"builtin://{definition['slug']}/1",
            original_filename=f"{definition['slug']}.html",
            mime_type="text/html",
            file_extension="html",
            file_size=0,
            checksum=CONTENT_CHECKSUM,
            effective_date=today,
            change_summary="Initial first-login agreement.",
            material_change=True,
            uploaded_by="system",
            reviewed_by="system",
            reviewed_at=timezone.now(),
            review_decision="approved",
            published_by="system",
            published_at=timezone.now(),
            preview_status="not_required",
            scan_status="skipped",
            scan_detail="Application-rendered source-controlled content.",
        )
        document.current_version = version
        document.save(update_fields=["current_version", "updated_at"])

        # One deliberately empty rule means everyone. The audience matcher
        # treats no rules as nobody and a present, unconstrained rule as all.
        DocumentAudienceRule.objects.create(document=document)


def remove_first_login_agreements(apps, schema_editor):
    DocumentAsset = apps.get_model("documents", "DocumentAsset")
    DocumentAsset.objects.filter(
        slug__in=("edify-safeguarding-policy", "edify-apostles-creed"),
        created_by="system",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [
        migrations.RunPython(
            seed_first_login_agreements,
            reverse_code=remove_first_login_agreements,
        )
    ]
