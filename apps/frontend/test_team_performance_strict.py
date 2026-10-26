"""Team Performance is role-strict on every tab (owner, 2026-10-24).

"Team performance should be highly role strict and not just the summary.
each role can only and only see what they are supposed to see. Especially
for CCEO and Program leads."

A CCEO reads only their own portfolio; a Programme Lead their own and their
CCEOs'. Every tab, every dashboard view and every chart section is opened as
each of them, with links that name other people, other teams, the country
and the region view, and nothing outside their scope may appear — no name,
no id, no country total, and no figure counted from anyone else's schools.
"""

from __future__ import annotations

import re
from datetime import date

from apps.accounts.models import StaffSupervisorAssignment
from apps.team_performance.periods import ReportPeriod
from apps.team_performance.report import Report
from apps.team_performance.test_ledger import FY, LedgerFixture, make_officer

#: A page's security tokens (CSRF): 64 random letters and digits, so one in
#: many reads "Zed" or "Mary" — main's CI failed on "…soZedGwo" (2026-10-25).
#: A staff id is 25, so an id that leaks is still found.
_TOKEN = re.compile(r"[A-Za-z0-9]{40,}")


def _without_tokens(body: str) -> str:
    return _TOKEN.sub("", body)


URL = "/team-performance/"
TABS = ("summary", "weekly", "milestones", "dashboard", "month", "core")
VIEWS = ("cceos", "deep", "milestones", "leads", "grid")


class RoleStrictTest(LedgerFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Lena leads James; Otto leads Zed. Mary has no lead.
        cls.lena = make_officer("lena@tp-strict.test", "Program Lead")
        cls.otto = make_officer("otto@tp-strict.test", "Program Lead")
        cls.zed = make_officer("zed@tp-strict.test")
        for officer, lead in ((cls.james, cls.lena), (cls.zed, cls.otto)):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer.staff_profile, supervisor=lead.staff_profile
            )
        cls.zeds = cls.school("TP-ZED", cls.zed, "client")

    def outsiders(self):
        """Everyone James and Lena must never see, by name and by id."""
        people = (self.mary, self.zed, self.otto)
        return [p.name for p in people] + [str(p.staff_profile.id) for p in people]

    def links(self, reader):
        """Every page of the report, with links that name the people the
        reader may not see."""
        other = str(self.zed.staff_profile.id)
        other_team = str(self.otto.staff_profile.id)
        for tab in TABS:
            yield {"tab": tab}
            yield {"tab": tab, "scope": "country"}
            yield {"tab": tab, "scope": other}
            yield {"tab": tab, "scope": f"region:{other_team}"}
        for view in VIEWS:
            yield {"tab": "dashboard", "view": view, "officer": other}
            yield {"tab": "dashboard", "view": view, "lead": other_team}
        for by in ("region", "lead", "cceo", "district"):
            yield {"tab": "summary", "by": by}
            yield {"tab": "summary", "by": by, "in_lead": other_team}
            yield {"tab": "summary", "by": by, "in_region": "Northern"}
        for section in self.sections(reader):
            yield {"tab": "summary", "charts": section, "by": "region"}
            yield {"tab": "summary", "charts": section, "in_lead": other_team}

    def sections(self, reader):
        period = ReportPeriod.resolve(FY, 2, today=date(2026, 11, 18))
        summary = Report.build(reader, period).executive_summary()
        return [section for section, _areas in summary["sections"]]

    def assert_strict(self, reader):
        self.client.force_login(reader)
        forbidden = self.outsiders() + [
            "National Total",
            "No Programme Lead",
            'data-tp-chart="region"',
            'data-tp-chart="lead"',
            'data-tp-by="region"',
        ]
        for query in self.links(reader):
            response = self.client.get(URL, {"fy": FY, **query})
            self.assertEqual(response.status_code, 200, query)
            body = _without_tokens(response.content.decode())
            for text in forbidden:
                self.assertNotIn(text, body, f"{query}: {text}")

    def test_a_cceo_sees_only_their_own_on_every_page_and_link(self):
        self.assert_strict(self.james)

    def test_a_lead_sees_only_their_team_on_every_page_and_link(self):
        self.assert_strict(self.lena)

    def test_their_figures_are_counted_from_their_own_schools_only(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        self.work("school_visit", self.other, day=date(2026, 11, 4))
        self.work("school_visit", self.zeds, day=date(2026, 11, 5))
        period = ReportPeriod.resolve(FY, 2, today=date(2026, 11, 18))

        # James holds the Core and a client school; Lena's team is James.
        for reader in (self.james, self.lena):
            with self.subTest(reader=reader.email):
                report = Report.build(reader, period)
                summary = report.executive_summary()
                self.assertEqual(summary["now"]["portfolio"], 2)
                self.assertEqual(summary["now"]["client_visits_staff_n"], 1)
                self.assertEqual(report.ledger.portfolio(None), 2)
                cards = report.cceo_board()["cards"]
                self.assertEqual([c["officer"].name for c in cards], [self.james.name])
