"""Scheduled cluster meetings appear in My Plan (owner brief, 2026-09-15).

What was broken, each pinned below:

* My Plan's fiscal-year select was hard-coded to FY2023–FY2026, so a meeting
  planned now for October 2026 (FY2027) had no year to be shown under.
* The Clusters page drawer created meetings with no catalogue item, and left
  the planner on the Clusters page — a meeting in a future week looked unsaved.
* A cluster whose owner was stored as a User id passed that id on as the
  meeting's owner.
* The Special Projects My Plan listed staff visits and trainings only, so a
  project cluster meeting fell out of the page.
"""

from __future__ import annotations

import datetime
from urllib.parse import parse_qs, urlsplit

from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.governance_service import carry_forward_rate_card
from apps.budget.reference import ensure_active_catalogue, ensure_cost_reference
from apps.clusters.models import Cluster
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _schedulable_date,
)


def _month_query(day):
    """The My Plan filter a just-saved activity opens on.

    The week — and the week view it opened — is gone: My Plan filters by FY,
    quarter and month now, and groups its rows by month (owner, 2026-09-17).
    """
    return {
        "fy": "2027" if day >= datetime.date(2026, 10, 1) else "2026",
        "month": str(day.month),
        "period": "month",
    }


class ClusterMeetingInMyPlanTest(StandardSupportBase):
    def setUp(self):
        ensure_cost_reference(ensure_active_catalogue())
        # The cluster belongs to the CCEO, stored as a User id — the shape the
        # cluster edit drawer writes.
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.user.id
        )
        self.cluster.refresh_from_db()
        self.client.force_login(self.user)

    def _schedule(self, day):
        before = set(Activity.objects.values_list("id", flat=True))
        response = self.client.post(
            "/clusters/schedule-activity",
            {
                "cluster_id": self.cluster.id,
                "activity_type": "meeting",
                "purpose": "Termly cluster meeting",
                "scheduled_date": day.isoformat(),
                "responsible_staff_id": self.cluster.responsible_staff_id,
                "participants_per_school": "2",
            },
            HTTP_HX_REQUEST="true",
        )
        created = Activity.objects.exclude(id__in=before).get(
            activity_type="cluster_meeting"
        )
        return response, created

    def _my_plan_meeting_ids(self, day):
        from apps.my_plan.services import get_frontend_context

        context = get_frontend_context(self.user, _month_query(day))
        return {row["id"] for row in context["cluster_meetings_all"]}

    def test_a_scheduled_meeting_is_costed_owned_and_in_my_plan(self):
        day = _schedulable_date()
        response, meeting = self._schedule(day)
        self.assertEqual(response.status_code, 200)
        # Lands on the month it sits in.
        body = response.content.decode()
        self.assertIn("/my-plan?", body)
        url = body.split('window.location.href = "')[1].split('"')[0]
        query = parse_qs(urlsplit(url.replace("&amp;", "&")).query)
        self.assertEqual(query["month"], [_month_query(day)["month"]])
        self.assertEqual(query["period"], ["month"])
        self.assertNotIn("week", query)
        # Governed and owned once, by the StaffProfile id.
        self.assertIsNotNone(meeting.catalogue_item_id)
        self.assertEqual(meeting.catalogue_item.workflow_kind, "cluster_meeting")
        self.assertTrue(meeting.costing_profile_snapshot)
        self.assertEqual(meeting.responsible_staff_id, self.staff.id)
        self.assertEqual(meeting.status, "scheduled")
        self.assertIn(meeting.id, self._my_plan_meeting_ids(day))
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(activity=meeting).exists()
        )

    def test_rescheduling_moves_the_period_without_duplicating_cost(self):
        """It moved the WEEK until 2026-09-17, when the week view was retired.

        A month is the narrowest period My Plan now filters on, so the move
        has to cross one for "it left the old plan and joined the new" to be
        observable at all. The cost half of this test is unchanged and is the
        half that matters: re-priced in place, never duplicated.
        """
        from apps.activities.services import reschedule

        day = _schedulable_date()
        _response, meeting = self._schedule(day)
        lines_before = ActivityScheduleCostLine.objects.filter(activity=meeting).count()
        later = day + datetime.timedelta(days=35)
        if later.weekday() == 6:
            later += datetime.timedelta(days=1)
        reschedule(
            meeting.id,
            {"scheduledDate": later.isoformat(), "reason": "Venue moved"},
            self.user,
        )
        meeting.refresh_from_db()
        self.assertEqual(meeting.planned_date, later)
        self.assertIn(meeting.id, self._my_plan_meeting_ids(later))
        self.assertNotIn(meeting.id, self._my_plan_meeting_ids(day))
        # Re-priced in place: the same number of lines, all on the new date.
        lines = ActivityScheduleCostLine.objects.filter(activity=meeting)
        self.assertEqual(lines.count(), lines_before)
        self.assertEqual(set(lines.values_list("planned_date", flat=True)), {later})

    def test_a_cancelled_meeting_leaves_my_plan(self):
        day = _schedulable_date()
        _response, meeting = self._schedule(day)
        Activity.objects.filter(id=meeting.id).update(status="cancelled")
        self.assertNotIn(meeting.id, self._my_plan_meeting_ids(day))

    def test_an_october_2026_meeting_is_in_the_fy2027_my_plan(self):
        from apps.accounts.models import User
        from apps.my_plan.services import get_frontend_context

        cd = User.objects.create_user(
            email="cm-cd@edify.org",
            name="CM CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
        )
        carry_forward_rate_card(cd, "2027")
        october = datetime.date(2026, 10, 6)
        _response, meeting = self._schedule(october)
        self.assertEqual(meeting.fy, "2027")
        context = get_frontend_context(self.user, _month_query(october))
        self.assertIn("2027", context["fy_options"])
        self.assertIn(meeting.id, {r["id"] for r in context["cluster_meetings_all"]})
        page = self.client.get(
            "/my-plan?fy=2027&month=10&period=month", HTTP_HX_REQUEST="true"
        )
        self.assertContains(page, 'value="2027" selected')

    def test_a_next_year_meeting_may_be_started_when_it_happens(self):
        """The fiscal year no longer gates delivery.

        This pinned the opposite until 2026-09-17: starting an FY2027 meeting
        before 1 October 2026 was refused. Planning forward was already
        allowed, so the rule's only effect was that a team who had entered the
        term ahead could not act on it — the same wall, one step later. Lifted
        on the owner's instruction, "can you make sure all restrictions are
        lifted throughout the platform".
        """
        from apps.activities.services import start_completion

        meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy="2027",
            quarter="Q1",
            planned_date=datetime.date(2026, 10, 6),
            scheduled_date=timezone.make_aware(datetime.datetime(2026, 10, 6, 9)),
            status="scheduled",
            responsible_staff_id=self.staff.id,
            delivery_type="staff",
        )
        start_completion(meeting.id, {}, self.user)
        meeting.refresh_from_db()
        self.assertNotEqual(meeting.status, "scheduled")


class ProjectMyPlanListsClusterMeetingsTest(StandardSupportBase):
    def test_a_staff_project_cluster_meeting_is_listed(self):
        from apps.accounts.models import StaffProfile, User
        from apps.projects.models import Project
        from apps.projects.my_plan_service import get_my_plan

        coordinator = User.objects.create_user(
            email="cm-pc@edify.org",
            name="CM Coordinator",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
            password="x",
        )
        profile = StaffProfile.objects.create(user=coordinator, country="Uganda")
        project = Project.objects.create(
            name="Cluster Meetings Project",
            category="pilot",
            status="active",
            manager_staff_id=profile.id,
        )
        day = _schedulable_date()
        meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            project_id=project.id,
            fy="2026" if day < datetime.date(2026, 10, 1) else "2027",
            quarter="Q4",
            planned_date=day,
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
            status="scheduled",
            responsible_staff_id=profile.id,
            delivery_type="staff",
        )
        data = get_my_plan(
            coordinator,
            {"fy": meeting.fy, "period": "fy"},
        )
        self.assertIn(meeting.id, {row["id"] for row in data["meetings"]})


class ClusterMeetingEntryPointsTest(StandardSupportBase):
    """The two doors into cluster scheduling, both of which led nowhere.

    * The cluster's own page offered "Schedule Cluster Meeting" and "Schedule
      Group Training" pointing at `/planning` — the dashboard, which reads
      neither `action` nor `cluster`. The planner got a list of schools.
    * `/planning/schedule` rendered the form, but its submit posted back to
      that same GET-only view, which answered with the form again. Nothing was
      recorded, and nothing said so.
    """

    def setUp(self):
        ensure_cost_reference(ensure_active_catalogue())
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.staff.id
        )
        self.cluster.refresh_from_db()
        self.client.force_login(self.user)

    def test_the_cluster_page_links_to_the_scheduling_surface(self):
        page = self.client.get(f"/clusters/{self.cluster.id}")
        body = page.content.decode()
        self.assertIn(
            f"/planning/schedule?action=meeting&cluster={self.cluster.id}", body
        )
        self.assertIn(
            f"/planning/schedule?action=training&cluster={self.cluster.id}", body
        )
        # And never at the dashboard, which cannot act on either parameter.
        self.assertNotIn(f'"/planning?action=meeting&cluster={self.cluster.id}"', body)

    def test_the_schedule_page_form_posts_to_the_action(self):
        page = self.client.get(
            f"/planning/schedule?action=meeting&cluster={self.cluster.id}"
        )
        body = page.content.decode()
        self.assertIn('hx-post="/planning/schedule-action"', body)
        # The costing preview still runs, but it no longer owns the form.
        self.assertIn('hx-post="/partials/costing/preview"', body)
        self.assertNotIn('hx-post="/planning/schedule?action=meeting"', body)
        # The cluster arrives preselected, so the planner does not re-pick it.
        self.assertIn(f'value="{self.cluster.id}" selected', body)

    def test_scheduling_from_that_page_records_the_meeting(self):
        day = _schedulable_date()
        before = set(Activity.objects.values_list("id", flat=True))
        response = self.client.post(
            "/planning/schedule-action",
            {
                # Exactly the field names the page's form sends.
                "activity_type": "cluster_meeting",
                "cluster_id": self.cluster.id,
                "scheduled_date": day.isoformat(),
                "purpose_type": "planning_meeting",
                "expected_participants": "18",
                "activity_purpose_text": "Termly planning meeting.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("/my-plan?", response.content.decode())
        meeting = Activity.objects.exclude(id__in=before).get(
            activity_type="cluster_meeting"
        )
        self.assertEqual(meeting.status, "scheduled")
        self.assertEqual(meeting.responsible_staff_id, self.staff.id)
        self.assertIsNotNone(meeting.catalogue_item_id)
        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(activity=meeting).exists()
        )
