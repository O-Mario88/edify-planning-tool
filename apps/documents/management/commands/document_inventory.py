"""Report what the Upload Center indexes, and what needs attention.

There is deliberately no backfill here. The specification asks for a migration
of existing policies, manuals and training resources — and there were none to
migrate: no model held them before this app, which is why it exists. Activity
evidence and PD certificates were *not* migrated either, on purpose: they stay
in the canonical records that own them, and the Upload Center reads those.

Writing a migration that manufactured DocumentAsset rows for evidence and
certificates would have created exactly the duplicate file system this work
was meant to avoid — and, worse, a migration that invented acknowledgement
records would assert that people agreed to things they never saw.

So this command inventories rather than transforms. Run it to see the shape of
the estate and the defects worth fixing.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Inventory every file category the Upload Center indexes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--health",
            action="store_true",
            help="Also print the Document Library health checks that are not OK.",
        )

    def handle(self, *args, **options):
        from apps.documents.models import (
            AcknowledgementState,
            DocumentAcknowledgement,
            DocumentAsset,
            DocumentType,
            DocumentVersion,
            PreviewStatus,
        )
        from apps.evidence.models import EvidenceRecord
        from apps.professional_development.models import (
            ProfessionalDevelopmentCertificate,
        )
        from apps.schools.models import SchoolImportBatch, SSAImportBatch

        self.stdout.write(self.style.MIGRATE_HEADING("Document Library"))
        for value, label in DocumentType.choices:
            count = DocumentAsset.objects.filter(document_type=value).count()
            published = DocumentAsset.objects.filter(
                document_type=value, status__in=("published", "effective")
            ).count()
            self.stdout.write(f"  {label:34} {count:5}  ({published} live)")

        versions = DocumentVersion.objects.count()
        previews = DocumentVersion.objects.filter(
            preview_status=PreviewStatus.READY
        ).count()
        failed = DocumentVersion.objects.filter(
            preview_status=PreviewStatus.FAILED
        ).count()
        self.stdout.write(
            f"  {'Versions':34} {versions:5}  ({previews} previewable, {failed} failed)"
        )

        self.stdout.write(self.style.MIGRATE_HEADING("\nAcknowledgements"))
        for state, label in AcknowledgementState.choices:
            count = DocumentAcknowledgement.objects.filter(state=state).count()
            self.stdout.write(f"  {label:34} {count:5}")

        self.stdout.write(
            self.style.MIGRATE_HEADING("\nIndexed from their own workflows")
        )
        self.stdout.write(
            f"  {'School import batches':34} {SchoolImportBatch.objects.count():5}"
        )
        self.stdout.write(
            f"  {'SSA import batches':34} {SSAImportBatch.objects.count():5}"
        )
        self.stdout.write(
            f"  {'Activity evidence records':34} {EvidenceRecord.objects.count():5}"
        )
        self.stdout.write(
            f"  {'PD certificates':34} "
            f"{ProfessionalDevelopmentCertificate.objects.count():5}"
        )
        self.stdout.write(
            self.style.WARNING(
                "\n  These four are read in place. Nothing above was copied into "
                "the Document Library."
            )
        )

        if options["health"]:
            from apps.documents.health import document_health

            self.stdout.write(self.style.MIGRATE_HEADING("\nHealth"))
            issues = [c for c in document_health()["checks"] if c["severity"] != "ok"]
            if not issues:
                self.stdout.write(self.style.SUCCESS("  All checks green."))
            for check in issues:
                style = (
                    self.style.ERROR
                    if check["severity"] == "critical"
                    else self.style.WARNING
                )
                self.stdout.write(
                    style(f"  [{check['severity']}] {check['current_state']}")
                )
                self.stdout.write(f"      → {check['recommended_action']}")
