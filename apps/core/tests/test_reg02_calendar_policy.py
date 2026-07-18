"""REG-02 — Calendar and Clock Policy (production-readiness program, Phase 1).

Canonical rule (apps/core/calendar_policy.py::SchedulingPolicyService):
  - Sunday is always blocked.
  - Saturday is never blocked by this policy (existing org policy permits it).
  - A public holiday (PublicHoliday row OR CalendarBlock PUBLIC_HOLIDAY) blocks.
  - Approved leave blocks the affected staff member.
  - The same rule is enforced by Planning, My Plan rescheduling, Partner
    scheduling, Core School scheduling, Project scheduling, Budget Amendment
    reschedule, and Daily Visit Batches — one surface must never block a date
    another surface allows.

All dates below are fixed ISO literals, never `date.today()`/`timezone.now()`
— this suite must pass identically regardless of the real wall-clock date
the suite happens to run on (see test_frozen_clock_independent_of_real_today).
"""

from __future__ import annotations

from datetime import date

from django.test import Client, TestCase
from freezegun import freeze_time

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffProfile,
    StaffSchoolAssignment,
    User,
)
from apps.activities.services import create, partner_schedule, reschedule
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.calendar_policy import SchedulingPolicyService
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools.services import slot_action
from apps.core_schools.models import CorePlan, CoreActivitySlot, cplan_id, cslot_id
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

# Fixed calendar — August 2026, all inside FY2026, none touching a real
# "today" wherever this suite happens to run.
SATURDAY = "2026-08-15"  # allowed — Saturday is not blocked by this policy
SUNDAY = "2026-08-16"  # blocked
MONDAY = "2026-08-17"  # allowed — ordinary in-FY weekday
HOLIDAY = "2026-08-19"  # Wednesday, made a PublicHoliday below
LEAVE_DAY = "2026-08-20"  # Thursday, covered by an approved Leave below
RESCHEDULE_TARGET_SUNDAY = "2026-08-23"  # blocked


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
        status="active",
    )


class Reg02CalendarPolicyTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="REG02 Region")
        self.district = District.objects.create(
            name="REG02 District", region=self.region, district_type="primary"
        )
        self.school = School.objects.create(
            school_id="REG02-1",
            name="REG02 School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.cceo = _user("reg02-cceo@edify.test", EdifyRole.CCEO.value)
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)

        catalogue = CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(date(2026, 8, 17)),
            version=1,
            defaults={"label": "REG-02 test catalogue"},
        )[0]
        for key in (
            "school_visit_cost_per_school_primary",
            "school_visit_cost_per_school_secondary",
            "school_visit_cost_per_school",
        ):
            CostSetting.objects.get_or_create(
                key=key,
                defaults={"label": key, "unit_cost": 50_000, "catalogue": catalogue},
            )

    def _create(self, scheduled_date: str, **extra) -> dict:
        payload = {
            "activityType": "school_visit",
            "schoolId": self.school.school_id,
            "scheduledDate": scheduled_date,
            "responsibleStaffId": self.staff.id,
            "activityPurposeText": "REG-02 test visit",
            **extra,
        }
        return create(payload, self.cceo)

    # ── 1. Sunday scheduling is blocked ─────────────────────────────────────
    def test_sunday_scheduling_is_blocked(self):
        with self.assertRaises(BadRequest) as ctx:
            self._create(SUNDAY)
        self.assertIn("Sunday", str(ctx.exception))

    # ── 2. Saturday follows configured policy (i.e. is allowed) ────────────
    def test_saturday_is_allowed(self):
        result = self._create(SATURDAY)
        self.assertEqual(result["status"], "scheduled")

    # ── 3. Public-holiday scheduling is blocked ─────────────────────────────
    def test_public_holiday_scheduling_is_blocked(self):
        PublicHoliday.objects.create(name="REG-02 Test Holiday", date=HOLIDAY)
        with self.assertRaises(BadRequest) as ctx:
            self._create(HOLIDAY)
        self.assertIn("public holiday", str(ctx.exception))

    def test_calendar_block_holiday_also_blocks(self):
        """The other independent holiday source (CalendarBlock, e.g. the
        /public-holidays admin surface) must block exactly like a PublicHoliday
        row — this is the same holiday-source-union the policy checks for
        PublicHoliday, applied to CalendarBlock as well."""
        CalendarBlock.objects.create(
            title="REG-02 Blackout",
            block_type="BLACKOUT_DATE",
            start_date=HOLIDAY,
            end_date=HOLIDAY,
            country="Uganda",
            is_active=True,
        )
        with self.assertRaises(BadRequest) as ctx:
            self._create(HOLIDAY)
        self.assertIn("blackout", str(ctx.exception))

    # ── 4. Leave blocks employee scheduling ─────────────────────────────────
    def test_approved_leave_blocks_employee_scheduling(self):
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date=LEAVE_DAY,
            end_date=LEAVE_DAY,
            days=1,
            status="approved",
        )
        with self.assertRaises(BadRequest) as ctx:
            self._create(LEAVE_DAY)
        self.assertIn("approved leave", str(ctx.exception))

    def test_pending_leave_only_warns_not_blocks(self):
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date=LEAVE_DAY,
            end_date=LEAVE_DAY,
            days=1,
            status="pending",
        )
        avail = SchedulingPolicyService.check(self.cceo, LEAVE_DAY)
        self.assertEqual(avail["status"], "warning")
        result = self._create(LEAVE_DAY)
        self.assertEqual(result["status"], "scheduled")

    # ── 5. A fixed Monday can be scheduled ──────────────────────────────────
    def test_fixed_monday_can_be_scheduled(self):
        result = self._create(MONDAY)
        self.assertEqual(result["status"], "scheduled")

    # ── 6. A fixed in-FY date maps to the correct fiscal year ──────────────
    def test_fixed_date_maps_to_correct_fy(self):
        self.assertEqual(get_operational_fy(date(2026, 8, 17)), "2026")
        result = self._create(MONDAY)
        self.assertEqual(result["fy"], "2026")

    # ── 7. Rescheduling to Sunday is blocked ────────────────────────────────
    def test_reschedule_to_sunday_is_blocked(self):
        activity = self._create(MONDAY)
        with self.assertRaises(BadRequest) as ctx:
            reschedule(
                activity["id"],
                {"scheduledDate": RESCHEDULE_TARGET_SUNDAY, "reason": "test"},
                self.cceo,
            )
        self.assertIn("Sunday", str(ctx.exception))

    # ── 8. Partner scheduling follows the same calendar policy ─────────────
    def test_partner_scheduling_blocks_sunday(self):
        partner_user = _user("reg02-partner@edify.test", EdifyRole.PARTNER_ADMIN.value)
        partner = Partner.objects.create(
            name="REG02 Partner", user=partner_user, active_status=True
        )
        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=partner,
            assigning_staff_id=self.staff.id,
            expected_activity_type="school_visit",
        )
        with self.assertRaises(BadRequest) as ctx:
            partner_schedule(pa.id, {"scheduledDate": SUNDAY}, partner_user)
        self.assertIn("Sunday", str(ctx.exception))

    def test_partner_scheduling_allows_monday(self):
        partner_user = _user(
            "reg02-partner-ok@edify.test", EdifyRole.PARTNER_ADMIN.value
        )
        partner = Partner.objects.create(
            name="REG02 Partner OK", user=partner_user, active_status=True
        )
        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=partner,
            assigning_staff_id=self.staff.id,
            expected_activity_type="school_visit",
        )
        result = partner_schedule(pa.id, {"scheduledDate": MONDAY}, partner_user)
        self.assertEqual(result["status"], "partner_scheduled")

    # ── 9. Core scheduling follows the same policy ──────────────────────────
    def test_core_slot_scheduling_blocks_sunday(self):
        plan = CorePlan.objects.create(
            id=cplan_id(self.school.school_id),
            school_id=self.school.school_id,
            fy="2026",
        )
        slot = CoreActivitySlot.objects.create(
            id=cslot_id(self.school.school_id, "v", 1),
            core_plan=plan,
            school_id=self.school.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=1,
            assigned_staff_id=self.staff.id,
        )
        with self.assertRaises(BadRequest) as ctx:
            slot_action(slot.id, "schedule", {"scheduledFor": SUNDAY}, self.cceo)
        self.assertIn("Sunday", str(ctx.exception))
        slot.refresh_from_db()
        self.assertNotEqual(slot.status, "Scheduled")

    def test_core_slot_scheduling_allows_monday(self):
        plan = CorePlan.objects.create(
            id=cplan_id(self.school.school_id),
            school_id=self.school.school_id,
            fy="2026",
        )
        slot = CoreActivitySlot.objects.create(
            id=cslot_id(self.school.school_id, "v", 1),
            core_plan=plan,
            school_id=self.school.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=1,
            assigned_staff_id=self.staff.id,
        )
        result = slot_action(slot.id, "schedule", {"scheduledFor": MONDAY}, self.cceo)
        self.assertEqual(result["status"], "Scheduled")

    # ── 10. Project scheduling follows the same policy ──────────────────────
    def test_project_scheduling_blocks_sunday(self):
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="REG02 Project", category=ProjectCategory.choices[0][0]
        )
        with self.assertRaises(BadRequest) as ctx:
            self._create(SUNDAY, projectId=project.id)
        self.assertIn("Sunday", str(ctx.exception))

    # ── 11. API, HTMX and server-rendered workflows agree ────────────────────
    def test_api_htmx_and_service_layer_agree_on_sunday_block(self):
        # Service layer (already exercised by test_sunday_scheduling_is_blocked)
        with self.assertRaises(BadRequest) as ctx:
            self._create(SUNDAY)
        service_message = str(ctx.exception)
        self.assertIn("Sunday", service_message)

        # DRF API surface — POST /api/activities
        client = Client()
        client.force_login(self.cceo)
        api_resp = client.post(
            "/api/activities",
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": SUNDAY,
                "responsibleStaffId": self.staff.id,
                "activityPurposeText": "REG-02 API test visit",
            },
            content_type="application/json",
        )
        self.assertEqual(api_resp.status_code, 400)
        self.assertIn("Sunday", str(api_resp.json().get("message", "")))

        # HTMX server-rendered surface — POST /planning/schedule-action
        htmx_resp = client.post(
            "/planning/schedule-action",
            {
                "activity_type": "school_visit",
                "school_id": self.school.school_id,
                "scheduled_date": SUNDAY,
                "delivery_type": "staff",
                "activity_goal": "REG-02 HTMX test visit",
                "ssa_collection_expected": "no",
                # Below the CD daily-target floor with only one school — supply
                # a reason so that SOFT gate doesn't mask the calendar gate
                # this assertion is actually about.
                "reason": "REG-02 test visit",
            },
        )
        self.assertEqual(htmx_resp.status_code, 400)
        self.assertIn("Sunday", htmx_resp.content.decode())

    # ── 12. Frozen-clock tests pass regardless of the real current date ────
    @freeze_time("2031-03-12")  # an arbitrary real "today" far from the
    # fixed 2026 business dates used throughout this file — proves nothing
    # here secretly depends on date.today()/timezone.now().
    def test_frozen_clock_independent_of_real_today(self):
        with self.assertRaises(BadRequest) as ctx:
            self._create(SUNDAY)
        self.assertIn("Sunday", str(ctx.exception))
        result = self._create(MONDAY)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["fy"], "2026")
