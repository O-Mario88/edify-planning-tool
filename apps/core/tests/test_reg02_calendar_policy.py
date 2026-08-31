"""Calendar availability remains advisory when activities are scheduled.

Calendar and leave records remain visible, but they no longer reject planning,
rescheduling, partner, core-slot, or project activity creation. Fixed dates keep
this contract independent of the day on which the suite runs.
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
SUNDAY = "2026-08-16"  # advisory conflict
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

    def test_sunday_scheduling_is_allowed(self):
        result = self._create(SUNDAY)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(
            Activity.objects.get(id=result["id"]).planned_date.isoformat(), SUNDAY
        )
        self.assertEqual(result["fy"], "2026")

    def test_saturday_is_allowed(self):
        result = self._create(SATURDAY)
        self.assertEqual(result["status"], "scheduled")

    def test_public_holiday_scheduling_is_allowed(self):
        PublicHoliday.objects.create(name="REG-02 Test Holiday", date=HOLIDAY)
        result = self._create(HOLIDAY)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(
            Activity.objects.get(id=result["id"]).planned_date.isoformat(), HOLIDAY
        )
        self.assertEqual(result["fy"], "2026")

    def test_calendar_blackout_is_advisory(self):
        """The other independent holiday source (CalendarBlock, e.g. the
        /public-holidays admin surface) remains advisory like a PublicHoliday
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
        result = self._create(HOLIDAY)
        self.assertEqual(result["status"], "scheduled")

    def test_country_calendar_event_is_visible_but_does_not_block_planning(self):
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
        visit = self._create(MONDAY)
        training = create(
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
        self.assertEqual(visit["status"], "scheduled")
        self.assertEqual(training["status"], "scheduled")

    def test_approved_leave_does_not_block_employee_scheduling(self):
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date=LEAVE_DAY,
            end_date=LEAVE_DAY,
            days=1,
            status="approved",
        )
        result = self._create(LEAVE_DAY)
        self.assertEqual(result["status"], "scheduled")

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

    def test_reschedule_to_sunday_is_allowed(self):
        activity = self._create(MONDAY)
        reschedule(
            activity["id"],
            {"scheduledDate": RESCHEDULE_TARGET_SUNDAY, "reason": "test"},
            self.cceo,
        )
        updated = Activity.objects.get(id=activity["id"])
        self.assertEqual(updated.planned_date.isoformat(), RESCHEDULE_TARGET_SUNDAY)

    def test_partner_scheduling_allows_sunday(self):
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
        result = partner_schedule(pa.id, {"scheduledDate": SUNDAY}, partner_user)
        self.assertEqual(result["status"], "partner_scheduled")

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

    def test_core_slot_scheduling_allows_sunday(self):
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
        result = slot_action(slot.id, "schedule", {"scheduledFor": SUNDAY}, self.cceo)
        self.assertEqual(result["status"], "Scheduled")
        slot.refresh_from_db()
        self.assertEqual(slot.status, "Scheduled")

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

    def test_project_scheduling_allows_sunday(self):
        from apps.projects.models import Project, ProjectCategory

        project = Project.objects.create(
            name="REG02 Project", category=ProjectCategory.choices[0][0]
        )
        result = self._create(SUNDAY, projectId=project.id)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(Activity.objects.get(id=result["id"]).project_id, project.id)

    def test_api_htmx_and_service_layer_allow_sunday_scheduling(self):
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        activity = self._create(SUNDAY)
        self.assertEqual(activity["status"], "scheduled")
        # Isolate the entry points so the duplicate guard cannot mask date policy.
        Activity.objects.filter(id=activity["id"]).update(status="cancelled")
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
        self.assertEqual(api_resp.status_code, 201, api_resp.content.decode())
        api_activity = (
            Activity.objects.filter(school=self.school)
            .exclude(status="cancelled")
            .get()
        )
        self.assertEqual(api_activity.planned_date.isoformat(), SUNDAY)
        Activity.objects.filter(id=api_activity.id).update(status="cancelled")
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
        self.assertEqual(htmx_resp.status_code, 200, htmx_resp.content.decode())
        planned = (
            Activity.objects.filter(school=self.school)
            .exclude(status="cancelled")
            .get()
        )
        self.assertEqual(planned.planned_date.isoformat(), SUNDAY)
        self.assertEqual(planned.status, "scheduled")

    @freeze_time("2031-03-12")  # an arbitrary real "today" far from the
    # fixed 2026 business dates used throughout this file — proves nothing
    # here secretly depends on date.today()/timezone.now().
    def test_frozen_clock_independent_of_real_today(self):
        result = self._create(SUNDAY)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(
            Activity.objects.get(id=result["id"]).planned_date.isoformat(), SUNDAY
        )
        self.assertEqual(result["fy"], "2026")
