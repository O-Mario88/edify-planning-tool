"""The decision review lives in the Country Profile's Needs Attention.

Owner, 2026-10-19: "Move the Decision Intelligence review (leadership and
budget insights, review and rescan) into the Country Profile's Needs Attention
for the CD and RVP." The Decision Intelligence page left with the Analytics
entry; its two queues, the Record form and the rescan are on the Country
Profile's Overview now, and Needs Attention counts what awaits the reader.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.budget_intelligence.models import BudgetIntelligenceInsight
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.leadership.models import LeadershipDecisionInsight

OPERATIONAL = "Recruit two officers for the northern districts."
FINANCIAL = "Chase the advances unaccounted for over 60 days."


def _person(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    StaffProfile.objects.create(user=user, title=role.value, country="Uganda")
    return user


class DecisionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = str(get_operational_fy())
        cls.cd = _person("dec-cd@t.test", EdifyRole.COUNTRY_DIRECTOR)
        cls.rvp = _person("dec-rvp@t.test", EdifyRole.REGIONAL_VICE_PRESIDENT)
        cls.ia = _person("dec-ia@t.test", EdifyRole.IMPACT_ASSESSMENT)
        cls.cceo = _person("dec-cceo@t.test", EdifyRole.CCEO)

    def setUp(self):
        self.operational = LeadershipDecisionInsight.objects.create(
            fy=self.fy,
            decision_type="recruitment",
            scope_type="region",
            scope_name="Northern",
            recommendation=OPERATIONAL,
            reason="Two vacancies have stayed open for a quarter.",
            risk_level="high",
            confidence_level="high",
            confidence_score=0.8,
            suggested_action="Open the requisition.",
            generated_at=timezone.now(),
        )
        self.financial = BudgetIntelligenceInsight.objects.create(
            fy=self.fy,
            period_type="fy",
            period=self.fy,
            insight_type="monthly",
            scope_type="country",
            recommendation=FINANCIAL,
            reason="Four advances are past their accounting date.",
            risk_level="medium",
            impact_yield="low",
            confidence_level="medium",
            confidence_score=0.6,
            amount_affected=1200000,
            suggested_action="Ask the holders to account.",
            generated_at=timezone.now(),
        )

    def overview(self, user):
        self.client.force_login(user)
        response = self.client.get("/country-profile", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def post(self, user, **data):
        self.client.force_login(user)
        return self.client.post("/country-profile/decisions", {"fy": self.fy, **data})


class TheReviewIsOnTheOverviewTest(DecisionFixture):
    def test_the_country_director_reviews_both_queues_on_the_profile(self):
        body = self.overview(self.cd)

        self.assertIn('id="profile-decisions"', body)
        self.assertIn(OPERATIONAL, body)
        self.assertIn(FINANCIAL, body)
        self.assertIn('action="/country-profile/decisions"', body)
        self.assertIn('value="review_leadership"', body)
        self.assertIn('value="review_budget"', body)
        self.assertIn('value="recompute"', body)

    def test_needs_attention_counts_what_awaits_the_reader(self):
        body = self.overview(self.cd)
        attention = body.split('data-rail-part="attention"', 1)[1]

        self.assertIn("1 operational decision awaits you", attention)
        self.assertIn("1 financial decision awaits you", attention)
        self.assertIn('href="#profile-decisions"', attention)

    def test_the_regional_vp_reviews_leadership_but_not_finance(self):
        body = self.overview(self.rvp)

        self.assertIn(OPERATIONAL, body)
        self.assertIn(FINANCIAL, body)
        self.assertIn('value="review_leadership"', body)
        self.assertNotIn('value="review_budget"', body)

    def test_a_reader_without_the_review_sees_no_queue(self):
        body = self.overview(self.ia)

        self.assertNotIn('id="profile-decisions"', body)
        self.assertNotIn(OPERATIONAL, body)
        self.assertNotIn("decision awaits you", body)

    def test_the_queue_is_on_the_overview_alone(self):
        self.client.force_login(self.cd)
        body = self.client.get(
            "/country-profile", {"fy": self.fy, "tab": "districts"}
        ).content.decode()

        self.assertNotIn('id="profile-decisions"', body)


class RecordingADecisionTest(DecisionFixture):
    def test_the_country_director_records_a_decision(self):
        response = self.post(
            self.cd,
            action="review_leadership",
            insight_id=self.operational.id,
            status="accepted",
            note="Approved for Q2.",
        )

        self.assertEqual(
            response["Location"],
            f"/country-profile?fy={self.fy}#profile-decisions",
        )
        self.operational.refresh_from_db()
        self.assertEqual(self.operational.status, "accepted")
        self.assertEqual(self.operational.review_note, "Approved for Q2.")
        self.assertNotIn("1 operational decision awaits you", self.overview(self.cd))

    def test_the_regional_vp_may_not_decide_a_financial_insight(self):
        self.post(
            self.rvp,
            action="review_budget",
            insight_id=self.financial.id,
            status="accepted",
        )

        self.financial.refresh_from_db()
        self.assertEqual(self.financial.status, "new")

    def test_the_country_director_rescans_both_engines(self):
        response = self.post(self.cd, action="recompute")

        self.assertEqual(response.status_code, 302)
        self.assertIn("#profile-decisions", response["Location"])

    def test_a_reader_without_the_review_is_refused(self):
        self.post(
            self.cceo,
            action="review_leadership",
            insight_id=self.operational.id,
            status="rejected",
        )

        self.operational.refresh_from_db()
        self.assertEqual(self.operational.status, "new")
