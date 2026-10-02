"""The Programme Lead's navigation follows their role description (owner, 2026-09-13).

"Strategic Direction · Team Leadership & Management · Performance Management ·
Program Implementation · Collaboration" — the owner asked to align the role to
those five responsibilities, add what was missing, delete what was not the
role's, and reorganize the UI around it. This holds the result: one group per
responsibility in that order, each page offered once, and the doors the role
lost kept shut.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.navigation import (
    ADMIN,
    CCEO,
    CD,
    HR,
    PAGE_PERMISSIONS,
    PL,
    build_sidebar_for_user,
    build_workspace,
)


def _user(role):
    return SimpleNamespace(is_authenticated=True, active_role=role)


# Grouped by what each page is about (owner, 2026-10-02; apps.core.nav_groups),
# most visited first inside each group (owner, 2026-09-14;
# apps.core.nav_cadence). The Staff Activity Log and the Planning Monitor are
# on the Dashboard (owner, 2026-09-29), so neither has an entry; Closed Schools
# is here because the owner put it in this sidebar (2026-09-15).
EXPECTED_PL_SIDEBAR = [
    (
        "MY WORK",
        [
            ("Dashboard", "/dashboard"),
            ("My Plan", "/my-plan"),
            ("Calendar", "/calendar"),
            ("Completion Reviews", "/pl/review-queue"),
            ("To-Do", "/todos"),
            ("My Actions", "/actions/mine"),
            ("Field Debrief", "/debriefs"),
            ("Analytics", "/analytics/program-lead"),
        ],
    ),
    (
        "PLANNING",
        [
            ("Planning", "/planning"),
            ("Programme Rollout", "/programme-rollout"),
            ("Work Plan", "/work-plan"),
            ("Priorities", "/priorities/master"),
        ],
    ),
    (
        "SCHOOLS",
        [
            ("School Directory", "/schools"),
            ("Clusters", "/clusters"),
            ("Core Schools", "/core-schools"),
            ("Programme Schools", "/programme-schools"),
            ("Closed Schools", "/schools/closed"),
        ],
    ),
    (
        "OVERSIGHT",
        [
            ("Planning Oversight", "/team-planning-oversight/"),
            ("Cluster Oversight", "/cluster-oversight/"),
            ("Core School Oversight", "/core-schools-oversight/"),
            ("Partner Monitoring", "/partner-oversight/"),
            ("Project Monitoring", "/projects/monitoring"),
        ],
    ),
    (
        "TEAM & PEOPLE",
        [
            ("My Team", "/my-team"),
            ("Team Leave", "/leave/approvals"),
            ("Coaching", "/team/coaching"),
            ("Escalations", "/escalations"),
            ("Team Assignments", "/actions/sent"),
            ("Quality Flags", "/quality-checks"),
            ("Regional Lead", "/cce-leadership/feedback"),
            ("Team Performance", "/performance-reviews"),
        ],
    ),
    (
        "FINANCE",
        [
            ("Fund Approvals", "/fund-approvals"),
            ("Weekly Advance Request", "/fund-requests/weekly"),
            ("Budget", "/budget"),
        ],
    ),
    (
        "MY PERFORMANCE",
        [
            ("My Targets", "/my-targets"),
            ("My Performance Agreement", "/my-performance"),
            ("My Professional Development", "/my-professional-development"),
            ("Leave & Personal Time Off", "/personal-time-off/"),
        ],
    ),
]


class ProgramLeadSidebarTest(SimpleTestCase):
    def _sidebar(self, role, path="/dashboard"):
        return build_sidebar_for_user(_user(role), path)

    def test_the_sidebar_is_grouped_by_subject_and_ordered_by_visits(self):
        sidebar = [
            (group["label"], [(item["label"], item["url"]) for item in group["items"]])
            for group in self._sidebar(PL)
        ]
        self.assertEqual(sidebar, EXPECTED_PL_SIDEBAR)

    def test_every_page_is_offered_once(self):
        keys = [
            item["page_key"] for group in self._sidebar(PL) for item in group["items"]
        ]
        self.assertEqual(
            sorted({key for key in keys if keys.count(key) > 1}),
            [],
        )

    def test_pages_that_are_not_the_role_are_gone(self):
        urls = {item["url"] for group in self._sidebar(PL) for item in group["items"]}
        for gone in (
            "/hr-today",
            "/staff",
            "/coverage",
            "/leave/tracker",
            "/leave/team-availability",
            "/policy-compliance",
            "/projects",
            "/priorities",
            # On the dashboard now (owner, 2026-09-29).
            "/planning-monitor/",
            "/staff-activity",
        ):
            with self.subTest(url=gone):
                self.assertNotIn(gone, urls)

    def test_access_the_role_no_longer_holds(self):
        for key in (
            "hr_today",
            "coverage",
            "decision_intelligence",
            "reports",
            "business_transformation",
            "business_transformation_reports",
            "monthly_request",
        ):
            with self.subTest(page=key):
                self.assertNotIn(PL, PAGE_PERMISSIONS[key])

    def test_the_role_holds_its_new_pages(self):
        for key in (
            "my_team",
            "team_coaching",
            "team_guidance",
            "programme_rollout",
            "pl_review_queue",
        ):
            with self.subTest(page=key):
                self.assertIn(PL, PAGE_PERMISSIONS[key])
        # The officer reads and acknowledges the coaching shared with them.
        self.assertIn(CCEO, PAGE_PERMISSIONS["my_coaching"])
        self.assertNotIn(PL, PAGE_PERMISSIONS["my_coaching"])

    def test_merged_pages_keep_their_single_link_lit(self):
        for path, label in (
            ("/leave/tracker", "Team Leave"),
            ("/leave/team-availability", "Team Leave"),
            ("/extra-work", "Team Assignments"),
            ("/recovery-plans", "Team Performance"),
            ("/cpd-learning", "Team Performance"),
            ("/policy-compliance", "Team Performance"),
            ("/cce-leadership/coaching", "Regional Lead"),
            ("/strategic-priorities", "Priorities"),
            ("/target-distribution/team", "Priorities"),
            ("/priorities/guidance", "Priorities"),
            ("/team-targets", "Planning Oversight"),
            ("/partner-oversight/", "Partner Monitoring"),
        ):
            with self.subTest(path=path):
                lit = [
                    item["label"]
                    for group in self._sidebar(PL, path)
                    for item in group["items"]
                    if item["active"]
                ]
                self.assertEqual(lit, [label])

    def test_the_team_workspaces_are_the_leads_alone(self):
        for path, expected in (
            (
                "/performance-reviews",
                [
                    "Coaching",
                    "Performance Reviews",
                    "Recovery Plans",
                    "Professional Development",
                    "Policy Compliance",
                ],
            ),
            ("/actions/sent", ["Actions Sent", "Extra Work"]),
            (
                "/cce-leadership/feedback",
                ["Training Feedback", "Regional Lead Coaching"],
            ),
        ):
            with self.subTest(path=path):
                workspace = build_workspace(_user(PL), path)
                self.assertIsNotNone(workspace)
                self.assertEqual([s["label"] for s in workspace["sections"]], expected)
        # HR and the CD open the same pages from their own groups, unchanged.
        self.assertIsNone(build_workspace(_user(HR), "/performance-reviews"))
        self.assertIsNone(build_workspace(_user(CD), "/actions/sent"))


class OtherRolesKeepTheirSidebarTest(SimpleTestCase):
    def test_the_programme_lead_team_pages_are_not_offered_to_other_roles(self):
        pl_only = {"/my-team", "/team/coaching", "/programme-rollout"}
        for role in (CCEO, CD, HR):
            with self.subTest(role=role):
                urls = {
                    item["url"]
                    for group in build_sidebar_for_user(_user(role), "/")
                    for item in group["items"]
                }
                self.assertFalse(urls & pl_only)

    def test_admin_is_offered_each_page_once(self):
        items = [
            (item["label"], item["page_key"])
            for group in build_sidebar_for_user(_user(ADMIN), "/dashboard")
            for item in group["items"]
        ]
        labels = [label for label, _key in items]
        self.assertEqual(sorted({x for x in labels if labels.count(x) > 1}), [])
        for label in ("My Team", "Coaching", "Completion Reviews", "Programme Rollout"):
            with self.subTest(label=label):
                self.assertIn(label, labels)
