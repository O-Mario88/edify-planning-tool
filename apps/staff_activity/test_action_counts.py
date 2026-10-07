"""The Staff Activity Log counts what a person did (owner, 2026-10-06).

"fix the count on staff activity table to make sure it is doing the right
calculation. fetching the right data, and every data has the right description,
right header and NOT add fake data. everything should be fetch frm the
database."

Read against the audit chain, the Actions column was wrong three ways:

* one thing a person did was counted as two when its request wrote two rows
  (scheduling a Core visit, a Lead's confirmation);
* a school handed to a partner was not counted at all, because that row is
  filed under the person's staff-record id and the log read user ids;
* adding a school to a project, taking one back from a partner or setting a
  training ceiling were on nobody's list of actions.

And the strip above the table added each person's schools together, so a
school two people worked on was two schools.
"""

from __future__ import annotations

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.audit.services import log as audit_log

from .registry import MEANINGFUL_ACTIONS
from .services import activity_log, actor_identities, fold_acts, person_detail
from .tests import Team


def _person(log, name):
    return {p["name"]: p for p in log["people"]}[name]


class OneActionIsCountedOnceTest(Team):
    def _row(
        self, action, subject_id="A1", *, kind="Activity", actor=None, request="", **kw
    ):
        """One audit row; ``request`` is the id of the request that wrote it
        (the middleware's correlation id), none for a row written alone."""
        audit_log(
            action=action,
            subject_kind=kind,
            subject_id=subject_id,
            actor_id=(actor or self.mina).id,
            correlation_id=request or None,
            **kw,
        )

    def test_scheduling_a_core_visit_is_one_action_not_its_two_rows(self):
        self._row("activity.scheduled", request="req-1")
        self._row("schedule_core_visit", request="req-1")

        mina = _person(activity_log(self.lead), "Mina")

        self.assertEqual(mina["actions"], 1)
        self.assertEqual(mina["last_action"], "Scheduled a core school visit")

    def test_a_lead_s_confirmation_is_one_action(self):
        self._row("pl_review_confirm", actor=self.lead, request="req-2")
        self._row("pl_approve_completion", actor=self.lead, request="req-2")

        lead = _person(activity_log(self.lead), "Lena")

        self.assertEqual(lead["actions"], 1)
        self.assertEqual(lead["last_action"], "Confirmed a completed activity")

    def test_one_request_about_thirty_schools_is_thirty_actions(self):
        for n in range(30):
            self._row("activity.scheduled", f"A{n}", request="req-bulk")

        self.assertEqual(_person(activity_log(self.lead), "Mina")["actions"], 30)

    def test_the_same_record_in_two_requests_is_two_actions(self):
        self._row("reschedule_activity", request="req-a")
        self._row("reschedule_activity", request="req-b")

        self.assertEqual(_person(activity_log(self.lead), "Mina")["actions"], 2)

    def test_rows_with_no_request_each_stand_alone(self):
        self._row("start_activity")
        self._row("start_activity")

        self.assertEqual(_person(activity_log(self.lead), "Mina")["actions"], 2)

    def test_the_opened_row_shows_the_same_number_as_the_table(self):
        self._row("activity.scheduled", request="req-1")
        self._row("schedule_core_visit", request="req-1")
        self._row("upload_evidence", "A2", request="req-2")
        self._row("request_failed", "x", kind="Request", success=False)

        row = _person(activity_log(self.lead), "Mina")
        detail = person_detail(self.lead, self.mina.id)

        self.assertEqual(row["actions"], 2)
        self.assertEqual(row["failed"], 1)
        self.assertEqual(detail["timeline_total"], 3)
        self.assertEqual(
            sum(1 for line in detail["timeline"] if line["ok"]), row["actions"]
        )
        self.assertEqual(sum(m["actions"] for m in detail["modules"]), row["actions"])
        self.assertEqual(sum(bar["actions"] for bar in detail["trend"]), row["actions"])
        self.assertEqual(
            sorted(line["label"] for line in detail["timeline"] if line["ok"]),
            ["Scheduled a core school visit", "Submitted activity evidence"],
        )


class EveryIdThePersonIsFiledUnderTest(Team):
    def test_a_hand_over_filed_under_the_staff_record_is_the_person_s(self):
        """apps.partners.signals writes ``partner.assigned`` with
        ``assigning_staff_id``, the staff-profile id."""
        audit_log(
            action="partner.assigned",
            subject_kind="PartnerAssignment",
            subject_id="PA1",
            actor_id=self.mina.staff_profile.id,
            payload={"partner_id": "P1", "school_id": "S9"},
        )

        mina = _person(activity_log(self.lead), "Mina")
        detail = person_detail(self.lead, self.mina.id)

        self.assertEqual(mina["actions"], 1)
        self.assertEqual(mina["last_action"], "Assigned a school to a partner")
        self.assertEqual(detail["timeline_total"], 1)

    def test_both_ids_add_up_and_belong_to_one_person(self):
        audit_log(
            action="partner.assigned",
            subject_kind="PartnerAssignment",
            subject_id="PA1",
            actor_id=self.mina.staff_profile.id,
            payload={"school_id": "S9"},
        )
        audit_log(
            action="start_activity",
            subject_kind="school",
            subject_id="S1",
            actor_id=self.mina.id,
        )

        log = activity_log(self.lead)

        self.assertEqual(_person(log, "Mina")["actions"], 2)
        self.assertEqual(_person(log, "Max")["actions"], 0)
        self.assertEqual(log["kpis"]["meaningful_actions"], 2)

    def test_the_identities_of_a_person(self):
        owners = actor_identities([self.mina.id])

        self.assertEqual(
            owners,
            {self.mina.id: self.mina.id, self.mina.staff_profile.id: self.mina.id},
        )


class SchoolsActedOnTest(Team):
    def test_a_hand_over_names_its_school_in_the_payload(self):
        for n, school in enumerate(("S1", "S2", "S2")):
            audit_log(
                action="partner.assigned",
                subject_kind="PartnerAssignment",
                subject_id=f"PA{n}",
                actor_id=self.mina.staff_profile.id,
                payload={"school_id": school},
            )
        audit_log(
            action="partner.assignment_withdrawn",
            subject_kind="PartnerAssignmentWithdrawal",
            subject_id="W1",
            actor_id=self.mina.id,
            payload={"school_id": "S3"},
        )

        mina = _person(activity_log(self.lead), "Mina")

        self.assertEqual(mina["actions"], 4)
        self.assertEqual(mina["schools"], 3)

    def test_a_school_two_people_worked_on_is_one_school_for_the_team(self):
        for person in (self.mina, self.max):
            audit_log(
                action="project.school_added",
                subject_kind="School",
                subject_id="S1",
                actor_id=person.id,
            )
        audit_log(
            action="project.school_added",
            subject_kind="School",
            subject_id="S2",
            actor_id=self.max.id,
        )

        log = activity_log(self.lead)

        self.assertEqual(_person(log, "Mina")["schools"], 1)
        self.assertEqual(_person(log, "Max")["schools"], 2)
        self.assertEqual(log["kpis"]["schools"], 2)
        self.assertEqual(log["kpis"]["meaningful_actions"], 3)


class WhatCountsAsAnActionTest(TestCase):
    def test_the_work_officers_and_leads_do_is_on_the_list(self):
        for action in (
            "project.school_added",
            "project.school_withdrawn",
            "partner.assigned",
            "partner.assignment_withdrawn",
            "partner.assignment_return_resolved",
            "edit_activity",
            "training_ceiling.set",
            "training_ceiling.removed",
        ):
            with self.subTest(action=action):
                self.assertIn(action, MEANINGFUL_ACTIONS)

    def test_the_door_s_own_row_for_a_hand_over_is_not_counted_twice(self):
        """Every hand-over writes ``partner.assigned``; a Core School's door
        also writes ``assign_core_partner`` about the same hand-over."""
        self.assertNotIn("assign_core_partner", MEANINGFUL_ACTIONS)

    def test_a_page_view_or_a_refusal_is_not_an_action(self):
        for action in ("documents.opened", "unauthorized_page_access", "role_switch"):
            with self.subTest(action=action):
                self.assertNotIn(action, MEANINGFUL_ACTIONS)

    def test_an_echo_never_names_the_action_when_the_other_row_is_there(self):
        for action in ("activity.scheduled", "schedule_core_visit"):
            audit_log(
                action=action,
                subject_kind="Activity",
                subject_id="A1",
                correlation_id="req-1",
            )
        rows = AuditLog.objects.filter(correlation_id="req-1")
        self.assertEqual(rows.count(), 2)

        for order in ("created_at", "-created_at"):
            with self.subTest(order=order):
                acts = fold_acts(rows.order_by(order))
                self.assertEqual(
                    [act["label"] for act in acts], ["Scheduled a core school visit"]
                )


class TheStripAboveTheTableTest(Team):
    def test_the_active_share_is_of_the_staff_expected(self):
        log = activity_log(self.lead)
        kpis = log["kpis"]

        self.assertLessEqual(kpis["staff_active"], kpis["staff_total"])
        if kpis["active_share"] is not None:
            self.assertLessEqual(kpis["active_share"], 100)

    def test_every_figure_is_the_sum_of_the_rows_under_it(self):
        audit_log(
            action="start_activity",
            subject_kind="school",
            subject_id="S1",
            actor_id=self.mina.id,
        )
        log = activity_log(self.lead)

        self.assertEqual(
            log["kpis"]["meaningful_actions"], sum(p["actions"] for p in log["people"])
        )
        self.assertEqual(log["kpis"]["staff_total"], len(log["people"]))
