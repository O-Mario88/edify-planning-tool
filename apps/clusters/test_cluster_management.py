"""Cluster Management: scores, the interventions ledger, the workspace.

Owner brief, 2026-10-08, third round ("build these"): Cluster Health and
Cluster Impact with weights the Country Director and Impact Assessment set, a
maturity level, Teacher and Leader indices, the "Cluster Intervention" trace,
and the brief's eighteen sections.

What is held:

* a score is a weighted mean of the parts that can be measured — a part with
  no figure is left out, never counted as zero — and below the minimum number
  of parts there is no score;
* a weight change is a new record and moves every cluster's score;
* a maturity level is reached only when every level below it is;
* an intervention's outcome is the SSA movement of the schools it reached, on
  the same pairs the SSA Movement tab shows, and a school nothing reached is
  named;
* a workspace figure is the figure its link opens, a reader sees only their
  own clusters, the eighteen sections are tabs behind one sidebar entry, and
  each downloads as CSV.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters import interventions, scores, workspace
from apps.clusters.models import Cluster, ClusterScoreSetting
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.clusters.test_cluster_profile_tabs import _ClusterCase
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.schools.models import SchoolEnrollmentHistory
from apps.ssa.models import SsaRecord, SsaScore


class _Scored(_ClusterCase):
    """A cluster with two meetings and a Leadership training this year, and
    SSA in both years: one school came to everything and rose, one came to
    nothing and fell."""

    def setUp(self):
        super().setUp()
        self.rises, self.falls = self._school(0), self._school(1)
        self.today = date(int(self.fy) - 1, 12, 15)
        self.meetings = [
            self._session("cluster_meeting", date(int(self.fy) - 1, 10, day))
            for day in (5, 19)
        ]
        self.training = self._session(
            "cluster_training",
            date(int(self.fy) - 1, 11, 2),
            focus_intervention="leadership",
        )
        for school, before, after in ((self.rises, 5.0, 7.0), (self.falls, 6.0, 4.0)):
            self._ssa(school, self.last_fy, before, month=11)
            self._ssa(school, self.fy, after, month=12)

    def _session(self, kind, day, *, status="ia_verified", came=None, **kw):
        session = Activity.objects.create(
            activity_type=kind,
            cluster=self.cluster,
            fy=self.fy,
            planned_date=day,
            status=status,
            **kw,
        )
        for school in (self.rises, self.falls):
            ClusterActivityAttendance.objects.create(
                activity=session,
                school=school,
                invited=True,
                attended=school is self.rises if came is None else school in came,
                teachers=5 if school is self.rises else None,
                leaders=2 if school is self.rises else None,
            )
        return session

    def _ssa(self, school, fy, score, *, month):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=score,
            verification_status="confirmed",
            date_of_ssa=datetime(int(fy) - 1, month, 1, tzinfo=timezone.utc),
            uploaded_by="test",
        )
        for area in ("leadership", "financial_health", "teaching_environment"):
            SsaScore.objects.create(ssa_record=record, intervention=area, score=score)

    def _card(self, **kw):
        facts = scores.gather([self.cluster.id], fy=self.fy, today=self.today)
        return scores.scorecards([self.cluster.id], fy=self.fy, facts=facts, **kw)[
            self.cluster.id
        ]


class ScoresTest(_Scored):
    def test_each_part_is_a_share_with_its_basis_in_words(self):
        card = self._card()
        health = {d.key: d for d in card.health.dimensions}
        impact = {d.key: d for d in card.impact.dimensions}

        # Three sessions due and delivered; one school kept all three
        # invitations and the other none.
        self.assertEqual(health["meetings"].score, 100.0)
        self.assertIn("2 of 2 meetings due by now delivered", health["meetings"].basis)
        self.assertEqual(health["trainings"].score, 100.0)
        self.assertEqual(health["attendance"].score, 50.0)
        self.assertIn("3 of 6 invitations kept", health["attendance"].basis)
        self.assertEqual(health["participation"].score, 50.0)
        self.assertEqual(health["planning"].score, 100.0)
        # One of two schools has missed three in a row.
        self.assertEqual(health["follow_up"].score, 50.0)

        self.assertEqual(impact["ssa"].score, 50.0)
        self.assertIn("1 of 2 schools improved", impact["ssa"].basis)
        # The school that came to the Leadership training rose on Leadership;
        # the one that stayed away is not a trained school.
        self.assertEqual(impact["training_effect"].score, 100.0)
        self.assertEqual(impact["meeting_engagement"].score, 50.0)
        # Nothing recorded: the part says so and has no score.
        self.assertIsNone(impact["exams"].score)
        self.assertIn(
            "No school has a confirmed learning result", impact["exams"].basis
        )
        self.assertIsNone(impact["enrolment"].score)
        self.assertEqual(impact["loans"].score, 0.0)

    def test_a_part_with_no_figure_is_left_out_not_counted_as_zero(self):
        card = self._card()

        # Health: every part measured. (20*100 + 20*100 + 20*50 + 20*50 +
        # 10*100 + 10*50) / 100.
        self.assertEqual(card.health.score, 75)
        self.assertEqual(card.health.band, ("High", "success"))
        self.assertEqual(card.health.coverage, "6 of 6 parts measured")
        # Impact: Enrolment and Exams have no figure, and the Teacher index
        # stands on too few parts to be one: 30 points are not in the divisor.
        measured = {d.key for d in card.impact.scored}
        self.assertEqual(
            measured,
            {
                "ssa",
                "training_effect",
                "meeting_engagement",
                "leader",
                "bt",
                "loans",
            },
        )
        total = sum(d.weight for d in card.impact.scored)
        expected = round(sum(d.score * d.weight for d in card.impact.scored) / total)
        self.assertEqual(card.impact.score, expected)
        self.assertEqual(card.impact.coverage, "6 of 9 parts measured")

    def test_too_few_parts_is_no_score(self):
        Activity.objects.all().delete()
        SsaRecord.objects.all().delete()

        card = self._card()

        self.assertIsNone(card.impact.score)
        self.assertEqual(card.impact.band, ("Not enough data", "neutral"))
        self.assertIsNone(card.teacher.score)

    def test_the_indices_say_what_is_not_collected(self):
        card = self._card()
        teacher = {d.key: d for d in card.teacher.dimensions}

        self.assertEqual(teacher["training_attendance"].score, 50.0)
        self.assertIn("5 teachers reached", teacher["training_attendance"].basis)
        self.assertEqual(teacher["teaching_ssa"].score, 50.0)
        # Learning Environment was never scored: left out, two parts remain,
        # which is fewer than a score needs by default.
        self.assertIsNone(teacher["learning_env_ssa"].score)
        self.assertIsNone(card.teacher.score)
        self.assertEqual(card.leader.score, 50)
        self.assertIn("Classroom practice adoption", scores.NOT_COLLECTED["teacher"])

    def test_weights_are_set_as_a_new_record_and_move_the_score(self):
        before = self._card().health.score
        weights = scores.default_weights()
        weights["health"] = {key: 0 for key in weights["health"]}
        weights["health"]["meetings"] = 10
        weights["health"]["trainings"] = 10
        weights["health"]["planning"] = 10

        scores.save_settings(
            weights=weights,
            maturity=dict(scores.MATURITY_DEFAULTS),
            actor_id=self.cd.id,
            note="Delivery only",
        )
        scores.save_settings(
            weights=weights, maturity={"healthy_health": 90}, actor_id=self.cd.id
        )

        self.assertEqual(ClusterScoreSetting.objects.count(), 2)
        settings = scores.current_settings()
        self.assertFalse(settings.is_default)
        self.assertEqual(settings.maturity["healthy_health"], 90.0)
        # A rule the form did not send keeps its starting value.
        self.assertEqual(settings.maturity["model_stories"], 2)
        after = self._card()
        self.assertEqual(before, 75)
        self.assertEqual(after.health.score, 100)
        self.assertEqual(after.health.coverage, "3 of 3 parts measured")

    def test_a_score_with_no_weight_at_all_is_refused(self):
        weights = scores.default_weights()
        weights["impact"] = {key: 0 for key in weights["impact"]}

        with self.assertRaises(BadRequest):
            scores.save_settings(weights=weights, maturity={}, actor_id=self.cd.id)
        self.assertEqual(ClusterScoreSetting.objects.count(), 0)

    def test_a_level_is_reached_only_when_every_level_below_it_is(self):
        maturity = self._card().maturity

        # Three sessions and half the schools represented: Active. Health is
        # 75 and half the schools improved: Healthy.
        self.assertEqual((maturity["level"], maturity["label"]), (3, "Healthy"))
        self.assertEqual(maturity["next"]["label"], "High Impact")
        self.assertEqual(
            [c["reached"] for c in maturity["criteria"]],
            [True, True, True, False, False],
        )

        # Without sessions the cluster is Forming, whatever its SSA says.
        Activity.objects.all().delete()
        forming = self._card().maturity
        self.assertEqual((forming["level"], forming["label"]), (1, "Forming"))

    def test_the_profile_tab_shows_a_score_its_parts_and_the_maturity_table(self):
        self.client.force_login(self.cd)
        body = self._page(tab="scores").content.decode()

        self.assertIn('data-cluster-profile-panel="scores"', body)
        self.assertIn("Cluster Health:", body)
        self.assertEqual(body.count("data-score-part="), 6)
        self.assertIn("kept, FY", body)
        self.assertIn('href="/cluster-management/scoring"', body)

        teacher = self._page(tab="scores", part="teacher").content.decode()
        self.assertIn("Teacher Impact: Not Enough Data", teacher)
        self.assertIn("data-score-not-collected", teacher)
        self.assertIn("Lesson quality", teacher)

        maturity = self._page(tab="scores", part="maturity").content.decode()
        self.assertEqual(maturity.count("data-maturity-level="), 5)


class InterventionsTest(_Scored):
    def test_an_intervention_is_traced_to_the_schools_it_reached(self):
        visit = Activity.objects.create(
            activity_type="school_visit",
            school=self.falls,
            fy=self.fy,
            planned_date=date(int(self.fy) - 1, 11, 20),
            status="ia_verified",
            focus_intervention="leadership",
        )
        Activity.objects.create(
            activity_type="school_visit",
            school=self.falls,
            fy=self.fy,
            planned_date=date(int(self.fy) - 1, 11, 25),
            status="scheduled",
        )

        ledger = interventions.cluster_interventions(self.cluster, fy=self.fy)
        rows = {r.key: r for r in ledger["all_rows"]}

        # Two meetings, the training and the delivered visit; a planned visit
        # is an intention, not an intervention.
        self.assertEqual(len(rows), 4)
        training = rows[f"session-{self.training.id}"]
        self.assertEqual(training.kind, "Group Training")
        self.assertEqual(training.area_label, "Leadership")
        self.assertIn("1 of 2 schools", training.reach)
        self.assertEqual((training.compared, training.better), (1, 1))
        self.assertEqual(training.outcome, "1 of 1 schools rose on Leadership")
        # The visit reached the school whose Leadership fell.
        own = rows[f"activity-{visit.id}"]
        self.assertEqual(own.school_code, "TAB-001")
        self.assertEqual(own.outcome, "Leadership -2.0")
        self.assertEqual(own.outcome_tone, "danger")
        # A meeting with no SSA area named claims no outcome.
        meeting = rows[f"session-{self.meetings[0].id}"]
        self.assertEqual(meeting.outcome, "No SSA area named")

        leadership = next(a for a in ledger["areas"] if a.key == "leadership")
        self.assertEqual(leadership.interventions, 2)
        self.assertEqual(leadership.reached_count, 2)
        self.assertEqual((leadership.better, leadership.worse), (1, 1))
        self.assertEqual((leadership.before, leadership.after), (5.5, 5.5))
        self.assertEqual(ledger["unreached"], [])

    def test_a_school_nothing_reached_is_named(self):
        ledger = interventions.cluster_interventions(self.cluster, fy=self.fy)

        self.assertEqual([s["code"] for s in ledger["unreached"]], ["TAB-001"])
        self.assertEqual(ledger["reached_count"], 1)

        only = interventions.cluster_interventions(
            self.cluster, fy=self.fy, area="leadership"
        )
        self.assertEqual([r.kind for r in only["rows"]], ["Group Training"])

    def test_the_tab_has_three_views_and_the_unreached_school_can_be_scheduled(self):
        body = self._page(tab="interventions").content.decode()
        self.assertIn('data-cluster-profile-panel="interventions"', body)
        self.assertEqual(body.count("data-intervention="), 3)
        self.assertIn("1 of 1 schools rose on Leadership", body)
        self.assertIn("not a measure of what the work caused", body)
        for heading in ("School ID", "School / Cluster", "SSA Outcome"):
            self.assertIn(f">{heading}</th>", body)

        areas = self._page(tab="interventions", view="areas").content.decode()
        self.assertEqual(areas.count("data-intervention-area="), 8)
        self.assertIn("view=all&amp;area=leadership", areas)

        unreached = self._page(tab="interventions", view="unreached").content.decode()
        self.assertIn(f'data-unreached-school="{self.falls.id}"', unreached)
        self.assertIn("/planning/schedule-modal?school_id=TAB-001", unreached)

    def test_courses_are_compared_on_the_schools_that_attended(self):
        facts = scores.gather([self.cluster.id], fy=self.fy, today=self.today)

        courses = interventions.course_effectiveness(facts)

        self.assertEqual(len(courses), 1)
        row = courses[0]
        self.assertEqual(row["area"], "Leadership")
        self.assertEqual((row["sessions"], row["clusters"], row["readings"]), (1, 1, 1))
        self.assertEqual(
            (row["better"], row["better_pct"], row["mean_change"]), (1, 100, 2.0)
        )


class WorkspaceTest(_Scored):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cd)

    def _section(self, key="", **query):
        response = self.client.get(f"/cluster-management/{key}", query)
        self.assertEqual(response.status_code, 200, key)
        return response

    def test_the_brief_s_eighteen_sections_are_tabs_of_one_page(self):
        self.assertEqual(
            [s.label for s in workspace.SECTIONS],
            [
                "Command Center",
                "My Clusters",
                "Clusters",
                "Meetings",
                "Training",
                "Attendance",
                "Schools",
                "SSA Performance",
                "Teacher Impact",
                "Leader Impact",
                "Student Impact",
                "Academic Impact",
                "Loans & BT",
                "MSCS",
                "Impact Analytics",
                "Planning",
                "Evidence",
                "Reports",
            ],
        )
        body = self._section().content.decode()
        self.assertIn('data-cluster-management="command"', body)
        for section in workspace.SECTIONS:
            if section.key in ("my", "directory"):
                continue
            self.assertIn(
                f'href="/cluster-management/{section.key}?fy={self.fy}"', body
            )
        # The directory already has its page: the tab is a door to it.
        self.assertIn('<a class="oversight-entity-tabs__link" href="/clusters"', body)
        # My Clusters is for someone who holds one.
        self.assertNotIn("/cluster-management/my?", body)

    def test_every_section_opens_and_downloads(self):
        for section in workspace.SECTIONS:
            if section.url:
                response = self.client.get(f"/cluster-management/{section.key}")
                self.assertRedirects(
                    response, section.url, fetch_redirect_response=False
                )
                continue
            with self.subTest(section=section.key):
                body = self._section(section.key).content.decode()
                self.assertIn(f'data-cluster-management="{section.key}"', body)
                download = self.client.get(
                    f"/cluster-management/{section.key}", {"format": "csv"}
                )
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download["Content-Type"], "text/csv; charset=utf-8")
                self.assertIn(
                    f"cluster-management-{section.key}-fy{self.fy}.csv",
                    download["Content-Disposition"],
                )

    def test_a_command_center_figure_is_the_figure_its_link_opens(self):
        ws = workspace.load(self.cd, fy=self.fy, today=self.today)
        table = workspace.build(ws, "command")

        self.assertEqual(len(table.rows), 1)
        cells = dict(zip([c["label"] for c in table.columns], table.rows[0]["cells"]))
        self.assertEqual(cells["Cluster"]["text"], "Tabs cluster")
        self.assertEqual(cells["Schools"]["text"], "2")
        self.assertEqual(cells["Attendance"]["text"], "50%")
        self.assertEqual(cells["Attendance"]["query"], f"?tab=attendance&fy={self.fy}")
        self.assertEqual(cells["Absent 3+ Sessions"]["text"], "1")
        self.assertEqual(cells["SSA Change"]["text"], "0.0")
        self.assertEqual(cells["Health"]["text"], "75 · High")
        self.assertEqual(
            cells["Health"]["query"], f"?tab=scores&fy={self.fy}&part=health"
        )
        self.assertEqual(cells["Maturity"]["text"], "3 · Healthy")
        # A figure the records cannot give is a dash, not a zero.
        self.assertEqual(cells["Enrolment Growth"]["text"], "—")
        self.assertIn("1 cluster · 2 schools · 50% attendance", table.summary)

        body = self._section().content.decode()
        self.assertIn(
            f'href="/clusters/{self.cluster.id}/profile?tab=attendance&amp;fy={self.fy}"',
            body,
        )
        self.assertIn("75 · High", body)

    def test_the_attendance_section_names_the_absent_schools(self):
        body = self._section("attendance").content.decode()

        self.assertIn(f'data-cluster-management-row="{self.falls.id}"', body)
        self.assertNotIn(f'data-cluster-management-row="{self.rises.id}"', body)
        self.assertIn(f'href="/schools/{self.falls.id}"', body)
        for heading in ("School ID", "School Name", "Consecutive Misses"):
            self.assertIn(f">{heading}</th>", body)

    def test_ssa_performance_filters_by_area_and_counts_open_schools(self):
        body = self._section("ssa", area="leadership").content.decode()

        self.assertIn("SSA Performance: Leadership", body)
        self.assertIn("area=leadership&amp;verdict=declined", body)
        self.assertIn("2 schools compared · 1 improved · 1 declined", body)

    def test_impact_analytics_compares_clusters_and_courses(self):
        clusters = self._section("impact").content.decode()
        self.assertIn("Clusters Compared", clusters)
        self.assertIn(">Training Effectiveness</th>", clusters)

        courses = self._section("impact", view="courses").content.decode()
        self.assertIn("SSA Movement After Each Training", courses)
        self.assertIn("does not show that the training caused", courses)

    def test_student_impact_is_like_for_like(self):
        for school, before, after in ((self.rises, 100, 150), (self.falls, 200, 200)):
            for fy, figure in ((self.last_fy, before), (self.fy, after)):
                SchoolEnrollmentHistory.objects.create(
                    school=school,
                    fy=fy,
                    enrollment=figure,
                    recorded_at=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
                )

        body = self._section("students").content.decode()

        self.assertIn("300 to 350 learners (+16.7%) across 2 schools compared", body)

    def test_the_download_holds_the_rows_the_section_shows(self):
        response = self.client.get("/cluster-management/command", {"format": "csv"})

        lines = response.content.decode().splitlines()
        self.assertTrue(lines[0].startswith("Cluster,District,CCEO,Schools,Attendance"))
        self.assertIn("Tabs cluster", lines[1])
        self.assertIn("75 · High", lines[1])

    def test_a_reader_sees_only_the_clusters_in_their_scope(self):
        mine = _create_user("holder@workspace.test", EdifyRole.CCEO)
        other = _create_user("other@workspace.test", EdifyRole.CCEO)
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=mine.staff_profile.id
        )

        held = workspace.load(mine, fy=self.fy, today=self.today)
        self.assertEqual([c.id for c in held.clusters], [self.cluster.id])
        self.assertEqual(held.my_ids, {self.cluster.id})
        self.assertEqual(workspace.load(other, fy=self.fy).clusters, [])

        self.client.force_login(mine)
        body = self._section("my").content.decode()
        self.assertIn(f'data-cluster-management-row="{self.cluster.id}"', body)
        self.assertIn(f'href="/cluster-management/my?fy={self.fy}"', body)

    def test_one_sidebar_entry_and_only_for_the_roles_that_read_clusters(self):
        from apps.core.navigation import build_sidebar_for_user

        def entries(user):
            return [
                item["label"]
                for section in build_sidebar_for_user(user, "/dashboard")
                for item in section["items"]
                if "Cluster Management" in item["label"]
            ]

        self.assertEqual(entries(self.cd), ["Cluster Management"])
        cceo = _create_user("nav@workspace.test", EdifyRole.CCEO)
        self.assertEqual(entries(cceo), ["Cluster Management"])
        accountant = _create_user("books@workspace.test", EdifyRole.PROGRAM_ACCOUNTANT)
        self.assertEqual(entries(accountant), [])
        self.client.force_login(accountant)
        self.assertEqual(self.client.get("/cluster-management/").status_code, 302)


class ScoringPageTest(_Scored):
    def _post(self, **changes):
        data = {
            f"{key}__{dim}": str(default)
            for key, (_title, dimensions) in scores.SCORES.items()
            for dim, _label, default in dimensions
        }
        data.update(
            {
                f"maturity__{rule}": str(v)
                for rule, v in scores.MATURITY_DEFAULTS.items()
            }
        )
        data.update(changes)
        return self.client.post("/cluster-management/scoring", data)

    def test_the_country_director_sets_the_weights(self):
        self.client.force_login(self.cd)
        page = self.client.get("/cluster-management/scoring")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("These are the starting weights", body)
        self.assertIn('name="impact__ssa" value="25"', body)
        self.assertIn('name="maturity__model_stories" value="2"', body)

        response = self._post(impact__ssa="60", note="SSA first")

        self.assertRedirects(response, "/cluster-management/scoring")
        saved = ClusterScoreSetting.objects.get()
        self.assertEqual(saved.impact_weights["ssa"], 60.0)
        self.assertEqual(saved.set_by, self.cd.id)
        self.assertEqual(saved.note, "SSA first")
        after = self.client.get("/cluster-management/scoring").content.decode()
        self.assertIn('name="impact__ssa" value="60"', after)
        self.assertIn("Last set on", after)

    def test_an_officer_may_read_the_scores_and_not_set_them(self):
        cceo = _create_user("officer@scoring.test", EdifyRole.CCEO)
        self.client.force_login(cceo)

        self.assertEqual(
            self.client.get("/cluster-management/scoring").status_code, 302
        )
        self.assertEqual(self._post(impact__ssa="90").status_code, 403)
        self.assertEqual(ClusterScoreSetting.objects.count(), 0)
