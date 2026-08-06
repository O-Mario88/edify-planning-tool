"""Every full page names itself in the browser tab.

`layouts/shell.html` supplies a fallback `<title>`, so a page that forgets
`{% block title %}` still renders — it just renders as the product name. That
is invisible in review and only shows up where it costs something: the browser
tab, the history entry, the bookmark and the search result all say "Edify
School Improvement Planning" instead of what the page is.

Four templates had drifted that way. `/my-performance` was the one caught on
production during the live audit; grepping the other 175 shell pages found
three more, all in the same HR corner, which is what a ratchet is for — the
fourth one is added by someone in a hurry, not by the person who wrote the
first three.

This asserts the property directly against the template files rather than by
crawling routes: a page can be unreachable for the current role, or need
fixtures to render, and still owe the user a title.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SHELL = 'extends "layouts/shell.html"'


def _shell_pages():
    root = Path(settings.BASE_DIR) / "templates" / "pages"
    return [p for p in root.rglob("*.html") if SHELL in p.read_text(encoding="utf-8")]


class EveryShellPageDeclaresATitleTest(SimpleTestCase):
    def test_the_scan_finds_the_pages_at_all(self):
        # Guards the guard: a glob that matched nothing would make the real
        # assertion below pass forever.
        self.assertGreater(len(_shell_pages()), 100)

    def test_no_shell_page_falls_back_to_the_default_title(self):
        missing = sorted(
            str(p.relative_to(settings.BASE_DIR))
            for p in _shell_pages()
            if "{% block title %}" not in p.read_text(encoding="utf-8")
        )
        self.assertEqual(
            missing,
            [],
            "these pages inherit the shell's default <title>, so their browser "
            f"tab reads as the product name rather than the page: {missing}",
        )
