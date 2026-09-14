"""Programme learning and impact findings (IA review, owner, 2026-09-13).

Pinned here:
- Programme Learning compares weak-baseline schools a programme reached with
  similar schools it did not, per training group and per EdTech exposure,
  with Holm-corrected verdicts and the shared evidence grade; its filters
  reach the table; another country's schools never enter it;
- lending rows flag an immature cohort; visits reuse the engine's corrected
  per-intervention comparison;
- Impact Assessment reads the Regional Lead's SHARED training observations of
  its own country only;
- a finding is written by IA, reviewed by someone else (a second IA officer;
  the Country Director only where the country has one officer), keeps the
  server's figures rather than the browser's, and a revision supersedes the
  approved finding once approved;
- /ia/attribution/ lands on the Training tab; the pages refuse other roles;
- the notification routes open the finding, and the To-Do builder and the
  programme service cost a fixed number of queries.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.analytics import programme_effectiveness as pe
from apps.audit.models import AuditLog
from apps.cce_leadership.models import EngagementKind, RegionalEngagement
from apps.cce_leadership.services import feedback_visible_to
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.impact import findings as fs
from apps.impact.learning_todos import learning_todos
from apps.impact.models import EdTechDeployment, ImpactFinding
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
CCEO = EdifyRole.CCEO.value
ADMIN = EdifyRole.ADMIN.value
LE = SsaIntervention.LEARNING_ENVIRONMENT.value

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-learning-tests",
    }
}


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    if country is not None:
        StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _paired(school, fy, before, after, intervention=LE):
    now = timezone.now()
    for cycle, days_ago, score in ((str(int(fy) - 1), 300, before), (fy, 10, after)):
        record = SsaRecord.objects.create(
            school=school,
            fy=cycle,
            quarter=get_quarter_for_date(),
            date_of_ssa=now - timedelta(days=days_ago),
            verification_status="confirmed",
        )
        for value in SsaIntervention.values:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=value,
                score=score if value == intervention else 7.5,
            )


@override_settings(CACHES=LOCMEM)
class LearningFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.ug = Region.objects.create(name="Learning Central", country="Uganda")
        cls.ke = Region.objects.create(name="Learning Coast", country="Kenya")
        cls.tz = Region.objects.create(name="Learning Lake", country="Tanzania")
        cls.ug_district = District.objects.create(name="Learning Wakiso", region=cls.ug)
        cls.ke_district = District.objects.create(name="Learning Kilifi", region=cls.ke)
        cls.edtech = ActivityCatalogueItem.objects.create(
            stable_code="LEARN_EDTECH_FOUNDATIONS",
            source_name="EdTech Foundations",
            display_name="EdTech Foundations Training",
            activity_type="training",
            delivery_method="in_school_training",
            workflow_kind="in_school_training",
            salesforce_record_type="TS",
            evidence_profile="training",
            costing_profile="training",
            programme_category=pe.EDTECH_PROGRAMME_CATEGORY,
            status="active",
            is_training_course=True,
        )
        cls.exposed, cls.comparison = [], []
        for i in range(10):
            school = School.objects.create(
                name=f"Exposed {i}",
                school_id=f"LRN-E{i}",
                region=cls.ug,
                district=cls.ug_district,
            )
            _paired(school, cls.fy, 4.0, 6.0)
            cls.training = Activity.objects.create(
                school=school,
                activity_type="in_school_training",
                catalogue_item=cls.edtech,
                status="ia_verified",
                planned_date=timezone.localdate() - timedelta(days=60),
                fy=cls.fy,
                focus_intervention=LE,
                delivery_type="staff",
            )
            cls.exposed.append(school)
        for i in range(10):
            school = School.objects.create(
                name=f"Comparison {i}",
                school_id=f"LRN-C{i}",
                region=cls.ug,
                district=cls.ug_district,
            )
            _paired(school, cls.fy, 4.0, 4.2)
            cls.comparison.append(school)
        cls.kenya_school = School.objects.create(
            name="Kenya Exposed",
            school_id="LRN-KE",
            region=cls.ke,
            district=cls.ke_district,
        )
        _paired(cls.kenya_school, cls.fy, 4.0, 7.0)
        Activity.objects.create(
            school=cls.kenya_school,
            activity_type="in_school_training",
            catalogue_item=cls.edtech,
            status="ia_verified",
            planned_date=timezone.localdate() - timedelta(days=60),
            fy=cls.fy,
            focus_intervention=LE,
            delivery_type="staff",
        )

        cls.ia = _user("lrn-ia1@t.org", IA)
        cls.ia2 = _user("lrn-ia2@t.org", IA)
        cls.cd = _user("lrn-cd@t.org", CD)
        cls.cceo = _user("lrn-cceo@t.org", CCEO)
        cls.admin = _user("lrn-admin@t.org", ADMIN, country=None)
        cls.ke_ia = _user("lrn-ke-ia@t.org", IA, country="Kenya")
        cls.tz_ia = _user("lrn-tz-ia@t.org", IA, country="Tanzania")
        cls.tz_cd = _user("lrn-tz-cd@t.org", CD, country="Tanzania")

    def _training_row(self, data):
        return next(
            r for r in data["rows"] if r["label"] == "EdTech Foundations Training"
        )


class ProgrammeEffectivenessTests(LearningFixture):
    def test_training_group_compares_reached_schools_with_similar_schools(self):
        data = pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        row = self._training_row(data)
        self.assertEqual(row["exposed_n"], 10)
        self.assertEqual(row["comparison_n"], 10)
        self.assertEqual(row["median_exposed"], 2.0)
        self.assertEqual(row["median_comparison"], 0.2)
        self.assertAlmostEqual(row["difference"], 1.8, places=2)
        self.assertEqual(row["verdict"], "significant")
        self.assertIsNotNone(row["p_adjusted"])
        self.assertEqual(row["grade"], "associational")
        self.assertEqual(row["coverage_pct"], 100)
        self.assertEqual(row["detail"], "In-school · Edify staff")
        self.assertEqual(data["outputs"]["verified_trainings"], 10)
        self.assertEqual(data["coverage"]["schools_in_scope"], 20)
        # The merged attribution table covers every domain, with the caveat.
        contribution = {r["key"]: r for r in data["contribution"]}
        self.assertEqual(contribution[LE]["schools_measured"], 20)
        self.assertEqual(contribution[LE]["trainings"], 10)
        self.assertIn(pe.ASSOCIATION_CAVEAT, data["caveats"])

    def test_another_countrys_school_never_enters_the_comparison(self):
        uganda = pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        self.assertNotIn(self.kenya_school.id, pe.scoped_countries(self.ia))
        self.assertEqual(self._training_row(uganda)["exposed_n"], 10)
        kenya = pe.build(self.ke_ia, pe.TRAINING, {"fy": self.fy})
        self.assertEqual(kenya["coverage"]["schools_in_scope"], 1)
        self.assertEqual(self._training_row(kenya)["exposed_n"], 1)
        self.assertEqual(self._training_row(kenya)["grade"], "insufficient")
        self.assertEqual(
            pe.build(self.admin, pe.TRAINING, {"fy": self.fy})["coverage"][
                "schools_in_scope"
            ],
            21,
        )

    def test_filters_reach_the_table_and_single_choices_are_not_drawn(self):
        data = pe.build(self.ia, pe.TRAINING, {"fy": self.fy, "mode": "cluster"})
        # "cluster" is not a mode the data holds, so it is ignored, and a
        # filter with a single option is not drawn.
        self.assertEqual(len(data["rows"]), 1)
        self.assertTrue(all(not f["options"] for f in data["filters"]))
        Activity.objects.create(
            school=self.comparison[0],
            activity_type="cluster_training",
            status="ia_verified",
            planned_date=timezone.localdate() - timedelta(days=50),
            fy=self.fy,
            focus_intervention=SsaIntervention.LEADERSHIP.value,
            delivery_type="staff",
        )
        data = pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        modes = next(f for f in data["filters"] if f["name"] == "mode")
        self.assertEqual({v for v, _l in modes["options"]}, {"cluster", "in_school"})
        filtered = pe.build(self.ia, pe.TRAINING, {"fy": self.fy, "mode": "cluster"})
        self.assertEqual(
            [r["detail"].split(" · ")[0] for r in filtered["rows"]], ["Cluster"]
        )
        # The family (and so the correction) is the same whichever filter is on.
        self.assertEqual(filtered["rows"][0]["tests_run"], data["rows"][0]["tests_run"])

    def test_edtech_exposure_uses_the_governed_category_and_deployments(self):
        EdTechDeployment.objects.create(
            school=self.comparison[0],
            country="Uganda",
            fy=self.fy,
            recorded_by_user_id=self.ia.id,
            verification_status="confirmed",
            asset_type="tablet",
            quantity=20,
            deployed_on=timezone.localdate() - timedelta(days=30),
            funding="grant",
        )
        data = pe.build(self.ia, pe.EDTECH, {"fy": self.fy})
        rows = {r["key"]: r for r in data["all_rows"]}
        self.assertEqual(rows["edtech:trainings"]["exposed_n"], 10)
        self.assertEqual(rows["edtech:deployments"]["exposed_n"], 1)
        self.assertEqual(rows["edtech:any"]["exposed_n"], 11)
        # A proxy outcome is never graded above descriptive.
        self.assertEqual(rows["edtech:trainings"]["grade"], "descriptive")
        self.assertIn(pe.EDTECH_CAVEAT, data["caveats"])
        self.assertEqual(data["outputs"]["deployments"], 1)
        only = pe.build(self.ia, pe.EDTECH, {"fy": self.fy, "source": "deployments"})
        self.assertEqual(
            {r["key"] for r in only["rows"]}, {"edtech:any", "edtech:deployments"}
        )

    def test_lending_flags_an_immature_cohort(self):
        disbursed = timezone.localdate() - timedelta(days=30)
        rows = [
            {
                "loan_id": f"loan-{s.id}",
                "loan__school_id": s.id,
                "loan__purpose_id": "purpose-1",
                "loan__purpose__label": "Classroom construction",
                "loan__purpose__follow_up_days": 180,
                "loan__purpose__is_edtech": False,
                "disbursed_on": disbursed,
            }
            for s in self.exposed
        ]
        with patch.object(pe, "_disbursements", return_value=rows):
            data = pe.build(self.ia, pe.LENDING, {"fy": self.fy})
        shown = {r["key"]: r for r in data["rows"]}
        row = shown[f"lending:all:{SsaIntervention.FINANCIAL_HEALTH.value}"]
        self.assertEqual(row["exposed_n"], 0)  # Financial Health started strong (7.5)
        self.assertEqual(data["outputs"]["schools_financed"], 10)
        purposes = next(f for f in data["filters"] if f["name"] == "purpose")
        self.assertEqual(purposes["options"], [])  # one purpose: nothing to choose
        self.assertIn(
            "lending:purpose-1:financial_health", {r["key"] for r in data["all_rows"]}
        )
        # Rebuild the frame with a weak Financial Health baseline for the exposed.
        for s in self.exposed:
            SsaScore.objects.filter(
                ssa_record__school=s,
                intervention=SsaIntervention.FINANCIAL_HEALTH.value,
            ).update(score=4.0)
        with patch.object(pe, "_disbursements", return_value=rows):
            data = pe.build(self.ia, pe.LENDING, {"fy": self.fy})
        row = next(
            r
            for r in data["rows"]
            if r["key"] == f"lending:all:{SsaIntervention.FINANCIAL_HEALTH.value}"
        )
        self.assertEqual(row["exposed_n"], 10)
        self.assertEqual(row["grade"], "descriptive")
        self.assertIn("follow-up window", " ".join(row["grade_reasons"]))

    def test_visits_tab_reads_the_engines_corrected_comparison(self):
        data = pe.build(self.ia, pe.VISITS, {"fy": self.fy})
        self.assertEqual(data["outputs"]["verified_visits"], 0)
        self.assertTrue(
            all(r["verdict"] == "insufficient data" for r in data["all_rows"])
        )
        self.assertIn("comparable_schools", data["effectiveness"])

    def test_the_service_costs_a_fixed_number_of_queries(self):
        with CaptureQueriesContext(connection) as small:
            pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        for i in range(10, 16):
            school = School.objects.create(
                name=f"More {i}",
                school_id=f"LRN-M{i}",
                region=self.ug,
                district=self.ug_district,
            )
            _paired(school, self.fy, 4.0, 5.0)
            Activity.objects.create(
                school=school,
                activity_type="in_school_training",
                catalogue_item=self.edtech,
                status="ia_verified",
                planned_date=timezone.localdate() - timedelta(days=60),
                fy=self.fy,
                focus_intervention=LE,
                delivery_type="staff",
            )
        with CaptureQueriesContext(connection) as large:
            pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        self.assertEqual(len(small), len(large))
        self.assertLessEqual(len(large), 25)


class ObservationReachTests(LearningFixture):
    def test_ia_reads_shared_observations_of_its_country_only(self):
        lead = _user("lrn-rpl@t.org", EdifyRole.REGIONAL_PROGRAM_LEAD.value)

        def observation(country, shared):
            return RegionalEngagement.objects.create(
                author_id=lead.id,
                kind=EngagementKind.TRAINING_OBSERVATION,
                held_on=timezone.localdate(),
                fy=self.fy,
                country=country,
                subject="Observed",
                activity=self.training,
                rating_facilitation=3,
                feedback_shared_at=timezone.now() if shared else None,
            )

        shared_ug = observation("Uganda", True)
        draft_ug = observation("Uganda", False)
        shared_ke = observation("Kenya", True)
        blank = observation("", True)
        visible = set(feedback_visible_to(self.ia).values_list("id", flat=True))
        self.assertIn(shared_ug.id, visible)
        self.assertNotIn(draft_ug.id, visible)
        self.assertNotIn(shared_ke.id, visible)
        self.assertNotIn(blank.id, visible)
        self.assertFalse(
            feedback_visible_to(_user("lrn-ia-none@t.org", IA, country="")).exists()
        )
        data = pe.build(self.ia, pe.TRAINING, {"fy": self.fy})
        self.assertEqual(data["qualitative"]["quality"]["observed"], 1)
        self.assertEqual(data["qualitative"]["quality"]["mean_rubric"], 3)


class FindingLifecycleTests(LearningFixture):
    def _data(self, **overrides):
        data = {
            "programme": "training",
            "intervention": LE,
            "statement": "Schools reached by EdTech Foundations moved further on Learning Environment.",
            "contrary_evidence": "Two schools declined.",
            "limitations": "Association only; the SSA is self-assessed.",
            "recommendation": "Keep the course in the next plan.",
            "action_owner_role": CD,
        }
        data.update(overrides)
        return data

    def test_only_impact_assessment_writes_findings(self):
        for user in (self.cd, self.cceo, self.admin):
            with self.subTest(role=user.active_role), self.assertRaises(Forbidden):
                fs.record_finding(user, self._data())
        with self.assertRaises(BadRequest):
            fs.record_finding(
                _user("lrn-ia-nocountry@t.org", IA, country=""), self._data()
            )
        with self.assertRaises(BadRequest):
            fs.record_finding(
                self.ia, self._data(recommendation="Act", action_owner_role="")
            )

    def test_a_second_officer_reviews_and_the_author_never_does(self):
        finding = fs.record_finding(self.ia, self._data(), submit=True)
        self.assertEqual(finding.status, fs.IN_REVIEW)
        self.assertEqual(finding.country, "Uganda")
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.ia2.id, context_id=finding.id
            ).exists()
        )
        with self.assertRaises(Forbidden):
            fs.review_finding(self.ia, finding.id, decision="approve")
        with self.assertRaises(Forbidden):  # Uganda has a second IA officer
            fs.review_finding(self.cd, finding.id, decision="approve")
        with self.assertRaises(NotFoundError):
            fs.review_finding(self.ke_ia, finding.id, decision="approve")
        with self.assertRaises(BadRequest):
            fs.review_finding(self.ia2, finding.id, decision="return")
        approved = fs.review_finding(
            self.ia2, finding.id, decision="approve", note="Sound"
        )
        self.assertEqual(approved.status, fs.APPROVED)
        self.assertEqual(approved.review_basis, "peer_ia")
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.finding.approved", subject_id=finding.id
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.ia.id, source_event_type=fs.EVENT_REVIEW_DECIDED
            ).exists()
        )
        self.assertFalse(fs.visible_findings(self.ke_ia).filter(id=finding.id).exists())
        self.assertTrue(fs.visible_findings(self.admin).filter(id=finding.id).exists())

    def test_the_country_director_acknowledges_where_there_is_one_officer(self):
        finding = fs.record_finding(self.tz_ia, self._data(), submit=True)
        self.assertEqual(fs.reviewer_ids(finding), [str(self.tz_cd.id)])
        todos = learning_todos(self.tz_cd, CD, timezone.localdate())
        self.assertEqual([t["id"] for t in todos], ["ia-findings-review"])
        approved = fs.review_finding(self.tz_cd, finding.id, decision="approve")
        self.assertEqual(approved.review_basis, "cd_fallback")

    def test_returned_findings_go_back_to_their_author_to_correct(self):
        finding = fs.record_finding(self.ia, self._data(), submit=True)
        fs.review_finding(
            self.ia2, finding.id, decision="return", note="Name the comparison"
        )
        todos = learning_todos(self.ia, IA, timezone.localdate())
        self.assertIn("ia-findings-returned", [t["id"] for t in todos])
        with self.assertRaises(Forbidden):
            fs.update_finding(self.ia2, finding.id, self._data())
        fs.update_finding(self.ia, finding.id, self._data(statement="Corrected."))
        resubmitted = fs.submit_finding(self.ia, finding.id)
        self.assertEqual(resubmitted.status, fs.IN_REVIEW)

    def test_a_revision_supersedes_the_approved_finding_once_approved(self):
        finding = fs.record_finding(self.ia, self._data(), submit=True)
        fs.review_finding(self.ia2, finding.id, decision="approve")
        revision = fs.revise_finding(self.ia, finding.id)
        with self.assertRaises(BadRequest):
            fs.revise_finding(self.ia, finding.id)
        fs.submit_finding(self.ia, revision.id)
        fs.review_finding(self.ia2, revision.id, decision="approve")
        finding.refresh_from_db()
        self.assertEqual(finding.status, fs.SUPERSEDED)
        self.assertEqual(
            list(fs.approved_findings(self.cd)),
            [ImpactFinding.objects.get(id=revision.id)],
        )

    def test_the_notification_routes_open_the_finding(self):
        route, label = NotificationLinkResolver.resolve(
            fs.EVENT_REVIEW_REQUESTED, "ImpactFinding", "f1", IA
        )
        self.assertEqual(route, "/ia/learning/?view=findings&status=in_review&open=f1")
        self.assertEqual(label, "Review Finding")
        route, _label = NotificationLinkResolver.resolve(
            fs.EVENT_REVIEW_DECIDED, "ImpactFinding", "f1", IA
        )
        self.assertEqual(route, "/ia/learning/?view=findings&open=f1")
        route, _label = NotificationLinkResolver.resolve(
            fs.EVENT_REVIEW_DECIDED, "ImpactFinding", "f1", CCEO
        )
        self.assertEqual(route, "/dashboard")

    def test_the_todo_builder_costs_a_fixed_number_of_queries(self):
        fs.record_finding(self.ia, self._data(), submit=True)
        with CaptureQueriesContext(connection) as one:
            learning_todos(self.ia2, IA, timezone.localdate())
        for _ in range(5):
            fs.record_finding(self.ia, self._data(), submit=True)
        with CaptureQueriesContext(connection) as many:
            rows = learning_todos(self.ia2, IA, timezone.localdate())
        self.assertEqual(len(one), len(many))
        self.assertEqual(rows[0]["linked"], "6 waiting")


class LearningPageTests(LearningFixture):
    def test_every_tab_renders_for_impact_assessment(self):
        self.client.force_login(self.ia)
        for view in pe.TAB_LABELS:
            with self.subTest(view=view):
                response = self.client.get(f"/ia/learning/?view={view}&fy={self.fy}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-ia-learning")
        response = self.client.get(f"/ia/learning/?view=training&fy={self.fy}")
        self.assertContains(response, "EdTech Foundations Training")
        self.assertContains(response, "Record finding")
        self.assertContains(response, pe.OUTPUTS_NOTE)
        self.assertContains(response, "Intervention contribution (association)")

    def test_the_country_director_reads_but_does_not_record(self):
        self.client.force_login(self.cd)
        response = self.client.get(f"/ia/learning/?view=training&fy={self.fy}")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "/ia/learning/findings/new")
        response = self.client.post("/ia/learning/findings/save", self._post())
        self.assertEqual(ImpactFinding.objects.count(), 0)

    def _post(self, **extra):
        return {
            "programme": "training",
            "statement": "Reached schools moved further.",
            "limitations": "Association only.",
            "row": f"training:{self.edtech.id}|in_school|staff",
            "fy": self.fy,
            **extra,
        }

    def test_other_roles_are_refused(self):
        self.client.force_login(self.cceo)
        for url in ("/ia/learning/", "/ia/learning/findings/new", "/ia/attribution/"):
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.get(url, HTTP_HX_REQUEST="true").status_code, 403
                )
                self.assertNotEqual(self.client.get(url).status_code, 200)
        response = self.client.post("/ia/learning/findings/save", self._post())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ImpactFinding.objects.count(), 0)

    def test_a_finding_keeps_the_servers_figures_not_the_browsers(self):
        self.client.force_login(self.ia)
        drawer = self.client.get(
            "/ia/learning/findings/new",
            {"row": f"training:{self.edtech.id}|in_school|staff", "fy": self.fy},
        )
        self.assertContains(drawer, "10 exposed / 10 comparison")
        response = self.client.post(
            "/ia/learning/findings/save",
            self._post(exposed_n="999", metric_snapshot="{}", submit_now="1"),
        )
        self.assertEqual(response.status_code, 302)
        finding = ImpactFinding.objects.get()
        self.assertEqual(finding.metric_snapshot["exposed_n"], 10)
        self.assertEqual(finding.metric_snapshot["grade"], "associational")
        self.assertEqual(finding.status, fs.IN_REVIEW)
        self.assertEqual(finding.cohort_filters["fy"], self.fy)
        bad = self.client.post(
            "/ia/learning/findings/save",
            self._post(row="training:missing|x|y"),
            follow=True,
        )
        self.assertContains(bad, "no longer in the table")
        self.assertEqual(ImpactFinding.objects.count(), 1)

    def test_review_drawer_and_refusal_messages(self):
        finding = fs.record_finding(
            self.ia,
            {"programme": "visits", "statement": "S", "limitations": "L"},
            submit=True,
        )
        self.client.force_login(self.ia)
        own = self.client.get(f"/ia/learning/findings/{finding.id}/")
        self.assertContains(own, "second Impact Assessment officer reviews it")
        refused = self.client.post(
            f"/ia/learning/findings/{finding.id}/review",
            {"decision": "approve"},
            follow=True,
        )
        self.assertContains(refused, "You wrote this")
        self.client.force_login(self.ia2)
        drawer = self.client.get(f"/ia/learning/findings/{finding.id}/")
        self.assertContains(drawer, "Review impact finding")
        self.client.post(
            f"/ia/learning/findings/{finding.id}/review", {"decision": "approve"}
        )
        finding.refresh_from_db()
        self.assertEqual(finding.status, fs.APPROVED)
        self.client.force_login(self.ke_ia)
        self.assertContains(
            self.client.get(f"/ia/learning/findings/{finding.id}/"),
            "not in your country",
        )

    def test_attribution_lands_on_the_training_tab(self):
        self.client.force_login(self.ia)
        response = self.client.get("/ia/attribution/?fy=2026")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/ia/learning/?view=training&fy=2026")
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get("/ia/attribution/").status_code, 302)

    def test_the_page_costs_a_fixed_number_of_queries(self):
        self.client.force_login(self.ia)
        url = f"/ia/learning/?view=training&fy={self.fy}"
        self.client.get(url)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url)
        for i in range(10, 14):
            school = School.objects.create(
                name=f"Page {i}",
                school_id=f"LRN-P{i}",
                region=self.ug,
                district=self.ug_district,
            )
            _paired(school, self.fy, 4.0, 5.0)
        with CaptureQueriesContext(connection) as large:
            self.client.get(url)
        self.assertEqual(len(small), len(large))
