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
    build_home_shortcuts_for_user,
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
            "max(var(--edify-page-gutter), env(safe-area-inset-left, 0px))",
            landscape_rule,
        )
        self.assertIn(
            "max(var(--edify-page-gutter), env(safe-area-inset-right, 0px))",
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
            standalone = {"/home", "/messages"}
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
    def test_program_lead_has_one_planning_oversight_destination(self):
        # The destination was renamed from Team Oversight on 2026-09-20 when
        # What Needs You Now moved to the dashboard; it is still one entry.
        sections = build_sidebar_for_user(_User(ROLE_LABELS[PL]), "/dashboard")
        items = [item for section in sections for item in section["items"]]

        self.assertEqual(
            [item["label"] for item in items].count("Planning Oversight"),
            1,
        )
        self.assertNotIn("Team Oversight", {item["label"] for item in items})
        self.assertNotIn("Team Targets", {item["label"] for item in items})
        self.assertNotIn("Team Target Oversight", {item["label"] for item in items})

    def test_every_bar_is_home_two_role_pages_and_messages(self):
        # Home leads (owner, 2026-10-21, the approved mockup); Messages keeps
        # its tab and the notification bell its place in the top bar (owner,
        # same day: "where they were").
        self.assertEqual(PAGE_PERMISSIONS["home"], ALL_ROLES)
        self.assertEqual(PAGE_PERMISSIONS["messages"], ALL_ROLES)
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                urls = [i["url"] for i in nav_for(role)]
                self.assertEqual(urls[0], "/home")
                self.assertEqual(urls[-1], "/messages")
                self.assertNotIn("/notifications", urls)

    def test_the_field_officers_bar_is_the_mockups(self):
        self.assertEqual(
            [(i["label"], i["url"]) for i in nav_for(CCEO)],
            [
                ("Home", "/home"),
                ("My Plan", "/my-plan"),
                ("Schools", "/schools"),
                ("Messages", "/messages"),
            ],
        )

    def test_each_roles_own_home_is_homes_first_shortcut(self):
        # The page each role's phone used to open on — its dashboard, IA's
        # own dashboard, Country Oversight, a partner's Assigned Schools
        # intake — is one tap from Home rather than a tab.
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                if role == PARTNER:
                    expected = "/partner/assigned-schools"
                elif role == IA:
                    expected = "/ia/dashboard/"
                elif role == CD:
                    expected = "/country-planning-oversight/"
                else:
                    expected = "/dashboard"
                bar = [i["url"] for i in nav_for(role)]
                shortcuts = [
                    i["url"]
                    for i in build_home_shortcuts_for_user(
                        _User(ROLE_LABELS[role]), "/home"
                    )
                ]
                if expected in bar:
                    # A partner's intake is a tab of its own.
                    self.assertNotIn(expected, shortcuts)
                else:
                    self.assertEqual(shortcuts[0], expected)

    def test_portal_roles_keep_their_own_home_beside_home(self):
        # The MFI portal and the Business Transformation workspace are those
        # roles' homes, so they are the tab after Home.
        for role, expected in (
            ("MFI_ADMIN", "/mfi-portal/dashboard"),
            ("MFI_OFFICER", "/mfi-portal/dashboard"),
            ("BUSINESS_TRANSFORMATION", "/business-transformation/overview"),
        ):
            with self.subTest(role=role):
                nav = build_mobile_nav_for_user(_User(role), expected)
                self.assertEqual(nav[0]["url"], "/home")
                self.assertEqual(nav[1]["url"], expected)
                self.assertTrue(nav[1]["active"])
                urls = [item["url"] for item in nav]
                self.assertEqual(len(urls), len(set(urls)))

    def test_ia_phone_leads_with_the_days_queue(self):
        # IA review (2026-09-13): To-Do and the verification queue. SSA
        # Verification and Partner Evidence are Home shortcuts.
        urls = [item["url"] for item in nav_for(IA)]
        self.assertEqual(urls, ["/home", "/todos", "/ia/verification/", "/messages"])

    def test_shortcuts_never_repeat_a_tab(self):
        for role in ROLE_LABELS:
            with self.subTest(role=role):
                user = _User(ROLE_LABELS[role])
                bar = {i["url"] for i in nav_for(role)}
                shortcuts = build_home_shortcuts_for_user(user, "/home")
                self.assertTrue(shortcuts)
                self.assertFalse(bar & {i["url"] for i in shortcuts})


class MobileNavActiveStateTests(SimpleTestCase):
    def test_current_page_is_marked_active(self):
        nav = nav_for(CCEO, path="/my-plan")
        active = [item for item in nav if item["active"]]
        self.assertEqual([i["url"] for i in active], ["/my-plan"])

    def test_home_is_active_on_home_and_only_there(self):
        nav = nav_for(RVP, path="/home")
        self.assertEqual(nav[0]["url"], "/home")
        self.assertTrue(nav[0]["active"])
        self.assertFalse(nav_for(RVP, path="/home/else")[0]["active"])
        self.assertFalse(nav_for(RVP, path="/dashboard")[0]["active"])

    def test_the_field_bar_has_no_today_or_dashboard_tab(self):
        # Today and Dashboard are one page (owner, 2026-09-14), and it is a
        # Home shortcut now.
        for role in (CCEO, PL, PROJECT_COORDINATOR):
            with self.subTest(role=role):
                urls = [item["url"] for item in nav_for(role, path="/dashboard")]
                self.assertNotIn("/today", urls)
                self.assertNotIn("/dashboard", urls)

    def test_messages_is_active_on_a_thread_page(self):
        nav = nav_for(CCEO, path="/messages/42")
        messages = [i for i in nav if i["url"] == "/messages"][0]
        self.assertTrue(messages["active"])

    def test_long_sidebar_labels_are_shortened(self):
        nav = nav_for(ACCOUNTANT)
        labels = {i["page_key"]: i["label"] for i in nav}
        self.assertEqual(labels["weekly_fund_request"], "Funds")

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
        self.assertEqual(
            sidebar_labels["weekly_fund_request"], "Weekly Advance Request"
        )

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
                        f"add a MOBILE_NAV_SHORT_LABELS entry for {item['page_key']}",
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
