"""The profile engine and the District profile, the first built on it.

Owner, 2026-10-09: "Build a unified, FY-aware Profile Intelligence System ...
Profiles must not create duplicate sources of truth. Every aggregate metric
must drill into the underlying records", and then "start the profile work".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.analytics import profile_intelligence as engine
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.year_comparison import fy_label

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
ALL = [value for value, _label in SsaIntervention.choices]


class ProfileFixture(TestCase):
    """A district of six schools in two clusters, one school outside any
    cluster, and a second district the profile must never read."""

    @classmethod
    def setUpTestData(cls):
        cls.fy = str(get_operational_fy())
        cls.last = str(int(cls.fy) - 1)
        cls.region = Region.objects.create(name="Profile Region")
        cls.district = District.objects.create(name="Profile", region=cls.region)
        cls.elsewhere = District.objects.create(name="Elsewhere", region=cls.region)
        cls.north = cls._cluster("North Cluster")
        cls.south = cls._cluster("South Cluster")
        # (name, type, cluster, last year, this year)
        plan = [
            ("Alpha", "core", cls.north, 4.0, 7.0),
            ("Bravo", "client", cls.north, 6.0, 5.0),
            ("Charlie", "client", cls.north, None, 8.0),
            ("Delta", "client", cls.south, 5.0, None),
            ("Echo", "core_trained", cls.south, 3.0, 3.0),
            ("Foxtrot", "client", None, None, None),
        ]
        cls.schools = {}
        for index, (name, kind, cluster, before, now) in enumerate(plan):
            school = School.objects.create(
                school_id=f"PROFILE-{index}",
                name=f"{name} Primary",
                region=cls.region,
                district=cls.district,
                school_type=kind,
                cluster_id=cluster.id if cluster else None,
                enrollment=100 * (index + 1),
            )
            cls.schools[name] = school
            if before is not None:
                cls._ssa(school, cls.last, before)
            if now is not None:
                cls._ssa(school, cls.fy, now)
        cls.outsider = School.objects.create(
            school_id="PROFILE-OUT",
            name="Outsider Primary",
            region=cls.region,
            district=cls.elsewhere,
            cluster_id=cls.north.id,
        )
        cls._ssa(cls.outsider, cls.fy, 10.0)
        cls.director = User.objects.create_user(
            email="profile-cd@edify.org",
            name="Dora Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.director, country="Uganda")

    @classmethod
    def _cluster(cls, name):
        return Cluster.objects.create(
            name=name, region=cls.region, district=cls.district, status="active"
        )

    @classmethod
    def _ssa(cls, school, fy, score, *, status="confirmed"):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            # A year apart, so the change rule reads a before and an after.
            date_of_ssa=datetime(int(fy) - 1, 11, 5, tzinfo=dt_tz.utc),
            average_score=score,
            verification_status=status,
        )
        for intervention in ALL:
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=score
            )
        return record

    def activity(self, kind, *, school=None, cluster=None, status="scheduled", days=5):
        return Activity.objects.create(
            school=school,
            cluster=cluster,
            activity_type=kind,
            status=status,
            fy=self.fy,
            planned_date=timezone.localdate() + timedelta(days=days),
        )

    def profile(self, fy=None):
        return engine.build(engine.district_scope(self.district), fy or self.fy)


class PortfolioTest(ProfileFixture):
    def test_the_scope_is_the_district_s_operating_schools(self):
        portfolio = self.profile()["portfolio"]

        self.assertEqual(portfolio["schools"], 6)
        self.assertEqual(
            {row["label"]: row["count"] for row in portfolio["types"]},
            {"Client": 4, "Core": 1, "Core Trained": 1},
        )
        self.assertEqual(
            (portfolio["clusters"], portfolio["clustered_schools"]), (2, 5)
        )
        self.assertEqual(portfolio["cluster_coverage"], 83)
        self.assertEqual(portfolio["enrollment"], 2100)

    def test_a_closed_school_leaves_the_profile(self):
        from apps.schools.lifecycle_service import active_schools

        gone = self.schools["Foxtrot"]
        School.objects.filter(id=gone.id).update(deleted_at=timezone.now())
        self.assertNotIn(gone.id, set(active_schools().values_list("id", flat=True)))

        self.assertEqual(self.profile()["portfolio"]["schools"], 5)

    def test_every_figure_opens_exactly_the_schools_it_counted(self):
        """No orphan figures (the brief, point 28): the list behind a number
        is as long as the number."""
        self.activity("school_visit", school=self.schools["Alpha"])
        PartnerAssignment.objects.create(
            school=self.schools["Bravo"],
            partner=Partner.objects.create(
                name="Profile Partner", active_status=True, source="test"
            ),
            status=PartnerAssignment.STATUS_ASSIGNED,
        )

        profile = self.profile()
        portfolio = profile["portfolio"]

        for show in engine.SHOW_LABELS:
            rows = engine.school_rows(profile, show)
            expected = portfolio["schools"] if show == "all" else portfolio[show]
            with self.subTest(show=show):
                self.assertEqual(len(rows), expected)
        self.assertEqual(
            {r["name"] for r in engine.school_rows(profile, "no_ssa")},
            {"Delta Primary", "Foxtrot Primary"},
        )
        self.assertEqual(portfolio["unplanned"], 5)
        self.assertEqual(
            [r["name"] for r in engine.school_rows(profile, "awaiting_partner")],
            ["Bravo Primary"],
        )
        self.assertEqual(portfolio["assessed"] + portfolio["no_ssa"], 6)


class SsaTest(ProfileFixture):
    def test_each_intervention_has_last_year_this_year_and_the_change(self):
        ssa = self.profile()["ssa"]

        # Last year: Alpha 4, Bravo 6, Delta 5, Echo 3. This year: Alpha 7,
        # Bravo 5, Charlie 8, Echo 3. The outsider's 10 is another district's.
        self.assertEqual((ssa["previous"], ssa["current"]), (4.5, 5.75))
        self.assertEqual((ssa["previous_schools"], ssa["schools"]), (4, 4))
        self.assertEqual(len(ssa["rows"]), len(ALL))
        for row in ssa["rows"]:
            self.assertEqual((row["previous"], row["current"]), (4.5, 5.75))
            self.assertEqual((row["change"], row["status"]), (1.25, "improved"))
        self.assertEqual(ssa["overall"]["status_label"], "Improved")
        self.assertEqual(
            (ssa["label"], ssa["previous_label"]),
            (fy_label(self.fy), fy_label(self.last)),
        )

    def test_a_school_s_change_is_called_by_the_one_rule(self):
        profile = self.profile()
        rows = {row["name"]: row for row in engine.school_rows(profile)}

        self.assertEqual(rows["Alpha Primary"]["status_label"], "Improved")
        self.assertEqual(rows["Bravo Primary"]["status_label"], "Declined")
        self.assertEqual(rows["Echo Primary"]["status_label"], "No change")
        # One year alone is not a change, and never a zero.
        for name in ("Charlie Primary", "Delta Primary", "Foxtrot Primary"):
            self.assertIsNone(rows[name]["change"])
            self.assertEqual(rows[name]["status_label"], "No comparison yet")

    def test_a_cluster_is_its_schools_in_the_district(self):
        clusters = {row["name"]: row for row in self.profile()["clusters"]}

        north = clusters["North Cluster"]
        # Alpha, Bravo, Charlie: the outsider in the same cluster is not here.
        self.assertEqual((north["schools"], north["assessed"]), (3, 3))
        self.assertEqual((north["previous"], north["current"]), (5.0, 6.67))
        self.assertEqual(north["status_label"], "Improved")
        south = clusters["South Cluster"]
        self.assertEqual((south["schools"], south["assessed"]), (2, 1))
        self.assertEqual((south["previous"], south["current"]), (4.0, 3.0))
        self.assertEqual(south["status_label"], "Declined")

    def test_an_unconfirmed_record_is_not_the_year_s_score(self):
        self._ssa(self.schools["Foxtrot"], self.fy, 9.5, status="pending")

        profile = self.profile()

        self.assertEqual(profile["ssa"]["current"], 5.75)
        self.assertIn(
            "Foxtrot Primary",
            {r["name"] for r in engine.school_rows(profile, "no_ssa")},
        )


class RankingTest(ProfileFixture):
    def test_schools_are_ranked_by_this_year_s_score_with_their_figures(self):
        rankings = self.profile()["rankings"]

        best = rankings["best_schools"]
        self.assertEqual(
            [(r["rank"], r["name"], r["current"]) for r in best],
            [
                (1, "Charlie Primary", 8.0),
                (2, "Alpha Primary", 7.0),
                (3, "Bravo Primary", 5.0),
                (4, "Echo Primary", 3.0),
            ],
        )
        # Four schools have a score: all four are in the top five, so none
        # is repeated as "worst".
        self.assertEqual(rankings["worst_schools"], [])
        self.assertIn("average confirmed SSA score", rankings["method"])

    def test_the_bottom_is_read_from_the_other_end(self):
        for index in range(4):
            school = School.objects.create(
                school_id=f"PROFILE-X{index}",
                name=f"Extra {index}",
                region=self.region,
                district=self.district,
            )
            self._ssa(school, self.fy, 1.0 + index / 10)

        rankings = self.profile()["rankings"]

        self.assertEqual(len(rankings["best_schools"]), engine.RANKED)
        worst = rankings["worst_schools"]
        self.assertEqual(
            [(r["rank"], r["name"]) for r in worst],
            [(8, "Extra 0"), (7, "Extra 1"), (6, "Extra 2")],
        )
        self.assertFalse(
            {r["id"] for r in worst} & {r["id"] for r in rankings["best_schools"]}
        )


class ExecutionTest(ProfileFixture):
    def test_work_is_counted_by_the_shared_type_and_status_groups(self):
        alpha, bravo = self.schools["Alpha"], self.schools["Bravo"]
        self.activity("school_visit", school=alpha)
        self.activity("follow_up_visit", school=alpha, status="rescheduled", days=-3)
        self.activity("school_visit", school=bravo, status="ia_verified", days=-9)
        self.activity("school_visit", school=bravo, status="cancelled")
        self.activity("in_school_training", school=alpha)
        self.activity("cluster_training", cluster=self.north)
        self.activity("cluster_meeting", cluster=self.south, days=-2)
        # Another district's visit, and another year's.
        self.activity("school_visit", school=self.outsider)
        Activity.objects.create(
            school=alpha, activity_type="school_visit", status="scheduled", fy=self.last
        )

        execution = self.profile()["execution"]

        visits = execution["visits"]
        self.assertEqual((visits["planned"], visits["completed"]), (3, 1))
        self.assertEqual((visits["outstanding"], visits["upcoming"]), (2, 1))
        # A moved visit is still live work, and past its day (rescheduled).
        self.assertEqual(visits["overdue"], 1)
        self.assertEqual((visits["schools"], visits["schools_done"]), (2, 1))
        trainings = execution["trainings"]
        self.assertEqual((trainings["planned"], trainings["group_sessions"]), (2, 1))
        self.assertEqual(execution["meetings"]["overdue"], 1)

    def test_what_needs_attention_is_said_with_its_count_and_its_list(self):
        self.activity("cluster_meeting", cluster=self.south, days=-2)

        attention = {
            item["show"] or item["tab"]: item for item in self.profile()["attention"]
        }

        self.assertEqual(attention["no_ssa"]["count"], 2)
        self.assertIn("2 schools have no confirmed SSA", attention["no_ssa"]["text"])
        self.assertEqual(attention["unplanned"]["count"], 6)
        self.assertEqual(attention["declined"]["count"], 1)
        self.assertIn("1 school's SSA declined", attention["declined"]["text"])
        self.assertEqual(attention["clusters"]["count"], 1)
        self.assertEqual(attention["activities"]["count"], 1)
        self.assertNotIn("awaiting_partner", attention)


class CostTest(ProfileFixture):
    def test_the_cost_does_not_grow_with_the_schools(self):
        with CaptureQueriesContext(connection) as small:
            self.profile()
        for index in range(30):
            school = School.objects.create(
                school_id=f"PROFILE-M{index}",
                name=f"More {index}",
                region=self.region,
                district=self.district,
                cluster_id=self.north.id,
            )
            self._ssa(school, self.fy, 5.0)

        with CaptureQueriesContext(connection) as large:
            self.profile()

        self.assertEqual(len(large), len(small))
        self.assertLessEqual(len(large), 20)


class DistrictPageTest(ProfileFixture):
    def page(self, **query):
        client = Client()
        client.force_login(self.director, backend=BACKEND)
        return client.get(f"/districts/{self.district.id}", query)

    def test_every_tab_opens(self):
        for tab, _label in (
            ("overview", ""),
            ("ssa", ""),
            ("clusters", ""),
            ("schools", ""),
            ("activities", ""),
            ("projects", ""),
        ):
            with self.subTest(tab=tab):
                response = self.page(tab=tab)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'data-profile-tab="{tab}"', response.content.decode())

    def test_it_opens_on_the_running_year_and_says_what_the_numbers_cover(self):
        body = self.page().content.decode()

        self.assertIn('data-profile-tab="overview"', body)
        self.assertIn(f"All schools in the district, {fy_label(self.fy)}", body)
        self.assertIn("Portfolio: 6 schools · 2 clusters", body)
        # A year the page does not offer is the running year, not an error.
        self.assertIn(fy_label(self.fy), self.page(fy="1999").content.decode())

    def test_a_figure_opens_the_list_it_counted(self):
        base = f"/districts/{self.district.id}"
        body = self.page().content.decode()

        self.assertIn(f"{base}?tab=schools&amp;fy={self.fy}&amp;show=no_ssa", body)
        self.assertIn('data-profile-attention-item="declined"', body)

        declined = self.page(tab="schools", show="declined").content.decode()
        self.assertEqual(declined.count("data-profile-school="), 1)
        self.assertIn("Bravo Primary", declined)
        self.assertIn("SSA declined", declined)
        # School ID on every school table, and the name opens the profile.
        self.assertIn(">PROFILE-1<", declined)
        self.assertIn(f'href="/schools/{self.schools["Bravo"].id}"', declined)

    def test_an_earlier_year_is_a_choice(self):
        body = self.page(tab="ssa", fy=self.last).content.decode()

        self.assertIn(f"Current ({fy_label(self.last)})</th>", body)
        row = body.split('data-profile-intervention="overall"', 1)[1].split("</tr>", 1)[
            0
        ]
        # Last year's 4.50 is this page's current column; nothing before it.
        self.assertRegex(row, r"<strong>4\.50\s*</strong>")
        self.assertIn("No comparison yet", row)
        # A profile never says "Not measured" (owner, 2026-10-10).
        self.assertNotIn("Not measured", body)

    def test_the_ranking_says_how_it_was_made(self):
        body = self.page().content.decode()

        self.assertIn("data-profile-method", body)
        self.assertIn("Ranked by the average confirmed SSA score", body)
        self.assertLess(body.index("Charlie Primary"), body.index("Alpha Primary"))


class EveryScopeTest(ProfileFixture):
    """The same sections over a different set of schools (owner, 2026-10-09:
    "Work on all profiles in a sequential order")."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.geography.models import SubRegion

        def person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return StaffProfile.objects.create(user=user, country="Uganda")

        cls.lead = person("profile-pl@edify.org", "Lena Lead", "Program Lead")
        cls.officer = person("profile-cceo@edify.org", "Otto Officer", "CCEO")
        cls.other = person("profile-other@edify.org", "Una Other", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.lead, supervisee=cls.officer
        )
        # The Lead holds Alpha, the officer Bravo and Charlie (one by staff
        # id, one by user id: both are how a holder is written), somebody
        # outside the team Delta.
        holders = {
            "Alpha": cls.lead.id,
            "Bravo": cls.officer.id,
            "Charlie": cls.officer.user_id,
            "Delta": cls.other.id,
        }
        for name, holder in holders.items():
            School.objects.filter(id=cls.schools[name].id).update(
                account_owner_id=holder
            )
        cls.sub_region = SubRegion.objects.create(
            name="Profile Sub-region",
            normalized_name="profile sub-region",
            region=cls.region,
        )
        School.objects.filter(
            id__in=[cls.schools[n].id for n in ("Alpha", "Bravo", "Echo")]
        ).update(sub_region_id=cls.sub_region.id)
        cls.partner = Partner.objects.create(
            name="Profile Partner", active_status=True, source="test"
        )

    def names(self, scope):
        return {row["name"] for row in engine.school_rows(engine.build(scope, self.fy))}

    def test_a_cluster_is_its_member_schools_wherever_they_are(self):
        scope = engine.cluster_scope(self.north)

        self.assertEqual(
            self.names(scope),
            {"Alpha Primary", "Bravo Primary", "Charlie Primary", "Outsider Primary"},
        )
        self.assertEqual(scope.covers, "Cluster schools")

    def test_a_school_is_itself(self):
        profile = engine.build(engine.school_scope(self.schools["Bravo"]), self.fy)

        self.assertEqual(profile["portfolio"]["schools"], 1)
        self.assertEqual(
            (profile["ssa"]["previous"], profile["ssa"]["current"]), (6.0, 5.0)
        )
        # Every intervention fell by one: the struggling one is named.
        self.assertEqual(profile["ssa"]["most_declined"]["change"], -1.0)
        self.assertIsNone(profile["ssa"]["most_improved"])

    def test_a_person_s_profile_is_the_schools_they_hold_by_either_id(self):
        self.assertEqual(
            self.names(engine.staff_scope(self.officer)),
            {"Bravo Primary", "Charlie Primary"},
        )

    def test_a_programme_lead_s_profile_is_the_whole_team_s(self):
        """ "The PL's entire portfolio + the entire portfolio of everyone
        under the PL" (the brief, point 20)."""
        scope = engine.program_lead_scope(self.lead)
        profile = engine.build(scope, self.fy)

        self.assertEqual(scope.covers, "Entire team portfolio")
        self.assertEqual(
            {row["name"] for row in engine.school_rows(profile)},
            {"Alpha Primary", "Bravo Primary", "Charlie Primary"},
        )
        team = engine.groups(profile, "staff")
        # The officer's two ids are one row.
        self.assertEqual(
            {row["name"]: row["schools"] for row in team["rows"]},
            {"Lena Lead": 1, "Otto Officer": 2},
        )
        self.assertEqual(team["rows"][1]["id"], self.officer.user_id)
        self.assertEqual(sum(row["schools"] for row in team["rows"]), 3)

    def test_a_sub_region_and_the_country_reconcile_with_their_districts(self):
        sub = engine.build(engine.sub_region_scope(self.sub_region), self.fy)
        self.assertEqual(sub["portfolio"]["schools"], 3)

        country = engine.build(engine.country_scope(), self.fy)
        districts = engine.groups(country, "districts")
        self.assertEqual(
            {row["name"]: row["schools"] for row in districts["rows"]},
            {"Profile": 6, "Elsewhere": 1},
        )
        # A district's line on the country is the district's own profile.
        mine = next(row for row in districts["rows"] if row["name"] == "Profile")
        own = self.profile()
        self.assertEqual(
            (mine["previous"], mine["current"], mine["assessed"]),
            (
                own["ssa"]["previous"],
                own["ssa"]["current"],
                own["portfolio"]["assessed"],
            ),
        )
        # Four schools have no sub-region: said, and still in the totals.
        regions = engine.groups(country, "sub_regions")
        self.assertEqual((len(regions["rows"]), regions["unplaced"]), (1, 4))
        self.assertEqual(country["portfolio"]["schools"], 7)

    def test_a_partner_s_profile_keeps_assigned_scheduled_and_completed_apart(self):
        """ "Assigned ≠ Scheduled ≠ Completed" (the brief, point 15)."""
        statuses = {
            "Alpha": PartnerAssignment.STATUS_ASSIGNED,
            "Bravo": PartnerAssignment.STATUS_PARTNER_SCHEDULED,
            "Charlie": PartnerAssignment.STATUS_COMPLETED,
            "Delta": PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        }
        for name, status in statuses.items():
            PartnerAssignment.objects.create(
                school=self.schools[name], partner=self.partner, status=status
            )
        # The Partner's own visit, and a staff visit at the same school.
        Activity.objects.create(
            school=self.schools["Bravo"],
            activity_type="school_visit",
            status="partner_scheduled",
            fy=self.fy,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
        )
        self.activity("school_visit", school=self.schools["Bravo"])

        scope = engine.partner_scope(self.partner)
        profile = engine.build(scope, self.fy)

        # A school taken back is no longer the Partner's.
        self.assertEqual(
            {row["name"] for row in engine.school_rows(profile)},
            {"Alpha Primary", "Bravo Primary", "Charlie Primary"},
        )
        self.assertEqual(
            profile["portfolio"]["handovers"],
            {"assigned": 3, "awaiting": 1, "completed": 1, "scheduled": 1},
        )
        self.assertEqual(profile["execution"]["visits"]["planned"], 1)
        self.assertEqual(profile["execution"]["visits"]["by_partner"], 1)


class ClusterManagementTest(ProfileFixture):
    """Owner, 2026-10-09: "Integrate cluster management into all the profiles
    that has anything to do with cluster"."""

    def test_each_cluster_carries_what_cluster_management_knows_of_it(self):
        from apps.clusters import scores

        profile = self.profile()
        totals = engine.cluster_management(profile)

        cards = scores.scorecards([self.north.id, self.south.id], fy=self.fy)
        for row in profile["clusters"]:
            card = cards[row["id"]]
            with self.subTest(cluster=row["name"]):
                # The cluster profile's own figures, not a second count.
                self.assertEqual(row["health"], card.health.score)
                self.assertEqual(row["impact"], card.impact.score)
                self.assertEqual(row["maturity"], card.maturity["level"])
                self.assertIn("attendance_rate", row)
                self.assertIn("absent", row)
        self.assertEqual(totals["sessions"], 0)
        self.assertIsNone(totals["rate"])
        self.assertIn("enrolment_growth", totals["impact"])

    def test_a_scope_with_no_cluster_asks_nothing_of_cluster_management(self):
        profile = engine.build(engine.school_scope(self.schools["Foxtrot"]), self.fy)

        with CaptureQueriesContext(connection) as queries:
            totals = engine.cluster_management(profile)

        self.assertEqual(len(queries), 0)
        self.assertEqual((totals["sessions"], totals["impact"]), (0, None))


class EveryProfilePageTest(EveryScopeTest):
    def client_for(self, user=None):
        client = Client()
        client.force_login(user or self.director, backend=BACKEND)
        return client

    def open(self, url, **query):
        response = self.client_for().get(url, query)
        self.assertEqual(response.status_code, 200, url)
        return response.content.decode()

    def test_the_country_profile_reads_the_country_by_its_parts(self):
        body = self.open("/country-profile")
        self.assertIn('data-profile="country"', body)
        self.assertIn("Every school in the country", body)
        for tab in ("sub_regions", "districts", "staff", "clusters", "schools"):
            with self.subTest(tab=tab):
                page = self.open("/country-profile", tab=tab)
                self.assertIn(f'data-profile-tab="{tab}"', page)
        districts = self.open("/country-profile", tab="districts")
        self.assertEqual(districts.count("data-profile-part="), 2)
        self.assertIn(f'href="/districts/{self.district.id}?fy={self.fy}"', districts)
        self.assertIn("Best performing districts", districts)

    def test_the_country_profile_is_for_the_roles_that_read_the_country(self):
        response = self.client_for(self.officer.user).get("/country-profile")

        self.assertNotEqual(response.status_code, 200)

    def test_the_sub_region_profile_opens(self):
        body = self.open(f"/sub-regions/{self.sub_region.id}")

        self.assertIn("Profile Sub-region Sub-region", body)
        self.assertIn("Portfolio: 3 schools", body)
        self.assertIn("All schools in the sub-region", body)

    def test_the_clusters_tab_shows_cluster_management_on_any_profile(self):
        for url in (
            f"/districts/{self.district.id}",
            "/country-profile",
            f"/staff/{self.lead.user_id}",
        ):
            with self.subTest(url=url):
                body = self.open(url, tab="clusters")
                for heading in ("Attendance", "Health", "Impact", "Maturity"):
                    self.assertIn(f">{heading}</th>", body)
                self.assertIn(
                    f'href="/clusters/{self.north.id}/profile?tab=attendance&amp;fy={self.fy}"',
                    body,
                )
                self.assertIn("Teachers Reached", body)

    def test_a_staff_profile_keeps_its_page_and_gains_the_sections(self):
        url = f"/staff/{self.officer.user_id}"
        own = self.open(url)
        self.assertIn("data-profile-tabs", own)
        self.assertNotIn("data-profile-scope", own)

        body = self.open(url, tab="schools")
        self.assertIn("Portfolio: 2 schools", body)
        self.assertIn("Own portfolio", body)
        self.assertEqual(body.count("data-profile-school="), 2)

    def test_a_programme_lead_s_page_is_the_team_s_with_the_team_as_a_tab(self):
        url = f"/staff/{self.lead.user_id}"

        body = self.open(url, tab="staff")

        self.assertIn("Entire team portfolio", body)
        self.assertIn("<span>Team</span>", body)
        self.assertEqual(body.count("data-profile-part="), 2)
        self.assertIn("Otto Officer", body)

    def test_a_partner_profile_gains_the_sections(self):
        PartnerAssignment.objects.create(
            school=self.schools["Alpha"],
            partner=self.partner,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )

        body = self.open(f"/partners/{self.partner.id}", tab="overview")

        self.assertIn("Assigned portfolio", body)
        self.assertIn("Awaiting The Partner&#x27;s Date", body)
        # The tile opens the hand-overs it counts.
        self.assertIn("what=handovers_awaiting", body)

    def test_a_cluster_profile_gains_the_sections_beside_its_own_tabs(self):
        url = f"/clusters/{self.north.id}/profile"

        own = self.open(url)
        for label in ("Summary", "Schools", "Meetings &amp; Attendance"):
            self.assertIn(f"<span>{label}</span>", own)

        body = self.open(url, tab="school_ssa")
        self.assertIn("Cluster schools", body)
        self.assertEqual(body.count("data-profile-school="), 4)
        # A cluster is not ranked among clusters on its own profile.
        self.assertNotIn("Best performing clusters", self.open(url, tab="portfolio"))

    def test_a_school_profile_names_its_best_and_its_struggling_intervention(self):
        body = self.open(f"/schools/{self.schools['Bravo'].id}")

        struggling = body.split('data-profile-intervention-pick="struggling"', 1)[
            1
        ].split("</tr>", 1)[0]
        self.assertIn("Declined", struggling)
        self.assertIn("Change since the previous year", struggling)
        alpha = self.open(f"/schools/{self.schools['Alpha'].id}")
        best = alpha.split('data-profile-intervention-pick="best"', 1)[1].split(
            "</tr>", 1
        )[0]
        self.assertIn("Improved", best)
        self.assertIn("what=intervention&amp;key=", best)


class SummaryTest(EveryScopeTest):
    """Owner, 2026-10-09: "country should have summary of all the
    sub-region, district, clusters, schools, and their performance ... Same
    should apply to Sub-region (District, clusters, schools), District
    (clusters, schools), Schools (SSA, students impact, visit, trainings)"."""

    def lines(self, scope):
        profile = engine.build(scope, self.fy)
        return {line["level"]: line for line in engine.summary(profile)}

    def test_each_profile_names_the_levels_beneath_it(self):
        expected = {
            engine.country_scope(): ["sub_regions", "districts", "clusters", "schools"],
            engine.sub_region_scope(self.sub_region): [
                "districts",
                "clusters",
                "schools",
            ],
            engine.district_scope(self.district): ["clusters", "schools"],
            engine.program_lead_scope(self.lead): [
                "staff",
                "districts",
                "clusters",
                "schools",
            ],
            engine.cluster_scope(self.north): ["schools"],
            engine.school_scope(self.schools["Alpha"]): [],
        }
        for scope, levels in expected.items():
            with self.subTest(scope=scope.kind):
                self.assertEqual(list(self.lines(scope)), levels)

    def test_a_line_is_its_own_table_added_up(self):
        self.activity(
            "school_visit", school=self.schools["Alpha"], status="ia_verified"
        )
        self.activity("school_visit", school=self.schools["Bravo"])
        self.activity("in_school_training", school=self.schools["Alpha"])

        lines = self.lines(engine.district_scope(self.district))

        schools = lines["schools"]
        self.assertEqual((schools["count"], schools["measured"]), (6, 4))
        self.assertEqual((schools["improved"], schools["declined"]), (1, 1))
        self.assertEqual(schools["best"]["name"], "Charlie Primary")
        self.assertEqual(schools["lowest"]["name"], "Echo Primary")
        self.assertEqual((schools["visits"], schools["visits_done"]), (2, 1))
        self.assertEqual((schools["trainings"], schools["trainings_done"]), (1, 0))
        clusters = lines["clusters"]
        self.assertEqual((clusters["count"], clusters["improved"]), (2, 1))
        self.assertEqual(clusters["best"]["name"], "North Cluster")
        self.assertEqual(clusters["lowest"]["name"], "South Cluster")

    def test_a_school_s_row_says_what_was_planned_and_done_there(self):
        self.activity(
            "school_visit", school=self.schools["Alpha"], status="ia_verified"
        )
        self.activity("follow_up_visit", school=self.schools["Alpha"])

        profile = engine.build(engine.district_scope(self.district), self.fy)
        rows = {row["name"]: row for row in engine.school_rows(profile)}

        self.assertEqual(
            (rows["Alpha Primary"]["visits"], rows["Alpha Primary"]["visits_done"]),
            (2, 1),
        )
        self.assertEqual(rows["Bravo Primary"]["visits"], 0)
        districts = engine.groups(
            engine.build(engine.country_scope(), self.fy), "districts"
        )
        mine = next(r for r in districts["rows"] if r["name"] == "Profile")
        self.assertEqual(
            (mine["visits"], mine["visits_done"], mine["clusters"]), (2, 1, 2)
        )
        self.assertEqual(mine["enrollment"], 2100)

    def test_students_are_compared_like_for_like(self):
        from apps.schools.models import SchoolEnrollmentHistory

        for name, before, after in (("Alpha", 100, 130), ("Bravo", 200, 190)):
            for year, figure in ((self.last, before), (self.fy, after)):
                SchoolEnrollmentHistory.objects.create(
                    school=self.schools[name],
                    fy=year,
                    enrollment=figure,
                    recorded_at=timezone.now(),
                )
        # One year only: in no comparison.
        SchoolEnrollmentHistory.objects.create(
            school=self.schools["Charlie"],
            fy=self.fy,
            enrollment=999,
            recorded_at=timezone.now(),
        )

        students = engine.students(self.profile())

        self.assertEqual(students["enrolment_compared"], 2)
        self.assertEqual(
            (students["enrolment_before"], students["enrolment_after"]), (300, 320)
        )
        self.assertEqual(students["enrolment_growth"], 6.7)
        self.assertEqual(students["learning_compared"], 0)
        self.assertIsNone(students["learning_after"])

    def test_the_overview_shows_the_summary_and_each_line_opens_its_tab(self):
        client = Client()
        client.force_login(self.director, backend=BACKEND)

        body = client.get("/country-profile").content.decode()

        self.assertIn("What This Profile Covers", body)
        for level in ("sub_regions", "districts", "clusters", "schools"):
            self.assertIn(f'data-profile-level="{level}"', body)
            self.assertIn(f"/country-profile?tab={level}&amp;fy={self.fy}", body)
        self.assertIn("Enrolment Growth", body)
        self.assertIn("Visits Completed", body)
        # On a cluster's page the schools line opens the cluster's own key.
        cluster = client.get(f"/clusters/{self.north.id}/profile", {"tab": "portfolio"})
        self.assertIn(
            f"/clusters/{self.north.id}/profile?tab=school_ssa&amp;fy={self.fy}",
            cluster.content.decode(),
        )

    def test_a_school_s_page_shows_its_year_at_a_glance(self):
        client = Client()
        client.force_login(self.director, backend=BACKEND)
        self.activity(
            "school_visit", school=self.schools["Alpha"], status="ia_verified"
        )

        body = client.get(f"/schools/{self.schools['Alpha'].id}").content.decode()

        for label in ("Visits Completed", "Trainings Completed", "Enrolment Growth"):
            self.assertIn(label, body)


class TheRestOfTheBriefTest(EveryScopeTest):
    """Owner, 2026-10-09, on the list of what the brief still lacked: "build
    these too" — people trained, loans and Business Transformation, SSA
    targets, expected visits and coverage, quarter and month views, project
    capacity and outcomes."""

    def test_ssa_is_read_against_its_target(self):
        ssa = self.profile()["ssa"]

        # Owner, 2026-10-09: "SSA score target is 10 not 6".
        self.assertEqual((ssa["target"], engine.SSA_TARGET), (10.0, 10.0))
        # 5.75 this year: 4.25 to go, and no school at the top of the scale.
        self.assertEqual((ssa["to_target"], ssa["at_target"]), (4.25, 0))
        self.assertEqual({row["to_target"] for row in ssa["rows"]}, {4.25})
        top = self.schools["Charlie"]
        SsaRecord.objects.filter(school=top, fy=self.fy).update(average_score=10)
        SsaScore.objects.filter(ssa_record__school=top, ssa_record__fy=self.fy).update(
            score=10
        )
        school = engine.build(engine.school_scope(top), self.fy)
        self.assertEqual(
            (school["ssa"]["to_target"], school["ssa"]["at_target"]), (0, 1)
        )

    def test_expected_work_is_what_each_school_s_type_is_due(self):
        """A Core school is due four visits and four trainings, a Client or
        Core Trained school one of each; coverage is the schools reached."""
        self.activity(
            "school_visit", school=self.schools["Alpha"], status="ia_verified"
        )
        self.activity("school_visit", school=self.schools["Bravo"])

        visits = self.profile()["execution"]["visits"]

        # One Core, four Client, one Core Trained.
        self.assertEqual((visits["expected"], visits["schools_due"]), (9, 6))
        self.assertEqual((visits["schools_reached"], visits["schools_in_plan"]), (1, 2))
        self.assertEqual((visits["coverage"], visits["plan_coverage"]), (17, 33))
        self.assertIsNone(self.profile()["execution"]["meetings"]["expected"])

    def test_a_quarter_and_a_month_narrow_the_work_and_never_the_ssa(self):
        from datetime import date

        year = int(self.fy)
        october = Activity.objects.create(
            school=self.schools["Alpha"],
            activity_type="school_visit",
            status="ia_verified",
            fy=self.fy,
            planned_date=date(year - 1, 10, 12),
        )
        Activity.objects.create(
            school=self.schools["Bravo"],
            activity_type="school_visit",
            status="scheduled",
            fy=self.fy,
            planned_date=date(year, 2, 3),
        )
        scope = engine.district_scope(self.district)

        whole = engine.build(scope, self.fy)
        first = engine.build(scope, self.fy, "Q1")
        month = engine.build(scope, self.fy, "M5")

        self.assertEqual(whole["execution"]["visits"]["planned"], 2)
        self.assertEqual(first["execution"]["visits"]["planned"], 1)
        self.assertEqual(first["execution"]["visits"]["completed"], 1)
        self.assertEqual(first["period_label"], "Q1 (Oct–Dec)")
        self.assertEqual(month["execution"]["visits"]["planned"], 1)
        self.assertEqual(month["period_label"], f"Feb {year}")
        # A school with nothing in the period is unplanned for the period.
        self.assertEqual(
            (whole["portfolio"]["unplanned"], first["portfolio"]["unplanned"]), (4, 5)
        )
        self.assertEqual(first["ssa"]["current"], whole["ssa"]["current"])
        # A period that is not one is the whole year.
        self.assertEqual(engine.build(scope, self.fy, "Q9")["period"], "")
        self.assertIsNotNone(october.id)

    def test_teachers_and_leaders_trained_are_their_own_figures(self):
        from apps.activities.models import ClusterActivityAttendance

        Activity.objects.create(
            school=self.schools["Alpha"],
            activity_type="in_school_training",
            status="ia_verified",
            fy=self.fy,
            teachers_attended=12,
            leaders_attended=2,
        )
        # Planned, not delivered: nobody is trained yet.
        Activity.objects.create(
            school=self.schools["Bravo"],
            activity_type="in_school_training",
            status="scheduled",
            fy=self.fy,
            teachers_attended=99,
        )
        training = Activity.objects.create(
            cluster=self.north,
            activity_type="cluster_training",
            status="closed",
            fy=self.fy,
        )
        meeting = Activity.objects.create(
            cluster=self.north,
            activity_type="cluster_meeting",
            status="closed",
            fy=self.fy,
        )
        for activity, school, teachers, leaders in (
            (training, self.schools["Bravo"], 5, 1),
            (training, self.outsider, 50, 9),
            (meeting, self.schools["Charlie"], 3, 4),
        ):
            ClusterActivityAttendance.objects.create(
                activity=activity,
                school=school,
                invited=True,
                attended=True,
                teachers=teachers,
                leaders=leaders,
            )

        people = engine.people(self.profile())

        # The outsider's fifty are another district's.
        self.assertEqual(
            (people["teachers_trained"], people["leaders_trained"]), (17, 3)
        )
        self.assertEqual(
            (people["teachers_in_school"], people["teachers_group"]), (12, 5)
        )
        self.assertEqual(people["schools_trained"], 2)
        # A meeting is not a training.
        self.assertEqual(
            (people["teachers_at_meetings"], people["leaders_at_meetings"]), (3, 4)
        )

    def test_a_project_shows_its_capacity_its_work_and_its_schools_ssa(self):
        from apps.projects.models import (
            Project,
            ProjectSchoolAssignment,
            ProjectStaffCapacity,
        )

        project = Project.objects.create(name="Profile Project", category="general")
        for name in ("Alpha", "Bravo"):
            ProjectSchoolAssignment.objects.create(
                project=project, school=self.schools[name]
            )
        ProjectSchoolAssignment.objects.create(project=project, school=self.outsider)
        ProjectStaffCapacity.objects.create(
            project=project, staff=self.officer, max_schools=10
        )
        Activity.objects.create(
            school=self.schools["Alpha"],
            activity_type="school_visit",
            status="ia_verified",
            fy=self.fy,
            project_id=project.id,
        )

        (row,) = self.profile()["projects"]

        self.assertEqual((row["schools"], row["project_schools"]), (2, 3))
        self.assertEqual((row["capacity"], row["capacity_left"]), (10, 7))
        self.assertEqual((row["planned"], row["completed"]), (1, 1))
        # Alpha 4 → 7, Bravo 6 → 5.
        self.assertEqual(
            (row["previous"], row["current"], row["change"]), (5.0, 6.0, 1.0)
        )
        self.assertEqual((row["improved"], row["declined"]), (1, 1))
        self.assertEqual(row["project_status"], "Active")

    def test_loans_are_for_readers_of_the_loan_register(self):
        profile = self.profile()

        # A Programme Lead has no loan portfolio: the register is closed.
        self.assertIsNone(engine.finance(profile, self.lead.user))
        finance = engine.finance(profile, self.director)
        self.assertEqual((finance["loans"], finance["cases"]), (0, 0))

    def test_the_pages_carry_them(self):
        client = Client()
        client.force_login(self.director, backend=BACKEND)
        base = f"/districts/{self.district.id}"

        overview = client.get(base, {"period": "Q1"}).content.decode()
        for label in (
            "Teachers Trained",
            "School Leaders Trained",
            "SSA Score",
            "School Loans",
        ):
            self.assertIn(label, overview)
        self.assertIn(" expected", overview)
        self.assertIn("work in Q1 (Oct–Dec)", overview)
        # The period travels with every link of the profile.
        self.assertIn(f"{base}?period=Q1&amp;tab=schools&amp;fy={self.fy}", overview)

        ssa = client.get(base, {"tab": "ssa"}).content.decode()
        self.assertIn(">To Target</th>", ssa)
        work = client.get(base, {"tab": "activities"}).content.decode()
        for heading in ("Expected This Year", "Schools Due", "Coverage"):
            self.assertIn(f">{heading}</th>", work)
        projects = client.get(base, {"tab": "projects"}).content.decode()
        self.assertIn("No project has a school in this portfolio.", projects)

        school = client.get(f"/schools/{self.schools['Alpha'].id}").content.decode()
        for label in ("Teachers Trained", "SSA Score", " expected"):
            self.assertIn(label, school)
