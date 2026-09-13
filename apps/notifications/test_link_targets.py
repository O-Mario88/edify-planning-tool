"""Every notification lands on a page that exists.

A notification is the handoff between two workflows: an approval request, a
returned plan, a critical school. When its link resolves to no route the
recipient gets a 404 at the exact moment the platform asked them to act
(2026-09-13 ecosystem audit found the FY priority-setting notice sending HR to
/hr/performance, which never existed).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve

from apps.notifications.services import NotificationLinkResolver

SERVICES = Path(__file__).with_name("services.py").read_text(encoding="utf-8")

ROLES = (
    "CCEO",
    "Program Lead",
    "RegionalProgramLead",
    "CountryDirector",
    "RegionalVicePresident",
    "ImpactAssessment",
    "Accountant",
    "HumanResources",
    "Admin",
    "PartnerFieldOfficer",
    "PartnerAdmin",
    "ProjectCoordinator",
    "ProjectLeader",
    "BusinessTransformationOfficer",
    "MfiLoanOfficer",
    "MfiPartnerAdmin",
    "Staff",
)
CONTEXT_TYPES = (
    None,
    "School",
    "Cluster",
    "Activity",
    "Message",
    "WeeklyFundRequest",
    "FundRequest",
    "AdvanceRequest",
    "Leave",
    "Project",
    "MonthlyWorkPlanBudget",
    "PerformanceCycle",
)


def _event_types() -> set[str]:
    exact = set(re.findall(r'event_type == "([^"]+)"', SERVICES))
    for group in re.findall(r"event_type in \(([^)]*)\)", SERVICES):
        exact.update(re.findall(r'"([^"]+)"', group))
    prefixes = {
        f"{prefix}example"
        for prefix in re.findall(r'event_type\.startswith\("([^"]+)"\)', SERVICES)
    }
    return exact | prefixes | {"unmapped_event"}


class NotificationLinkTargetsTest(SimpleTestCase):
    def test_every_resolved_link_is_a_real_route(self):
        events = _event_types()
        self.assertGreater(len(events), 40, "the event vocabulary was not read")
        broken = set()
        for event_type in sorted(events):
            for role in ROLES:
                for context_type in CONTEXT_TYPES:
                    route, _label = NotificationLinkResolver.resolve(
                        event_type, context_type, "ctx123", role
                    )
                    path = urlsplit(route).path
                    try:
                        resolve(path)
                    except Resolver404:
                        broken.add((event_type, role, route))
        self.assertEqual(sorted(broken), [])
