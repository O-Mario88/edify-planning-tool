"""Name the invited schools on cluster sessions planned before invitations
were recorded.

Migration 0057 runs this once on deploy; the command is for a dry run first,
or to run it again after importing older sessions. It only ever adds
invitation rows to live, undelivered sessions that name no school at all, so
running it twice changes nothing. See
``apps.activities.cluster_attendance.backfill_session_invitations``.
"""

from django.core.management.base import BaseCommand

from apps.activities.cluster_attendance import backfill_session_invitations


class Command(BaseCommand):
    help = (
        "Invite the cluster's member schools on undelivered cluster sessions "
        "that were planned before invitations were recorded."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change and write nothing.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        report = backfill_session_invitations(dry_run=dry_run)
        verb = "Would invite" if dry_run else "Invited"
        self.stdout.write(
            f"{verb} {report['invitations']} school(s) across "
            f"{report['sessions']} cluster session(s); "
            f"{report['without_members']} session(s) have no active member "
            "school to invite."
        )
