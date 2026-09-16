"""Impact Assessment's navigation follows its role description.

IA review (owner, 2026-09-13): one workspace strip carries every IA page and
the shared analytics pages IA reads; the grants and doors that had nothing to
do with the role are gone; and the phone leads with the day's queue. Since
2026-09-14 the sidebar is grouped by how often each page is visited
(apps.core.nav_cadence): the verification queues IA works every day first, the
five responsibilities after them in the rhythm they are worked.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.navigation import (
    ADMIN,
    CD,
    IA,
    IA_SECTIONS,
    MOBILE_NAV_BY_ROLE,
    PAGE_PERMISSIONS,
    ROLE_SIDEBAR_GROUP_ORDER,
    WORKSPACE_CLUSTER_LABELS,
    build_mobile_nav_for_user,
    build_sidebar_for_user,
    build_workspace,
)
from apps.core.rbac import ROLE_PERMISSIONS, EdifyRole, Permission


def _user(role):
    return SimpleNamespace(is_authenticated=True, active_role=role)


def _groups(role, path="/dashboard"):
    return build_sidebar_for_user(_user(role), path)


# The order IA's pages are registered in, which breaks ties inside a visit
# tier: the day's work, the five responsibilities, then verification.
IA_RESPONSIBILITY_ORDER = (
    "MY WORK",
    "FRAMEWORK & STRATEGY",
    "BASELINE & FIELD DATA",
    "SCHOOL PROGRESS",
    "ANALYSIS & LEARNING",
    "REPORTING & ACCOUNTABILITY",
    "DATA QUALITY & VERIFICATION",
    "FINANCE & BUDGET",
    "MY PERFORMANCE",
)

IA_SIDEBAR = [
    (
        "DAILY",
        [
            ("Dashboard", "/ia/dashboard/"),
            ("To-Do", "/todos"),
            ("Verification Queue", "/ia/verification/"),
            ("SSA Verification", "/ssa/verification/"),
            ("Partner Evidence", "/ia/partner-evidence/"),
            ("My Plan", "/my-plan"),
            ("Calendar", "/calendar"),
        ],
    ),
    (
        "WEEKLY",
        [
            ("Weekly Advance Request", "/fund-requests/weekly"),
            ("Planning", "/planning"),
            ("Field Debrief", "/debriefs"),
            ("School Evidence", "/ia/school-evidence/"),
            ("SSA Upload Center", "/ssa/upload/"),
            ("Returned Activities", "/ia/returned/"),
            ("Data Quality", "/admin-panel/data-quality-center"),
            ("Upload Center", "/uploads"),
        ],
    ),
    (
        "MONTHLY",
        [
            ("My Targets", "/my-targets"),
            ("Impact Reports", "/ia/impact-reports/"),
            ("Programme Learning", "/ia/learning/"),
            ("Most Significant Change", "/ia/stories/"),
            ("Lending Evidence", "/ia/lending-evidence/"),
            ("Loans", "/loans"),
        ],
    ),
    (
        "PLANNING CYCLE",
        [
            ("Priorities", "/target-distribution"),
            ("Measurement Framework", "/ia/framework/"),
            ("My Performance Agreement", "/my-performance"),
            ("My Professional Development", "/my-professional-development"),
        ],
    ),
    (
        "REFERENCE",
        [
            ("Leave & Personal Time Off", "/personal-time-off/"),
            ("School Directory", "/schools"),
            ("Closed Schools", "/schools/closed"),
            # Reassigning a district portfolio is Impact Assessment work
            # (owner, 2026-09-15) and rare: a reference door, not a daily one.
            ("Ownership Transfers", "/ownership-transfers/"),
        ],
    ),
]


class IaSidebarTest(SimpleTestCase):
    def test_groups_run_from_most_to_least_visited(self):
        self.assertEqual(
            [g["label"] for g in _groups(IA)], [label for label, _ in IA_SIDEBAR]
        )
        self.assertEqual(ROLE_SIDEBAR_GROUP_ORDER[IA], IA_RESPONSIBILITY_ORDER)

    def test_each_page_sits_in_the_rhythm_it_is_worked(self):
        self.assertEqual(
            [
                (g["label"], [(i["label"], i["url"]) for i in g["items"]])
                for g in _groups(IA)
            ],
            IA_SIDEBAR,
        )

    def test_doors_unrelated_to_the_role_are_gone(self):
        labels = {i["label"] for g in _groups(IA) for i in g["items"]}
        urls = {i["url"] for g in _groups(IA) for i in g["items"]}
        for label in (
            "Team Oversight",
            "Quality Flags",
            "My Actions",
            "Actions Sent",
            "Work Plan",
            "Budget",
            "Analytics",
        ):
            with self.subTest(label=label):
                self.assertNotIn(label, labels)
        # The shared analytics pages sit in the workspace strip, not the
        # sidebar: the Analytics workspace has one door.
        for url in (
            "/analytics",
            "/ia/notifications/",
            "/impact",
            "/ssa",
            "/reports",
            "/decision-log",
        ):
            with self.subTest(url=url):
                self.assertNotIn(url, urls)

    def test_every_page_is_offered_once(self):
        keys = [i["page_key"] for g in _groups(IA) for i in g["items"]]
        self.assertEqual(len(keys), len(set(keys)), keys)

    def test_the_dashboard_link_lights_on_the_dashboard(self):
        lit = [
            i["label"]
            for g in _groups(IA, "/ia/dashboard/")
            for i in g["items"]
            if i["active"]
        ]
        self.assertEqual(lit, ["Dashboard"])

    def test_a_record_page_lights_its_queue(self):
        lit = [
            i["label"]
            for g in _groups(IA, "/ia/verification/act123/")
            for i in g["items"]
            if i["active"]
        ]
        self.assertEqual(lit, ["Verification Queue"])

    def test_the_country_directors_verification_doors_are_unchanged(self):
        cd_labels = [i["label"] for g in _groups(CD) for i in g["items"]]
        for label in (
            "Verification Queue",
            "Verification Analytics",
            "Sample Checks",
            "Programme Learning",
            "Team Oversight",
            "Quality Flags",
            "Analytics",
        ):
            with self.subTest(label=label):
                self.assertEqual(cd_labels.count(label), 1)
        # IA's own collection and framework doors stay with IA.
        for label in (
            "Measurement Framework",
            "School Evidence",
            "SSA Upload Center",
            "Most Significant Change",
        ):
            with self.subTest(ia_only=label):
                self.assertNotIn(label, cd_labels)

    def test_admin_is_never_offered_a_page_twice(self):
        labels = [i["label"] for g in _groups(ADMIN) for i in g["items"]]
        duplicates = {label for label in labels if labels.count(label) > 1}
        self.assertEqual(duplicates, set())


class IaMobileNavTest(SimpleTestCase):
    def test_the_phone_leads_with_the_days_queue(self):
        self.assertEqual(
            MOBILE_NAV_BY_ROLE[IA],
            ("dashboard", "todos", "ia_verification_queue", "messages"),
        )
        nav = build_mobile_nav_for_user(_user(IA), "/ia/dashboard/")
        self.assertEqual(
            [i["url"] for i in nav],
            ["/ia/dashboard/", "/todos", "/ia/verification/", "/messages"],
        )
        self.assertTrue(nav[0]["active"])


class IaWorkspaceRegistryTest(SimpleTestCase):
    def test_clusters_are_the_responsibilities_and_all_are_labelled(self):
        clusters = []
        for section in IA_SECTIONS:
            if section["cluster"] not in clusters:
                clusters.append(section["cluster"])
        self.assertEqual(
            clusters,
            [
                "overview",
                "framework",
                "collection",
                "progress",
                "learning",
                "accountability",
                "data_quality",
            ],
        )
        for cluster in clusters:
            with self.subTest(cluster=cluster):
                self.assertIn(cluster, WORKSPACE_CLUSTER_LABELS)

    def test_sections_are_distinct_and_ia_holds_each_one(self):
        self.assertEqual(
            len({s["key"] for s in IA_SECTIONS}), len(IA_SECTIONS), "unique keys"
        )
        self.assertEqual(
            len({s["url"] for s in IA_SECTIONS}), len(IA_SECTIONS), "unique urls"
        )
        for section in IA_SECTIONS:
            with self.subTest(section=section["key"]):
                self.assertIn(IA, PAGE_PERMISSIONS[section["page_key"]])

    def test_mislabelled_sections_carry_their_real_names(self):
        labels = {s["url"]: s["label"] for s in IA_SECTIONS}
        self.assertEqual(labels["/core-school-health"], "Core School Health")
        self.assertEqual(labels["/impact"], "Contribution Analysis")
        self.assertEqual(labels["/reports"], "Programme Output Reports")
        self.assertNotIn("/analytics", labels)
        self.assertNotIn("IA Analytics", labels.values())

    def test_every_ia_page_carries_the_strip_with_one_active_section(self):
        user = _user(IA)
        for path, active in (
            ("/ia/dashboard/", "Dashboard"),
            ("/ia/framework/", "Measurement Framework"),
            ("/ia/school-evidence/", "School Evidence"),
            ("/ia/stories/", "Most Significant Change"),
            ("/ia/learning/", "Programme Learning"),
            ("/ia/lending-evidence/", "Lending Evidence"),
            ("/ia/impact-reports/", "Impact Reports"),
            ("/ia/verification/", "Verification Queue"),
            ("/ia/verification/abc123/", "Verification Queue"),
            ("/ia/partner-evidence/abc123/", "Partner Evidence"),
            ("/ia/duplicates/", "Duplicate Review"),
            ("/ia/compare/", "Evidence Compare"),
            ("/ia/returned/", "Returned Activities"),
            ("/ia/history/", "Verification History"),
            ("/ia/analytics/", "Verification Analytics"),
            ("/ia/samples/", "Sample Checks"),
            ("/ssa/verification/", "SSA Verification"),
            ("/ssa/upload/batch1/result/", "SSA Upload Center"),
            ("/ssa/unmatched", "Unmatched SSA"),
            ("/ssa", "SSA Performance"),
            ("/declining-schools", "Declining Schools"),
            ("/core-school-health", "Core School Health"),
            ("/impact", "Contribution Analysis"),
            ("/analytics/visit-effectiveness", "Visit Effectiveness"),
            ("/reports", "Programme Output Reports"),
            ("/analytics/publishing", "Publishing"),
            ("/decision-log", "Decision Log"),
        ):
            with self.subTest(path=path):
                workspace = build_workspace(user, path)
                self.assertIsNotNone(workspace)
                self.assertEqual(workspace["key"], "ia")
                self.assertEqual(
                    [s["label"] for s in workspace["sections"] if s["active"]],
                    [active],
                )

    def test_the_generic_analytics_page_is_not_in_the_ia_strip(self):
        workspace = build_workspace(_user(IA), "/analytics")
        self.assertIsNotNone(workspace)
        self.assertEqual(workspace["key"], "analytics")

    def test_other_roles_keep_the_analytics_workspace_on_shared_pages(self):
        for path in ("/ssa", "/impact", "/reports"):
            with self.subTest(path=path):
                self.assertEqual(build_workspace(_user(CD), path)["key"], "analytics")


class IaGrantsTest(SimpleTestCase):
    def test_grants_unrelated_to_the_role_are_withdrawn(self):
        grants = ROLE_PERMISSIONS[EdifyRole.IMPACT_ASSESSMENT]
        for permission in (
            Permission.RECRUITMENT_INTELLIGENCE_VIEW,
            Permission.PLANNING_RECALC,
            Permission.LEADERSHIP_ENGINE_VIEW,
        ):
            with self.subTest(permission=permission.value):
                self.assertNotIn(permission, grants)
        self.assertEqual(len(grants), len(set(grants)), "no grant listed twice")
        # What the role does keep.
        for permission in (
            Permission.IA_VERIFY,
            Permission.SSA_ACTIVITY_MAPPING_MANAGE,
            Permission.ACTIVITY_CATALOGUE_VIEW,
            Permission.EXPORT,
        ):
            with self.subTest(kept=permission.value):
                self.assertIn(permission, grants)
