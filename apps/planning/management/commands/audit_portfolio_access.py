"""Find work a supervisor created inside a supervisee's portfolio.

The rule — a Programme Lead plans only for schools, clusters and core schools
directly assigned to them — is now enforced at every write. This command
answers the other half of the question: what already exists in the database
from before it was.

Every row is classified, because the right response is different for each:

    valid_direct        the creator did own the target. Nothing to do.
    valid_coverage      a temporary coverage assignment was active on the day
                        the row was created, which is a legitimate stand-in.
    unauthorized_draft  created outside the portfolio, still a draft. Safe to
                        cancel: nothing has been promised to a school.
    unauthorized_live   scheduled or in flight. NOT cancellable — a school is
                        expecting this, and somebody has to decide whether it
                        goes ahead under the right owner or is stood down.
    financially_locked  money has moved or a cost line is committed. Never
                        touched: reversing it here would put the ledger and
                        the activity out of step.
    historical_complete finished work. History is not rewritten.
    manual_review       could not be classified with confidence.

Only `unauthorized_draft` is repairable, and even that is opt-in. The repair
reassigns the row to the responsible CCEO rather than deleting it, because the
work was probably real and needed — what was wrong was who placed it.

    manage.py audit_portfolio_access                 # report only (default)
    manage.py audit_portfolio_access --repair        # reassign drafts
    manage.py audit_portfolio_access --fy 2026       # one financial year
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction


DRAFT_STATUSES = ("planned", "draft")
LOCKED_PAYMENT_STATUSES = ("paid", "processing", "confirmed", "approved")


class Command(BaseCommand):
    help = "Classify work supervisors created inside their supervisees' portfolios."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repair",
            action="store_true",
            help="Reassign unauthorised DRAFT rows to the responsible CCEO.",
        )
        parser.add_argument("--fy", default="", help="Limit to one financial year.")
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after N findings (0 = no limit).",
        )

    def handle(self, *args, **options):
        findings = self._collect(fy=options["fy"], limit=options["limit"])

        self.stdout.write("")
        self.stdout.write("PROGRAMME LEAD PORTFOLIO ACCESS — HISTORICAL AUDIT")
        self.stdout.write("=" * 66)

        counts = Counter(f["classification"] for f in findings)
        for label in (
            "valid_direct",
            "valid_coverage",
            "unauthorized_draft",
            "unauthorized_live",
            "financially_locked",
            "historical_complete",
            "manual_review",
        ):
            self.stdout.write(f"  {label:<22} {counts.get(label, 0)}")

        offending = [
            f
            for f in findings
            if f["classification"] not in ("valid_direct", "valid_coverage")
        ]
        self.stdout.write("")
        if not offending:
            self.stdout.write(
                self.style.SUCCESS(
                    "No work was created by a supervisor inside a supervisee's "
                    "portfolio."
                )
            )
            return

        self.stdout.write(f"{len(offending)} record(s) need attention:")
        for f in offending[:40]:
            self.stdout.write(
                f"  [{f['classification']}] {f['kind']} {f['id']} — "
                f"{f['school'] or f['cluster']} · created by {f['creator']} · "
                f"owner {f['owner']} · status {f['status']}"
            )
        if len(offending) > 40:
            self.stdout.write(f"  … and {len(offending) - 40} more")

        repairable = [
            f for f in offending if f["classification"] == "unauthorized_draft"
        ]
        self.stdout.write("")
        if not options["repair"]:
            self.stdout.write(
                f"{len(repairable)} draft(s) can be reassigned to the responsible "
                "CCEO. Re-run with --repair to apply. Everything else needs a "
                "human decision and is never changed by this command."
            )
            return

        repaired = self._repair(repairable)
        self.stdout.write(
            self.style.SUCCESS(
                f"Reassigned {repaired} draft activit(ies) to the responsible CCEO."
            )
        )

    # ── collection ──────────────────────────────────────────────────────────
    def _collect(self, *, fy: str, limit: int) -> list[dict]:
        from apps.accounts.models import (
            StaffProfile,
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
            TemporaryCoverageAssignment,
        )
        from apps.activities.models import Activity
        from apps.core.rbac import EdifyRole

        # Who supervises whom, in both id spaces — `responsible_staff_id` holds
        # a StaffProfile id on rows written through the service and a User id
        # on rows from the seeder or older paths, and a check that knows only
        # one of them silently reports every row of the other kind as clean.
        supervisors = {}
        for link in StaffSupervisorAssignment.objects.select_related(
            "supervisor__user", "supervisee"
        ):
            if getattr(link.supervisor, "user", None) is None:
                continue
            if link.supervisor.user.active_role != EdifyRole.COUNTRY_PROGRAM_LEAD.value:
                continue
            ids = {link.supervisor_id, link.supervisor.user_id}
            for i in ids:
                supervisors.setdefault(i, set()).add(link.supervisee_id)

        if not supervisors:
            return []

        own_schools: dict[str, set[str]] = {}
        for row in StaffSchoolAssignment.objects.values("staff_id", "school_id"):
            own_schools.setdefault(row["staff_id"], set()).add(row["school_id"])
        # Mirror each staff member's schools onto their user id too.
        for staff_id, user_id in StaffProfile.objects.values_list("id", "user_id"):
            if staff_id in own_schools and user_id:
                own_schools.setdefault(user_id, set()).update(own_schools[staff_id])

        coverage = list(
            TemporaryCoverageAssignment.objects.values(
                "covering_staff_id",
                "original_staff_id",
                "start_datetime",
                "end_datetime",
                "status",
            )
        )

        qs = Activity.objects.filter(
            deleted_at__isnull=True,
            responsible_staff_id__in=list(supervisors.keys()),
        ).select_related("school")
        if fy:
            qs = qs.filter(fy=fy)
        qs = qs.order_by("created_at")
        if limit:
            qs = qs[:limit]

        findings = []
        for activity in qs.iterator(chunk_size=500):
            creator = activity.responsible_staff_id
            mine = own_schools.get(creator, set())
            school_id = activity.school_id
            if school_id and school_id in mine:
                classification = "valid_direct"
            elif school_id is None:
                # Cluster work. Ownership of a cluster is not stored per
                # activity, so this cannot be settled mechanically.
                classification = "manual_review"
            elif self._covered(coverage, creator, activity, own_schools, school_id):
                classification = "valid_coverage"
            else:
                classification = self._classify_unauthorized(activity)

            findings.append(
                {
                    "kind": "Activity",
                    "id": activity.id,
                    "school": getattr(activity.school, "name", "") if school_id else "",
                    "cluster": activity.cluster_id or "",
                    "creator": creator,
                    "owner": self._owner_of(school_id, own_schools),
                    "status": activity.status,
                    "classification": classification,
                }
            )
        return findings

    @staticmethod
    def _covered(coverage, creator, activity, own_schools, school_id) -> bool:
        """Was a temporary coverage active when this row was created?

        Checked against the row's own created_at, not against today: coverage
        that has since expired still legitimised the write at the time, and
        judging historical rows by today's assignments would condemn every
        legitimate stand-in.
        """
        created = activity.created_at
        if created is None:
            return False
        for row in coverage:
            if row["covering_staff_id"] != creator:
                continue
            if row["status"] != "active":
                continue
            if not (row["start_datetime"] <= created <= row["end_datetime"]):
                continue
            if school_id in own_schools.get(row["original_staff_id"], set()):
                return True
        return False

    @staticmethod
    def _classify_unauthorized(activity) -> str:
        from apps.core.activity_types import COMPLETED_WORK_STATUSES

        payment = (getattr(activity, "payment_status", "") or "").lower()
        if payment in LOCKED_PAYMENT_STATUSES:
            return "financially_locked"
        if activity.status in COMPLETED_WORK_STATUSES:
            return "historical_complete"
        if (activity.status or "").lower() in DRAFT_STATUSES:
            return "unauthorized_draft"
        if (activity.status or "").lower() == "cancelled":
            return "valid_direct"  # already stood down; nothing outstanding
        return "unauthorized_live"

    @staticmethod
    def _owner_of(school_id, own_schools) -> str:
        if not school_id:
            return "—"
        for staff_id, schools in own_schools.items():
            if school_id in schools:
                return staff_id
        return "unassigned"

    # ── repair ──────────────────────────────────────────────────────────────
    def _repair(self, repairable: list[dict]) -> int:
        from apps.activities.models import Activity
        from apps.audit.services import log

        repaired = 0
        for finding in repairable:
            owner = finding["owner"]
            if owner in ("unassigned", "—"):
                # No owner to hand it to. Reassigning to nobody would leave the
                # row in exactly the state that produced this audit.
                continue
            with transaction.atomic():
                activity = (
                    Activity.objects.select_for_update()
                    .filter(id=finding["id"])
                    .first()
                )
                if activity is None:
                    continue
                previous = activity.responsible_staff_id
                activity.responsible_staff_id = owner
                activity.save(update_fields=["responsible_staff_id", "updated_at"])
                log(
                    action="portfolio_access.draft_reassigned",
                    subject_kind="Activity",
                    subject_id=activity.id,
                    payload={
                        "from": previous,
                        "to": owner,
                        "reason": "created by a supervisor outside their direct portfolio",
                    },
                )
                repaired += 1
        return repaired
