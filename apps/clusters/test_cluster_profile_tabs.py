"""The cluster profile's tabs: SSA Movement, Attendance, Membership History.

Owner brief, 2026-10-08 (Cluster Management): the cluster profile becomes a
set of tabs over records the platform already keeps, and "every number should
drill into the underlying data". Three things are held here:

* attendance is the session register and nothing else — a school is invited
  only where an invitation is recorded, a delivered session nobody was ticked
  at counts against no school, and "missed in a row" runs across the year
  boundary;
* SSA movement uses the platform's one definition of improved and declined
  (apps.ssa.change_rules), compares a school only where it has a confirmed SSA
  in both years, and every count names its schools;
* the Overview is the page as it was, and a tab does not build the Overview's
  roster.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from django.test import TestCase

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters import profile_insights as insights
from apps.clusters.models import Cluster, SchoolClusterMembership
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa import change_rules
from apps.ssa.models import SsaRecord, SsaScore


class _ClusterCase(TestCase):
    def setUp(self):
        self.cd = _create_user("cd@profile-tabs.test", EdifyRole.COUNTRY_DIRECTOR)
        self.region = Region.objects.create(name="Tabs region")
        self.district = District.objects.create(
            name="Tabs district", region=self.region
        )
        self.cluster = Cluster.objects.create(
            name="Tabs cluster", region=self.region, district=self.district
        )
        self.fy = get_operational_fy()
        self.last_fy = str(int(self.fy) - 1)

    def _school(self, n: int, **kw) -> School:
        return School.objects.create(
            name=f"Tabs school {n}",
            school_id=f"TAB-{n:03d}",
            region=self.region,
            district=self.district,
            cluster_id=str(self.cluster.id),
            **kw,
        )

    def _page(self, **query):
        """The Cluster Profile at a tab; with no tab, the Cluster Page."""
        self.client.force_login(self.cd)
        path = f"/clusters/{self.cluster.id}" + ("/profile" if query else "")
        response = self.client.get(path, query)
        self.assertEqual(response.status_code, 200)
        return response


class AttendanceTest(_ClusterCase):
    def setUp(self):
        super().setUp()
        self.schools = [self._school(n) for n in range(4)]

    def _session(
        self, day, *, fy=None, invited=(), came=(), status="ia_verified", kind=None
    ):
        session = Activity.objects.create(
            activity_type=kind or "cluster_meeting",
            cluster=self.cluster,
            fy=fy or self.fy,
            planned_date=day,
            status=status,
        )
        for school in set(invited) | set(came):
            ClusterActivityAttendance.objects.create(
                activity=session,
                school=school,
                invited=school in invited,
                attended=school in came,
                teachers=3 if school in came else None,
                leaders=1 if school in came else None,
            )
        return session

    def _rows(self, **kw):
        data = insights.cluster_attendance(self.cluster, fy=kw.pop("fy", self.fy))
        return data, {row.code: row for row in data["schools"]}

    def test_a_school_counts_its_invitations_and_the_ones_it_kept(self):
        a, b, c, _d = self.schools
        start = date(int(self.fy) - 1, 10, 10)
        self._session(start, invited=[a, b, c], came=[a, b])
        self._session(start.replace(day=20), invited=[a, b, c], came=[a])

        data, rows = self._rows()

        self.assertEqual((rows["TAB-000"].invited, rows["TAB-000"].attended), (2, 2))
        self.assertEqual(rows["TAB-000"].rate, 100)
        self.assertEqual((rows["TAB-001"].invited, rows["TAB-001"].attended), (2, 1))
        self.assertEqual(rows["TAB-001"].rate, 50)
        self.assertEqual(rows["TAB-001"].missed_in_a_row, 1)
        self.assertEqual(rows["TAB-001"].last_attended, start)
        # Invited twice, came to neither.
        self.assertEqual((rows["TAB-002"].invited, rows["TAB-002"].attended), (2, 0))
        self.assertIsNone(rows["TAB-002"].last_attended)
        self.assertEqual([s.code for s in data["never"]], ["TAB-002"])
        # A member nobody invited is not charged with a session.
        self.assertEqual(rows["TAB-003"].invited, 0)
        self.assertIsNone(rows["TAB-003"].rate)
        self.assertEqual(rows["TAB-003"].standing[0], "Not invited")
        # 3 of 6 invitations kept; two of four schools were in a room.
        self.assertEqual(data["rate"], 50)
        self.assertEqual(data["represented"], 2)
        self.assertEqual(rows["TAB-000"].teachers, 6)
        self.assertEqual(rows["TAB-000"].leaders, 2)

    def test_misses_in_a_row_run_across_the_year_and_name_the_school(self):
        """A school that stopped coming in August has not started again on
        1 October: two misses last year and one this year are three."""
        a, b, *_ = self.schools
        last_year = date(int(self.last_fy), 8, 5)
        self._session(
            date(int(self.last_fy), 6, 2), fy=self.last_fy, invited=[a, b], came=[a, b]
        )
        self._session(last_year, fy=self.last_fy, invited=[a, b], came=[a])
        self._session(
            last_year.replace(day=25), fy=self.last_fy, invited=[a, b], came=[a]
        )
        self._session(date(int(self.fy) - 1, 10, 6), invited=[a, b], came=[a])

        data, rows = self._rows()

        drifting = rows["TAB-001"]
        self.assertEqual(drifting.missed_in_a_row, 3)
        self.assertTrue(drifting.is_drifting)
        self.assertEqual(drifting.standing, ("Missed 3 in a row", "danger"))
        self.assertEqual(drifting.last_attended, date(int(self.last_fy), 6, 2))
        # The year's own columns stay the year's: one invitation, not kept.
        self.assertEqual((drifting.invited, drifting.attended), (1, 0))
        self.assertEqual([s.code for s in data["drifting"]], ["TAB-001"])
        self.assertEqual(rows["TAB-000"].missed_in_a_row, 0)
        # Sessions Held lists this year's; the count of every year is kept.
        self.assertEqual(len(data["sessions"]), 1)
        self.assertEqual(data["sessions_all_years"], 4)

    def test_a_delivered_session_nobody_was_ticked_at_is_no_ones_absence(self):
        """Delivered with an invitation list and no tick is a register that
        was not taken, not an empty room."""
        a, b, *_ = self.schools
        self._session(date(int(self.fy) - 1, 10, 3), invited=[a, b], came=[])

        data, rows = self._rows()

        self.assertEqual(data["without_register"], 1)
        self.assertEqual(data["sessions"], [])
        self.assertEqual(rows["TAB-000"].invited, 0)
        self.assertEqual(rows["TAB-000"].missed_in_a_row, 0)

    def test_a_planned_or_cancelled_session_is_not_attendance(self):
        a, b, *_ = self.schools
        day = date(int(self.fy) - 1, 10, 9)
        self._session(day, invited=[a, b], status="scheduled")
        self._session(day, invited=[a, b], came=[a], status="cancelled")

        data, rows = self._rows()

        self.assertEqual(data["sessions"], [])
        self.assertEqual(data["without_register"], 0)
        self.assertEqual(rows["TAB-001"].invited, 0)

    def test_the_older_attendance_record_on_the_activity_counts(self):
        """Sessions completed before the register table wrote who came on the
        activity itself; those schools attended."""
        a, b, *_ = self.schools
        session = self._session(date(int(self.fy) - 1, 10, 4), invited=[a, b])
        session.attended_school_ids = [a.id]
        session.save(update_fields=["attended_school_ids"])

        data, rows = self._rows()

        self.assertEqual((rows["TAB-000"].invited, rows["TAB-000"].attended), (1, 1))
        self.assertEqual((rows["TAB-001"].invited, rows["TAB-001"].attended), (1, 0))
        self.assertEqual(data["sessions"][0].attended, 1)

    def test_a_training_is_named_by_its_course_and_a_meeting_by_its_kind(self):
        a, *_ = self.schools
        day = date(int(self.fy) - 1, 10, 7)
        self._session(day, invited=[a], came=[a], kind="cluster_training")
        self._session(day.replace(day=8), invited=[a], came=[a])

        sessions = insights.cluster_attendance(self.cluster, fy=self.fy)["sessions"]

        self.assertEqual(
            [(s.kind, s.name) for s in sessions],
            [
                ("Cluster Meeting", "Cluster Meeting"),
                ("Group Training", "Not yet named"),
            ],
        )

    def test_the_tab_shows_the_register_and_each_view_is_a_link(self):
        a, b, c, _d = self.schools
        self._session(
            date(int(self.last_fy), 8, 5), fy=self.last_fy, invited=[a, b], came=[a]
        )
        self._session(
            date(int(self.last_fy), 9, 5), fy=self.last_fy, invited=[a, b], came=[a]
        )
        self._session(date(int(self.fy) - 1, 10, 6), invited=[a, b, c], came=[a])

        body = self._page(tab="attendance").content.decode()

        self.assertIn('data-cluster-profile-panel="attendance"', body)
        self.assertIn("School Attendance, FY", body)
        for heading in (
            "School ID",
            "School Name",
            "Invited",
            "Attended",
            "Last Attended",
            "Consecutive Misses",
            "Standing",
        ):
            self.assertIn(f">{heading}</th>", body)
        self.assertIn("Missed 3 in a row", body)
        base = f"/clusters/{self.cluster.id}/profile?tab=attendance&amp;fy={self.fy}&amp;show="
        for view in insights.ATTENDANCE_VIEWS:
            self.assertIn(base + view, body)
        # The schools it lists link to their profiles.
        self.assertIn(f'href="/schools/{a.id}"', body)

        missing = self._page(tab="attendance", show="missing").content.decode()
        self.assertIn(f'data-attendance-school="{b.id}"', missing)
        self.assertNotIn(f'data-attendance-school="{a.id}"', missing)

        never = self._page(tab="attendance", show="never").content.decode()
        self.assertIn(f'data-attendance-school="{c.id}"', never)
        self.assertNotIn(f'data-attendance-school="{a.id}"', never)

        sessions = self._page(tab="attendance", show="sessions").content.decode()
        self.assertIn("Sessions Held, FY", sessions)
        self.assertEqual(sessions.count("data-attendance-session="), 1)


class SsaMovementTest(_ClusterCase):
    def setUp(self):
        super().setUp()
        self.up, self.down, self.same, self.new, self.none = (
            self._school(n) for n in range(5)
        )
        # Year on year, more than MIN_INTERVAL_DAYS apart.
        self._ssa(self.up, self.last_fy, {"leadership": 5.0, "financial_health": 4.0})
        self._ssa(self.up, self.fy, {"leadership": 7.0, "financial_health": 6.0})
        self._ssa(self.down, self.last_fy, {"leadership": 7.0, "financial_health": 6.0})
        self._ssa(self.down, self.fy, {"leadership": 5.0, "financial_health": 6.0})
        self._ssa(self.same, self.last_fy, {"leadership": 6.0})
        self._ssa(self.same, self.fy, {"leadership": 6.0})
        # Assessed for the first time this year: nothing to compare with.
        self._ssa(self.new, self.fy, {"leadership": 8.0})

    def _ssa(self, school, fy, scores, status="confirmed"):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=sum(scores.values()) / len(scores),
            verification_status=status,
            date_of_ssa=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
            uploaded_by="test",
        )
        for intervention, score in scores.items():
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=score
            )
        return record

    def _movement(self):
        movement = insights.cluster_ssa_movement(self.cluster, fy=self.fy)
        return movement, {area.key: area for area in movement["areas"]}

    def test_an_area_counts_its_schools_by_what_happened_to_them(self):
        movement, areas = self._movement()

        leadership = areas["leadership"]
        self.assertEqual(leadership.compared, 3)
        self.assertEqual(
            (leadership.improved, leadership.held, leadership.declined), (1, 1, 1)
        )
        # First-time and never-assessed schools are in no average.
        self.assertEqual(leadership.not_compared, 2)
        self.assertEqual((leadership.before, leadership.after), (6.0, 6.0))
        self.assertEqual(leadership.change, 0.0)

        finance = areas["financial_health"]
        self.assertEqual(finance.compared, 2)
        self.assertEqual((finance.improved, finance.held, finance.declined), (1, 1, 0))
        self.assertEqual(
            (finance.before, finance.after, finance.change), (5.0, 6.0, 1.0)
        )

        # An area nobody scored in both years says so rather than showing 0.
        unscored = areas["enrolment"]
        self.assertEqual(unscored.compared, 0)
        self.assertIsNone(unscored.change)
        self.assertEqual(unscored.not_compared, 5)

        self.assertEqual(movement["compared"], 3)
        self.assertEqual(movement["school_count"], 5)

    def test_the_overall_row_is_each_schools_own_verdict(self):
        """The platform's one definition: a school improved when its mean
        movement across the areas it can be compared on classifies so."""
        _movement, areas = self._movement()

        overall = areas[insights.OVERALL]
        self.assertEqual(overall.compared, 3)
        self.assertEqual((overall.improved, overall.held, overall.declined), (1, 1, 1))
        self.assertEqual(overall.not_compared, 2)

    def test_a_count_opens_the_schools_behind_it(self):
        movement, _areas = self._movement()

        declined = insights.ssa_schools(movement, "leadership", change_rules.DECLINED)
        self.assertEqual([r["code"] for r in declined["rows"]], ["TAB-001"])
        self.assertEqual(
            (declined["rows"][0]["before"], declined["rows"][0]["after"]), (7.0, 5.0)
        )
        self.assertEqual(declined["rows"][0]["change"], -2.0)

        skipped = insights.ssa_schools(
            movement, insights.OVERALL, insights.NOT_COMPARED
        )
        notes = {r["code"]: r["note"] for r in skipped["rows"]}
        self.assertEqual(
            notes,
            {
                "TAB-003": f"No confirmed SSA in FY {self.last_fy}",
                "TAB-004": f"No confirmed SSA in FY {self.last_fy} or FY {self.fy}",
            },
        )
        self.assertIsNone(insights.ssa_schools(movement, "leadership", "bogus"))
        self.assertIsNone(insights.ssa_schools(movement, "bogus", "declined"))

    def test_an_unconfirmed_ssa_is_not_a_reading(self):
        """An SSA waits for a verifier other than its collector; until then
        it moves no figure."""
        self._ssa(self.none, self.last_fy, {"leadership": 2.0}, status="pending")
        self._ssa(self.none, self.fy, {"leadership": 9.0}, status="pending")

        _movement, areas = self._movement()

        self.assertEqual(areas["leadership"].compared, 3)
        self.assertEqual(areas["leadership"].improved, 1)

    def test_the_tab_draws_the_table_and_a_count_opens_its_schools(self):
        body = self._page(tab="ssa").content.decode()

        self.assertIn('data-cluster-profile-panel="ssa"', body)
        self.assertIn(f"SSA Movement, FY {self.last_fy} to FY {self.fy}", body)
        self.assertIn("3 of 5 schools compared", body)
        self.assertEqual(body.count("data-ssa-area="), 9)
        link = (
            f"/clusters/{self.cluster.id}/profile?tab=ssa&amp;fy={self.fy}"
            "&amp;area=leadership&amp;verdict=declined"
        )
        self.assertIn(link, body)
        self.assertIn(change_rules.RULE_SENTENCE.split(";")[0][:40], body)

        drill = self._page(
            tab="ssa", fy=self.fy, area="leadership", verdict="declined"
        ).content.decode()
        self.assertIn("Leadership: Declined", drill)
        self.assertIn(f'data-ssa-school="{self.down.id}"', drill)
        self.assertNotIn(f'data-ssa-school="{self.up.id}"', drill)
        self.assertIn(">School ID</th>", drill)
        self.assertIn(f'href="/schools/{self.down.id}"', drill)
        self.assertIn("data-ssa-back", drill)

    def test_the_tab_opens_on_the_running_year_against_the_last(self):
        """Owner, 2026-10-09: "fy2026 vs fy2027 not 2025". With no SSA yet in
        the new year the tab still opens on it; an earlier year is a choice
        in its list."""
        SsaRecord.objects.filter(fy=self.fy).delete()

        response = self._page(tab="ssa")

        self.assertEqual(response.context["profile_fy"], self.fy)
        self.assertIn(self.last_fy, response.context["profile_fy_options"])
        self.assertEqual(insights.ssa_years_with_records(self.cluster), [self.last_fy])


class MembershipHistoryTest(_ClusterCase):
    def test_a_school_that_left_keeps_its_row(self):
        stays, left = self._school(0), self._school(1)
        # Joining a cluster opens the school's history row by itself
        # (apps.clusters.membership_history); the test dates and closes them.
        joined = datetime(int(self.last_fy) - 1, 11, 3, tzinfo=timezone.utc)
        SchoolClusterMembership.objects.filter(school=stays).update(
            started_at=joined, started_by=self.cd.id, start_reason="Founding member"
        )
        SchoolClusterMembership.objects.filter(school=left).update(
            started_at=joined,
            ended_at=datetime(int(self.fy) - 1, 10, 2, tzinfo=timezone.utc),
            ended_by=self.cd.id,
            end_reason="Moved to the cluster nearer the school",
        )
        self.assertEqual(
            SchoolClusterMembership.objects.filter(cluster=self.cluster).count(), 2
        )

        history = insights.cluster_membership_history(self.cluster)

        self.assertEqual((history["current"], history["former"]), (1, 1))
        # Current members first.
        self.assertEqual([r["code"] for r in history["rows"]], ["TAB-000", "TAB-001"])
        self.assertEqual(history["rows"][0]["joined_by"], self.cd.name)
        self.assertEqual(history["rows"][1]["ended_by"], self.cd.name)

        body = self._page(tab="history").content.decode()
        self.assertIn('data-cluster-profile-panel="history"', body)
        self.assertIn("1 current member · 1 former", body)
        self.assertIn("Moved to the cluster nearer the school", body)
        self.assertIn(">School ID</th>", body)


class ProfileTabsTest(_ClusterCase):
    def test_the_cluster_page_keeps_the_roster_and_opens_the_profile(self):
        """Owner, 2026-10-10: "The Cluster Page manages the cluster. The
        Cluster Profile explains the cluster." The page has no profile tabs;
        it has one door to the profile."""
        self._school(0)

        response = self._page()
        body = response.content.decode()

        self.assertIn("data-cluster-page", body)
        self.assertNotIn("data-cluster-profile-tabs", body)
        self.assertIn(
            f'href="/clusters/{self.cluster.id}/profile" '
            'class="edify-action-button secondary h-9" data-cluster-profile-link',
            body,
        )
        self.assertIn("Schools in This Cluster", body)
        self.assertIn("Cluster Logistics", body)
        self.assertNotIn("data-cluster-profile-panel", body)

    def test_the_profile_has_the_tabs_and_not_the_roster(self):
        self._school(0)
        self.client.force_login(self.cd)

        response = self.client.get(f"/clusters/{self.cluster.id}/profile")
        body = response.content.decode()

        self.assertEqual(response.context["profile_tab"], "portfolio")
        self.assertIn("data-cluster-profile-tabs", body)
        for key in ("portfolio", "ssa", "attendance", "history", "sources"):
            self.assertIn(f'href="/clusters/{self.cluster.id}/profile?tab={key}', body)
        self.assertNotIn("Schools in This Cluster", body)
        self.assertIn("data-cluster-page-link", body)

    def test_an_address_from_before_the_two_were_parted_is_sent_on(self):
        self.client.force_login(self.cd)

        response = self.client.get(
            f"/clusters/{self.cluster.id}", {"tab": "attendance", "fy": self.fy}
        )

        self.assertRedirects(
            response,
            f"/clusters/{self.cluster.id}/profile?tab=attendance&fy={self.fy}",
            fetch_redirect_response=False,
        )

    def test_a_tab_does_not_build_the_overviews_roster(self):
        self._school(0)

        response = self._page(tab="attendance")
        body = response.content.decode()

        self.assertNotIn("schools", response.context)
        self.assertNotIn("Schools in This Cluster", body)
        self.assertIn(
            f'href="/clusters/{self.cluster.id}/profile?tab=attendance&amp;fy={self.fy}" '
            'aria-current="page"',
            body,
        )

    def test_an_unknown_tab_opens_the_summary(self):
        response = self._page(tab="nonsense")

        self.assertEqual(response.context["profile_tab"], "portfolio")

    def test_a_year_the_page_does_not_offer_falls_back(self):
        response = self._page(tab="attendance", fy="1066")

        self.assertEqual(response.context["profile_fy"], self.fy)
