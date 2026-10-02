"""HR Today says each exception once (2026-10-01).

A missed review cycle gave every person the same exception, and the queue drew
it once per person: "Performance review overdue · FY2026 review is 335 days
late", thirty-three times, of which the page showed ten identical rows. Rows
alike in everything but the person are now one row whose "Who" is a count that
opens the list of people, each linked to their own record.
"""

from __future__ import annotations

import copy
from unittest import mock

from django.test import TestCase

from apps.accounts.models import User
from apps.frontend.views.hr_today_views import FOLD_FROM, _fold_identical
from apps.hr.hr_exceptions import (
    DEADLINES,
    GROUP_LABELS,
    MANAGER_OVERDUE,
    PEOPLE_RISK,
    WAITING_ON_HR,
)


def _overdue(person: str, days: int = 335) -> dict:
    return {
        "group": MANAGER_OVERDUE,
        "kind": "review_overdue",
        "title": "Performance review overdue",
        "detail": f"FY2026 review is {days} days late.",
        "url": f"/performance-reviews?person={person.replace(' ', '-').lower()}",
        "severity": "high",
        "person": person,
        "due_label": f"{days} days overdue",
    }


class FoldIdenticalTests(TestCase):
    def test_rows_alike_but_for_the_person_become_one(self):
        rows = _fold_identical([_overdue(f"Person {n}") for n in range(5)])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 5)
        self.assertEqual(
            [person["name"] for person in rows[0]["people"]],
            [f"Person {n}" for n in range(5)],
        )
        # Each person keeps the way to their own record.
        self.assertEqual(len({person["url"] for person in rows[0]["people"]}), 5)

    def test_a_pair_stays_as_two_rows(self):
        rows = _fold_identical([_overdue("A"), _overdue("B")])

        self.assertEqual(FOLD_FROM, 3)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("people", rows[0])

    def test_a_different_lateness_is_a_different_exception(self):
        items = [_overdue(f"Late {n}") for n in range(3)]
        items += [_overdue(f"Later {n}", days=400) for n in range(3)]

        rows = _fold_identical(items)

        self.assertEqual([row["count"] for row in rows], [3, 3])

    def test_a_folded_row_keeps_its_place_in_the_queue(self):
        urgent = {**_overdue("Solo"), "title": "Leave decision overdue"}
        items = [_overdue("A"), urgent, _overdue("B"), _overdue("C")]

        rows = _fold_identical(items)

        self.assertEqual(
            [row["title"] for row in rows],
            ["Performance review overdue", "Leave decision overdue"],
        )


class HrTodayPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = User.objects.create(
            email="hr-folding@links.test",
            name="HR viewer",
            roles=["HumanResources"],
            active_role="HumanResources",
            is_active=True,
        )

    def _queue(self, overdue: list[dict]) -> dict:
        return {
            "groups": [
                {
                    "key": key,
                    "label": GROUP_LABELS[key],
                    "items": overdue if key == MANAGER_OVERDUE else [],
                }
                for key in (WAITING_ON_HR, MANAGER_OVERDUE, PEOPLE_RISK, DEADLINES)
            ],
            "counts": {},
            "critical_count": 0,
            "total": len(overdue),
        }

    def _page(self, queue: dict) -> str:
        self.client.force_login(self.hr)
        with mock.patch(
            "apps.frontend.views.hr_today_views.grouped_hr_exceptions",
            side_effect=lambda *args, **kwargs: copy.deepcopy(queue),
        ):
            response = self.client.get("/hr-today")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_thirty_three_people_with_one_exception_are_one_row(self):
        html = self._page(self._queue([_overdue(f"Person {n}") for n in range(33)]))

        self.assertEqual(html.count("FY2026 review is 335 days late."), 1)
        self.assertIn("<summary>33 people</summary>", html)
        # Every person is still there, behind the count.
        self.assertIn("Person 0", html)
        self.assertIn("Person 32", html)
        # The headline stays the true number of exceptions, and nothing is
        # reported as left out: the one row stands for all thirty-three.
        self.assertIn("33 open", html)
        self.assertNotIn("more in this queue", html)

    def test_distinct_exceptions_still_get_a_row_each(self):
        overdue = [
            {**_overdue(f"Person {n}"), "detail": f"Review {n} is late."}
            for n in range(4)
        ]

        html = self._page(self._queue(overdue))

        for n in range(4):
            self.assertIn(f"Review {n} is late.", html)
        self.assertNotIn("<summary>", html)
