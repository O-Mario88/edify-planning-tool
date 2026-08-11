"""Audit and conservatively repair PL work outside direct portfolios."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Audit PL Activities, Partner assignments and Core slots targeting "
        "schools outside each PL's direct portfolio. Dry-run is the default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Cancel/return only safely reversible draft records; leave locked and completed work for review.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.audit.services import log as audit_log
        from apps.core.rbac import EdifyRole
        from apps.core_schools.models import CoreActivitySlot
        from apps.partners.models import PartnerAssignment
        from apps.schools.models import School

        apply = bool(options["apply"])
        findings = []
        repaired = 0
        leads = StaffProfile.objects.filter(
            user__active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            deleted_at__isnull=True,
        ).select_related("user")

        for lead in leads:
            identities = [lead.id, lead.user_id]
            direct_ids = set(
                StaffSchoolAssignment.objects.filter(staff=lead).values_list(
                    "school_id", flat=True
                )
            )

            activities = Activity.objects.filter(
                responsible_staff_id__in=identities,
                school__isnull=False,
                deleted_at__isnull=True,
            ).exclude(school_id__in=direct_ids)
            for record in activities.select_related("school"):
                has_cost = ActivityScheduleCostLine.objects.filter(
                    activity=record
                ).exists()
                classification = self._classification(record.status, has_cost)
                did_repair = False
                if apply and classification == "Unauthorized but Draft":
                    record.status = "cancelled"
                    record.save(update_fields=["status", "updated_at"])
                    did_repair = True
                findings.append(
                    self._row("Activity", record, lead, record.school, classification, did_repair)
                )
                repaired += int(did_repair)

            assignments = PartnerAssignment.objects.filter(
                assigning_staff_id__in=identities,
                school__isnull=False,
            ).exclude(school_id__in=direct_ids)
            for record in assignments.select_related("school"):
                classification = (
                    "Unauthorized but Draft"
                    if record.status in PartnerAssignment.UNSCHEDULED_STATUSES
                    else self._classification(record.status, False)
                )
                did_repair = False
                if apply and classification == "Unauthorized but Draft":
                    record.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
                    record.save(update_fields=["status", "updated_at"])
                    did_repair = True
                findings.append(
                    self._row(
                        "PartnerAssignment", record, lead, record.school, classification, did_repair
                    )
                )
                repaired += int(did_repair)

            public_direct_ids = set(
                School.objects.filter(id__in=direct_ids).values_list(
                    "school_id", flat=True
                )
            )
            slots = CoreActivitySlot.objects.filter(
                assigned_staff_id__in=identities
            ).exclude(school_id__in=public_direct_ids)
            schools = {
                school.school_id: school
                for school in School.objects.filter(
                    school_id__in=slots.values("school_id")
                )
            }
            for record in slots:
                school = schools.get(record.school_id)
                classification = self._classification(record.status, False)
                did_repair = False
                if apply and record.status.lower() in {"assigned", "planned"}:
                    record.assigned_staff_id = None
                    record.assigned_staff_name = None
                    record.status = "Missing"
                    record.save(
                        update_fields=[
                            "assigned_staff_id",
                            "assigned_staff_name",
                            "status",
                            "updated_at",
                        ]
                    )
                    classification = "Unauthorized but Draft"
                    did_repair = True
                findings.append(
                    self._row("CoreActivitySlot", record, lead, school, classification, did_repair)
                )
                repaired += int(did_repair)

        if apply:
            for finding in findings:
                if finding["repaired"]:
                    audit_log(
                        action="repair_pl_portfolio_access",
                        subject_kind=finding["kind"],
                        subject_id=finding["id"],
                        actor_id="management-command",
                        actor_role="Admin",
                        success=True,
                        reason="Removed reversible draft work outside the PL direct portfolio.",
                    )

        payload = {
            "mode": "apply" if apply else "dry-run",
            "findingCount": len(findings),
            "repairedCount": repaired,
            "manualReviewCount": sum(
                not finding["repaired"] for finding in findings
            ),
            "findings": findings,
        }
        self.stdout.write(json.dumps(payload, indent=2, default=str))

    @staticmethod
    def _classification(status, has_cost):
        normalized = str(status or "").lower().replace(" ", "_")
        if has_cost:
            return "Financially locked historical record"
        if normalized in {"not_planned", "planned", "draft", "assigned", "missing"}:
            return "Unauthorized but Draft"
        if normalized in {
            "completed",
            "closed",
            "ia_verified",
            "accountant_confirmed",
        }:
            return "Completed historical record"
        if normalized in {"scheduled", "partner_scheduled", "in_progress"}:
            return "Unauthorized and Scheduled"
        return "Manual Review Required"

    @staticmethod
    def _row(kind, record, lead, school, classification, repaired):
        return {
            "kind": kind,
            "id": str(record.id),
            "programLead": lead.user.name or lead.user.email,
            "school": getattr(school, "name", "Missing school") if school else "Missing school",
            "schoolId": getattr(school, "school_id", "") if school else "",
            "expectedAccess": "Read-Only Team Oversight",
            "actualAccess": "Operational record attributed to Programme Lead",
            "classification": classification,
            "repaired": repaired,
            "resolution": (
                "Draft safely returned/cancelled"
                if repaired
                else "Manual review required; no historical record was deleted"
            ),
        }
