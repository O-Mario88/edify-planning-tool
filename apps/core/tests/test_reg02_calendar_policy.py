"""REG-02: calendar and leave records block scheduling, on every surface.

Restored by owner decision (2026-09-22): "keep the calendar and leave blocks,
drop the frequency caps". 23e3bfba had removed the whole of the scheduling
governance and this file was rewritten to assert the opposite; only the
calendar half comes back, so only those assertions flip. The frequency caps and
the client/partner annual entitlements stay removed, and nothing here asserts
them.

The gate lives in one place (apps/core/calendar_policy.SchedulingPolicyService)
and every scheduling surface calls it: create, reschedule, the two partner
paths, core slots, follow-ups, batch reschedule, budget amendments (at request
AND at apply) and route feasibility. That breadth is the point — b4fc9570 once
deleted it from a single module and left a blocked date reachable by going in
through another door.

Fixed dates keep this contract independent of the day on which the suite runs.
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
from apps.activities.models import Activity
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
SUNDAY = "2026-08-16"  # blocked by policy
MONDAY = "2026-08-17"  # allowed — ordinary in-FY weekday
HOLIDAY = "2026-08-19"  # Wednesday, made a PublicHoliday below
LEAVE_DAY = "2026-08-20"  # Thursday, covered by an approved Leave below
RESCHEDULE_TARGET_SUNDAY = "2026-08-23"  # advisory conflict


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


# Scheduling refuses a date that is not ahead of today (owner, 2026-09-16),
# and the dates below are fixed. "Today" therefore sits just before them, in
# the same fiscal year, so every calendar fact they encode stays true.
@freeze_time("2026-08-08")
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

    def test_sunday_scheduling_is_blocked(self):
        with self.assertRaises(BadRequest) as caught:
            self._create(SUNDAY)
        self.assertIn("Sunday", str(caught.exception))
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_saturday_is_allowed(self):
        result = self._create(SATURDAY)
        self.assertEqual(result["status"], "scheduled")

    def test_public_holiday_scheduling_is_blocked(self):
        PublicHoliday.objects.create(name="REG-02 Test Holiday", date=HOLIDAY)
        with self.assertRaises(BadRequest) as caught:
            self._create(HOLIDAY)
        self.assertIn("REG-02 Test Holiday", str(caught.exception))

    def test_calendar_blackout_blocks_scheduling(self):
        """CalendarBlock is the second, independent holiday source (the
        /public-holidays admin surface). It blocks exactly as a PublicHoliday
        row does — the same holiday-source union the policy checks."""
        CalendarBlock.objects.create(
            title="REG-02 Blackout",
            block_type="BLACKOUT_DATE",
            start_date=HOLIDAY,
            end_date=HOLIDAY,
            country="Uganda",
            is_active=True,
        )
        with self.assertRaises(BadRequest) as caught:
            self._create(HOLIDAY)
        self.assertIn("REG-02 Blackout", str(caught.exception))

    def test_country_calendar_event_blocks_planning(self):
        CalendarBlock.objects.create(
            title="Country strategy summit",
            block_type="ORG_EVENT",
            start_date=MONDAY,
            end_date=MONDAY,
            country="Uganda",
            applies_to_all_roles=True,
            is_active=True,
        )
        assigned_check = SchedulingPolicyService.check(self.cceo, MONDAY)
        pre_assignment_check = SchedulingPolicyService.check(None, MONDAY)
        self.assertEqual(assigned_check["status"], "blocked")
        self.assertEqual(pre_assignment_check["status"], "blocked")
        self.assertIn("Country strategy summit", assigned_check["blockers"][0])
        with self.assertRaises(BadRequest):
            self._create(MONDAY)
        with self.assertRaises(BadRequest):
            create(
                {
                    "activityType": "school_improvement_training",
                    "schoolId": self.school.school_id,
                    "scheduledDate": MONDAY,
                    "expectedParticipants": 12,
                    "focusIntervention": "leadership",
                    "activityPurposeText": "Calendar-event training",
                },
                self.cceo,
            )

    def test_approved_leave_blocks_employee_scheduling(self):
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date=LEAVE_DAY,
            end_date=LEAVE_DAY,
            days=1,
            status="approved",
        )
        with self.assertRaises(BadRequest) as caught:
            self._create(LEAVE_DAY)
        self.assertIn("approved leave", str(caught.exception))

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

    def test_fixed_monday_can_be_scheduled(self):
        result = self._create(MONDAY)
        self.assertEqual(result["status"], "scheduled")

    def test_fixed_date_maps_to_correct_fy(self):
        self.assertEqual(get_operational_fy(date(2026, 8, 17)), "2026")
        result = self._create(MONDAY)
        self.assertEqual(result["fy"], "2026")

    def test_reschedule_to_sunday_is_blocked(self):
        """The asymmetry calendar_policy.py exists to prevent: a date create()
        refuses must not be reachable by rescheduling into it."""
        activity = self._create(MONDAY)
        with self.assertRaises(BadRequest):
            reschedule(
                activity["id"],
                {"scheduledDate": RESCHEDULE_TARGET_SUNDAY, "reason": "test"},
                self.cceo,
            )
        updated = Activity.objects.get(id=activity["id"])
        self.assertEqual(updated.planned_date.isoformat(), MONDAY)

    def test_partner_scheduling_is_blocked_on_sunday(self):
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
        with self.assertRaises(BadRequest):
            partner_schedule(pa.id, {"scheduledDate": SUNDAY}, partner_user)

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

    def test_core_slot_scheduling_is_blocked_on_sunday(self):
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
        with self.assertRaises(BadRequest):
            slot_action(slot.id, "schedule", {"scheduledFor": SUNDAY}, self.cceo)
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

    def test_project_scheduling_is_blocked_on_sunday(self):
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="REG02 Project", category=ProjectCategory.choices[0][0]
        )
        with self.assertRaises(BadRequest):
            self._create(SUNDAY, projectId=project.id)

    def test_api_and_htmx_entry_points_refuse_sunday_too(self):
        """The gate lives in the service, so every door inherits it.

        Asserted through the real HTTP surfaces rather than the service alone:
        a gate that only the service call path honours is the b4fc9570 shape.
        """
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        with self.assertRaises(BadRequest):
            self._create(SUNDAY)
        client = Client()
        client.force_login(self.cceo)
        api_resp = client.post(
            "/api/activities",
            {
                "catalogueItemId": "CLIENT_SCHOOL_FOLLOWUP_VISIT",
                "schoolId": self.school.school_id,
                "scheduledDate": SUNDAY,
                "responsibleStaffId": self.staff.id,
                "activityPurposeText": "REG-02 API test visit",
                "focusIntervention": "leadership",
            },
            content_type="application/json",
        )
        self.assertNotEqual(api_resp.status_code, 201, api_resp.content.decode())
        self.assertFalse(
            Activity.objects.filter(school=self.school)
            .exclude(status="cancelled")
            .exists()
        )
        htmx_resp = client.post(
            "/planning/schedule-action",
            {
                "catalogue_item_id": "CLIENT_SCHOOL_FOLLOWUP_VISIT",
                "school_id": self.school.school_id,
                "scheduled_date": SUNDAY,
                "delivery_type": "staff",
                "activity_goal": "REG-02 HTMX test visit",
                "ssa_collection_expected": "no",
                "reason": "REG-02 test visit",
                "focus_intervention": "leadership",
            },
        )
        self.assertFalse(
            Activity.objects.filter(school=self.school)
            .exclude(status="cancelled")
            .exists(),
            "the HTMX door scheduled a Sunday the service refuses",
        )

    @freeze_time("2021-03-12")  # an arbitrary real "today" far from the
    # fixed 2026 business dates used throughout this file — proves the fiscal
    # year and planned date are derived from the date given, never from the
    # clock: a 2021 "today" would yield FY2021, and this asserts FY2026.
    # It sits BEFORE those dates rather than after, because scheduling now
    # refuses a date that has passed (owner, 2026-09-16); what the clock may
    # not do is decide which year or day the work belongs to.
    def test_frozen_clock_independent_of_real_today(self):
        # MONDAY, not SUNDAY: this test is about the clock not deciding the
        # fiscal year, and it must not double as a calendar-policy assertion.
        result = self._create(MONDAY)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(
            Activity.objects.get(id=result["id"]).planned_date.isoformat(), MONDAY
        )
        self.assertEqual(result["fy"], "2026")
