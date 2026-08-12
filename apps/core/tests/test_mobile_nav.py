"""Mobile bottom navigation — apps/core/navigation.build_mobile_nav_for_user.

The property that matters most is the one that cannot be seen by looking at the
bar: it advertises only pages the role's own sidebar would offer. A hand-kept
second table of destinations would drift the first time a permission changed,
and the drift would present as a role tapping a tab into a 403.
"""

from pathlib import Path

from django.test import SimpleTestCase

from apps.core.navigation import (
    ACCOUNTANT,
    ADMIN,
    ALL_ROLES,
    CCEO,
    CD,
    HR,
    IA,
    MOBILE_NAV_BY_ROLE,
    MOBILE_NAV_MAX_PRIMARY,
    MOBILE_NAV_SHORT_LABELS,
    PAGE_PERMISSIONS,
    PARTNER,
    PL,
    PROJECT_COORDINATOR,
    RVP,
    build_mobile_nav_for_user,
    build_sidebar_for_user,
)

ROOT = Path(__file__).resolve().parents[3]
MOBILE_SHELL_CSS = ROOT / "static" / "css" / "components" / "mobile-shell.css"

# The label each role constant arrives as on user.active_role.
ROLE_LABELS = {
    ADMIN: "Admin",
    CCEO: "CCEO",
    PL: "Program Lead",
    CD: "Country Director",
    IA: "Impact Assessment",
    RVP: "Regional Vice President",
    HR: "Human Resources",
    ACCOUNTANT: "Accountant",
    PROJECT_COORDINATOR: "Project Coordinator",
    PARTNER: "PartnerFieldOfficer",
}


class _User:
    is_authenticated = True

    def __init__(self, active_role):
        self.active_role = active_role


class _Anon:
    is_authenticated = False
    active_role = None


def nav_for(role, path="/dashboard"):
    return build_mobile_nav_for_user(_User(ROLE_LABELS[role]), path)


class MobileNavShapeTests(SimpleTestCase):
    def test_every_role_gets_a_full_bar(self):
        # A half-empty bar is worse than none: the gap reads as a broken tab.
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                self.assertEqual(len(nav_for(role)), MOBILE_NAV_MAX_PRIMARY)

    def test_no_role_gets_a_duplicate_destination(self):
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                urls = [item["url"] for item in nav_for(role)]
                self.assertEqual(len(urls), len(set(urls)))

    def test_every_item_carries_label_url_and_icon(self):
        for role in ROLE_LABELS:
            for item in nav_for(role):
                with self.subTest(role=role, url=item["url"]):
                    self.assertTrue(item["label"])
                    self.assertTrue(item["url"].startswith("/"))
                    self.assertTrue(item["icon"], "an unlabelled icon slot")

    def test_unauthenticated_user_gets_nothing(self):
        # The template keys the whole bar off this, and the shell falls back to
        # the hamburger when it is empty.
        self.assertEqual(build_mobile_nav_for_user(_Anon(), "/"), [])

    def test_role_with_no_recognised_active_role_gets_nothing(self):
        self.assertEqual(build_mobile_nav_for_user(_User(None), "/"), [])


class MobileShellCssContractTests(SimpleTestCase):
    def test_landscape_safe_area_never_erases_the_workspace_gutter(self):
        css = MOBILE_SHELL_CSS.read_text(encoding="utf-8")
        landscape_rule = css.split("@media (orientation: landscape)", 1)[1].split(
            "/* The off-canvas drawer", 1
        )[0]

        self.assertIn(
            "max(var(--edify-page-gutter), " "env(safe-area-inset-left, 0px))",
            landscape_rule,
        )
        self.assertIn(
            "max(var(--edify-page-gutter), " "env(safe-area-inset-right, 0px))",
            landscape_rule,
        )
        self.assertNotIn(
            "padding-inline: env(safe-area-inset-left, 0px)",
            landscape_rule,
        )


class MobileNavAuthorizationTests(SimpleTestCase):
    """§7: no bottom navigation item for a page the role cannot access."""

    def test_destinations_never_exceed_the_roles_own_sidebar(self):
        for role in ROLE_LABELS:
            sidebar_urls = {
                item["url"]
                for section in build_sidebar_for_user(
                    _User(ROLE_LABELS[role]), "/dashboard"
                )
                for item in section["items"]
            }
            # Standalone destinations are authorized through PAGE_PERMISSIONS
            # rather than the sidebar, so they are allowed to sit outside it.
            standalone = {"/messages", "/ssa", "/ssa/verification/"}
            for item in nav_for(role):
                with self.subTest(role=role, url=item["url"]):
                    self.assertIn(item["url"], sidebar_urls | standalone)

    def test_every_preferred_key_is_a_real_page(self):
        # A typo here would silently fall through to the backfill and nobody
        # would notice the intended destination had never appeared.
        for role, keys in MOBILE_NAV_BY_ROLE.items():
            for key in keys:
                with self.subTest(role=role, key=key):
                    self.assertIn(key, PAGE_PERMISSIONS)

    def test_every_preferred_key_is_authorized_for_that_role(self):
        for role, keys in MOBILE_NAV_BY_ROLE.items():
            for key in keys:
                with self.subTest(role=role, key=key):
                    self.assertIn(
                        role,
                        PAGE_PERMISSIONS[key],
                        f"{role} is offered {key} but is not authorized for it",
                    )

    def test_partner_is_never_offered_the_school_directory(self):
        # PARTNER is absent from PAGE_PERMISSIONS["schools"]; this is the
        # regression guard for the version that offered it anyway.
        urls = {item["url"] for item in nav_for(PARTNER)}
        self.assertNotIn("/schools", urls)


class MobileNavDestinationTests(SimpleTestCase):
    def test_program_lead_has_one_team_oversight_destination(self):
        sections = build_sidebar_for_user(_User(ROLE_LABELS[PL]), "/dashboard")
        items = [item for section in sections for item in section["items"]]

        self.assertEqual(
            [item["label"] for item in items].count("Team Oversight"),
            1,
        )
        self.assertNotIn("Team Targets", {item["label"] for item in items})
        self.assertNotIn("Team Target Oversight", {item["label"] for item in items})

    def test_messages_is_present_for_every_role(self):
        # PAGE_PERMISSIONS["messages"] is ALL_ROLES, and it is the one shared
        # destination the mandate names for every persona.
        self.assertEqual(PAGE_PERMISSIONS["messages"], ALL_ROLES)
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                self.assertIn("/messages", {i["url"] for i in nav_for(role)})

    def test_dashboard_leads_for_every_role(self):
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                self.assertEqual(nav_for(role)[0]["url"], "/dashboard")

    def test_ia_reaches_the_ssa_verification_queue(self):
        # ssa lives in IA_SECTIONS, not SIDEBAR_ITEMS, so it never appears in
        # build_sidebar_for_user output — it arrives via _MOBILE_NAV_STANDALONE.
        urls = [item["url"] for item in nav_for(IA)]
        self.assertIn("/ia/verification/", urls)
        self.assertIn("/ssa/verification/", urls)

    def test_non_ia_roles_get_the_plain_ssa_page(self):
        # role_urls sends only IA to the verification queue.
        nav = build_mobile_nav_for_user(_User(ROLE_LABELS[CD]), "/ssa")
        ssa = [i for i in nav if i["page_key"] == "ssa"]
        if ssa:
            self.assertEqual(ssa[0]["url"], "/ssa")


class MobileNavActiveStateTests(SimpleTestCase):
    def test_current_page_is_marked_active(self):
        nav = nav_for(CCEO, path="/my-plan")
        active = [item for item in nav if item["active"]]
        self.assertEqual([i["url"] for i in active], ["/my-plan"])

    def test_dashboard_is_active_on_root(self):
        nav = nav_for(CCEO, path="/")
        self.assertTrue(nav[0]["active"])

    def test_messages_is_active_on_a_thread_page(self):
        nav = nav_for(CCEO, path="/messages/42")
        messages = [i for i in nav if i["url"] == "/messages"][0]
        self.assertTrue(messages["active"])


class MobileNavLabelTests(SimpleTestCase):
    def test_long_sidebar_labels_are_shortened(self):
        nav = nav_for(ACCOUNTANT)
        labels = {i["page_key"]: i["label"] for i in nav}
        self.assertEqual(labels["disbursements"], "Disburse")

    def test_shortening_does_not_rename_the_sidebar(self):
        # The mobile items are built from the same dicts the sidebar renders.
        # Mutating them in place would rename the desktop sidebar too.
        user = _User(ROLE_LABELS[ACCOUNTANT])
        sections = build_sidebar_for_user(user, "/dashboard")
        build_mobile_nav_for_user(user, "/dashboard", sections=sections)
        sidebar_labels = {
            item["page_key"]: item["label"]
            for section in sections
            for item in section["items"]
        }
        self.assertEqual(sidebar_labels["disbursements"], "Disbursement Dashboard")

    def test_short_labels_stay_short_enough_for_a_tab(self):
        # ~10 characters is what fits a fifth of a 360px screen at 11px before
        # the ellipsis starts eating the word.
        for key, label in MOBILE_NAV_SHORT_LABELS.items():
            with self.subTest(key=key):
                self.assertLessEqual(len(label), 10)

    def test_no_rendered_label_is_unreasonably_long(self):
        for role in ROLE_LABELS:
            for item in nav_for(role):
                with self.subTest(role=role, label=item["label"]):
                    self.assertLessEqual(
                        len(item["label"]),
                        22,
                        "add a MOBILE_NAV_SHORT_LABELS entry for "
                        f"{item['page_key']}",
                    )


class MobileNavReuseTests(SimpleTestCase):
    def test_passing_sections_matches_building_them_internally(self):
        # The context processor passes the sections it already built; the two
        # paths must not diverge.
        user = _User(ROLE_LABELS[PL])
        sections = build_sidebar_for_user(user, "/dashboard")
        self.assertEqual(
            build_mobile_nav_for_user(user, "/dashboard", sections=sections),
            build_mobile_nav_for_user(user, "/dashboard"),
        )
