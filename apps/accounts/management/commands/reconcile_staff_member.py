"""Safely reconcile one uploaded staff roster row with production data.

Dry-run is the default.  ``--apply`` is deliberately explicit because the
command can change account identity, reporting lines, and school ownership.
The uploaded ``School.account_owner_name_raw`` value is authoritative; the
command never invents assignments merely to reach a requested count.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.accounts.models import (
    StaffOnboardingState,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSetupCandidate,
    StaffSetupCandidateStatus,
    StaffSupervisorAssignment,
    User,
    UserStatus,
)
from apps.accounts.staff_matching import normalize_name
from apps.core.enums import AccountOwnerStatus
from apps.core.rbac import EdifyRole
from apps.schools.models import School


_RECONCILE_LOCK_ID = 0x4544494659535446  # "EDIFYSTF"


class Command(BaseCommand):
    help = "Dry-run or apply one exact staff-roster reconciliation."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--phone", required=True)
        parser.add_argument("--position", required=True)
        parser.add_argument("--role", required=True, choices=EdifyRole.values())
        parser.add_argument("--expected-schools", required=True, type=int)
        parser.add_argument("--manager-email", default="")
        parser.add_argument("--actor-email", required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the reported changes. Without this flag no data is changed.",
        )

    def handle(self, *args, **options):
        desired = {
            "name": options["name"].strip(),
            "email": options["email"].strip().lower(),
            "phone": options["phone"].strip(),
            "position": options["position"].strip(),
            "role": options["role"],
            "expected_schools": options["expected_schools"],
            "manager_email": options["manager_email"].strip().lower(),
        }
        if desired["expected_schools"] < 0:
            raise CommandError("--expected-schools cannot be negative.")

        actor = User.objects.filter(
            email__iexact=options["actor_email"].strip(),
            deleted_at__isnull=True,
            active_role=EdifyRole.ADMIN.value,
            status=UserStatus.ACTIVE,
            is_active=True,
        ).first()
        if not actor:
            raise CommandError("--actor-email must identify an active Admin account.")

        matched_school_ids = self._matched_school_ids(desired["name"])
        if len(matched_school_ids) != desired["expected_schools"]:
            raise CommandError(
                "Uploaded owner-name count mismatch for "
                f"{desired['name']}: expected {desired['expected_schools']}, "
                f"found {len(matched_school_ids)}. No changes were made."
            )

        current_user = self._resolve_user(desired)
        manager = self._resolve_manager(desired["manager_email"])
        report = self._report(desired, current_user, manager, matched_school_ids)
        mode = "APPLY" if options["apply"] else "DRY_RUN"

        if not options["apply"]:
            self.stdout.write(f"{mode} {json.dumps(report, sort_keys=True)}")
            return

        with transaction.atomic():
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(%s)", [_RECONCILE_LOCK_ID]
                    )
            user, created = self._upsert_user(desired, current_user)
            staff, _ = StaffProfile.objects.select_for_update().get_or_create(
                user=user,
                defaults={
                    "title": desired["position"],
                    "country": "Uganda",
                    "onboarding_state": StaffOnboardingState.ACTIVE,
                },
            )
            staff.title = desired["position"]
            staff.country = staff.country or "Uganda"
            staff.onboarding_state = StaffOnboardingState.ACTIVE
            staff.deleted_at = None
            staff.save(
                update_fields=[
                    "title",
                    "country",
                    "onboarding_state",
                    "deleted_at",
                    "updated_at",
                ]
            )

            manager_staff = None
            if desired["manager_email"]:
                manager = self._resolve_manager(desired["manager_email"], required=True)
                manager_staff = manager.staff_profile
                if manager_staff.id == staff.id:
                    raise CommandError("A staff member cannot supervise themselves.")

            old_manager_ids = list(
                StaffSupervisorAssignment.objects.filter(supervisee=staff).values_list(
                    "supervisor_id", flat=True
                )
            )
            StaffSupervisorAssignment.objects.filter(supervisee=staff).delete()
            if manager_staff:
                StaffSupervisorAssignment.objects.create(
                    supervisee=staff, supervisor=manager_staff
                )

            stale_ids = list(
                StaffSchoolAssignment.objects.filter(staff=staff)
                .exclude(school_id__in=matched_school_ids)
                .values_list("school_id", flat=True)
            )
            if stale_ids:
                StaffSchoolAssignment.objects.filter(
                    staff=staff, school_id__in=stale_ids
                ).delete()
                School.objects.filter(
                    id__in=stale_ids, account_owner_id=staff.id
                ).update(
                    account_owner_id=None,
                    account_owner_status=AccountOwnerStatus.UNMATCHED,
                )

            conflicting = StaffSchoolAssignment.objects.filter(
                school_id__in=matched_school_ids
            ).exclude(staff=staff)
            conflicting_count = conflicting.count()
            conflicting.delete()
            existing_ids = set(
                StaffSchoolAssignment.objects.filter(
                    staff=staff, school_id__in=matched_school_ids
                ).values_list("school_id", flat=True)
            )
            StaffSchoolAssignment.objects.bulk_create(
                [
                    StaffSchoolAssignment(staff=staff, school_id=school_id)
                    for school_id in matched_school_ids
                    if school_id not in existing_ids
                ]
            )
            School.objects.filter(id__in=matched_school_ids).update(
                account_owner_id=staff.id,
                account_owner_status=AccountOwnerStatus.MATCHED,
            )

            StaffSetupCandidate.objects.filter(
                normalized_name=normalize_name(desired["name"])
            ).update(
                full_name=desired["name"],
                email=desired["email"],
                phone=desired["phone"],
                school_count=len(matched_school_ids),
                matched_user_id=user.id,
                status=StaffSetupCandidateStatus.ACTIVE,
            )

            from apps.audit.services import log as audit_log

            audit_log(
                action="admin.staff_roster_reconciled",
                subject_kind="staff_profile",
                subject_id=staff.id,
                actor_id=actor.id,
                actor_role=actor.active_role,
                payload={
                    "email": desired["email"],
                    "role": desired["role"],
                    "schoolCount": len(matched_school_ids),
                    "created": created,
                    "staleAssignmentsRemoved": len(stale_ids),
                    "conflictingAssignmentsRemoved": conflicting_count,
                    "oldManagerIds": old_manager_ids,
                    "newManagerId": manager_staff.id if manager_staff else None,
                },
            )

        final_user = User.objects.select_related("staff_profile").get(pk=user.pk)
        final_report = self._report(
            desired,
            final_user,
            manager,
            matched_school_ids,
        )
        final_report["created"] = created
        self.stdout.write(
            self.style.SUCCESS(f"{mode} {json.dumps(final_report, sort_keys=True)}")
        )

    @staticmethod
    def _matched_school_ids(name: str) -> list[str]:
        wanted = normalize_name(name)
        return [
            school_id
            for school_id, raw_name in School.objects.filter(
                deleted_at__isnull=True
            ).values_list("id", "account_owner_name_raw")
            if normalize_name(raw_name) == wanted
        ]

    @staticmethod
    def _resolve_user(desired: dict) -> User | None:
        by_email = list(
            User.objects.filter(
                email__iexact=desired["email"], deleted_at__isnull=True
            ).select_related("staff_profile")
        )
        if len(by_email) == 1:
            return by_email[0]
        if len(by_email) > 1:
            raise CommandError("Multiple live users share the requested email.")

        named = [
            user
            for user in User.objects.filter(deleted_at__isnull=True).select_related(
                "staff_profile"
            )
            if normalize_name(user.name) == normalize_name(desired["name"])
        ]
        if len(named) > 1:
            raise CommandError(
                "Multiple live users share the requested name; reconcile manually."
            )
        return named[0] if named else None

    @staticmethod
    def _resolve_manager(email: str, *, required: bool = False) -> User | None:
        if not email:
            return None
        manager = (
            User.objects.filter(email__iexact=email, deleted_at__isnull=True)
            .select_related("staff_profile")
            .first()
        )
        if required and (not manager or not hasattr(manager, "staff_profile")):
            raise CommandError(f"Manager {email} does not have a staff profile.")
        return manager

    @staticmethod
    def _upsert_user(desired: dict, current: User | None) -> tuple[User, bool]:
        created = current is None
        if created:
            user = User.objects.create_user(
                email=desired["email"],
                name=desired["name"],
                phone=desired["phone"],
                roles=[desired["role"]],
                active_role=desired["role"],
                password=None,
                status=UserStatus.ACTIVE,
                is_active=True,
            )
        else:
            user = User.objects.select_for_update().get(pk=current.pk)
            user.email = desired["email"]
            user.name = desired["name"]
            user.phone = desired["phone"]
            user.roles = [desired["role"]]
            user.active_role = desired["role"]
            user.status = UserStatus.ACTIVE
            user.is_active = True
            user.deleted_at = None
            user.save(
                update_fields=[
                    "email",
                    "name",
                    "phone",
                    "roles",
                    "active_role",
                    "status",
                    "is_active",
                    "deleted_at",
                    "updated_at",
                ]
            )
        return user, created

    @staticmethod
    def _report(
        desired: dict,
        user: User | None,
        manager: User | None,
        matched_school_ids: list[str],
    ) -> dict:
        staff = getattr(user, "staff_profile", None) if user else None
        managers = (
            list(
                staff.supervisor_links.select_related("supervisor__user").values_list(
                    "supervisor__user__email", flat=True
                )
            )
            if staff
            else []
        )
        return {
            "name": desired["name"],
            "email": desired["email"],
            "exists": user is not None,
            "currentName": user.name if user else None,
            "currentPhone": user.phone if user else None,
            "currentRole": user.active_role if user else None,
            "currentStatus": user.status if user else None,
            "currentIsActive": user.is_active if user else None,
            "passwordUsable": user.has_usable_password() if user else False,
            "currentTitle": staff.title if staff else None,
            "currentDirectSchools": staff.school_links.count() if staff else 0,
            "uploadedOwnerSchools": len(matched_school_ids),
            "expectedSchools": desired["expected_schools"],
            "currentManagers": managers,
            "requestedManager": desired["manager_email"] or None,
            "managerExists": manager is not None if desired["manager_email"] else True,
        }
