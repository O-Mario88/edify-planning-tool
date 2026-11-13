"""The group check the Go gateway asks before it changes ticked activities
together (gateway_relay.visit_group_check, docs/migration/33): it plays the
group exactly as ``group_actions`` makes it, writes nothing, and says what
became of each activity, in which way, and the group's own refusal.

Each test asks the check, holds that nothing changed, then makes the real
group on the same records and holds the check's answer to what it did."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest import mock

from django.test import RequestFactory, override_settings

from apps.activities import group_actions
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.daily_visit_batches import gateway_relay, services
from apps.daily_visit_batches.test_day_priced_once import (
    MON,
    TUE,
    WED,
    _ADayOfVisits,
    _Compared,
    _everything,
)

KEY = "k" * 40
REASON = "The district moved its meeting"
#: A Monday a week on: its week is the one a test sends for approval.
NEXT_MON = MON + timedelta(days=7)


class GroupCheckTest(_ADayOfVisits):
    def ask(self, kind, ids, day="", reason=REASON, **extra):
        body = {
            "kind": kind,
            "activityIds": ids,
            "scheduledDate": day,
            "reason": reason,
            "userId": self.user.id,
            "role": self.user.active_role,
            **extra,
        }
        if "kindOverride" in body:
            body["kind"] = body.pop("kindOverride")
        request = RequestFactory().post(
            "/", data=json.dumps(body), content_type="application/json"
        )
        request.META["HTTP_X_EDIFY_INTERNAL_KEY"] = KEY
        with override_settings(EDIFY_INTERNAL_KEY=KEY):
            response = gateway_relay.visit_group_check(request)
        return response.status_code, json.loads(response.content)

    def asked_and_unchanged(self, kind, ids, day=""):
        """The check's answer, holding that it changed nothing at all."""
        before = _everything()
        status, answer = self.ask(kind, ids, day)
        self.assertEqual(status, 200, answer)
        changed = _Compared(before, _everything(), started="2026-07-27")
        self.assertEqual(sorted(changed.tables), [], "the check wrote")
        return answer

    def assertTheGroupDidWhatTheCheckSaid(self, answer, outcome):
        said = {p["id"]: (p["done"], p["refusal"]) for p in answer["picks"]}
        did = {p.id: (True, "") for p in outcome.done}
        did.update({p.id: (False, p.refusal) for p in outcome.refused})
        self.assertEqual(said, did)

    def test_the_check_takes_only_what_it_was_built_for(self):
        for extra in (
            {"kindOverride": "complete"},
            {"activityIds": []},
            {"activityIds": ["x" * 31]},
            {"userId": ""},
            {"scheduledDate": "2026-08-04T00:00"},
        ):
            with self.subTest(extra=extra):
                status, _answer = self.ask("reschedule", ["a"], "2026-08-04", **extra)
                self.assertEqual(status, 400)
        status, answer = self.ask("reschedule", ["a"], role="Admin")
        self.assertEqual((status, answer["reason"]), (400, "bad_principal"))

    def test_a_group_moved_together_writes_nothing_and_answers_as_the_group(self):
        monday = self.plan(MON, self.near[:4])["created"]
        wednesday = self.plan(WED, self.near[4:6])["created"]
        ids = monday[:2] + wednesday[:1] + [monday[3]]

        answer = self.asked_and_unchanged("reschedule", ids, TUE.isoformat())
        outcome = group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        self.assertTrue(answer["together"])
        self.assertEqual(answer["groupRefusal"], "")
        self.assertTheGroupDidWhatTheCheckSaid(answer, outcome)
        self.assertEqual(len(outcome.done), 4)

    def test_the_groups_own_refusals_are_said_before_anything(self):
        monday = self.plan(MON, self.near[:2])["created"]
        for kind, day, reason, words in (
            ("reschedule", "", REASON, "Choose the date these activities move to."),
            (
                "reschedule",
                TUE.isoformat(),
                " ",
                "Give the reason these activities are moving.",
            ),
            ("cancel", "", "", "Give the reason these activities are being cancelled."),
        ):
            with self.subTest(kind=kind, day=day):
                _status, answer = self.ask(kind, monday, day, reason)
                self.assertEqual(answer["refusal"], words)
                self.assertEqual(answer["picks"], [])

    def test_the_second_visit_meets_the_day_the_first_made(self):
        """Two visits moved onto a day with none yet, in a week whose request
        has been sent: the first makes the day, and the second meets it and is
        refused, as the group makes them (the 1 December case, docs/migration
        /33 §33.4)."""
        from apps.fund_requests.models import WeeklyFundRequest

        monday = self.plan(MON, self.near[:3])["created"]
        WeeklyFundRequest.objects.create(
            fy=get_operational_fy(NEXT_MON),
            week_start_date=NEXT_MON,
            week_end_date=NEXT_MON + timedelta(days=6),
            responsible_user=self.user.id,
            status="submitted",
        )
        ids = monday[:2]

        answer = self.asked_and_unchanged("reschedule", ids, NEXT_MON.isoformat())
        outcome = group_actions.reschedule(ids, NEXT_MON.isoformat(), REASON, self.user)

        self.assertTheGroupDidWhatTheCheckSaid(answer, outcome)
        self.assertEqual(
            [(p["done"], p["refusal"]) for p in answer["picks"]],
            [
                (True, ""),
                (
                    False,
                    "This date's visits have already left draft status. "
                    "Choose another date.",
                ),
            ],
        )
        self.assertTrue(answer["together"])

    def test_when_the_groups_pricing_refuses_it_is_changed_one_at_a_time(self):
        """A visit staying on Monday has its advance with the accountant:
        priced together the group refuses, and it is changed one activity at
        a time, Monday's refused and Wednesday's moved."""
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        monday = self.plan(MON, self.near[:4])["created"]
        wednesday = self.plan(WED, self.near[4:7])["created"]
        AdvanceRequest.objects.filter(budget_line__activity_id=monday[3]).update(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        )
        ids = monday[:2] + wednesday[:2]

        answer = self.asked_and_unchanged("reschedule", ids, TUE.isoformat())
        outcome = group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        self.assertFalse(answer["together"])
        self.assertIn("accountant", answer["groupRefusal"])
        self.assertTheGroupDidWhatTheCheckSaid(answer, outcome)
        self.assertEqual(len(outcome.done), 2)

    def test_a_refusal_only_the_whole_group_meets_changes_every_one_alone(self):
        """A refusal the group's pricing meets only when its days are priced
        together, none of its activities alone: every one is changed alone."""
        original = services.price_kept_days

        def priced(days, *, together, beside=None):
            if together:
                raise BadRequest("Only the whole group is refused.")
            return original(days, together=together, beside=beside)

        monday = self.plan(MON, self.near[:3])["created"]
        ids = monday[:2]
        with mock.patch.object(services, "price_kept_days", priced):
            answer = self.asked_and_unchanged("reschedule", ids, TUE.isoformat())
            outcome = group_actions.reschedule(ids, TUE.isoformat(), REASON, self.user)

        self.assertFalse(answer["together"])
        self.assertEqual(answer["groupRefusal"], "Only the whole group is refused.")
        self.assertTheGroupDidWhatTheCheckSaid(answer, outcome)
        self.assertEqual(len(outcome.done), 2)

    def test_a_group_cancel_writes_nothing_and_answers_as_the_group(self):
        monday = self.plan(MON, self.near[:3])["created"]
        ids = monday[:2]

        answer = self.asked_and_unchanged("cancel", ids)
        outcome = group_actions.cancel(ids, REASON, self.user)

        self.assertTrue(answer["together"])
        self.assertTheGroupDidWhatTheCheckSaid(answer, outcome)
        self.assertEqual(len(outcome.done), 2)
