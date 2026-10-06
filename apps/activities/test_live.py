"""Open pages hear when the plan changes (owner, 2026-10-05).

"This should happen in real time ... Every event should update (schedules,
school withdrawal from the partner or project, training schedules, activity
completion etc) should update in real time and fast."

What is pinned here: which records announce a change, who is told, that one
commit tells each person once, that nothing is sent before the change
commits, and that the pages that show the plan are marked to read themselves
again.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.activities import live
from apps.activities.test_profile_activities import PASSWORD, ProfileActivitiesFixture

TEMPLATES = settings.BASE_DIR / "templates"


class LiveFixture(ProfileActivitiesFixture):
    def setUp(self):
        super().setUp()
        live.reset()
        self.partner_user = User.objects.create_user(
            email="live-partner@edify.org",
            name="Live Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            password=PASSWORD,
            is_active=True,
        )
        self.partner.user = self.partner_user
        self.partner.save(update_fields=["user"])
        self.director = User.objects.create_user(
            email="live-cd@edify.org",
            name="Live Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password=PASSWORD,
            is_active=True,
        )
        self.stranger = User.objects.create_user(
            email="live-stranger@edify.org",
            name="Live Stranger",
            roles=["CCEO"],
            active_role="CCEO",
            password=PASSWORD,
            is_active=True,
        )

    def _told(self, publish) -> set[str]:
        """Who was sent ``plan.changed``. Notifications ride the same bus
        under their own names and are not counted."""
        told: set[str] = set()
        for call in publish.call_args_list:
            users, event = call.args
            if event["type"] != live.EVENT:
                continue
            # Nothing of anyone's work travels in the event.
            self.assertEqual(set(event), {"type", "at"})
            told.update(users)
        return told


class WhoIsTold(LiveFixture):
    def test_the_owner_their_lead_the_partner_and_the_country_readers(self):
        told = live.audience(
            staff_ids=(self.partner_work.responsible_staff_id,),
            school_id=self.partner_work.school_id,
            partner_ids=(self.partner.id,),
        )

        self.assertIn(str(self.cceo.id), told)
        self.assertIn(str(self.pl.id), told)
        self.assertIn(str(self.partner_user.id), told)
        self.assertIn(str(self.director.id), told)
        self.assertNotIn(str(self.stranger.id), told)

    def test_the_holder_of_the_school_is_told_of_somebody_elses_work_there(self):
        told = live.audience(staff_ids=(), school_id=self.school.id)

        self.assertIn(str(self.cceo.id), told)

    def test_a_cluster_session_reaches_whoever_holds_the_cluster(self):
        told = live.audience(staff_ids=(), cluster_id=self.cluster.id)

        self.assertIn(str(self.cceo.id), told)
        self.assertIn(str(self.pl.id), told)


@override_settings(LIVE_UPDATES_ENABLED=True)
class WhatAnnouncesItself(LiveFixture):
    def test_a_saved_activity_tells_its_people_once_it_commits(self):
        new_day = timezone.localdate() + datetime.timedelta(days=12)
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                self.planned.planned_date = new_day
                self.planned.save(update_fields=["planned_date"])
                # Nothing leaves before the change is committed.
                publish.assert_not_called()

        told = self._told(publish)
        self.assertIn(str(self.cceo.id), told)
        self.assertIn(str(self.pl.id), told)
        self.assertNotIn(str(self.stranger.id), told)

    def test_one_commit_of_many_saves_tells_each_person_once(self):
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                for activity in (self.planned, self.overdue, self.session):
                    activity.save()
                    activity.save()

        counts: dict[str, int] = {}
        for call in publish.call_args_list:
            if call.args[1]["type"] != live.EVENT:
                continue
            for user in call.args[0]:
                counts[user] = counts.get(user, 0) + 1
        self.assertEqual(counts[str(self.cceo.id)], 1)
        self.assertEqual(counts[str(self.pl.id)], 1)

    def test_a_hand_over_to_a_partner_and_its_withdrawal_announce(self):
        from apps.partners.models import PartnerAssignment

        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                assignment = PartnerAssignment.objects.create(
                    school=self.other,
                    partner=self.partner,
                    assigning_staff_id=str(self.cceo_staff.id),
                )
        told = self._told(publish)
        self.assertIn(str(self.partner_user.id), told)
        self.assertIn(str(self.cceo.id), told)

        live.reset()
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                assignment.delete()
        self.assertIn(str(self.partner_user.id), self._told(publish))

    def test_a_school_joining_or_leaving_a_project_announces(self):
        from apps.projects.models import Project, ProjectSchoolAssignment

        project = Project.objects.create(
            name="Live Project", manager_staff_id=str(self.pl_staff.id)
        )
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                enrolment = ProjectSchoolAssignment.objects.create(
                    project=project, school=self.other
                )
        told = self._told(publish)
        self.assertIn(str(self.cceo.id), told)
        self.assertIn(str(self.pl.id), told)

        live.reset()
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                enrolment.delete()
        self.assertIn(str(self.cceo.id), self._told(publish))

    def test_a_returning_reader_is_told_something_changed_while_away(self):
        with patch("apps.realtime.bus.bus.publish_many"):
            with self.captureOnCommitCallbacks(execute=True):
                self.planned.save()

        self.assertTrue(live.last_change(str(self.cceo.id)))
        self.assertIsNone(live.last_change(str(self.stranger.id)))

    def test_a_stream_that_cannot_be_reached_does_not_undo_the_change(self):
        new_day = timezone.localdate() + datetime.timedelta(days=13)
        with patch(
            "apps.realtime.bus.bus.publish_many", side_effect=RuntimeError("down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.planned.planned_date = new_day
                self.planned.save(update_fields=["planned_date"])

        self.planned.refresh_from_db()
        self.assertEqual(self.planned.planned_date, new_day)


class OffUnderTheTestRunner(LiveFixture):
    def test_nothing_is_announced_unless_a_test_turns_it_on(self):
        """Its queries would be counted against every query budget in the
        suite (config.settings.base.LIVE_UPDATES_ENABLED)."""
        self.assertFalse(settings.LIVE_UPDATES_ENABLED)
        with patch("apps.realtime.bus.bus.publish_many") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                self.planned.save()

        self.assertEqual(self._told(publish), set())


class LiveRegionsContract(SimpleTestCase):
    """The pages that show the plan are marked to read themselves again."""

    REGIONS = {
        "pages/my_plan/index.html": 'id="my-plan-workspace"',
        "partials/dashboards/what_needs_you_now.html": 'id="what-needs-you-now"',
        "partials/dashboards/cceo/this_week.html": 'id="pl-week-panel"',
        "partials/dashboards/pl/week_view.html": 'id="pl-week-panel"',
        "pages/calendar/index.html": 'id="calendar-workspace"',
        "pages/work_plan/index.html": 'id="work-plan-detail"',
        "partials/work_plan/plan_summary.html": 'id="work-plan-summary"',
        "partials/components/profile_activities.html": 'id="{{ acts.param }}-activities"',
        "pages/partner/my_plan.html": 'id="partner-plan"',
        "partials/planning/school_table.html": 'id="schools-table-container"',
        "pages/core_schools/index.html": 'id="core-schools-table-container"',
        "pages/oversight/planning_monitor.html": 'id="oversight-workspace"',
        "pages/oversight/team_planning.html": 'id="oversight-workspace"',
        "pages/oversight/country_planning.html": 'id="oversight-workspace"',
        "pages/oversight/partner_oversight.html": 'id="partner-workspace"',
        "pages/oversight/cluster_oversight.html": 'id="cluster-workspace"',
        "pages/oversight/core_schools_oversight.html": 'id="core-workspace"',
    }

    def test_each_region_has_its_id_and_its_mark(self):
        for name, ident in self.REGIONS.items():
            with self.subTest(template=name):
                text = (TEMPLATES / name).read_text()
                start = text.index(ident)
                tag_start = text.rindex("<", 0, start)
                tag = text[tag_start : text.index(">", start)]
                self.assertIn("data-live-region", tag)

    def test_the_listener_is_loaded_by_the_shell_and_names_the_event(self):
        self.assertIn("js/live-regions.js", (TEMPLATES / "base.html").read_text())
        script = (settings.BASE_DIR / "static/js/live-regions.js").read_text()
        self.assertIn(f"'{live.EVENT}'", script)
        self.assertIn("/api/realtime/stream", script)

    def test_the_stream_says_on_connecting_when_the_plan_last_changed(self):
        view = (settings.BASE_DIR / "apps/realtime/views.py").read_text()
        self.assertIn('"changed": changed', view)
