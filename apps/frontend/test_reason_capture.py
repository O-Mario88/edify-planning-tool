"""Asking a user "why?" is a form field, not a browser prompt.

Two governance actions on the HR performance console — returning an agreement
and recommending a formal performance improvement plan — collected their
justification with `window.prompt()` from an inline `onsubmit` handler, then
wrote the answer into a hidden input. That is unlabelled, unstyled, impossible
to review or correct before sending, and silent to a screen reader; the
validation ("did they type anything?") ran in JavaScript after the fact.

Both now use the shared reason disclosure. These tests pin the outcome and the
rule that produced it, so the pattern cannot come back anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.core.rbac import EdifyRole

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
COMPONENT = "partials/components/reason_disclosure.html"

# Inline handlers, excluding htmx's own hx-on: attribute, which is the
# supported way to attach behaviour in this stack.
INLINE_HANDLER = re.compile(
    r'\bon(click|change|input|submit|mouseover|mouseout|focus|blur)\s*=\s*["\']'
)

# Django comments in both forms, so a note about a removed pattern is not
# mistaken for the pattern.
DJANGO_COMMENT = re.compile(
    r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|\{#.*?#\}", re.S
)
# All three. confirm() joined the list once the shared confirm_action dialog
# and the drawer's own discard panel replaced the twelve call sites that used
# it — a guard that runs ahead of the work it describes is not a guard.
BROWSER_DIALOG = re.compile(r"\b(?:window\.)?(prompt|alert|confirm)\s*\(")


class NoInlineHandlersTest(TestCase):
    """Behaviour belongs to Alpine or htmx, not to an attribute.

    An inline handler cannot be reached by the shared interaction layer, is the
    first thing a Content-Security-Policy blocks, and hides logic from anyone
    reading the component it belongs to.
    """

    def test_no_template_carries_an_inline_event_handler(self):
        offenders = []
        for path in TEMPLATES.rglob("*.html"):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if "hx-on" in line:
                    continue
                if INLINE_HANDLER.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(offenders, [], f"inline event handlers: {offenders}")

    def test_no_template_opens_a_browser_prompt_or_alert(self):
        """`prompt()` and `alert()` are not part of this interface.

        A browser dialog sits outside the page, cannot be styled or themed,
        blocks the tab, and leaves the user to find their own way back to the
        control it was about. Both replacements put the message where the
        problem is: a labelled field for the reason, an inline announced error
        for the missing partner.
        """
        offenders = []
        for path in TEMPLATES.rglob("*.html"):
            # Comments explaining why these were removed are not uses of them.
            source = DJANGO_COMMENT.sub(" ", path.read_text())
            if BROWSER_DIALOG.search(source):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"browser dialogs in templates: {offenders}")


class ReasonDisclosureTest(TestCase):
    def setUp(self):
        self.source = (TEMPLATES / COMPONENT).read_text()

    def test_the_field_is_labelled_and_tied_to_its_input(self):
        """A placeholder is not a label, and an unassociated label is not one
        either — which is what a screen reader got from the prompt version."""
        self.assertIn('for="reason-{{ uid }}"', self.source)
        self.assertIn('id="reason-{{ uid }}"', self.source)

    def test_the_reason_is_required_by_the_browser(self):
        """The prompt version checked for an empty string in JavaScript after
        the user had already committed to submitting."""
        self.assertIn("required", self.source)

    def test_the_disclosure_reports_its_state(self):
        self.assertIn("aria-expanded", self.source)
        self.assertIn("aria-controls", self.source)

    def test_escape_closes_it(self):
        self.assertIn("@keydown.escape", self.source)


class PerformanceConsoleReasonTest(TestCase):
    """The two call sites that had the defect, rendered."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            email="reason-hr@edify.test",
            password="password123",
            name="Hana HR",
            roles=[EdifyRole.HUMAN_RESOURCES.value],
            active_role=EdifyRole.HUMAN_RESOURCES.value,
            is_active=True,
        )
        self.client = Client()
        self.client.force_login(user)

    def test_the_page_opens(self):
        self.assertEqual(self.client.get("/hr/performance-cycle").status_code, 200)

    def test_it_carries_no_browser_dialog(self):
        body = self.client.get("/hr/performance-cycle").content.decode()
        self.assertNotIn("prompt(", body)
        self.assertNotIn("onsubmit=", body)
