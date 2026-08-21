from datetime import date

from django.test import TestCase

from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.frontend.views.extended_views import _reference_holidays_for_year
from apps.geography.models import District, Region
from apps.schools.models import School


class CalendarWorkspaceTest(TestCase):
    """The operations calendar joins live, role-scoped records by date."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="calendar-owner@example.com",
            name="Calendar Owner",
            roles=["CCEO"],
            active_role="CCEO",
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="CCEO")
        region = Region.objects.create(name="Calendar Region")
        district = District.objects.create(name="Calendar District", region=region)
        self.school = School.objects.create(
            school_id="CAL-001",
            name="Calendar School",
            region=region,
            district=district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        self.client.force_login(self.user)

    def test_calendar_combines_live_activity_leave_and_government_holiday(self):
        activity_date = date(2026, 7, 16)
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=get_operational_fy(activity_date),
            quarter=get_quarter_for_date(activity_date),
            planned_date=activity_date,
            responsible_staff_id=self.staff.id,
            status="scheduled",
        )
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date="2026-07-17",
            end_date="2026-07-17",
            days=1,
            status="approved",
        )
        PublicHoliday.objects.create(
            name="Government-declared holiday", date=date(2026, 7, 18)
        )

        response = self.client.get("/calendar?year=2026&month=7")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apply for Leave")
        self.assertContains(response, "School Visit")
        self.assertContains(response, "Your leave")
        self.assertContains(response, "Government-declared holiday")
        self.assertEqual(response.context["event_counts"]["activity"], 1)
        self.assertEqual(response.context["event_counts"]["leave"], 1)

    def test_reference_holidays_omit_presidential_inauguration(self):
        holiday_titles = {
            holiday["title"] for holiday in _reference_holidays_for_year(2026)
        }

        self.assertIn("Christmas Day", holiday_titles)
        self.assertNotIn("Presidential Inauguration", holiday_titles)

    def test_mobile_calendar_places_connected_event_tabs_below_filters(self):
        response = self.client.get(
            "/calendar?year=2026&month=12&view=agenda&event_kind=holiday"
        )
        markup = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            markup.index('class="calendar-workspace__filter-form'),
            markup.index('class="calendar-workspace__filters"'),
        )
        self.assertLess(
            markup.index('class="calendar-workspace__filters"'),
            markup.index('class="calendar-mobile"'),
        )
        self.assertContains(response, 'class="calendar-mobile__month-grid"')
        self.assertContains(response, "setEventFilter('holiday')")
        self.assertContains(response, 'x-show="dayMatches(')
        self.assertEqual(response.context["selected_event_kind"], "holiday")
        self.assertIn("event_kind=holiday", response.context["next_qs"])
        self.assertNotIn("event_kind", response.context["clear_qs"])

    def test_mobile_calendar_days_expose_per_kind_counts(self):
        PublicHoliday.objects.create(
            name="Calendar mobile holiday", date=date(2026, 8, 8)
        )

        response = self.client.get("/calendar?year=2026&month=8")
        agenda_day = next(
            day
            for day in response.context["agenda_days"]
            if day["date"] == date(2026, 8, 8)
        )

        self.assertGreaterEqual(agenda_day["kind_counts"]["holiday"], 1)
        self.assertEqual(agenda_day["kind_counts"]["all"], len(agenda_day["events"]))

    def test_government_can_add_a_one_off_inauguration_holiday(self):
        PublicHoliday.objects.create(
            name="Presidential Inauguration", date=date(2026, 5, 13)
        )

        response = self.client.get("/calendar?year=2026&month=5")

        self.assertContains(response, "Presidential Inauguration")


class CalendarEventAuthoringTest(TestCase):
    event_date = date(2026, 9, 14)

    def setUp(self):
        self.cd = User.objects.create_user(
            email="calendar-cd@example.com",
            name="Calendar CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        StaffProfile.objects.create(
            user=self.cd,
            title="Country Director",
            country="Uganda",
        )
        self.cceo = User.objects.create_user(
            email="calendar-cceo@example.com",
            name="Calendar CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        StaffProfile.objects.create(user=self.cceo, title="CCEO", country="Uganda")

    def test_country_director_can_add_an_other_event_from_calendar(self):
        self.client.force_login(self.cd)
        page = self.client.get("/calendar?year=2026&month=9")

        self.assertContains(page, "Add other event")
        self.assertContains(page, 'action="/calendar/events"')

        response = self.client.post(
            "/calendar/events",
            {
                "title": "Annual strategy summit",
                "description": "Country team convening",
                "start_date": self.event_date.isoformat(),
                "end_date": self.event_date.isoformat(),
            },
        )

        self.assertRedirects(
            response,
            "/calendar?year=2026&month=9",
            fetch_redirect_response=False,
        )
        block = CalendarBlock.objects.get(title="Annual strategy summit")
        self.assertEqual(block.block_type, "ORG_EVENT")
        self.assertTrue(block.applies_to_all_roles)
        self.assertEqual(block.created_by, self.cd.id)

        page = self.client.get("/calendar?year=2026&month=9&event_kind=event")
        self.assertContains(page, "Annual strategy summit")
        self.assertContains(page, "Country team convening")
        self.assertEqual(page.context["event_counts"]["event"], 1)
        self.assertEqual(page.context["selected_event_kind"], "event")

    def test_field_user_cannot_add_an_organization_event(self):
        self.client.force_login(self.cceo)

        page = self.client.get("/calendar?year=2026&month=9")
        response = self.client.post(
            "/calendar/events",
            {
                "title": "Unauthorized block",
                "start_date": self.event_date.isoformat(),
            },
        )

        self.assertNotContains(page, "Add other event")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            CalendarBlock.objects.filter(title="Unauthorized block").exists()
        )

    def test_event_end_date_cannot_precede_start_date(self):
        self.client.force_login(self.cd)

        response = self.client.post(
            "/calendar/events",
            {
                "title": "Invalid event",
                "start_date": "2026-09-14",
                "end_date": "2026-09-13",
            },
        )

        self.assertRedirects(
            response,
            "/calendar",
            fetch_redirect_response=False,
        )
        self.assertFalse(CalendarBlock.objects.filter(title="Invalid event").exists())


class CalendarRoleScheduleAudienceTest(TestCase):
    """The calendar is personal: every role sees only the work they planned."""

    calendar_date = date(2026, 7, 16)

    def _staff(self, role, label):
        user = User.objects.create_user(
            email=f"{label.lower().replace(' ', '-')}@calendar.example.com",
            name=label,
            roles=[role],
            active_role=role,
        )
        return user, StaffProfile.objects.create(user=user, title=role)

    def _schedule(self, staff):
        return Activity.objects.create(
            activity_type="school_visit",
            fy=get_operational_fy(self.calendar_date),
            quarter=get_quarter_for_date(self.calendar_date),
            planned_date=self.calendar_date,
            responsible_staff_id=staff.id,
            status="scheduled",
        )

    def _visible_owner_ids(self, user):
        self.client.force_login(user)
        response = self.client.get("/calendar?year=2026&month=7")
        self.assertEqual(response.status_code, 200)
        return set(
            response.context["activities"].values_list(
                "responsible_staff_id", flat=True
            )
        )

    def test_program_lead_calendar_is_personal_even_with_supervisees(self):
        pl, pl_staff = self._staff(EdifyRole.COUNTRY_PROGRAM_LEAD.value, "PL One")
        _, cceo_staff = self._staff(EdifyRole.CCEO.value, "CCEO One")
        _, other_cceo_staff = self._staff(EdifyRole.CCEO.value, "CCEO Two")
        StaffSupervisorAssignment.objects.create(
            supervisor=pl_staff, supervisee=cceo_staff
        )
        self._schedule(pl_staff)
        self._schedule(cceo_staff)
        self._schedule(other_cceo_staff)

        self.assertEqual(self._visible_owner_ids(pl), {pl_staff.id})

    def test_country_director_calendar_shows_only_their_own_schedule(self):
        cd, cd_staff = self._staff(EdifyRole.COUNTRY_DIRECTOR.value, "CD One")
        _, pl_staff = self._staff(EdifyRole.COUNTRY_PROGRAM_LEAD.value, "PL One")
        _, accountant_staff = self._staff(
            EdifyRole.PROGRAM_ACCOUNTANT.value, "Accountant One"
        )
        _, ia_staff = self._staff(EdifyRole.IMPACT_ASSESSMENT.value, "IA One")
        _, cceo_staff = self._staff(EdifyRole.CCEO.value, "CCEO One")
        for staff in (cd_staff, pl_staff, accountant_staff, ia_staff, cceo_staff):
            self._schedule(staff)

        self.assertEqual(self._visible_owner_ids(cd), {cd_staff.id})

    def test_rvp_calendar_shows_only_their_own_schedule(self):
        rvp, rvp_staff = self._staff(EdifyRole.REGIONAL_VICE_PRESIDENT.value, "RVP One")
        _, cd_staff = self._staff(EdifyRole.COUNTRY_DIRECTOR.value, "CD One")
        _, hr_staff = self._staff(EdifyRole.HUMAN_RESOURCES.value, "HR One")
        _, pl_staff = self._staff(EdifyRole.COUNTRY_PROGRAM_LEAD.value, "PL One")
        for staff in (rvp_staff, cd_staff, hr_staff, pl_staff):
            self._schedule(staff)

        self.assertEqual(self._visible_owner_ids(rvp), {rvp_staff.id})
