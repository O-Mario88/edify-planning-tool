"""One persistent search per page: the top bar's.

The UI mandate: no page-level search bar may compete with the canonical
top-bar search. This guard enforces it structurally — pages still carrying a
body search input are pinned in a SHRINKING allowlist. Rewiring a page means
deleting its line here; adding a new body search anywhere fails this test.
Drawer/modal selector searches (an enclosed dataset picker) are exempt by
detection: inputs inside files whose path says drawer/modal/compose, and the
dedicated /search and help pages.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# Pages the inventory found with a persistent body search, not yet rewired to
# the top-bar contract. THIS LIST MAY ONLY SHRINK.
REMAINING = {
    "pages/trainings/index.html",
    "pages/visits/index.html",
    "pages/debriefs/dashboard.html",
    "pages/ia/verification_queue.html",
    "pages/planning/index.html",
    "pages/accounts/dashboard.html",
    "pages/partners/index.html",
    "pages/hr/professional_development_dashboard.html",
    "pages/notifications/index.html",
    "pages/leave/leave_approvals.html",
    "partials/evidence/workspace.html",
    "partials/disbursements/root.html",
    "partials/fund_requests/root.html",
    "partials/clusters/filters.html",
    "partials/finance/fund_allocation_filters.html",
    "partials/fund_approvals/root.html",
    "partials/finance/country_budget/root.html",
}

# Enclosed-selector or dedicated-search surfaces, allowed by design (§17).
# pages/messages/new.html: the compose flow's context-record picker — an
# enclosed selector over one dataset, gone when the panel closes (§17).
EXEMPT_MARKERS = (
    "drawer",
    "modal",
    "compose",
    "pages/search/",
    "pages/help",
    "pages/messages/new.html",
)

SEARCH_INPUT = re.compile(
    r"<input[^>]*type=[\"']search[\"']"
    r"|<input[^>]*name=[\"'](q|search)[\"']"
    r"|<input[^>]*placeholder=[\"']Search",
    re.IGNORECASE,
)


class SearchConsolidationGuard(SimpleTestCase):
    def _template_files(self):
        root = Path(settings.BASE_DIR, "templates")
        for path in root.rglob("*.html"):
            rel = str(path.relative_to(root))
            if any(m in rel for m in EXEMPT_MARKERS):
                continue
            yield rel, path

    def test_no_page_outside_the_allowlist_carries_a_body_search(self):
        offenders = []
        for rel, path in self._template_files():
            if rel in REMAINING:
                continue
            if "layouts/shell.html" in rel:
                continue  # the canonical top-bar search itself
            if SEARCH_INPUT.search(path.read_text(errors="ignore")):
                offenders.append(rel)
        self.assertEqual(
            sorted(offenders),
            [],
            "a page grew a persistent body search — the top bar is the one "
            "search; bind topbar_search context instead (pattern in "
            "docs/verification-ledger-2026-07-21.md)",
        )

    def test_the_allowlist_only_shrinks(self):
        root = Path(settings.BASE_DIR, "templates")
        gone = [
            rel
            for rel in REMAINING
            if not (root / rel).exists()
            or not SEARCH_INPUT.search((root / rel).read_text(errors="ignore"))
        ]
        self.assertEqual(
            sorted(gone),
            [],
            "these pages no longer carry a body search — delete their lines "
            "from REMAINING so the guard tightens behind the fix",
        )
