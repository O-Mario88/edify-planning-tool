"""Every argument-free page, fetched as every role, must not fall over.

The platform has ~600 routes that take no URL arguments, and until now nothing
walked them. A page that 500s for one role and not another is invisible to a
suite organised by feature: each feature's own tests sign in as the role that
feature belongs to, so a scoping bug that only bites a Program Lead on the
Accountant's page has nowhere to show up.

This is deliberately a shallow crawl. It asserts what can be asserted about a
page without knowing what it is for: that asking for it does not raise. A 403
is a correct answer, so is a 302 to the dashboard, and so is a 404 for a
surface a role has no data behind. A 500 never is.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import get_resolver

from apps.core.rbac import EdifyRole

# Routes excluded from the crawl, each for a reason that is not "it fails".
SKIP_URL_PARTS = (
    # Django admin has its own suite and its own auth flow; crawling it tests
    # Django, not this application.
    "/admin/",
    # Ends the session, which would end the crawl on its first hit.
    "logout",
    # Server-sent events. The handler streams and hands back a closed
    # connection, so a synchronous test client is left holding a dead one and
    # every request after it fails — which is what the first run of this crawl
    # spent itself reporting.
    "stream",
    "realtime",
    "sse",
    # Liveness probes: deliberately cheap, and deliberately not pages.
    "healthz",
    "readyz",
)


def _zero_argument_routes() -> list[str]:
    """Every route pattern with no captured arguments, as a URL path.

    Patterns are walked and concatenated rather than reversed, because most of
    this platform's routes are unnamed — reverse() reaches 112 of them where
    the walk reaches nearly six hundred. The concatenation is exact: Django
    joins an include's prefix to its children the same way, which is why
    "/api/reports" and "/api/reports/generate" both appear here and both
    genuinely resolve.
    """

    def literal_path(pattern) -> str:
        """Turn our boundary-aware include regex into its literal prefix.

        API includes intentionally use ``^api/foo(?:/|$)`` so ``/api/foo``
        works without accidentally admitting ``/api/foobar``. Treating every
        regex as opaque made the crawl silently drop the whole API after that
        routing repair.
        """

        value = str(pattern)
        suffix = "(?:/|$)"
        if value.startswith("^") and value.endswith(suffix):
            return value[1 : -len(suffix)] + "/"
        return value

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            path = prefix + literal_path(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern, path)
            else:
                yield path

    seen, routes = set(), []
    for path in walk(get_resolver()):
        if "<" in path or "(?P" in path or "$" in path or "^" in path:
            continue
        url = "/" + path
        if any(part in url for part in SKIP_URL_PARTS):
            continue
        if url not in seen:
            seen.add(url)
            routes.append(url)
    return sorted(routes)


class RouteCrawlTest(TestCase):
    """One signed-in user per role, walking every argument-free page."""

    @classmethod
    def setUpTestData(cls):
        cls.routes = _zero_argument_routes()
        # Users are created here rather than looked up. The seeded demo
        # accounts only exist in a development database, so a crawl that
        # depended on them skipped every role in the test database and passed
        # in silence — which is indistinguishable from a crawl that found
        # nothing wrong.
        User = get_user_model()
        cls.users = {}
        for role in EdifyRole.values():
            slug = role.lower().replace(" ", "-")
            cls.users[role] = User.objects.create_user(
                email=f"crawl-{slug}@edify.test",
                password="password123",
                name=f"Crawl {role}",
                roles=[role],
                active_role=role,
                is_active=True,
            )

    def _crawl_as(self, role: str) -> list[str]:
        client = Client()
        client.force_login(self.users[role])

        failures = []
        for url in self.routes:
            try:
                response = client.get(url)
            except Exception as exc:  # noqa: BLE001 — the crawl reports, not raises
                failures.append(f"{url} raised {type(exc).__name__}: {exc}")
                continue
            if response.status_code >= 500:
                failures.append(f"{url} → {response.status_code}")
        return failures

    def test_the_route_table_is_worth_crawling(self):
        """A crawl over three routes would pass and mean nothing."""
        self.assertGreater(len(self.routes), 400, self.routes[:20])

    def test_every_role_has_a_user_to_crawl_with(self):
        """The version of this that looked up seeded accounts skipped all of
        them and reported two passing tests."""
        self.assertEqual(len(self.users), len(EdifyRole.values()))

    def test_no_page_raises_for_any_role(self):
        for role in EdifyRole.values():
            with self.subTest(role=role):
                failures = self._crawl_as(role)
                self.assertEqual(
                    failures,
                    [],
                    f"{len(failures)} route(s) failed for {role}: "
                    + "; ".join(failures[:15]),
                )
