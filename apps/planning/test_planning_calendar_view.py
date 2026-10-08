"""Planning's Calendar View: the reader's own dated work, named and scoped.

The Calendar View of the Scheduled tab was built from a query of its own. It
narrowed a CCEO to their own work and gave every other role the whole
country's year, written into the page; it listed six statuses by hand, so an
activity that had been rescheduled vanished from it; it titled each entry
with the raw type code ("School_Visit"); and it wrote its JSON through the
template, so a school with an apostrophe in its name arrived as an HTML
entity.

It now reads the rule the Calendar page reads
(apps.activities.calendar_scope): a calendar is personal (owner, 2026-08-20).
What is pinned here is whose work is on it, which work, how it is named and
dated, and what a click on an entry opens.
"""

from __future__ import annotations

import datetime
import html
import json
import re

from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.calendar_scope import OFF_CALENDAR_STATUSES, planning_events
from apps.activities.models import Activity
from apps.activities.test_profile_activities import (
    PASSWORD,
    ProfileActivitiesFixture,
)
from apps.core.fy import get_operational_fy
from apps.schools.models import School


class CalendarFixture(ProfileActivitiesFixture):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _events(self, user=None) -> dict[str, dict]:
        return {e["id"]: e for e in planning_events(user or self.cceo, self.fy)}

    def _in(self, days: int) -> datetime.date:
        """A day in the fixture's financial year, `days` from today."""
        day = self.today + datetime.timedelta(days)
        return day if get_operational_fy(day) == self.fy else self.today


class WhoseWorkIsOnIt(CalendarFixture):
    def test_the_officers_own_work_is_on_it(self):
        events = self._events()

        for activity in (self.planned, self.overdue, self.session):
            self.assertIn(activity.id, events)

    def test_work_written_under_the_user_id_is_still_theirs(self):
        """Ownership is written under two ids (apps.core.scoping.owner_ids)."""
        legacy = self._activity(school=self.school, status="scheduled", day=self._in(3))
        Activity.objects.filter(id=legacy.id).update(
            responsible_staff_id=str(self.cceo.id)
        )

        self.assertIn(legacy.id, self._events())

    def test_a_program_lead_is_given_their_own_plan_not_the_teams(self):
        own = self._activity(school=self.other, status="scheduled", day=self._in(4))
        Activity.objects.filter(id=own.id).update(
            responsible_staff_id=str(self.pl_staff.id)
        )

        events = self._events(self.pl)

        self.assertEqual(set(events), {own.id})

    def test_another_officers_work_is_not_on_it(self):
        other_user = User.objects.create_user(
            email="calendar-other@edify.test",
            password=PASSWORD,
            name="Other Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        other_staff = StaffProfile.objects.create(
            user=other_user, staff_number="ST-CALENDAR-OTHER", country="Uganda"
        )
        theirs = self._activity(school=self.other, status="scheduled", day=self._in(4))
        Activity.objects.filter(id=theirs.id).update(
            responsible_staff_id=str(other_staff.id)
        )

        self.assertNotIn(theirs.id, self._events())
        self.assertEqual(set(self._events(other_user)), {theirs.id})

    def test_partner_work_they_monitor_is_on_it(self):
        """A partner's activity has no responsible staff: it is reached
        through the staff member who monitors it."""
        Activity.objects.filter(id=self.partner_work.id).update(
            responsible_staff_id=None, monitored_by_staff_id=str(self.cceo_staff.id)
        )

        events = self._events()

        self.assertIn(self.partner_work.id, events)
        self.assertFalse(events[self.partner_work.id]["extendedProps"]["reschedule"])


class WhichWorkIsOnIt(CalendarFixture):
    def test_a_rescheduled_activity_stays_on_it(self):
        """The regression this exists for: `rescheduled` was not among the
        six statuses the old query named."""
        moved = self._activity(
            school=self.school, status="rescheduled", day=self._in(6)
        )

        self.assertIn(moved.id, self._events())

    def test_work_is_on_it_whatever_stage_it_has_reached(self):
        stages = [
            self._activity(school=self.school, status=status, day=self._in(-1))
            for status in (
                "completion_started",
                "submitted_to_pl",
                "returned_by_pl",
                "awaiting_ia_verification",
                "ia_verified",
                "closed",
                "deferred",
            )
        ]

        events = self._events()

        for activity in stages:
            with self.subTest(status=activity.status):
                self.assertIn(activity.id, events)

    def test_called_off_and_unapproved_work_is_not(self):
        waiting = self._activity(
            school=self.school, status="awaiting_owner_approval", day=self._in(8)
        )
        rejected = self._activity(
            school=self.school, status="rejected", day=self._in(8)
        )

        events = self._events()

        for activity in (self.cancelled, waiting, rejected):
            self.assertNotIn(activity.id, events)
        self.assertEqual(
            set(OFF_CALENDAR_STATUSES),
            {"cancelled", "rejected", "awaiting_owner_approval"},
        )

    def test_work_with_no_date_yet_is_left_off(self):
        undated = Activity.objects.create(
            activity_type="school_visit",
            status="assigned_to_partner",
            fy=self.fy,
            school=self.school,
            responsible_staff_id=str(self.cceo_staff.id),
        )

        self.assertNotIn(undated.id, self._events())

    def test_another_years_work_is_not_on_this_years_calendar(self):
        last_year = self._activity(
            school=self.school,
            status="ia_verified",
            day=self.today - datetime.timedelta(days=400),
        )

        self.assertNotEqual(last_year.fy, self.fy)
        self.assertNotIn(last_year.id, self._events())


class HowAnEntryReads(CalendarFixture):
    def test_an_entry_is_named_not_coded(self):
        events = self._events()

        self.assertEqual(
            events[self.planned.id]["title"], f"School Visit @ {self.school.name}"
        )
        self.assertEqual(
            events[self.session.id]["title"], f"Cluster Meeting @ {self.cluster.name}"
        )
        for event in events.values():
            self.assertNotIn("_", event["title"])
            self.assertNotIn("_", event["extendedProps"]["activity_type"])

    def test_the_name_it_was_scheduled_under_comes_first(self):
        Activity.objects.filter(id=self.planned.id).update(
            activity_name_snapshot="Leadership Coaching Visit"
        )

        self.assertEqual(
            self._events()[self.planned.id]["title"],
            f"Leadership Coaching Visit @ {self.school.name}",
        )

    def test_it_is_drawn_on_its_own_day_in_the_countrys_time(self):
        """`scheduled_date` is a local midnight stored in UTC: its UTC day is
        the day before (calendar audit, 2026-10-02)."""
        day = self._in(5)
        local_midnight = timezone.make_aware(
            datetime.datetime.combine(day, datetime.time.min),
            timezone.get_current_timezone(),
        )
        Activity.objects.filter(id=self.planned.id).update(
            scheduled_date=local_midnight, planned_date=day
        )

        self.assertEqual(self._events()[self.planned.id]["start"], day.isoformat())

    def test_work_of_several_days_ends_the_day_after_its_last(self):
        start = self.planned.planned_date
        Activity.objects.filter(id=self.planned.id).update(
            end_date=start + datetime.timedelta(days=2)
        )

        event = self._events()[self.planned.id]

        self.assertEqual(event["end"], (start + datetime.timedelta(days=3)).isoformat())
        self.assertNotIn("end", self._events()[self.overdue.id])

    def test_finished_work_is_coloured_finished_and_carries_no_tick(self):
        verified = self._activity(
            school=self.school, status="ia_verified", day=self._in(-1)
        )

        event = self._events()[verified.id]

        self.assertEqual(event["classNames"], ["fc-event-completed"])
        self.assertFalse(event["extendedProps"]["pick"])
        self.assertFalse(event["extendedProps"]["reschedule"])

    def test_live_work_of_their_own_is_ticked_and_opens_reschedule(self):
        event = self._events()[self.planned.id]

        self.assertEqual(event["classNames"], ["fc-event-planned"])
        self.assertTrue(event["extendedProps"]["pick"])
        self.assertTrue(event["extendedProps"]["reschedule"])

    def test_work_already_delivered_opens_its_own_record(self):
        delivered = self._activity(
            school=self.school, status="submitted_to_pl", day=self._in(-1)
        )

        self.assertFalse(self._events()[delivered.id]["extendedProps"]["reschedule"])

    def test_work_started_and_never_submitted_still_opens_reschedule(self):
        """Opening Complete and leaving it is not delivering (owner,
        2026-10-07)."""
        begun = self._activity(
            school=self.school, status="completion_started", day=self._in(-1)
        )

        self.assertTrue(self._events()[begun.id]["extendedProps"]["reschedule"])


class ThePage(CalendarFixture):
    URL = "/planning"

    def _page_events(self, user):
        self.client.login(email=user.email, password=PASSWORD)
        response = self.client.get(self.URL, {"tab": "scheduled", "fy": self.fy})
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        found = re.search(
            r'<script id="calendar-events-data" type="application/json">(.*?)</script>',
            body,
            re.S,
        )
        self.assertIsNotNone(found, "the Calendar View's data is not on the page")
        return body, found.group(1), json.loads(found.group(1))

    def test_a_schools_name_reaches_the_page_whole(self):
        awkward = School.objects.create(
            school_id="PROFILE-QUOTE",
            name='St. Mary\'s "Model" Primary & Nursery <A>',
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=self.cceo_staff.id,
        )
        visit = self._activity(school=awkward, status="scheduled", day=self._in(3))

        _body, raw, events = self._page_events(self.cceo)

        by_id = {event["id"]: event for event in events}
        self.assertEqual(by_id[visit.id]["title"], f"School Visit @ {awkward.name}")
        self.assertEqual(by_id[visit.id]["extendedProps"]["school"], awkward.name)
        # Nothing to unescape: it came through a JSON encoder, not as HTML.
        self.assertEqual(html.unescape(raw), raw)
        self.assertNotIn("</script", raw.lower())

    def test_the_page_carries_the_same_events_the_rule_gives(self):
        _body, _raw, events = self._page_events(self.cceo)

        self.assertEqual({e["id"] for e in events}, set(self._events()))

    def test_a_program_lead_is_not_handed_the_countrys_year(self):
        _body, _raw, events = self._page_events(self.pl)

        on_page = {event["id"] for event in events}
        for activity in (self.planned, self.overdue, self.session):
            self.assertNotIn(activity.id, on_page)

    def test_a_click_opens_the_door_that_fits_the_entry(self):
        body, _raw, _events = self._page_events(self.cceo)

        self.assertIn(
            "info.event.extendedProps.reschedule ? '/reschedule-drawer' : ''", body
        )

    def test_another_tab_carries_no_calendar_data(self):
        self.client.login(email=self.cceo.email, password=PASSWORD)

        response = self.client.get(self.URL, {"tab": "client", "fy": self.fy})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "calendar-events-data")
