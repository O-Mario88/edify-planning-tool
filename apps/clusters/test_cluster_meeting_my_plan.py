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


def _week_query(day):
    return {
        "fy": "2027" if day >= datetime.date(2026, 10, 1) else "2026",
        "month": str(day.month),
        "week": str(min(5, (day.day - 1) // 7 + 1)),
        "period": "week",
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

        context = get_frontend_context(self.user, _week_query(day))
        return {row["id"] for row in context["cluster_meetings_all"]}

    def test_a_scheduled_meeting_is_costed_owned_and_in_my_plan(self):
        day = _schedulable_date()
        response, meeting = self._schedule(day)
        self.assertEqual(response.status_code, 200)
        # Lands on the week it sits in.
        body = response.content.decode()
        self.assertIn("/my-plan?", body)
        url = body.split('window.location.href = "')[1].split('"')[0]
        query = parse_qs(urlsplit(url.replace("&amp;", "&")).query)
        self.assertEqual(query["week"], [_week_query(day)["week"]])
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

    def test_rescheduling_moves_the_week_without_duplicating_cost(self):
        from apps.activities.services import reschedule

        day = _schedulable_date()
        _response, meeting = self._schedule(day)
        lines_before = ActivityScheduleCostLine.objects.filter(activity=meeting).count()
        later = day + datetime.timedelta(days=7)
        if later.weekday() == 6:
            later += datetime.timedelta(days=1)
        if later.month != day.month and later >= datetime.date(2026, 10, 1) > day:
            self.skipTest("A week later crosses into FY2027 on this clock.")
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
        context = get_frontend_context(self.user, _week_query(october))
        self.assertIn("2027", context["fy_options"])
        self.assertIn(meeting.id, {r["id"] for r in context["cluster_meetings_all"]})
        page = self.client.get(
            "/my-plan?fy=2027&month=10&week=1&period=week", HTTP_HX_REQUEST="true"
        )
        self.assertContains(page, 'value="2027" selected')

    def test_fy2027_meeting_cannot_start_before_october(self):
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
        if timezone.localdate() >= datetime.date(2026, 10, 1):
            self.skipTest("FY2027 has started on this clock.")
        from apps.core.exceptions import BadRequest

        with self.assertRaisesMessage(BadRequest, "1 October 2026"):
            start_completion(meeting.id, {}, self.user)


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
