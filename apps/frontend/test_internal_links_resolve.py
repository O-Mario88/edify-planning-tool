"""Every hard-coded internal URL in the product must resolve to a real route.

A link that 404s is invisible to the test suite and to a status-code crawl: the
page it lives on returns 200, the control renders, the count next to it is
correct, and the defect only appears when somebody clicks. Two shipped that way
and were found by opening every Country Director page and following its
controls — `/activities?status=awaiting_ia_verification` behind the Team Targets
validation tiles, and `/weekly-fund-request` behind a Project Coordinator KPI
whose real route is `/fund-requests/weekly`.

Following controls at runtime only reaches pages a crawl can reach. This is the
static half: it reads the literals themselves, so a link on a page that needs a
particular role, a particular object id, or a particular state is checked too.

Deliberately narrow, to stay honest rather than noisy:

* only literals in link position — a template's `href`/`hx-*`/`action`, or a
  Python dict under a `href`/`link`/`url`/`action` key. A bare "/something"
  elsewhere in Python is as likely to be a file path as a route;
* only fully-literal URLs. Anything carrying a template variable or an f-string
  placeholder is skipped, because its real value is not knowable here;
* resolution only. That a route exists says nothing about whether this user may
  open it — that is the runtime sweep's job, and a different question.
"""

from __future__ import annotations

import pathlib
import re

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

TEMPLATE_LINK = re.compile(
    r'(?:href|hx-get|hx-post|hx-put|hx-delete|action)\s*=\s*"(/[^"]*)"'
)
PYTHON_LINK = re.compile(
    r'[\'"](?:href|link|url|action)[\'"]\s*:\s*[\'"](/[^\'"]*)[\'"]'
)

# Not routed by Django's URLconf, or deliberately handled elsewhere.
EXEMPT_PREFIXES = ("/static/", "/media/", "/admin/", "/favicon", "/__")

# A value is only checkable if it is entirely literal.
INTERPOLATED = re.compile(r"[{}%]|\$\{")

# Usage examples are not links. Component templates document themselves with a
# sample call in a {% comment %} block, and Python docstrings do the same —
# `href="/back"` in button.html and `hx-post="/validate"` in input.html are
# both illustrations of the attribute, not routes anybody navigates to.
TEMPLATE_COMMENT = re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S)
PY_DOCSTRING = re.compile(r'"""(?:.|\n)*?"""' + r"|'''(?:.|\n)*?'''")
PY_COMMENT = re.compile(r"^[ \t]*#.*$", re.M)


def _strip_prose(text: str, suffix: str) -> str:
    """Remove the parts of a file that talk about code rather than being it."""
    if suffix == ".html":
        return TEMPLATE_COMMENT.sub("", text)
    return PY_COMMENT.sub("", PY_DOCSTRING.sub("", text))


def _candidates():
    """(source file, url) for every literal internal link in link position."""
    for base, pattern in (
        (ROOT / "templates", TEMPLATE_LINK),
        (ROOT / "apps", PYTHON_LINK),
    ):
        suffix = ".html" if base.name == "templates" else ".py"
        for path in base.rglob(f"*{suffix}"):
            if "__pycache__" in path.parts or path.name.startswith("test_"):
                continue
            try:
                text = _strip_prose(path.read_text(encoding="utf8"), suffix)
            except (OSError, UnicodeDecodeError):
                continue
            for match in pattern.finditer(text):
                raw = match.group(1)
                if INTERPOLATED.search(raw) or raw.startswith(EXEMPT_PREFIXES):
                    continue
                url = raw.split("?", 1)[0].split("#", 1)[0]
                if url and url != "/" and not url.endswith("/"):
                    yield path.relative_to(ROOT), url
                elif url:
                    yield path.relative_to(ROOT), url


class InternalLinksResolveTest(SimpleTestCase):
    def test_every_literal_internal_link_resolves(self):
        broken: dict[str, set[str]] = {}
        for source, url in _candidates():
            try:
                resolve(url)
            except Resolver404:
                broken.setdefault(url, set()).add(str(source))
        if broken:
            lines = [
                f"  {url}\n      {', '.join(sorted(sources))}"
                for url, sources in sorted(broken.items())
            ]
            self.fail(
                f"{len(broken)} internal link(s) point at no route:\n"
                + "\n".join(lines)
            )

    def test_the_scan_actually_finds_links(self):
        """Guards the guard.

        If a refactor moved the templates, changed the attribute spelling, or
        broke either regex, the test above would pass by checking nothing —
        which is the failure mode that lets a dead link ship.
        """
        found = list(_candidates())
        self.assertGreater(
            len(found), 200, "the link scan found almost nothing; it is not working"
        )
        sources = {str(s) for s, _ in found}
        self.assertTrue(
            any(s.startswith("templates/") for s in sources), "no template links found"
        )
        self.assertTrue(
            any(s.startswith("apps/") for s in sources), "no Python links found"
        )

    def test_a_known_bad_url_would_be_caught(self):
        """The regexes are only worth having if a broken value fails them."""
        with self.assertRaises(Resolver404):
            resolve("/weekly-fund-request")
