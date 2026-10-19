"""Completed work reaches the lead, and verified work is counted wherever
work is counted (owner, 2026-10-19).

"make sure the PLs can see all the completed work and all completed and
verified work are all counted in the tables where they are counted."

One CCEO visit, followed from completion to the lead's approval:

  1. Completed with its Salesforce ID, it is on the lead's Execution &
     Completion table under Awaiting PL Approval, and not yet counted (owner,
     2026-10-15: "Any activity not approved by PL should not be counted").
  2. Approved, it is counted once on that table and once in the targets
     metrics My Targets and Team Targets read.
"""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

from apps.activities.services import complete
from apps.pl_review import services
from apps.pl_review.test_pl_approves import _Fixture
from apps.planning.execution_monitor import execution_monitor
from apps.targets.performance import staff_metrics

DAY = date(2026, 9, 1)  # inside FY2026, the fixture's year
FY = "2026"


class TheVisitIsSeenThenCounted(_Fixture):
    def _person(self, name="James"):
        monitor = execution_monitor(self.pl_user, fy=FY, today=date(2026, 9, 30))
        return next(
            person
            for team in monitor["teams"]
            for person in team.people
            if person.name == name
        )

    def test_from_completion_to_approval(self):
        work = self._started(
            self.james.id,
            fy=FY,
            planned_date=DAY,
            scheduled_date=timezone.make_aware(datetime(2026, 9, 1, 9, 0)),
        )
        complete(
            work.id,
            {"salesforceId": "SVE-9401", "actualDeliveryDate": DAY.isoformat()},
            self.james_user,
        )
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

        james = self._person()
        self.assertEqual(james.awaiting_pl, 1)
        self.assertEqual(james.visits_delivered, 0)
        self.assertIn(work.id, {row["id"] for row in services.queue(self.pl_user)})

        services.confirm(work.id, self.pl_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")

        james = self._person()
        self.assertEqual(james.awaiting_pl, 0)
        self.assertEqual(james.visits_delivered, 1)
        self.assertEqual(james.verified, 1)
        self.assertEqual(staff_metrics(str(self.james.id), FY)["school_visits"], 1)
        self.assertNotIn(work.id, {row["id"] for row in services.queue(self.pl_user)})
