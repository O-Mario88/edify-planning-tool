from django.test import TestCase

from apps.accounts.models import User
from apps.core.rbac import EdifyRole

from .models import HelpArticle, HelpArticleFeedback, HelpArticleRoleAccess, HelpArticleState, HelpCategory
from .services import (
    documentation_drift_report,
    ensure_canonical_content,
    sync_route_contexts,
    transition_article,
)


class KnowledgeCenterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_canonical_content()
        sync_route_contexts()
        cls.cceo = User.objects.create_user(
            email="help-cceo@edify.test", name="Help CCEO", password="Password123!",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
        )
        cls.accountant = User.objects.create_user(
            email="help-accountant@edify.test", name="Help Accountant", password="Password123!",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value], active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        cls.admin = User.objects.create_user(
            email="help-admin@edify.test", name="Help Admin", password="Password123!",
            roles=[EdifyRole.ADMIN.value], active_role=EdifyRole.ADMIN.value, is_staff=True,
        )

    def test_home_search_and_contextual_help_load_for_role(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/help")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What would you like help with?")
        self.assertContains(response, "Planning and Field Operations")
        self.assertContains(response, "View all")

        response = self.client.get("/help/search", {"q": "SF ID"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salesforce Activity IDs")

        response = self.client.get("/help/context", {"for": "/my-plan"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Help for this page")
        self.assertContains(response, "Open full article")

    def test_role_restricted_article_is_denied(self):
        self.client.force_login(self.accountant)
        response = self.client.get("/help/articles/feature-school-directory")
        self.assertEqual(response.status_code, 403)

    def test_feedback_and_print_are_available_for_authorised_article(self):
        self.client.force_login(self.cceo)
        response = self.client.post(
            "/help/articles/feature-my-plan/feedback",
            {"feedback_type": "helpful", "page_context": "/my-plan"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(HelpArticleFeedback.objects.filter(article__slug="feature-my-plan").count(), 1)
        response = self.client.get("/help/articles/feature-my-plan/print")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Version")

    def test_everyday_user_copy_does_not_show_internal_source_paths(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/help/articles/feature-my-plan")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "How this part of Edify works")
        self.assertContains(response, "Tips for getting this right")
        self.assertContains(response, "How this guide stays correct")
        self.assertNotContains(response, "apps/my_plan/services.py")

        response = self.client.get("/help/articles/workflow-planning-automatic-costing")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edify checks the date")
        self.assertNotContains(response, "canonical costing")
        self.assertNotContains(response, "ActivityScheduleCostLine")

    def test_publishing_requires_review_transitions_and_versions_are_auditable(self):
        category = HelpCategory.objects.get(slug="features")
        draft = HelpArticle.objects.create(
            title="Draft help", slug="draft-help", summary="A reviewed draft.",
            content=[{"heading": "What you do", "body": "Use the supported action.", "items": []}],
            category=category, keywords=["draft"], source_paths=["apps/core/rbac.py"],
            state=HelpArticleState.DRAFT, author=self.admin,
        )
        HelpArticleRoleAccess.objects.create(article=draft, role=EdifyRole.CCEO.value)
        transition_article(draft, "submit", self.admin)
        transition_article(draft, "technical_review", self.admin)
        transition_article(draft, "product_review", self.admin)
        transition_article(draft, "publish", self.admin)
        draft.refresh_from_db()
        self.assertEqual(draft.state, HelpArticleState.PUBLISHED)
        self.assertTrue(draft.versions.filter(state=HelpArticleState.PUBLISHED).exists())
        self.assertTrue(draft.last_reviewed_at)

    def test_drift_audit_has_full_route_and_status_coverage(self):
        report = documentation_drift_report()
        self.assertEqual(report["coverage_percent"], 100.0)
        self.assertEqual(report["missing_routes"], [])
        self.assertEqual(report["unknown_statuses"], [])
        self.assertEqual(report["broken_links"], [])
