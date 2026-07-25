"""Irreversible actions ask in the product, not in a browser dialog.

Twelve call sites used `window.confirm()`. Seven were the same "You have
unsaved changes. Discard changes?" block copied into the drawer shell three
times and into four child drawers; the other five guarded a delete, a revoke,
a batch flag and an audited strategic decision.

A browser dialog cannot be themed, renders identically whether it is deleting
a school or dismissing a tooltip, and offers "OK / Cancel" where the user needs
to read what is about to happen. Worse, its default answer is the destructive
one. These tests pin the replacements: a shared confirm_action dialog for the
destructive cases and a discard panel inside the drawer for unsaved work.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.accounts.models import PublicHoliday
from apps.core.rbac import EdifyRole

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
DIALOG = TEMPLATES / "partials" / "components" / "confirm_action.html"
DRAWER = TEMPLATES / "components" / "drawers" / "base_drawer.html"


def _user(email: str, role: str):
    return get_user_model().objects.create_user(
        email=email,
        password="password123",
        name="Confirm Tester",
        roles=[role],
        active_role=role,
        is_active=True,
    )


class DialogContractTest(TestCase):
    """What the platform's overlay contract asks of every dialog."""

    def setUp(self):
        self.source = DIALOG.read_text()

    def test_it_announces_itself_as_a_dialog_about_a_decision(self):
        self.assertIn('role="alertdialog"', self.source)
        self.assertIn('aria-modal="true"', self.source)

    def test_its_title_and_body_are_named_not_just_rendered(self):
        self.assertIn("aria-labelledby", self.source)
        self.assertIn("aria-describedby", self.source)

    def test_escape_closes_it(self):
        self.assertIn("@keydown.escape.window", self.source)

    def test_tab_is_trapped_inside_it(self):
        """Otherwise the next Tab lands on the page behind the dialog."""
        self.assertIn("@keydown.tab", self.source)
        self.assertIn("trap($event)", self.source)

    def test_the_safe_answer_holds_focus(self):
        """A browser confirm() defaults to OK. Here Return cancels."""
        self.assertIn('x-ref="cancel"', self.source)


class DrawerDiscardTest(TestCase):
    def setUp(self):
        self.source = DRAWER.read_text()

    def test_every_close_path_goes_through_one_method(self):
        """Backdrop, Escape, the header button and each footer Cancel — the
        seven-line confirm() block used to be written out at every one."""
        self.assertGreaterEqual(self.source.count("requestClose()"), 4)

    def test_the_drawer_asks_inside_itself(self):
        self.assertIn("drawer-discard", self.source)
        self.assertIn('role="alertdialog"', self.source)

    def test_keeping_your_work_holds_focus(self):
        self.assertIn('x-ref="discardKeep"', self.source)

    def test_escape_backs_out_of_the_question_before_the_drawer(self):
        """Escape while being asked should answer the question, not close the
        drawer underneath it and lose the work anyway."""
        self.assertIn(
            "confirmDiscard ? (confirmDiscard = false) : requestClose()", self.source
        )


class RenderedCallSiteTest(TestCase):
    """The dialog reaches the pages that used to open a browser one."""

    def test_school_delete_asks_in_the_page(self):
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="Confirm Region")
        district = District.objects.create(name="Confirm District", region=region)
        school = School.objects.create(
            school_id="CONF-1", name="Confirm Primary", region=region, district=district
        )
        client = Client()
        client.force_login(_user("confirm-admin@edify.test", EdifyRole.ADMIN.value))
        body = client.get(f"/schools/{school.school_id}").content.decode()
        self.assertIn("confirm-action__panel", body)
        self.assertNotIn("confirm(", body)

    def test_removing_a_public_holiday_asks_in_the_page(self):
        """This one is icon-only, so it also has to keep its accessible name."""
        PublicHoliday.objects.create(name="Confirm Day", date=dt.date(2026, 12, 26))
        client = Client()
        client.force_login(
            _user("confirm-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        )
        body = client.get("/leave/policies").content.decode()
        self.assertIn("confirm-action__panel", body)
        self.assertIn("Remove this public holiday?", body)
        self.assertIn('aria-label="Remove public holiday"', body)
        self.assertNotIn("confirm(", body)

    def test_the_body_says_what_will_actually_happen(self):
        """ "Are you sure?" is not information. The batch flag in particular
        had to keep its warning that schools are not reverted."""
        PublicHoliday.objects.create(name="Confirm Day 2", date=dt.date(2026, 12, 27))
        client = Client()
        client.force_login(
            _user("confirm-hr2@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        )
        body = client.get("/leave/policies").content.decode()
        self.assertIn("Activities already scheduled on it are not moved", body)
