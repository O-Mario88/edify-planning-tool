"""Profile records: every figure of a profile opens the records it counted.

Owner's brief, 2026-10-10: "Every number must be traceable. There must be
zero orphan KPIs", "No 'Not Measured' for applicable quantitative KPIs ...
Show: 0", "If: District = 120 schools its school list must produce 120", and
"Online training attendance must be treated as a first-class training
channel".
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.analytics import profile_intelligence as engine
from apps.analytics import profile_records as records
from apps.analytics.test_profile_intelligence import BACKEND, ProfileFixture
from apps.geography.models import SubCounty, SubRegion
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.models import MostSignificantChangeStory

DONE = "ia_verified"


class RecordsFixture(ProfileFixture):
    """The district of `ProfileFixture`, placed in a sub-region, with two
    sub-counties, a holder and that holder's Programme Lead."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.sub_region = SubRegion.objects.create(
            name="Records Sub-region",
            normalized_name="records sub-region",
            region=cls.region,
        )
        cls.district.sub_region = cls.sub_region
        cls.district.save(update_fields=["sub_region"])
        cls.east = SubCounty.objects.create(name="East", district=cls.district)
        cls.west = SubCounty.objects.create(name="West", district=cls.district)
        for name, place in (
            ("Alpha", cls.east),
            ("Bravo", cls.east),
            ("Charlie", cls.east),
            ("Delta", cls.west),
            ("Echo", cls.west),
        ):
            School.objects.filter(id=cls.schools[name].id).update(sub_county=place)

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

        cls.lead = person("records-pl@edify.org", "Lena Lead", "Program Lead")
        cls.officer = person("records-cceo@edify.org", "Otto Officer", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.lead, supervisee=cls.officer
        )
        School.objects.filter(id=cls.schools["Alpha"].id).update(
            account_owner_id=cls.officer.id
        )
        cls.partner = Partner.objects.create(
            name="Records Partner", active_status=True, source="test"
        )

    def training(self, school, *, teachers=0, leaders=0, status=DONE, **extra):
        return Activity.objects.create(
            school=school,
            activity_type="in_school_training",
            status=status,
            fy=self.fy,
            planned_date=timezone.localdate() - timedelta(days=2),
            teachers_attended=teachers,
            leaders_attended=leaders,
            **extra,
        )

    def session(self, kind, cluster, *, status=DONE, days=-3, **extra):
        return Activity.objects.create(
            cluster=cluster,
            activity_type=kind,
            status=status,
            fy=self.fy,
            planned_date=timezone.localdate() + timedelta(days=days),
            **extra,
        )

    def attend(self, activity, school, *, attended=True, teachers=0, leaders=0):
        return ClusterActivityAttendance.objects.create(
            activity=activity,
            school=school,
            invited=True,
            attended=attended,
            teachers=teachers,
            leaders=leaders,
        )

    def rows(self, profile, what, **kwargs):
        return [
            (table, list(table["rows"][0 : len(table["rows"])]))
            for table in records.records(profile, what, **kwargs)
        ]


class WorkRecordsTest(RecordsFixture):
    def test_every_work_figure_opens_exactly_the_activities_it_counted(self):
        alpha, bravo = self.schools["Alpha"], self.schools["Bravo"]
        self.activity("school_visit", school=alpha, status=DONE)
        self.activity("school_visit", school=alpha)
        self.activity("school_visit", school=bravo, days=-4)  # past its date
        self.activity("school_visit", school=bravo, status="cancelled")
        self.training(alpha, teachers=5)
        self.training(bravo, status="scheduled")
        self.session("cluster_training", self.north)
        self.session("cluster_meeting", self.north)
        self.session("cluster_meeting", self.south, status="scheduled", days=6)
        self.session("cluster_meeting", self.south, status="scheduled", days=-6)
        profile = self.profile()
        work = profile["execution"]

        for what, figure in (
            ("visits", work["visits"]["planned"]),
            ("visits_done", work["visits"]["completed"]),
            ("visits_overdue", work["visits"]["overdue"]),
            ("trainings", work["trainings"]["planned"]),
            ("trainings_done", work["trainings"]["completed"]),
            ("meetings", work["meetings"]["planned"]),
            ("meetings_done", work["meetings"]["completed"]),
            ("meetings_upcoming", work["meetings"]["upcoming"]),
            ("meetings_overdue", work["meetings"]["overdue"]),
        ):
            with self.subTest(what=what):
                (table,) = records.records(profile, what)
                self.assertEqual(len(table["rows"]), figure)
        # Cancelled work is in no list, as it is in no figure.
        self.assertEqual((work["visits"]["planned"], work["visits"]["overdue"]), (3, 1))
        self.assertEqual(work["meetings"]["upcoming"], 1)

    def test_a_row_names_the_activity_and_opens_it(self):
        visit = self.activity("school_visit", school=self.schools["Alpha"], status=DONE)

        (table,) = records.records(self.profile(), "visits_done")
        (row,) = table["rows"][0:1]

        self.assertEqual(row[1]["href"], f"/activities/{visit.id}")
        self.assertEqual(row[3]["value"], "Alpha Primary")
        self.assertEqual(row[3]["href"], f"/schools/{self.schools['Alpha'].id}")

    def test_another_district_s_work_is_in_no_list(self):
        self.activity("school_visit", school=self.outsider, status=DONE)

        (table,) = records.records(self.profile(), "visits_done")

        self.assertEqual(len(table["rows"]), 0)


class ZeroStateTest(RecordsFixture):
    """ "No records: 0. Add one record: 1. Add another: 2." """

    def test_teachers_trained_counts_up_from_nothing(self):
        def figure():
            profile = self.profile()
            people = engine.people(profile)
            listed = sum(
                table["total"][-2]
                for table in records.records(profile, "teachers_trained")
            )
            by_school = sum(row["teachers"] for row in profile["_scores"].values())
            # The figure, its record list and the schools table agree.
            self.assertEqual(people["teachers_trained"], listed)
            self.assertEqual(people["teachers_trained"], by_school)
            return people["teachers_trained"]

        self.assertEqual(figure(), 0)
        self.training(self.schools["Alpha"], teachers=1)
        self.assertEqual(figure(), 1)
        group = self.session("cluster_training", self.north)
        self.attend(group, self.schools["Bravo"], teachers=1)
        self.assertEqual(figure(), 2)

    def test_a_training_still_to_come_trains_nobody_yet(self):
        self.training(self.schools["Alpha"], teachers=9, status="scheduled")

        self.assertEqual(engine.people(self.profile())["teachers_trained"], 0)

    def test_stories_count_up_and_only_an_approved_one_is_evidence(self):
        def story(status):
            return MostSignificantChangeStory.objects.create(
                user_id=self.director.id,
                school=self.schools["Alpha"],
                title="A change",
                narrative="What changed.",
                story_date=timezone.localdate(),
                status=status,
                intervention="leadership",
            )

        profile = self.profile()
        self.assertEqual(records.stories(profile)["total"], 0)
        story("draft")  # its author's own: not counted, not listed
        story("submitted")
        summary = records.stories(profile)
        self.assertEqual((summary["total"], summary["approved"]), (1, 0))
        story("approved")
        summary = records.stories(profile)
        self.assertEqual(
            (summary["total"], summary["approved"], summary["waiting"]), (2, 1, 1)
        )
        self.assertEqual(summary["areas"], [("Leadership", 2)])
        (listed,) = records.records(profile, "stories")
        (approved,) = records.records(profile, "stories_approved")
        self.assertEqual((len(listed["rows"]), len(approved["rows"])), (2, 1))

    def test_a_profile_with_nothing_says_zero_and_never_not_measured(self):
        """An empty district: every figure of every tab is a number."""
        from apps.geography.models import District

        empty = District.objects.create(name="Empty", region=self.region)
        client = Client()
        client.force_login(self.director, backend=BACKEND)

        for tab in ("overview", "ssa", "clusters", "schools", "activities"):
            with self.subTest(tab=tab):
                body = client.get(
                    f"/districts/{empty.id}", {"tab": tab}
                ).content.decode()
                self.assertNotIn("Not measured", body)
                self.assertNotIn("Not recorded", body)
        overview = client.get(f"/districts/{empty.id}").content.decode()
        values = re.findall(
            r'<strong class="context-metrics__value[^"]*" title="([^"]*)"', overview
        )
        self.assertGreater(len(values), 12)
        for value in values:
            self.assertRegex(value, r"^(UGX )?[+-]?[\d.,]+%?$")


class ChannelTest(RecordsFixture):
    def test_online_training_is_a_channel_of_its_own(self):
        alpha, bravo, charlie = (
            self.schools[name] for name in ("Alpha", "Bravo", "Charlie")
        )
        self.training(alpha, teachers=4, leaders=1)
        self.training(bravo, status="scheduled", delivery_type="partner")
        group = self.session("cluster_training", self.north)
        self.attend(group, alpha, teachers=3)
        self.attend(group, bravo, attended=False)
        online = self.session(
            "cluster_training", self.north, programme_delivery_mode="online"
        )
        self.attend(online, alpha, teachers=2, leaders=2)
        self.attend(online, bravo, teachers=1)
        self.attend(online, charlie, attended=False)
        self.session(
            "cluster_training",
            self.south,
            status="scheduled",
            days=9,
            programme_delivery_mode="online",
        )
        PartnerAssignment.objects.create(
            school=bravo,
            partner=self.partner,
            assigning_staff_id=self.officer.id,
            expected_activity_type="in_school_training",
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        profile = self.profile()

        channels = {row["key"]: row for row in records.channels(profile)}

        in_school, group_row, online_row = (
            channels[key] for key in ("in_school", "group", "online")
        )
        self.assertEqual(
            (
                in_school["planned"],
                in_school["staff_planned"],
                in_school["partner_assigned"],
                in_school["partner_scheduled"],
                in_school["completed"],
                in_school["people"],
            ),
            (2, 1, 1, 1, 1, 5),
        )
        self.assertEqual(
            (group_row["planned"], group_row["completed"], group_row["rate"]),
            (1, 1, 50),
        )
        self.assertEqual(
            (
                online_row["planned"],
                online_row["scheduled"],
                online_row["completed"],
                online_row["invited"],
                online_row["attended"],
                online_row["rate"],
                online_row["people"],
            ),
            (2, 1, 1, 3, 2, 67, 5),
        )
        # Assigned, scheduled and completed are three figures, and the three
        # channels are the Trainings line, neither more nor less.
        self.assertEqual(
            sum(row["planned"] for row in channels.values()),
            profile["execution"]["trainings"]["planned"],
        )
        for row in channels.values():
            with self.subTest(channel=row["key"]):
                (planned,) = records.records(profile, row["what"])
                (done,) = records.records(profile, row["what"] + "_done")
                self.assertEqual(len(planned["rows"]), row["planned"])
                self.assertEqual(len(done["rows"]), row["completed"])

    def test_meetings_are_read_by_kind_with_their_attendance(self):
        held = self.session("cluster_meeting", self.north, meeting_kind="only_meeting")
        self.session(
            "cluster_meeting",
            self.south,
            status="scheduled",
            days=4,
            meeting_kind="cluster_leaders",
        )
        self.attend(held, self.schools["Alpha"])
        self.attend(held, self.schools["Bravo"])
        self.attend(held, self.schools["Charlie"], attended=False)

        meetings = records.meetings(self.profile())

        self.assertEqual(
            (meetings["planned"], meetings["held"], meetings["upcoming_count"]),
            (2, 1, 1),
        )
        self.assertEqual(
            (meetings["invited"], meetings["attended"], meetings["schools"]), (3, 2, 2)
        )
        self.assertEqual(meetings["rate"], 67)
        self.assertEqual(
            {row["label"]: (row["planned"], row["held"]) for row in meetings["kinds"]},
            {"Only Meeting": (1, 1), "Cluster Leaders Meeting": (1, 0)},
        )
        self.assertEqual(len(meetings["upcoming"]), 1)


class InterventionTest(RecordsFixture):
    def _score(self, school, fy, **scores):
        record = SsaRecord.objects.filter(school=school, fy=fy).first()
        for key, value in scores.items():
            SsaScore.objects.filter(ssa_record=record, intervention=key).update(
                score=value
            )

    def test_the_best_and_the_struggling_are_named_by_a_stated_rule(self):
        alpha = self.schools["Alpha"]  # 4.0 → 7.0 on every intervention
        self._score(alpha, self.fy, leadership=9.5, enrolment=2.0, financial_health=8.0)
        self._score(alpha, self.last, enrolment=6.0)
        profile = engine.build(engine.school_scope(alpha), self.fy)

        best, struggling = profile["ssa"]["best"], profile["ssa"]["struggling"]

        # Leadership rose most (4.0 → 9.5); enrolment is the one that fell,
        # though nothing says it is the only low score.
        self.assertEqual((best["key"], best["basis"]), ("leadership", "change"))
        self.assertEqual(
            (struggling["key"], struggling["basis"]), ("enrolment", "change")
        )
        self.assertEqual(struggling["change"], -4.0)
        self.assertIn("declined most", profile["ssa"]["method"])

    def test_a_sharp_decline_outranks_a_low_score(self):
        """ "Do not simply select the lowest absolute score if another
        intervention is declining sharply." """
        alpha = self.schools["Alpha"]
        self._score(alpha, self.last, leadership=9.0, enrolment=1.0)
        self._score(alpha, self.fy, leadership=5.0, enrolment=1.0)

        struggling = engine.build(engine.school_scope(alpha), self.fy)["ssa"][
            "struggling"
        ]

        # Enrolment is the lowest (1.0) but did not move; leadership fell 4.
        self.assertEqual(struggling["key"], "leadership")

    def test_where_every_intervention_moved_alike_they_are_still_two(self):
        bravo = self.schools["Bravo"]  # 6.0 → 5.0 on every intervention
        profile = engine.build(engine.school_scope(bravo), self.fy)

        best, struggling = profile["ssa"]["best"], profile["ssa"]["struggling"]

        self.assertIsNotNone(struggling)
        self.assertNotEqual(best["key"], struggling["key"])

    def test_no_score_this_year_names_neither(self):
        delta = self.schools["Delta"]  # last year only
        ssa = engine.build(engine.school_scope(delta), self.fy)["ssa"]

        self.assertIsNone(ssa["best"])
        self.assertIsNone(ssa["struggling"])

    def test_an_intervention_opens_its_schools_and_the_work_that_named_it(self):
        focused = self.activity(
            "school_visit", school=self.schools["Alpha"], status=DONE
        )
        Activity.objects.filter(id=focused.id).update(focus_intervention="leadership")
        self.activity("school_visit", school=self.schools["Alpha"], status=DONE)
        profile = self.profile()

        schools, work = records.records(profile, "intervention", key="leadership")

        # Every school with a confirmed score for it in either year.
        self.assertEqual(len(schools["rows"]), 5)
        alpha = next(
            row for row in schools["rows"] if row[1]["value"] == "Alpha Primary"
        )
        self.assertEqual([cell["value"] for cell in alpha[2:5]], [4.0, 7.0, 3.0])
        self.assertEqual(len(work["rows"]), 1)
        self.assertEqual(
            records.focus_work(profile), {"leadership": {"planned": 1, "done": 1}}
        )
        self.assertEqual(records.records(profile, "intervention", key="nonsense"), [])

    def test_improving_and_declining_are_lists_of_their_own(self):
        rankings = self.profile()["rankings"]

        self.assertEqual(
            [row["name"] for row in rankings["improving_schools"]], ["Alpha Primary"]
        )
        self.assertEqual(
            [row["name"] for row in rankings["declining_schools"]], ["Bravo Primary"]
        )
        self.assertIn("biggest change comes first", rankings["movers_method"])


class ReconciliationTest(RecordsFixture):
    """ "If: District = 120 schools, its school list must produce 120." """

    def test_each_level_is_the_sum_of_the_level_beneath_it(self):
        country = engine.build(engine.country_scope(""), self.fy)
        sub_region = engine.build(engine.sub_region_scope(self.sub_region), self.fy)
        district = self.profile()

        # Seven schools in the country: the district's six and the outsider.
        self.assertEqual(country["portfolio"]["schools"], 7)
        by_district = engine.groups(country, "districts")
        self.assertEqual(
            sum(row["schools"] for row in by_district["rows"])
            + by_district["unplaced"],
            country["portfolio"]["schools"],
        )
        by_sub_region = engine.groups(country, "sub_regions")
        self.assertEqual(
            sum(row["schools"] for row in by_sub_region["rows"])
            + by_sub_region["unplaced"],
            country["portfolio"]["schools"],
        )
        # A school's sub-region is its district's: the school's own column
        # is empty here, as an upload leaves it.
        self.assertEqual(sub_region["portfolio"]["schools"], 6)
        self.assertEqual(
            {row["name"]: row["schools"] for row in by_sub_region["rows"]},
            {"Records Sub-region": 6},
        )
        self.assertEqual(by_sub_region["unplaced"], 1)
        # The district's list is the district's figure, and so is every
        # cluster's and every sub-county's.
        self.assertEqual(len(engine.school_rows(district)), 6)
        by_place = engine.groups(district, "sub_counties")
        self.assertEqual(
            {row["name"]: row["schools"] for row in by_place["rows"]},
            {"East": 3, "West": 2},
        )
        self.assertEqual(by_place["unplaced"], 1)
        for row in by_place["rows"]:
            listed = engine.school_rows(district, where=("sub_county_id", row["id"]))
            self.assertEqual(len(listed), row["schools"])
        for row in district["clusters"]:
            cluster = engine.build(
                engine.cluster_scope(
                    self.north if row["id"] == self.north.id else self.south
                ),
                self.fy,
            )
            # A cluster's own profile also counts its school in another
            # district; the district's line counts its own.
            self.assertGreaterEqual(cluster["portfolio"]["schools"], row["schools"])

    def test_a_closed_or_deleted_school_is_in_no_count(self):
        School.objects.filter(id=self.schools["Echo"].id).update(
            deleted_at=timezone.now()
        )

        district = self.profile()

        self.assertEqual(district["portfolio"]["schools"], 5)
        self.assertEqual(len(engine.school_rows(district)), 5)
        self.assertEqual(
            sum(r["schools"] for r in engine.groups(district, "sub_counties")["rows"]),
            4,
        )

    def test_another_year_s_work_and_scores_stay_in_their_year(self):
        Activity.objects.create(
            school=self.schools["Alpha"],
            activity_type="school_visit",
            status=DONE,
            fy=self.last,
            planned_date=date(int(self.last) - 1, 11, 20),
        )

        this_year, last_year = self.profile(), self.profile(self.last)

        self.assertEqual(this_year["execution"]["visits"]["completed"], 0)
        self.assertEqual(last_year["execution"]["visits"]["completed"], 1)
        self.assertEqual(len(records.records(this_year, "visits_done")[0]["rows"]), 0)
        # Last year's page reads last year's score as its current one.
        self.assertEqual(last_year["ssa"]["current"], 4.5)

    def test_hand_overs_are_three_stages_that_add_up(self):
        def hand_over(school, status, **extra):
            return PartnerAssignment.objects.create(
                school=self.schools[school],
                partner=self.partner,
                assigning_staff_id=self.officer.id,
                expected_activity_type="school_visit",
                status=status,
                **extra,
            )

        hand_over("Alpha", PartnerAssignment.STATUS_ASSIGNED)
        hand_over("Bravo", "scheduled")
        hand_over("Charlie", PartnerAssignment.STATUS_COMPLETED)
        hand_over("Delta", "returned_to_staff")  # taken back: nobody's
        profile = self.profile()
        pipeline = profile["portfolio"]["handovers"]

        counts = {
            stage: len(records.records(profile, f"handovers{stage}")[0]["rows"])
            for stage in ("", "_awaiting", "_scheduled", "_completed")
        }

        self.assertEqual(counts[""], pipeline["assigned"])
        self.assertEqual(
            (counts["_awaiting"], counts["_scheduled"], counts["_completed"]),
            (pipeline["awaiting"], pipeline["scheduled"], pipeline["completed"]),
        )
        self.assertEqual(
            counts["_awaiting"] + counts["_scheduled"] + counts["_completed"],
            counts[""],
        )
        # An assignment is not a school: one partner, three schools.
        (partners,) = records.records(profile, "partners")
        self.assertEqual(
            [[cell["value"] for cell in row] for row in partners["rows"]],
            [["Records Partner", 3, 3]],
        )

    def test_a_repeated_training_is_counted_each_time(self):
        """Two trainings at one school are two trainings and one school."""
        self.training(self.schools["Alpha"], teachers=3)
        self.training(self.schools["Alpha"], teachers=4)
        profile = self.profile()

        self.assertEqual(profile["execution"]["trainings"]["completed"], 2)
        self.assertEqual(engine.people(profile)["teachers_trained"], 7)
        self.assertEqual(engine.people(profile)["schools_trained"], 1)


class IdentityTest(RecordsFixture):
    def facts(self, profile, subject=None):
        return {
            fact["label"]: fact
            for fact in records.identity(profile, subject, may_open_staff=True)
        }

    def test_a_school_says_where_it_sits_and_who_holds_it(self):
        alpha = School.objects.get(id=self.schools["Alpha"].id)
        PartnerAssignment.objects.create(
            school=alpha,
            partner=self.partner,
            assigning_staff_id=self.officer.id,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        profile = engine.build(engine.school_scope(alpha), self.fy)

        facts = self.facts(profile, alpha)

        self.assertEqual(facts["School ID"]["value"], "PROFILE-0")
        self.assertEqual(facts["Type"]["value"], "Core")
        self.assertEqual(facts["District"]["href"], f"/districts/{self.district.id}")
        self.assertEqual(facts["Sub-region"]["value"], "Records Sub-region")
        self.assertEqual(facts["Sub-county"]["value"], "East")
        self.assertEqual(facts["Cluster"]["href"], f"/clusters/{self.north.id}")
        self.assertEqual(facts["CCEO"]["people"][0]["name"], "Otto Officer")
        self.assertEqual(facts["Programme Lead"]["people"][0]["name"], "Lena Lead")
        self.assertEqual(facts["Partner"]["people"][0]["name"], "Records Partner")
        self.assertEqual(facts["Status"]["value"], "Operating")
        self.assertIn("Fiscal Year", facts)

    def test_a_school_nobody_holds_says_so(self):
        echo = School.objects.get(id=self.schools["Echo"].id)

        facts = self.facts(engine.build(engine.school_scope(echo), self.fy), echo)

        self.assertEqual(facts["CCEOs"]["value"], "Not assigned")

    def test_a_district_names_its_sub_region_and_its_people(self):
        facts = self.facts(self.profile(), self.district)

        self.assertEqual(facts["Type"]["value"], "District")
        self.assertEqual(
            facts["Sub-region"]["href"], f"/sub-regions/{self.sub_region.id}"
        )
        self.assertEqual(facts["Programme Lead"]["people"][0]["name"], "Lena Lead")


class ProfilePagesTest(RecordsFixture):
    """Every figure on every profile page is a link, and the link opens."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.director, backend=BACKEND)
        visit = self.activity("school_visit", school=self.schools["Alpha"], status=DONE)
        visit.focus_intervention = "leadership"
        visit.save(update_fields=["focus_intervention"])
        self.training(self.schools["Alpha"], teachers=6, leaders=2)
        held = self.session("cluster_meeting", self.north)
        self.attend(held, self.schools["Alpha"], teachers=2)

    def pages(self):
        alpha = self.schools["Alpha"].id
        return {
            "country": (
                "/country-profile",
                ("overview", "ssa", "clusters", "activities"),
            ),
            "sub_region": (
                f"/sub-regions/{self.sub_region.id}",
                ("overview", "districts", "activities"),
            ),
            "district": (
                f"/districts/{self.district.id}",
                (
                    "overview",
                    "ssa",
                    "sub_counties",
                    "clusters",
                    "schools",
                    "activities",
                ),
            ),
            "cluster": (
                f"/clusters/{self.north.id}",
                ("portfolio", "school_ssa", "work"),
            ),
            "school": (
                f"/schools/{alpha}",
                ("overview", "ssa", "activities", "academic", "stories", "details"),
            ),
            "staff": (f"/staff/{self.officer.user_id}", ("overview", "activities")),
            "partner": (f"/partners/{self.partner.id}", ("overview", "activities")),
        }

    def test_no_figure_is_an_orphan_and_none_says_not_measured(self):
        for name, (url, tabs) in self.pages().items():
            for tab in tabs:
                with self.subTest(profile=name, tab=tab):
                    response = self.client.get(url, {"tab": tab})
                    self.assertEqual(response.status_code, 200)
                    body = response.content.decode()
                    # A figure that opens nothing is drawn as plain text.
                    orphans = re.findall(
                        r'<span class="context-metrics__text">.*?'
                        r'<span class="context-metrics__label"[^>]*>(.*?)</span>',
                        body,
                        re.S,
                    )
                    self.assertEqual(orphans, [])
                    self.assertNotIn("Not measured", body)

    def test_every_record_link_on_every_overview_opens_its_records(self):
        from html import unescape

        opened = set()
        for name, (url, tabs) in self.pages().items():
            body = self.client.get(url, {"tab": tabs[0]}).content.decode()
            links = {
                unescape(href)
                for href in re.findall(r'href="([^"]*(?:[?&]|&amp;)what=[^"]*)"', body)
            }
            self.assertGreater(len(links), 8, name)
            for href in sorted(links):
                with self.subTest(profile=name, href=href):
                    response = self.client.get(href)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("data-profile-records=", response.content.decode())
                    opened.add(re.search(r"what=([a-z_]+)", href).group(1))
        # The figures the brief names, each with a list behind it.
        for what in (
            "teachers_trained",
            "leaders_trained",
            "enrolment",
            "enrolment_growth",
            "learning",
            "stories",
            "ssa",
            "intervention",
            "visits_done",
            "trainings_done",
            "trainings_online",
            "meetings_done",
            "at_meetings",
            "partners",
        ):
            self.assertIn(what, opened)

    def test_a_figure_s_list_holds_the_figure(self):
        body = self.client.get(
            f"/districts/{self.district.id}", {"what": "teachers_trained"}
        ).content.decode()

        self.assertIn("Teachers trained: in-school trainings", body)
        total = body.split("data-profile-record-total", 1)[1].split("</tr>", 1)[0]
        self.assertEqual(re.findall(r"<strong>(\d+)</strong>", total), ["6", "2"])
        self.assertIn(f'href="/schools/{self.schools["Alpha"].id}"', body)
        # The way back to the summary it came from.
        self.assertIn("Back to the summary", body)

    def test_the_school_profile_is_the_shared_sections_over_one_school(self):
        url = f"/schools/{self.schools['Alpha'].id}"

        overview = self.client.get(url).content.decode()

        for label in (
            "Overview",
            "SSA",
            "Participation",
            "Academic",
            "Stories",
            "Details",
        ):
            self.assertIn(f"<span>{label}</span>", overview)
        self.assertIn("data-profile-identity", overview)
        self.assertIn('data-profile-intervention-pick="best"', overview)
        self.assertIn('data-profile-intervention-pick="struggling"', overview)
        # One school has no portfolio of schools to count.
        self.assertNotIn('aria-label="Portfolio"', overview)
        ssa = self.client.get(url, {"tab": "ssa"}).content.decode()
        self.assertIn("Intervention Matrix", ssa)
        self.assertIn("data-school-ssa-change", ssa)
        work = self.client.get(url, {"tab": "activities"}).content.decode()
        for row in ("in_school", "group", "online"):
            self.assertIn(f'data-profile-channel="{row}"', work)
        details = self.client.get(url, {"tab": "details"}).content.decode()
        self.assertIn("School Demographics", details)
        self.assertNotIn("data-profile-identity", details)

    def test_a_closed_school_keeps_its_profile(self):
        from apps.schools.models import School as SchoolModel

        closed = SchoolModel.objects.get(id=self.schools["Bravo"].id)
        SchoolModel.objects.filter(id=closed.id).update(
            operational_status="closed", closed_at=timezone.now()
        )

        profile = engine.build(
            engine.school_scope(SchoolModel.objects.get(id=closed.id)), self.fy
        )

        self.assertEqual(profile["portfolio"]["schools"], 1)
        self.assertEqual(self.profile()["portfolio"]["schools"], 5)

    def test_the_district_reads_its_sub_counties_and_each_opens_its_schools(self):
        url = f"/districts/{self.district.id}"

        body = self.client.get(url, {"tab": "sub_counties"}).content.decode()

        self.assertIn(
            f"tab=schools&amp;fy={self.fy}&amp;sub_county={self.east.id}", body
        )
        schools = self.client.get(
            url, {"tab": "schools", "sub_county": self.east.id}
        ).content.decode()
        self.assertEqual(schools.count("data-profile-school="), 3)

    def test_the_profile_costs_the_same_whatever_its_size(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def cost():
            with CaptureQueriesContext(connection) as queries:
                profile = self.profile()
                records.channels(profile)
                records.meetings(profile)
                records.stories(profile)
                records.focus_work(profile)
            return len(queries)

        before = cost()
        for index in range(12):
            school = School.objects.create(
                school_id=f"PROFILE-MORE-{index}",
                name=f"More {index} Primary",
                region=self.region,
                district=self.district,
                cluster_id=self.north.id,
            )
            self.training(school, teachers=1)

        self.assertEqual(cost(), before)


class PhoneKpiTest(RecordsFixture):
    def test_every_part_of_every_fact_is_centred_on_a_phone(self):
        """ "ALL KPI CONTENT MUST BE CENTERED." One shared rule, in the one
        KPI component, inside its phone block."""
        css = Path(settings.BASE_DIR, "static/css/components.css").read_text()
        phone = css.split("@media (max-width: 47.999rem) {", 1)[1].split(
            "/* end of the phone KPI grid */", 1
        )[0]

        both = phone.split(
            ".context-metrics .context-metrics__text,\n"
            "  .context-metrics .context-metrics__link {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("align-items: center;", both)
        self.assertIn("text-align: center;", both)
        parts = phone.split(
            ".context-metrics :is(.context-metrics__label, "
            ".context-metrics__value, .context-metrics__helper) {",
            1,
        )[1].split("}", 1)[0]
        self.assertIn("text-align: center;", parts)

    def test_a_strip_can_say_what_its_figures_are(self):
        from django.template import Context, Template

        html = Template(
            '{% load kpi_metrics %}{% kpi_strip title="Portfolio" %}'
            "{% kpi_metric %}{% kpi_label %}Schools{% endkpi_label %}6"
            "{% kpi_link %}/x{% endkpi_link %}{% endkpi_metric %}{% endkpi_strip %}"
        ).render(Context({}))

        self.assertIn('aria-label="Portfolio"', html)
        self.assertIn('href="/x"', html)
