"""The Cluster Page manages the cluster; the Cluster Profile explains it.

Owner's brief, 2026-10-10. What is held here:

* the two are two pages: the Cluster Page keeps the record, the roster and
  the year's work, with one door to the profile; an address written before
  they were parted is sent on;
* nothing on either is typed or stored: a confirmed SSA already in the
  database is found, filtered to the cluster's schools by membership (not by
  the school's district), aggregated, and opens the school's own records —
  the brief's 22-step acceptance walk;
* a year in the address reads that year's records and no other's;
* the Executive Summary's ten figures are each a link, in the brief's order;
* the page's operational figures are the profile's own, and each line under
  Needs Attention Now opens a list of that length;
* `profile_map` describes every figure, and each entry opens something real.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from django.test import TestCase

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.analytics import profile_intelligence as engine
from apps.analytics.profile_records import RECORDS
from apps.clusters import page_summary, profile_insights, profile_map
from apps.clusters.models import Cluster
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.frontend.views.cluster_views import PROFILE_TABS
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

SCORES_A = {"leadership": 7.0, "financial_health": 8.0, "christlike_behaviour": 6.0}
SCORES_B = {"leadership": 4.0, "financial_health": 5.0, "christlike_behaviour": 9.0}


class _Case(TestCase):
    def setUp(self):
        self.cd = _create_user("cd@cluster-two-pages.test", EdifyRole.COUNTRY_DIRECTOR)
        self.region = Region.objects.create(name="Two pages region")
        self.district = District.objects.create(name="Home", region=self.region)
        # A neighbouring district: a cluster keeps a member school there.
        self.next_door = District.objects.create(name="Next door", region=self.region)
        self.cluster = Cluster.objects.create(
            name="Two pages cluster", region=self.region, district=self.district
        )
        self.fy = str(get_operational_fy())
        self.last_fy = str(int(self.fy) - 1)
        self.a = self._school(1)
        self.b = self._school(2, district=self.next_door)
        self.c = self._school(3)
        self.outsider = School.objects.create(
            name="Not a member",
            school_id="TWO-900",
            region=self.region,
            district=self.district,
        )
        self.client.force_login(self.cd)
        self.page_url = f"/clusters/{self.cluster.id}"
        self.profile_url = f"{self.page_url}/profile"

    def _school(self, n: int, **kw) -> School:
        kw.setdefault("district", self.district)
        return School.objects.create(
            name=f"Two pages school {n}",
            school_id=f"TWO-{n:03d}",
            region=self.region,
            cluster_id=str(self.cluster.id),
            enrollment=100 * n,
            **kw,
        )

    def _ssa(self, school, fy, scores):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=round(sum(scores.values()) / len(scores), 2),
            verification_status="confirmed",
            date_of_ssa=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
            uploaded_by="test",
        )
        for intervention, score in scores.items():
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=score
            )
        return record

    def _get(self, url, **query):
        response = self.client.get(url, query)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode()


class TwoPagesTest(_Case):
    def test_the_cluster_page_is_operational_and_opens_the_profile(self):
        body = self._get(self.page_url)

        self.assertIn("data-cluster-page", body)
        self.assertIn("This Year&#x27;s Work", body)
        self.assertIn("Needs Attention Now", body)
        self.assertIn("Schools in This Cluster", body)
        self.assertIn(f'href="{self.profile_url}"', body)
        # The deep reads are the profile's.
        for moved in (
            "data-cluster-profile-tabs",
            "Struggling Interventions",
            "Full Cluster Scorecard",
            "Cluster Activity &amp; Improvement Impact",
        ):
            self.assertNotIn(moved, body)

    def test_the_profile_has_every_section_and_no_roster_actions(self):
        body = self._get(self.profile_url)

        for key, label in PROFILE_TABS:
            self.assertIn(f"{self.profile_url}?tab={key}", body)
            self.assertIn(f"<span>{label.replace('&', '&amp;')}</span>", body)
        self.assertIn("Executive Summary", body)
        self.assertNotIn("Add Schools to Cluster", body)
        self.assertNotIn("Delete cluster", body)

    def test_an_old_tab_or_record_address_is_sent_to_the_profile(self):
        for query in (
            {"tab": "ssa", "fy": self.fy},
            {"what": "ssa", "fy": self.fy},
        ):
            with self.subTest(query=query):
                response = self.client.get(self.page_url, query)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response["Location"].startswith(f"{self.profile_url}?"),
                    response["Location"],
                )
        # The old first tab was the page itself.
        self.assertEqual(
            self.client.get(self.page_url, {"tab": "overview"}).status_code, 200
        )


class DatabaseFirstTest(_Case):
    """The brief's acceptance walk: FY SSA already stored is discovered,
    aggregated and opens the school's own record."""

    def setUp(self):
        super().setUp()
        self.record_a = self._ssa(self.a, self.fy, SCORES_A)
        self.record_b = self._ssa(self.b, self.fy, SCORES_B)
        self._ssa(self.a, self.last_fy, {k: v - 1 for k, v in SCORES_A.items()})
        # A school that is not a member, however near, is in no figure.
        self._ssa(self.outsider, self.fy, {k: 10.0 for k in SCORES_A})

    def test_the_cluster_score_is_aggregated_from_the_member_schools_records(self):
        profile = engine.build(engine.cluster_scope(self.cluster), self.fy)

        # Each intervention's mean over the member schools, then their mean.
        by_area = {key: (SCORES_A[key] + SCORES_B[key]) / 2 for key in SCORES_A}
        self.assertAlmostEqual(
            profile["ssa"]["current"], sum(by_area.values()) / len(by_area), places=2
        )
        self.assertEqual(profile["portfolio"]["assessed"], 2)
        self.assertEqual(profile["portfolio"]["schools"], 3)
        body = self._get(self.profile_url, tab="portfolio", fy=self.fy)
        self.assertIn(f"{profile['ssa']['current']:.2f}", body)

    def test_membership_decides_the_schools_not_the_schools_district(self):
        """A member in a neighbouring district counts; a school of the
        cluster's own district that is not a member does not."""
        ids = set(
            engine.cluster_scope(self.cluster).schools.values_list("id", flat=True)
        )

        self.assertIn(self.b.id, ids)
        self.assertNotIn(self.outsider.id, ids)

    def test_the_ssa_score_opens_the_schools_and_their_own_records(self):
        body = self._get(self.profile_url, what="ssa", fy=self.fy)

        self.assertIn(self.a.name, body)
        self.assertIn(self.b.name, body)
        self.assertNotIn(self.outsider.name, body)
        self.assertIn(f'href="/schools/{self.a.id}?tab=ssa"', body)
        # The school's own profile shows the same record's average.
        school = self._get(f"/schools/{self.a.id}", tab="ssa", fy=self.fy)
        self.assertIn(f"{self.record_a.average_score:.2f}", school)

    def test_each_school_names_its_strongest_and_struggling_intervention(self):
        members = profile_insights.member_schools([self.cluster.id])[self.cluster.id]
        rows = {
            row["id"]: row
            for row in profile_insights.school_ssa_standing(members, fy=self.fy)
        }

        self.assertEqual(rows[self.a.id]["strongest"], "Financial Health")
        self.assertEqual(rows[self.a.id]["strongest_score"], 8.0)
        self.assertEqual(rows[self.b.id]["struggling"], "Leadership")
        self.assertEqual(rows[self.a.id]["current"], self.record_a.average_score)
        self.assertEqual(rows[self.a.id]["change"], 1.0)
        # No record this year: listed, with nothing named.
        self.assertIsNone(rows[self.c.id]["current"])
        self.assertEqual(rows[self.c.id]["strongest"], "")
        # With the movement table's verdicts, a row is called what that
        # table counted it as: the two records here are a year apart.
        movement = profile_insights.cluster_ssa_movement(self.cluster, fy=self.fy)
        told = {
            row["id"]: row
            for row in profile_insights.school_ssa_standing(
                members,
                fy=self.fy,
                verdicts=movement["schools_by_area"][profile_insights.OVERALL],
            )
        }
        counted = {r["id"]: r for r in movement["schools_by_area"]["overall"]}
        for school in (self.a, self.b, self.c):
            self.assertEqual(told[school.id]["verdict"], counted[school.id]["verdict"])
        body = self._get(self.profile_url, tab="ssa", fy=self.fy, view="schools")
        self.assertIn(">Strongest Intervention</th>", body)
        self.assertIn(">Struggling Intervention</th>", body)
        self.assertIn("Financial Health · 8.0", body)

    def test_a_year_in_the_address_reads_that_years_records_only(self):
        this_year = engine.build(engine.cluster_scope(self.cluster), self.fy)
        last_year = engine.build(engine.cluster_scope(self.cluster), self.last_fy)

        self.assertEqual(this_year["portfolio"]["assessed"], 2)
        # Only school A was assessed the year before.
        self.assertEqual(last_year["portfolio"]["assessed"], 1)
        self.assertAlmostEqual(
            last_year["ssa"]["current"],
            sum(v - 1 for v in SCORES_A.values()) / len(SCORES_A),
            places=2,
        )
        self.assertNotEqual(this_year["ssa"]["current"], last_year["ssa"]["current"])

    def test_a_figure_with_no_record_is_zero_and_still_a_link(self):
        body = self._get(self.profile_url, tab="portfolio", fy=self.fy)

        self.assertNotIn("Not measured", body)
        self.assertNotIn("Not Measured", body)
        self.assertIn("what=stories", body)
        self.assertIn("what=teachers_trained", body)


class ExecutiveSummaryTest(_Case):
    ORDER = (
        "Schools",
        "SSA Score",
        "Teachers Trained",
        "Leaders Trained",
        "Students Impacted",
        "Enrolment Growth",
        "Exam Performance",
        "Training Attendance",
        "Meeting Attendance",
        "MSCS",
    )

    def test_the_ten_figures_are_in_the_briefs_order_and_each_is_a_link(self):
        body = self._get(self.profile_url, tab="portfolio", fy=self.fy)
        start = body.index("Executive Summary")
        strip = body[start : body.index("Partners And Projects", start)]

        found = [strip.find(f">{label}<") for label in self.ORDER]
        self.assertNotIn(-1, found, dict(zip(self.ORDER, found, strict=True)))
        self.assertEqual(found, sorted(found))
        # No tile of the strip is plain text.
        self.assertGreaterEqual(len(re.findall(r"<a\b", strip)), len(self.ORDER))

    def test_attendance_is_the_registers_and_meetings_are_kept_from_trainings(self):
        day = date.today() - timedelta(days=3)
        for kind, came in (
            ("cluster_meeting", (self.a,)),
            ("cluster_training", (self.a, self.b)),
        ):
            session = Activity.objects.create(
                activity_type=kind,
                cluster=self.cluster,
                fy=self.fy,
                planned_date=day,
                status="ia_verified",
            )
            for school in (self.a, self.b):
                ClusterActivityAttendance.objects.create(
                    activity=session,
                    school=school,
                    invited=True,
                    attended=school in came,
                )

        response = self.client.get(
            self.profile_url, {"tab": "portfolio", "fy": self.fy}
        )
        pi = response.context["pi"]

        self.assertEqual(pi["meetings"]["rate"], 50)
        self.assertEqual(pi["training_attendance"]["rate"], 100)


class OperationalSummaryTest(_Case):
    def test_the_pages_figures_are_the_profiles_own(self):
        day = date.today() + timedelta(days=10)
        Activity.objects.create(
            activity_type="school_visit",
            school=self.a,
            fy=self.fy,
            planned_date=day,
            status="scheduled",
        )
        Activity.objects.create(
            activity_type="school_visit",
            school=self.b,
            fy=self.fy,
            planned_date=date.today() - timedelta(days=5),
            status="scheduled",
        )

        ops = page_summary.operational_summary(self.cluster)
        profile = engine.build(engine.cluster_scope(self.cluster), self.fy)

        self.assertEqual(ops["schools"], 3)
        self.assertEqual(ops["planned"], 2)
        self.assertEqual(ops["upcoming"], 1)
        self.assertEqual(ops["overdue"], 1)
        self.assertEqual(ops["completed"], 0)
        self.assertEqual(
            ops["planned"],
            sum(
                profile["execution"][k]["planned"]
                for k in ("visits", "trainings", "meetings")
            ),
        )

    def test_each_line_under_needs_attention_opens_a_list_of_its_length(self):
        ops = page_summary.operational_summary(self.cluster)
        keys = {item["key"] for item in ops["attention"]}

        # Three schools, none assessed, none with a visit or training planned.
        self.assertTrue({"no_ssa", "unplanned"} <= keys, keys)
        self.assertEqual(ops["outstanding"], len(ops["attention"]))
        for item in ops["attention"]:
            with self.subTest(line=item["text"]):
                self.assertTrue(item["href"].startswith(self.profile_url))
                response = self.client.get(item["href"])
                self.assertEqual(response.status_code, 200)
        no_ssa = next(i for i in ops["attention"] if i["key"] == "no_ssa")
        self.assertTrue(no_ssa["text"].startswith("3 schools"))
        body = self.client.get(no_ssa["href"]).content.decode()
        for school in (self.a, self.b, self.c):
            self.assertIn(school.name, body)


class MetricMapTest(_Case):
    def test_every_entry_opens_a_tab_of_the_profile_or_a_record_list(self):
        tabs = dict(PROFILE_TABS)
        for metric in profile_map.METRICS:
            with self.subTest(figure=metric.figure):
                kind, _, key = metric.opens.partition(":")
                if kind == "tab":
                    self.assertIn(key, tabs)
                else:
                    self.assertEqual(kind, "what")
                    self.assertIn(key, RECORDS)
                for text in (metric.source, metric.filters, metric.aggregation):
                    self.assertTrue(text.strip())

    def test_every_figure_of_the_executive_summary_is_described(self):
        described = {
            m.figure for m in profile_map.METRICS if m.section == "Executive Summary"
        }

        self.assertEqual(
            described,
            {
                "Schools",
                "SSA Score",
                "Teachers Trained",
                "School Leaders Trained",
                "Students Impacted",
                "Enrolment Growth",
                "Exam Performance",
                "Training Attendance",
                "Meeting Attendance",
                "MSCS",
            },
        )

    def test_the_sources_tab_reads_the_map_out(self):
        body = self._get(self.profile_url, tab="sources")

        self.assertIn('data-cluster-profile-panel="sources"', body)
        self.assertEqual(body.count("data-profile-metric="), len(profile_map.METRICS))
