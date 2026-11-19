"""A part of a page carried as its own element structure, safely.

The Admin dashboard's workspace is a dozen bespoke cards (column charts,
two-year SSA bars, mini tiles, a quick-action grid) that the blocks cannot
say. On a desktop reading it is carried as its element structure for the web
app to draw with the existing stylesheets: only safe elements, class names,
text, in-app links and percentage sizes. Nothing that runs or posts is ever
carried. The phone's reading is unchanged.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.mobile_feed import markup_tree, page_blocks

WORKSPACE = """
<main>
<div class="admin-workspace mobile-home-deferred">
  <section class="admin-panel admin-planning-progress" aria-labelledby="t" data-card-key="planning_progress">
    <header class="admin-panel__header"><h2 id="t">Planning Progress</h2>
      <nav class="admin-period-switch" data-edify-tablist aria-label="Period">
        <a href="?progress_period=week" hx-get="/dashboard/planning-progress?progress_period=week" data-edify-tab class="is-active" aria-current="true">Week</a>
      </nav>
    </header>
    <div class="edify-column-chart">
      <div class="edify-column-chart__item"><div class="edify-column-chart__track"><span style="height:36%"><strong>36%</strong></span></div><span>19 Oct</span></div>
    </div>
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" d="M5 12h14"/></svg>
  </section>
</div>
</main>
"""


def _find(node: dict, tag: str) -> dict | None:
    if node.get("tag") == tag:
        return node
    for child in node.get("children", []):
        if (found := _find(child, tag)) is not None:
            return found
    return None


class MarkupTreeTest(SimpleTestCase):
    def test_the_workspace_is_one_markup_block_on_a_desktop(self):
        blocks = page_blocks.read(WORKSPACE, path="/dashboard", desktop=True)["blocks"]

        self.assertEqual(len(blocks), 1)
        root = blocks[0]["markup"]["root"]
        self.assertEqual(
            (root["tag"], root["className"]),
            ("div", "admin-workspace mobile-home-deferred"),
        )

    def test_the_phone_still_reads_it_as_blocks(self):
        blocks = page_blocks.read(WORKSPACE, path="/dashboard")["blocks"]

        self.assertFalse(any("markup" in block for block in blocks))

    def test_it_keeps_classes_links_sizes_and_the_attributes_css_reads(self):
        root = page_blocks.read(WORKSPACE, path="/dashboard", desktop=True)["blocks"][
            0
        ]["markup"]["root"]

        link = _find(root, "a")
        self.assertEqual(link["attrs"]["href"], "?progress_period=week")
        self.assertEqual(link["attrs"]["aria-current"], "true")
        self.assertIn("data-edify-tab", link["attrs"])
        self.assertNotIn("hx-get", link["attrs"])
        self.assertEqual(link["children"], [{"text": "Week"}])
        bar = _find(root, "span")
        self.assertEqual(bar["style"], {"height": "36%"})
        svg = _find(root, "svg")
        self.assertEqual(svg["attrs"]["viewBox"], "0 0 24 24")
        self.assertEqual(_find(svg, "path")["attrs"]["d"], "M5 12h14")


class MarkupSafetyTest(SimpleTestCase):
    def _tree(self, html: str) -> dict:
        return markup_tree.read(page_blocks.parse(html).children[0])

    def test_nothing_that_runs_is_carried(self):
        tree = self._tree(
            '<div class="admin-workspace" onclick="x()">'
            '<a href="javascript:alert(1)" onmouseover="x()">bad</a>'
            '<a href="//evil.example/x">far</a>'
            '<a href="https://evil.example/x">far</a>'
            "<script>alert(1)</script><style>p{}</style>"
            '<form action="/x"><input name="a"></form>'
            '<iframe src="/x"></iframe>'
            '<span style="background:url(https://evil.example/x);width:40%">s</span>'
            '<span style="width: calc(100% - 1px)">c</span>'
            '<img src="/x" onerror="x()">'
            "</div>"
        )
        self.assertNotIn("onclick", tree.get("attrs", {}))
        links = [c for c in tree["children"] if c.get("tag") == "a"]
        self.assertEqual(
            [link.get("attrs", {}).get("href") for link in links], [None, None, None]
        )
        self.assertTrue(
            all("onmouseover" not in link.get("attrs", {}) for link in links)
        )
        tags = {c.get("tag") for c in tree["children"]}
        self.assertTrue(
            tags.isdisjoint({"script", "style", "form", "input", "iframe", "img"})
        )
        spans = [c for c in tree["children"] if c.get("tag") == "span"]
        self.assertEqual(
            [span.get("style", {}) for span in spans], [{"width": "40%"}, {}]
        )
