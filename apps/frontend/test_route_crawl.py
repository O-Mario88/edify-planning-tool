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
from django.test import Client, SimpleTestCase, TestCase, override_settings
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
REQUIRED_CONTEXT_METRIC_PARTS = frozenset(
    {"context-metrics__label", "context-metrics__value"}
)


class _KpiVisualAuditParser(HTMLParser):
    """Validate contextual metric DOM without browser selectors."""

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
        self.total_metric_count = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        legacy = sorted(classes & LEGACY_KPI_CLASSES)
        if legacy:
            self.issues.append(f"legacy KPI class rendered: {', '.join(legacy)}")

        is_summary = "data-context-metrics" in attributes
        if "kpi-strip" in classes or "data-edify-summary-kpi" in attributes:
            self.issues.append("retired KPI strip rendered")
        if is_summary and "context-metrics" not in classes:
            self.issues.append("metric summary is missing its context class")

        current_metric = next(
            (node for node in reversed(self.stack) if node["is_metric"]), None
        )
        if current_metric is not None:
            current_metric["parts"].update(classes & REQUIRED_CONTEXT_METRIC_PARTS)

        if attributes.get("data-component") == "kpi-card":
            self.issues.append("retired KPI card rendered")

        is_metric = attributes.get("data-component") == "context-metric"
        if is_metric:
            self.total_metric_count += 1
            summary = next(
                (node for node in reversed(self.stack) if node["is_summary"]), None
            )
            if summary is None:
                self.issues.append("context metric rendered outside its summary")
            else:
                summary["metric_count"] += 1

        node = {
            "tag": tag,
            "is_summary": is_summary,
            "metric_count": 0,
            "is_metric": is_metric,
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
        # Context facts have no arbitrary cap; the component wraps as prose.

    def _finish_node(self, node):
        if node["is_summary"] and node["metric_count"] == 0:
            self.issues.append("context summary rendered no metrics at all")
        if node["is_metric"]:
            missing = sorted(REQUIRED_CONTEXT_METRIC_PARTS - node["parts"])
            if missing:
                self.issues.append(
                    "context metric is missing required parts: " + ", ".join(missing)
                )


class KpiVisualAuditParserTests(SimpleTestCase):
    def _issues(self, html: str) -> list[str]:
        parser = _KpiVisualAuditParser()
        parser.feed(html)
        parser.finish()
        return parser.issues

    def test_approved_context_summary_passes(self):
        html = """
        <section class="context-metrics" data-context-metrics>
          <div class="context-metrics__sentence">
            <span class="context-metrics__fact" data-component="context-metric">
              <strong class="context-metrics__value">892</strong>
              <span class="context-metrics__label">Orders</span>
            </span>
          </div>
        </section>
        """
        self.assertEqual(self._issues(html), [])

    def test_legacy_or_uncontained_metrics_fail(self):
        issues = self._issues(
            '<div class="admin-kpi-strip"><span data-component="context-metric"></span></div>'
        )
        self.assertTrue(any("legacy KPI class" in issue for issue in issues))
        self.assertTrue(any("outside its summary" in issue for issue in issues))

    FACT = """
        <span class="context-metrics__fact" data-component="context-metric">
          <strong class="context-metrics__value"></strong>
          <span class="context-metrics__label"></span>
        </span>
        """

    def test_seven_context_facts_is_not_a_fault(self):
        issues = self._issues(
            '<section class="context-metrics" data-context-metrics>'
            + self.FACT * 7
            + "</section>"
        )
        self.assertEqual(
            [issue for issue in issues if "maximum" in issue],
            [],
            "the crawl is capping the context summary",
        )

    def test_an_empty_summary_is_still_a_fault(self):
        issues = self._issues(
            '<section class="context-metrics" data-context-metrics>' "</section>"
        )
        self.assertIn("context summary rendered no metrics at all", issues)

    def test_every_metric_must_still_be_complete(self):
        issues = self._issues(
            '<section class="context-metrics" data-context-metrics>'
            + self.FACT * 7
            + '<span data-component="context-metric"></span>'
            + "</section>"
        )
        self.assertTrue(any("missing required parts" in issue for issue in issues))


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


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "kpi-platform-crawl",
        }
    }
)
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
        import json
        from pathlib import Path
        from django.conf import settings
        import re

        audit_dir = Path(settings.BASE_DIR) / "test-results/kpi-platform-crawl"
        audit_dir.mkdir(parents=True, exist_ok=True)
        records = []
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
            records.append(
                {
                    "url": url,
                    "status": response.status_code,
                    "metrics": parser.total_metric_count,
                    "issues": parser.issues,
                }
            )
            if response.status_code == 200 and b"<html" in response.content:
                filename = re.sub(r"[^a-zA-Z0-9_-]", "_", role + "-" + url) + ".html"
                (audit_dir / filename).write_bytes(response.content)
            failures.extend(f"{url} → {issue}" for issue in parser.issues)
        (audit_dir / (re.sub(r"[^a-zA-Z0-9_-]", "_", role) + ".json")).write_text(
            json.dumps(records, indent=2)
        )
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
