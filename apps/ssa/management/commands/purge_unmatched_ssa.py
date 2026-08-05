"""Delete unmatched SSA rows whose school genuinely is not in the directory.

Why this exists: a Salesforce export was filtered wrongly and included SSA for
schools that have closed. Those rows landed in the unmatched queue, where they
can never be resolved — the schools they name do not exist in Edify and are not
going to. 172 permanently-unresolvable rows in a triage queue is not a backlog,
it is noise that hides the rows someone should act on.

`UnmatchedSSARecord` is a `TimeStampedModel`, not a `SoftDeleteModel`, so this
is a hard delete and the rows do not come back. Three things make that
defensible rather than reckless:

**It re-verifies rather than trusting the stored reason.** A row says
"School ID does not exist in School Directory" as of upload time. If that
school has since been created, the row is now matchable and deleting it would
throw away real work. Every candidate is re-checked against the live directory
at delete time, and anything that has become matchable is refused and reported.

**It records what it destroyed.** Each deletion writes an audit row carrying
the school id, the assessment date and the full scores payload. The rows are
gone from the table but not from the record, so a mistake is answerable —
"what did we delete on 5 August" has an exact answer.

**It does nothing by default.** `--apply` is required. Without it the command
reports what it would do and exits, which is also how you get the count for a
change record.

    python manage.py purge_unmatched_ssa                    # dry run
    python manage.py purge_unmatched_ssa --batch <id>       # scope to one upload
    python manage.py purge_unmatched_ssa --apply --reason "closed schools, SF export filter"

Idempotent: a second run finds nothing, because the rows are gone.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Delete unmatched SSA records whose school id is absent from the directory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )
        parser.add_argument(
            "--batch",
            help="Restrict to one upload batch id. Recommended when clearing a "
            "single bad export rather than everything ever unmatched.",
        )
        parser.add_argument(
            "--status",
            default="pending,hold",
            help="Comma-separated statuses to consider (default: pending,hold). "
            "Records already matched are never touched.",
        )
        parser.add_argument(
            "--reason",
            default="",
            help="Free-text note stored on every audit row explaining the purge.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Stop after this many deletions. A safety valve for a first run.",
        )

    def handle(self, *args, **options):
        from apps.audit.services import log as audit_log
        from apps.schools.models import School, UnmatchedSSARecord

        statuses = [s.strip() for s in options["status"].split(",") if s.strip()]
        if "matched" in statuses:
            raise CommandError(
                "Refusing to consider matched records — those already produced an "
                "SsaRecord and deleting the source would orphan it."
            )

        candidates = UnmatchedSSARecord.objects.filter(status__in=statuses)
        if options["batch"]:
            candidates = candidates.filter(batch_id=options["batch"])
        candidates = candidates.order_by("id")

        total = candidates.count()
        if not total:
            self.stdout.write("Nothing matches those filters.")
            return

        # Re-verify against the live directory. The stored `reason` reflects
        # upload time; a school created since makes the row matchable, and
        # matchable rows are work, not noise.
        school_ids = {
            s for s in candidates.values_list("school_id", flat=True) if s is not None
        }
        existing = set(
            School.objects.filter(
                school_id__in=school_ids, deleted_at__isnull=True
            ).values_list("school_id", flat=True)
        )

        deletable, now_matchable = [], []
        for record in candidates:
            (now_matchable if record.school_id in existing else deletable).append(
                record
            )

        if options["limit"]:
            deletable = deletable[: options["limit"]]

        self.stdout.write(f"Considered      : {total}")
        self.stdout.write(f"Now matchable   : {len(now_matchable)}  (refused)")
        self.stdout.write(f"To delete       : {len(deletable)}")
        if now_matchable:
            self.stdout.write(
                self.style.WARNING(
                    "  These have a school in the directory now and were NOT "
                    "deleted — triage them in the queue instead:"
                )
            )
            for record in now_matchable[:10]:
                self.stdout.write(f"    {record.school_id}  {record.date_of_ssa}")
        for record in deletable[:10]:
            self.stdout.write(f"  - {record.school_id}  {record.date_of_ssa}")
        if len(deletable) > 10:
            self.stdout.write(f"  … and {len(deletable) - 10} more")

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("\nDry run. Re-run with --apply to delete.")
            )
            return

        deleted = 0
        for record in deletable:
            # One transaction per row: a failure part-way leaves a consistent
            # database and an audit trail that matches exactly what went.
            with transaction.atomic():
                audit_log(
                    action="ssa.unmatched_purged",
                    subject_kind="UnmatchedSSARecord",
                    subject_id=record.id,
                    actor_id="system",
                    actor_role="",
                    success=True,
                    reason=options["reason"]
                    or "Unmatched SSA purged: school not in directory",
                    # The whole row, so a hard delete is still answerable later.
                    payload={
                        "schoolIdRaw": record.school_id,
                        "schoolNameRaw": record.school_name_raw,
                        "districtRaw": record.district_raw,
                        "dateOfSsa": record.date_of_ssa,
                        "batchId": record.batch_id,
                        "status": record.status,
                        "scores": record.scores,
                    },
                )
                record.delete()
                deleted += 1

        self.stdout.write(self.style.SUCCESS(f"\nDeleted {deleted} record(s)."))
        self.stdout.write(
            "Each one is recorded in the audit log as ssa.unmatched_purged, "
            "including its scores."
        )
