"""Back · Forward · Refresh in the top bar (owner, 2026-09-12).

The app installs as a standalone PWA, so an installed user has no browser
chrome. The shell carries one three-button history group at the left of the
top bar; the script disables back and forward when there is nowhere to go and
spins refresh until the page is gone; forward is hidden on phones.
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase


def _read(path: str) -> str:
    return Path(path).read_text()


class HistoryControlsTest(SimpleTestCase):
    def test_the_shell_carries_one_history_group_before_everything_else(self):
        shell = _read("templates/layouts/shell.html")
        self.assertEqual(shell.count("data-history-controls"), 1)
        lead = shell.index('class="edify-topbar__lead')
        group = shell.index("data-history-controls")
        search = shell.index("<search")
        self.assertLess(lead, group)
        self.assertLess(group, search)
        for marker, label in (
            ("data-history-back", 'aria-label="Go back"'),
            ("data-history-forward", 'aria-label="Go forward"'),
            ("data-history-refresh", 'aria-label="Refresh this page"'),
        ):
            with self.subTest(marker=marker):
                self.assertEqual(shell.count(marker), 1)
                self.assertIn(label, shell)
        self.assertIn('aria-label="Page history"', shell)

    def test_the_script_is_loaded_and_does_what_the_browser_would(self):
        base = _read("templates/base.html")
        self.assertIn("js/history-controls.js", base)
        script = _read("static/js/history-controls.js")
        self.assertIn("window.history.back()", script)
        self.assertIn("window.history.forward()", script)
        self.assertIn("window.location.reload()", script)
        self.assertIn("backButton.disabled = !s.back", script)
        self.assertIn("forwardButton.disabled = !s.forward", script)
        self.assertIn('classList.add("is-refreshing")', script)

    def test_forward_hides_on_phones_and_a_dead_control_fades(self):
        css = _read("static/css/components.css")
        self.assertIn(".edify-topbar__history-control:disabled", css)
        self.assertIn(
            "@media (max-width: 48rem) {\n  .edify-topbar__history-control--forward {\n    display: none;",
            css,
        )
        self.assertIn("prefers-reduced-motion: reduce", css)
