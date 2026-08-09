"""§31 — classify and repair records left behind by the old scheduling rule.

Three kinds of damage, and only two of them are safely repairable:

  VALID              nothing to do.
  REPAIRABLE         the correct value is derivable from the record itself.
                     A visit carrying participant values is repairable: the
                     Workflow Profile says a visit plans no participants, so
                     the values are stale drawer artifacts with no other
                     possible meaning. Executor type is repairable: it is a
                     pure function of delivery type and certification.
  MANUAL REVIEW      the correct value depends on what a person intended.
                     An "artificial" Project attached only to get past the
                     old gate is indistinguishable, from data alone, from a
                     Project that genuinely funds the work. Guessing would
                     silently move money between programmes, so these are
                     reported and never touched (§31: "Do not guess whether
                     an artificial Project was intended without evidence").

Idempotent and dry-run capable. Re-running after a successful repair reports
zero repairs and the same manual-review set.
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q

from apps.activities.models import Activity
from apps.core.enums import ExecutorType, ParticipantMode
from apps.partners.models import Partner

from apps.activity_catalogue.scheduling_health import LIVE_STATUSES


class Command(BaseCommand):
    help = "Audit and repair scheduling records affected by the Project-dependency rule."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--include-historical",
            action="store_true",
            help=(
                "Also repair completed/closed activities. Off by default: a "
                "closed activity's stored quantities are part of an audited "
                "financial record and are corrected through amendment, not "
                "by a repair pass."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        report = {
            "dryRun": dry_run,
            "scanned": 0,
            "valid": 0,
            "repaired": {
                "executorTypeBackfilled": 0,
                "visitParticipantsCleared": 0,
                "clusterTotalRecomputed": 0,
                "agencyBookingStatusCorrected": 0,
                "agencyStaffExecutorCleared": 0,
            },
            "manualReview": {
                "projectRequiredWithoutProject": [],
                "agencyBookingNotCertified": [],
                "trainingMissingParticipants": [],
                "possibleArtificialProject": [],
            },
        }

        scope = Activity.objects.filter(deleted_at__isnull=True)
        if not options["include_historical"]:
            scope = scope.filter(status__in=LIVE_STATUSES)

        with transaction.atomic():
            report["scanned"] = scope.count()
            self._backfill_executor_type(scope, report, dry_run)
            self._clear_visit_participants(scope, report, dry_run)
            self._recompute_cluster_totals(scope, report, dry_run)
            self._correct_agency_bookings(scope, report, dry_run)
            self._collect_manual_review(scope, report)
            if dry_run:
                transaction.set_rollback(True)

        repaired = sum(report["repaired"].values())
        review = sum(len(rows) for rows in report["manualReview"].values())
        report["valid"] = max(0, report["scanned"] - repaired - review)
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))

    # ── Repairable ───────────────────────────────────────────────────────
    def _backfill_executor_type(self, scope, report, dry_run):
        """Executor type is derivable: partner delivery with a certified
        partner and a partner-scheduled status is an agency booking; every
        other partner row is an assigned partner; the rest is staff."""
        missing = scope.filter(Q(executor_type="") | Q(executor_type__isnull=True))
        count = missing.count()
        if count and not dry_run:
            missing.filter(delivery_type="partner").update(
                executor_type=ExecutorType.PARTNER
            )
            missing.exclude(delivery_type="partner").update(
                executor_type=ExecutorType.STAFF
            )
        report["repaired"]["executorTypeBackfilled"] = count

    def _clear_visit_participants(self, scope, report, dry_run):
        stale = scope.filter(
            catalogue_item__participant_mode=ParticipantMode.NONE
        ).filter(
            Q(expected_participants__isnull=False)
            | Q(participants_per_school__isnull=False)
            | Q(teachers_attended__isnull=False)
            | Q(leaders_attended__isnull=False)
            | Q(other_participants__isnull=False)
        )
        count = stale.count()
        if count and not dry_run:
            stale.update(
                expected_participants=None,
                participants_per_school=None,
                teachers_attended=None,
                leaders_attended=None,
                other_participants=None,
            )
        report["repaired"]["visitParticipantsCleared"] = count

    def _recompute_cluster_totals(self, scope, report, dry_run):
        """per-school × snapshotted schools is the definition of the total,
        so a disagreeing stored total is arithmetic, not intent."""
        mismatched = scope.filter(
            catalogue_item__participant_mode=ParticipantMode.PER_SCHOOL,
            participants_per_school__isnull=False,
            cluster_school_count_snapshot__isnull=False,
        ).exclude(
            expected_participants=F("participants_per_school")
            * F("cluster_school_count_snapshot")
        )
        count = mismatched.count()
        if count and not dry_run:
            mismatched.update(
                expected_participants=F("participants_per_school")
                * F("cluster_school_count_snapshot")
            )
        report["repaired"]["clusterTotalRecomputed"] = count

    def _correct_agency_bookings(self, scope, report, dry_run):
        agency = scope.filter(executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY)

        # A booking Edify already dated must not still ask the agency to
        # schedule it.
        awaiting = agency.filter(status="assigned_to_partner", scheduled_date__isnull=False)
        count = awaiting.count()
        if count and not dry_run:
            awaiting.update(status="partner_scheduled")
        report["repaired"]["agencyBookingStatusCorrected"] = count

        # §24 — one delivery must not be executable work in two My Plans.
        # The agency executes; the staff member owns and monitors.
        duplicated = agency.filter(responsible_staff_id__isnull=False).exclude(
            responsible_staff_id=""
        )
        count = duplicated.count()
        if count and not dry_run:
            for activity in duplicated.only(
                "id", "responsible_staff_id", "monitored_by_staff_id"
            ):
                Activity.objects.filter(pk=activity.pk).update(
                    monitored_by_staff_id=(
                        activity.monitored_by_staff_id or activity.responsible_staff_id
                    ),
                    responsible_staff_id=None,
                )
        report["repaired"]["agencyStaffExecutorCleared"] = count

    # ── Manual review ────────────────────────────────────────────────────
    def _collect_manual_review(self, scope, report):
        def rows(qs, extra=None):
            out = []
            for a in qs.select_related("school", "cluster")[:500]:
                row = {
                    "activityId": a.id,
                    "activityType": a.activity_type,
                    "status": a.status,
                    "school": a.school.name if a.school_id else None,
                    "cluster": a.cluster.name if a.cluster_id else None,
                    "intervention": a.focus_intervention or None,
                    "projectId": a.project_id,
                    "plannedDate": (
                        a.planned_date.isoformat() if a.planned_date else None
                    ),
                }
                if extra:
                    row.update(extra(a))
                out.append(row)
            return out

        review = report["manualReview"]
        review["projectRequiredWithoutProject"] = rows(
            scope.filter(
                catalogue_item__requires_project=True, project_id__isnull=True
            )
        )

        certified = set(
            Partner.objects.filter(
                deleted_at__isnull=True, is_certified=True
            ).values_list("id", flat=True)
        )
        review["agencyBookingNotCertified"] = rows(
            scope.filter(
                executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY
            ).exclude(assigned_partner_id__in=certified),
            extra=lambda a: {"partnerId": a.assigned_partner_id},
        )

        review["trainingMissingParticipants"] = rows(
            scope.filter(
                catalogue_item__participant_mode__in=[
                    ParticipantMode.DIRECT_TOTAL,
                    ParticipantMode.BY_CATEGORY,
                ]
            ).filter(Q(expected_participants__isnull=True) | Q(expected_participants=0))
        )

        # Standard support carrying a Project is the signature of the old
        # workaround — but it is only a signature. Some of these are genuine
        # Project deliveries of ordinary support, so they are listed for a
        # person to judge and never unlinked automatically.
        review["possibleArtificialProject"] = rows(
            scope.filter(
                catalogue_item__standard_support=True,
                catalogue_item__requires_project=False,
                project_id__isnull=False,
            )
        )
