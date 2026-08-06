from django.test import TestCase

from apps.accounts.models import User
from apps.core.rbac import EdifyRole

from .models import (
    HelpArticleRouteContext,
    HelpArticle,
    HelpArticleFeedback,
    HelpArticleRoleAccess,
    HelpArticleState,
    HelpCategory,
)
from .services import (
    contextual_article,
    knowledge_tree,
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
            email="help-cceo@edify.test",
            name="Help CCEO",
            password="Password123!",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        cls.accountant = User.objects.create_user(
            email="help-accountant@edify.test",
            name="Help Accountant",
            password="Password123!",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        cls.admin = User.objects.create_user(
            email="help-admin@edify.test",
            name="Help Admin",
            password="Password123!",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            is_staff=True,
        )

    def test_home_search_and_contextual_help_load_for_role(self):
        """The Knowledge Center home is the manual's front door.

        The old landing page was a hero + topic-card grid; it is replaced by
        the two-column documentation shell, so the assertions below pin the
        new contract — a hierarchical Table of Contents rendered beside the
        content — rather than the retired hero copy.
        """
        self.client.force_login(self.cceo)
        response = self.client.get("/help")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "help-shell__rail")
        self.assertContains(response, "help-toc__link")
        self.assertContains(response, "Planning and Field Operations")
        self.assertContains(response, "Documentation areas")
        # The retired hero must not survive alongside the replacement.
        self.assertNotContains(response, "What would you like help with?")

        response = self.client.get("/help/search", {"q": "SF ID"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salesforce Activity IDs")

        response = self.client.get("/help/context", {"for": "/my-plan"})
        self.assertEqual(response.status_code, 200)
        # Contextual help now renders the full article page (not a popup).
        self.assertTemplateUsed(response, "pages/help/article.html")

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
        self.assertEqual(
            HelpArticleFeedback.objects.filter(article__slug="feature-my-plan").count(),
            1,
        )
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
            title="Draft help",
            slug="draft-help",
            summary="A reviewed draft.",
            content=[
                {
                    "heading": "What you do",
                    "body": "Use the supported action.",
                    "items": [],
                }
            ],
            category=category,
            keywords=["draft"],
            source_paths=["apps/core/rbac.py"],
            state=HelpArticleState.DRAFT,
            author=self.admin,
        )
        HelpArticleRoleAccess.objects.create(article=draft, role=EdifyRole.CCEO.value)
        transition_article(draft, "submit", self.admin)
        transition_article(draft, "technical_review", self.admin)
        transition_article(draft, "product_review", self.admin)
        transition_article(draft, "publish", self.admin)
        draft.refresh_from_db()
        self.assertEqual(draft.state, HelpArticleState.PUBLISHED)
        self.assertTrue(
            draft.versions.filter(state=HelpArticleState.PUBLISHED).exists()
        )
        self.assertTrue(draft.last_reviewed_at)

    def test_drift_audit_has_full_route_and_status_coverage(self):
        report = documentation_drift_report()
        self.assertEqual(report["coverage_percent"], 100.0)
        self.assertEqual(report["missing_routes"], [])
        self.assertEqual(report["unknown_statuses"], [])
        self.assertEqual(report["broken_links"], [])


class KnowledgeCenterShellTest(TestCase):
    """The two-column documentation shell (§4).

    The Knowledge Center replaced a card-grid landing page. Its defining
    property is that the manual reads as one document: a hierarchical,
    role-aware Table of Contents sits beside every page, so a reader can reach
    any authorised article from wherever they are.
    """

    @classmethod
    def setUpTestData(cls):
        ensure_canonical_content()
        cls.cceo = User.objects.create_user(
            email="shell-cceo@edify.test",
            name="Shell CCEO",
            password="Password123!",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        cls.accountant = User.objects.create_user(
            email="shell-accountant@edify.test",
            name="Shell Accountant",
            password="Password123!",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
        )

    def test_every_knowledge_center_page_renders_the_contents_rail(self):
        self.client.force_login(self.cceo)
        category = HelpCategory.objects.first()
        for url in (
            "/help",
            f"/help/categories/{category.slug}",
            "/help/glossary",
            "/help/release-notes",
            "/help/troubleshooting",
            "/help/search?q=plan",
            "/help/articles/feature-my-plan",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "help-shell__rail")
                self.assertContains(response, "help-toc__link")

    def test_contents_are_one_always_visible_expandable_hierarchy(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/help")

        self.assertContains(response, "Table of contents")
        self.assertContains(response, 'class="help-toc"', count=1)
        self.assertContains(
            response, '<span class="help-toc__category">Glossary</span>'
        )
        self.assertContains(
            response,
            '<span class="help-toc__category">Troubleshooting</span>',
        )
        self.assertContains(
            response,
            '<span class="help-toc__category">Release notes</span>',
        )
        self.assertNotContains(response, "help-shell__contents-toggle")
        self.assertNotContains(response, "help-shell__drawer")
        self.assertNotContains(response, "help-toc__footer-link")

        tree = knowledge_tree(EdifyRole.CCEO.value)
        self.assertEqual(
            [group["category"].slug for group in tree][-3:],
            ["glossary", "troubleshooting", "release-notes"],
        )

    def test_the_open_article_is_marked_current_in_the_contents(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/help/articles/feature-my-plan")
        self.assertContains(response, "help-toc__link--active")
        # Screen readers must be told which entry is the open one, and the
        # marker must not rely on colour alone.
        self.assertContains(response, 'aria-current="page"')

    def test_the_contents_tree_is_role_aware(self):
        """A role must not be shown a route into guidance it cannot open."""
        cceo_tree = knowledge_tree(EdifyRole.CCEO.value)
        accountant_tree = knowledge_tree(EdifyRole.PROGRAM_ACCOUNTANT.value)

        def slugs(tree):
            return {
                entry["slug"]
                for group in tree
                if group["kind"] == "articles"
                for entry in group["articles"]
                if entry["slug"] != "glossary"
            }

        cceo_slugs, accountant_slugs = slugs(cceo_tree), slugs(accountant_tree)
        self.assertTrue(cceo_slugs)
        self.assertTrue(accountant_slugs)
        self.assertNotEqual(cceo_slugs, accountant_slugs)
        # Every entry offered to a role must actually open for that role.
        self.client.force_login(self.accountant)
        for slug in list(accountant_slugs)[:12]:
            with self.subTest(slug=slug):
                self.assertEqual(
                    self.client.get(f"/help/articles/{slug}").status_code, 200
                )

    def test_contents_groups_are_never_empty(self):
        tree = knowledge_tree(EdifyRole.CCEO.value)
        for group in tree:
            with self.subTest(category=group["category"].slug):
                self.assertTrue(group["articles"])
                self.assertEqual(group["count"], len(group["articles"]))

    def test_the_group_holding_the_open_article_is_expanded(self):
        """The reader's place survives a page load and the Back button."""
        article = HelpArticle.objects.get(slug="feature-my-plan")
        tree = knowledge_tree(EdifyRole.CCEO.value, "feature-my-plan")
        expanded = [g for g in tree if g["expanded"]]
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["category"].slug, article.category.slug)

    def test_new_platform_features_are_documented_and_reachable(self):
        """The Work Plan, non-school activities, Activity Catalogue and
        Strategic Priorities shipped with the platform; the manual must not
        lag behind the product."""
        self.client.force_login(self.cceo)
        for slug in ("feature-work-plan", "feature-non-school-activity"):
            with self.subTest(slug=slug):
                response = self.client.get(f"/help/articles/{slug}")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "help-toc__link")

    def test_contextual_help_opens_the_guide_that_owns_the_page(self):
        """Regression: several articles legitimately mention the same route,
        and the route→article map was last-wins, so /my-plan opened the
        Salesforce ID guide and /calendar opened Daily Visit Batches. A
        not-None assertion cannot catch that — pin the owning slug."""
        expected = {
            "/work-plan": "feature-work-plan",
            "/calendar": "feature-activity-calendar",
            "/my-plan": "feature-my-plan",
            "/planning": "feature-planning",
        }
        for route, slug in expected.items():
            with self.subTest(route=route):
                article = contextual_article(route, EdifyRole.CCEO.value)
                self.assertIsNotNone(article, f"{route} has no contextual Help")
                self.assertEqual(article.slug, slug)

    def test_a_route_has_exactly_one_owning_article(self):
        """Two contexts at equal priority made the opened guide depend on
        insertion order. Re-syncing must retire the superseded mapping."""
        from django.db.models import Count

        sync_route_contexts()
        duplicated = (
            HelpArticleRouteContext.objects.filter(workflow_status="")
            .values("route_pattern")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        self.assertEqual(list(duplicated), [])

    def test_restricted_contextual_help_falls_back_for_other_roles(self):
        """A CCEO on a CD-only page gets orientation, never the restricted
        guide itself."""
        restricted = contextual_article(
            "/settings/activity-catalogue/", EdifyRole.CCEO.value
        )
        self.assertEqual(restricted.slug, "getting-started")
        allowed = contextual_article(
            "/settings/activity-catalogue/", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.assertEqual(allowed.slug, "feature-activity-catalogue")

    def test_no_two_articles_explain_the_same_workflow(self):
        """One canonical workflow, one article.

        A near-duplicate is invisible in review — both articles read correctly
        on their own — and it splits maintenance, so the two drift apart. This
        caught a "Partner assignment scheduling" feature article sitting
        beside the existing "Partner Assignment and Scheduling" workflow
        guide.
        """
        import re

        def normalise(title: str) -> str:
            return re.sub(r"[^a-z]", "", title.lower())

        seen: dict[str, str] = {}
        collisions = []
        for title in HelpArticle.objects.values_list("title", flat=True):
            key = normalise(title)
            if key in seen and seen[key] != title:
                collisions.append((seen[key], title))
            seen.setdefault(key, title)
        self.assertEqual(collisions, [])
