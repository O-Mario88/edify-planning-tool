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

from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
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

LEGACY_KPI_CLASSES = frozenset(
    {
        "admin-kpi",
        "admin-kpi-strip",
        "card-kpi",
        "edify-kpi-card",
        "edify-kpi-strip",
        "hcos-metrics",
        "ia-metric",
        "mobile-home-metric",
        "partner-kpi-card",
        "partner-kpi-grid",
        "sp-kpi",
        "sp-kpi-grid",
        "sp-kpis",
        "spa-kpi",
        "spa-kpi-grid",
        "spp-kpi",
        "spp-kpi-grid",
        "tt-kpi",
        "tt-kpi-strip",
    }
)
REQUIRED_KPI_CARD_PARTS = frozenset(
    {
        "kpi-strip__topline",
        "kpi-strip__icon-container",
        "kpi-strip__item-details",
        "kpi-strip__label",
        "kpi-strip__value",
    }
)


class _KpiVisualAuditParser(HTMLParser):
    """Validate the rendered KPI DOM without depending on browser selectors."""

    _void_tags = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.issues: list[str] = []
        self.total_card_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        legacy = sorted(classes & LEGACY_KPI_CLASSES)
        if legacy:
            self.issues.append(f"legacy KPI class rendered: {', '.join(legacy)}")

        is_summary = "data-edify-summary-kpi" in attributes
        if "kpi-strip" in classes and "kpi-strip--executive" not in classes:
            self.issues.append("KPI strip rendered without kpi-strip--executive")
        if is_summary and not {"kpi-strip", "kpi-strip--executive"} <= classes:
            self.issues.append("approved KPI summary is missing executive tray classes")

        current_card = next(
            (node for node in reversed(self.stack) if node["is_card"]), None
        )
        if current_card is not None:
            current_card["parts"].update(classes & REQUIRED_KPI_CARD_PARTS)

        is_card = attributes.get("data-component") == "kpi-card"
        if is_card:
            self.total_card_count += 1
            summary = next(
                (node for node in reversed(self.stack) if node["is_summary"]), None
            )
            if summary is None:
                self.issues.append("KPI card rendered outside the approved tray")
            else:
                summary["card_count"] += 1

        node = {
            "tag": tag,
            "is_summary": is_summary,
            "card_count": 0,
            "is_card": is_card,
            "parts": set(),
        }
        self.stack.append(node)
        if tag in self._void_tags:
            self._finish_node(self.stack.pop())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]["tag"] == tag:
            self._finish_node(self.stack.pop())

    def handle_endtag(self, tag):
        match = next(
            (
                index
                for index in range(len(self.stack) - 1, -1, -1)
                if self.stack[index]["tag"] == tag
            ),
            None,
        )
        if match is None:
            return
        while len(self.stack) > match:
            self._finish_node(self.stack.pop())

    def finish(self):
        self.close()
        while self.stack:
            self._finish_node(self.stack.pop())
        if self.total_card_count > 6:
            self.issues.append(
                f"page rendered {self.total_card_count} KPI cards; maximum is 6"
            )

    def _finish_node(self, node):
        if node["is_summary"] and node["card_count"] > 6:
            self.issues.append(
                f"executive tray rendered {node['card_count']} cards; maximum is 6"
            )
        if node["is_card"]:
            missing = sorted(REQUIRED_KPI_CARD_PARTS - node["parts"])
            if missing:
                self.issues.append(
                    "KPI card is missing approved visual parts: " + ", ".join(missing)
                )


class KpiVisualAuditParserTests(SimpleTestCase):
    def _issues(self, html: str) -> list[str]:
        parser = _KpiVisualAuditParser()
        parser.feed(html)
        parser.finish()
        return parser.issues

    def test_approved_executive_tile_passes(self):
        html = """
        <section class="kpi-strip kpi-strip--executive" data-edify-summary-kpi>
          <div class="kpi-strip__grid">
            <div class="kpi-strip__item" data-component="kpi-card">
              <span class="kpi-strip__topline">
                <span class="kpi-strip__icon-container"></span>
              </span>
              <span class="kpi-strip__item-details">
                <span class="kpi-strip__label">Orders</span>
                <span class="kpi-strip__value">892</span>
              </span>
            </div>
          </div>
        </section>
        """
        self.assertEqual(self._issues(html), [])

    def test_legacy_or_uncontained_tiles_fail(self):
        issues = self._issues(
            '<div class="admin-kpi-strip"><div data-component="kpi-card"></div></div>'
        )
        self.assertTrue(any("legacy KPI class" in issue for issue in issues))
        self.assertTrue(any("outside the approved tray" in issue for issue in issues))

    def test_more_than_six_tiles_fails(self):
        card = """
        <div data-component="kpi-card">
          <span class="kpi-strip__topline"><span class="kpi-strip__icon-container"></span></span>
          <span class="kpi-strip__item-details"><span class="kpi-strip__label"></span><span class="kpi-strip__value"></span></span>
        </div>
        """
        issues = self._issues(
            '<section class="kpi-strip kpi-strip--executive" data-edify-summary-kpi>'
            + card * 7
            + "</section>"
        )
        self.assertTrue(any("maximum is 6" in issue for issue in issues))

    def test_multiple_valid_trays_cannot_bypass_the_page_maximum(self):
        card = """
        <div data-component="kpi-card">
          <span class="kpi-strip__topline"><span class="kpi-strip__icon-container"></span></span>
          <span class="kpi-strip__item-details"><span class="kpi-strip__label"></span><span class="kpi-strip__value"></span></span>
        </div>
        """
        tray = (
            '<section class="kpi-strip kpi-strip--executive" data-edify-summary-kpi>'
            + card * 4
            + "</section>"
        )
        issues = self._issues(tray + tray)
        self.assertIn("page rendered 8 KPI cards; maximum is 6", issues)


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
                continue
            content_type = response.get("Content-Type", "").lower()
            if "text/html" not in content_type or not response.content:
                continue
            parser = _KpiVisualAuditParser()
            parser.feed(
                response.content.decode(response.charset or "utf-8", errors="replace")
            )
            parser.finish()
            failures.extend(f"{url} → {issue}" for issue in parser.issues)
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
