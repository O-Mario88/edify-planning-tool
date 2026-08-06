"""One back control, in one place, on every drill-down page.

The app had a back link on some detail pages and not others, written eleven
different ways — different colours, different arrows ("&larr;" vs "←"), one
button-shaped, one icon-only, one pointing at javascript:history.back(). That
is close enough to absent that users read it as missing. These tests hold the
single shared control in place.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import TestCase

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "templates" / "pages"
PARTIAL = ROOT / "templates" / "partials" / "_back_link.html"

# Drill-down pages: opened from a list, so there is always somewhere to go back
# to. A page added here without the shared include fails the sweep below.
DRILL_DOWN_PAGES = [
    "schools/detail.html",
    "schools/upload.html",
    "clusters/detail.html",
    "districts/detail.html",
    "partners/detail.html",
    "staff/detail.html",
    "projects/detail.html",
    "core_schools/detail.html",
    "my_plan/detail.html",
    "my_plan/evidence_packet.html",
    "fund_requests/detail.html",
    "debriefs/detail.html",
    "planning/schedule.html",
    "closure/activity_closure_detail.html",
    "closure/completed_detail.html",
    "closure/activity_timeline.html",
    "accounts/activity_finance_detail.html",
    "accounts/activity_evidence.html",
    "ia/activity_timeline.html",
    "ia/compare_evidence.html",
    "ssa/upload_center.html",
    "ssa/verification_queue.html",
    "admin/duplicate_review.html",
    "admin/unmatched_ssa_queue.html",
    "hr/conversation_document.html",
    "core_schools/champions.html",
]

INCLUDE = re.compile(
    r'\{%\s*include\s+"partials/_back_link\.html"\s+with\s+'
    r'back_href="(?P<href>[^"]+)"\s+back_label="(?P<label>[^"]+)"'
)


class BackControlCoverageTest(TestCase):
    def test_every_drill_down_page_uses_the_shared_control(self):
        for rel in DRILL_DOWN_PAGES:
            path = PAGES / rel
            with self.subTest(page=rel):
                self.assertTrue(path.exists(), f"{rel} moved or was deleted")
                src = path.read_text()
                match = INCLUDE.search(src)
                self.assertIsNotNone(match, f"{rel} has no shared back control")
                self.assertTrue(match.group("href").startswith("/"))
                self.assertTrue(match.group("label").strip())

    def test_no_page_hand_rolls_its_own_back_link(self):
        """Eleven bespoke variants is what made it read as missing."""
        offenders = []
        for path in PAGES.rglob("*.html"):
            src = path.read_text()
            for line_no, line in enumerate(src.splitlines(), 1):
                if "_back_link.html" in line:
                    continue
                # "Prev"/"Next" pagination arrows are not back navigation.
                if re.search(r"(&larr;|←)\s*(Back|All\b)", line) and "Prev" not in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
        self.assertEqual(
            offenders,
            [],
            f"hand-rolled back links outside the shared partial: {offenders}",
        )

    def test_nothing_navigates_back_through_history(self):
        """history.back() strands anyone who arrived from a deep link, a
        notification or a redirect, and cannot say where it leads."""
        offenders = [
            str(p.relative_to(ROOT))
            for p in PAGES.rglob("*.html")
            if "history.back()" in p.read_text()
        ]
        self.assertEqual(offenders, [])


class BackControlContractTest(TestCase):
    def setUp(self):
        self.src = PARTIAL.read_text()

    def test_it_is_a_real_link_to_the_parent(self):
        self.assertIn('href="{{ back_href }}"', self.src)
        # The comment block explains why history.back() is wrong here, so the
        # markup is what gets checked, not the prose above it.
        markup = self.src.split("{% endcomment %}", 1)[1]
        self.assertNotIn("history.back", markup)

    def test_the_referrer_upgrade_is_same_origin_and_same_path_only(self):
        """Otherwise a hop between two sibling detail pages, or an inbound link
        from another site, could rewrite where 'back' goes."""
        self.assertIn("startsWith(window.location.origin)", self.src)
        self.assertIn("$el.dataset.parent", self.src)

    def test_it_carries_an_accessible_arrow(self):
        self.assertIn('aria-hidden="true"', self.src)
