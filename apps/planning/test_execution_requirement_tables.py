"""The requirement tables and the timeliness table of Execution & Completion
(owner, 2026-10-18).

* **Verified is My Plan's green.** A visit or a training is verified against
  the requirement only when it is verified (by the Programme Lead for a
  CCEO's work, by IA otherwise) AND its Salesforce ID and its form — the visit
  form, or the attendance register for a training — are both in: the state My
  Plan shows green. A verified status over a missing half is still in
  progress.
* **Visits by school type:** Total Visits Expected is four at each Core school
  and one at every other; Staff Target is two at each Core school and one at
  each school staff capacity reaches; Partner Target is the other two at each
  Core school and the schools beyond it. A Partner's SSA Support is verified
  nowhere. Every column after the expected one carries its share.
* **Trainings by school type:** Total Expected is four at each Core school and
  one at every other; Total Planned is staff's and the Partners', where a
  Partner's planned trainings are the schools assigned to it for an in-school
  training.
* **The same, by Programme Lead and CCEO**, under the type table.
* **Execution timeliness**: In-Progress is started work that is not yet
  complete and verified; Completed & PL Verified is the green state. Partners
  read Assigned, Scheduled, Started, Evidence Submitted, Verified, Awaiting
  Verification and Payment.
"""

from __future__ import annotations

from itertools import count

from apps.evidence.models import EvidenceRecord
from apps.planning.country_execution import service as esvc
from apps.planning.test_country_planning_oversight import FY, World

QUERY = f"view=execution&period=fy&fy={FY}"


def annual(**filters) -> esvc.ExecFilters:
    return esvc.ExecFilters(fy=FY, period="fy", **filters)


_SALESFORCE = count(1000)


def green(activity, *, form="visit_form"):
    """My Plan's green: the Salesforce ID and the form both in."""
    activity.salesforce_activity_id = f"SVE-{next(_SALESFORCE)}"
    activity.save(update_fields=["salesforce_activity_id"])
    EvidenceRecord.objects.create(
        activity=activity, kind=form, uri=f"{activity.id}-{form}", uploaded_by="t"
    )
    return activity


class RequirementWorld(World):
    """Officer One holds two Core schools and three Client schools."""

    def setUp(self):
        self.core1 = self.school("core", self.cceo)
        self.core2 = self.school("core", self.cceo)
        self.clients = [self.school("client", self.cceo) for _ in range(3)]

    def snapshot(self, **filters):
        return esvc.snapshot_for(self.cd_user, annual(**filters), refresh=True)

    def types(self):
        return {row["key"]: row for row in esvc.type_rows(self.snapshot())}

    def staff_visit(self, school, activity_type="training_follow_up_visit", **extra):
        return self.activity(school, activity_type, owner=self.cceo, **extra)

    def partner_visit(self, school, activity_type="training_follow_up_visit", **extra):
        return self.activity(
            school,
            activity_type,
            partner=self.partner,
            partner_date_set_by="partner",
            **extra,
        )


# ── Visits by school type ────────────────────────────────────────────────────
class VisitsByTypeTest(RequirementWorld):
    def test_the_expected_visits_and_each_sides_target(self):
        rows = self.types()
        core, client = rows["core"], rows["client"]
        self.assertEqual(core["visit_slots"], 4 * 2)
        self.assertEqual(core["staff_target"], 2 * 2)
        self.assertEqual(core["partner_target"], 2 * 2)
        self.assertEqual(client["visit_slots"], 3)
        # Three Client schools are well inside a CCEO's 560: all staff's.
        self.assertEqual((client["staff_target"], client["partner_target"]), (3, 0))

    def test_only_green_verified_work_is_verified(self):
        green(self.staff_visit(self.core1, status="ia_verified"))
        # Verified by the Lead, but no Salesforce ID: not green.
        self.staff_visit(self.core1, status="ia_verified")
        # The Salesforce ID and no visit form: not green either.
        self.staff_visit(
            self.core2,
            "school_visit",
            status="ia_verified",
            salesforce_activity_id="SVE-0002",
        )
        core = self.types()["core"]
        self.assertEqual(core["staff_verified"], 1)
        self.assertEqual(core["staff_share"], 25)
        self.assertEqual(core["visits_verified"], 1)
        self.assertEqual(core["visits_left"], 8 - 1)

    def test_a_partners_visits_are_verified_but_never_its_ssa_support(self):
        green(self.partner_visit(self.core1, status="ia_verified"))
        green(
            self.partner_visit(self.core2, "in_school_training", status="ia_verified"),
            form="attendance_form",
        )
        green(
            self.partner_visit(
                self.core2,
                "school_visit",
                status="ia_verified",
                purpose_type="ssa_support",
            )
        )
        core = self.types()["core"]
        self.assertEqual(core["partner_verified"], 2)
        self.assertEqual(core["partner_share"], 50)
        self.assertEqual(core["visits_verified"], 2)
        self.assertEqual(core["visits_left"], 6)

    def test_every_figure_carries_its_share(self):
        self.staff_visit(self.clients[0])
        green(self.staff_visit(self.clients[1], status="ia_verified"))
        client = self.types()["client"]
        self.assertEqual(
            (client["visits_planned"], client["visits_planned_share"]), (2, 67)
        )
        self.assertEqual(client["staff_target_share"], 100)
        self.assertEqual(client["partner_target_share"], 0)
        self.assertEqual((client["visits_verified"], client["visit_share"]), (1, 33))
        self.assertEqual((client["visits_left"], client["visits_left_share"]), (2, 67))


# ── Trainings by school type ─────────────────────────────────────────────────
class TrainingsByTypeTest(RequirementWorld):
    def test_four_trainings_at_a_core_school_and_one_elsewhere(self):
        rows = self.types()
        self.assertEqual(rows["core"]["training_slots"], 4 * 2)
        self.assertEqual(rows["client"]["training_slots"], 3)

    def test_a_partners_planned_trainings_are_the_schools_assigned_to_it(self):
        self.handover(self.clients[0], self.partner, kind="training")
        self.handover(
            self.core1, self.partner, support_type="training", training_number=3
        )
        self.staff_visit(self.clients[1], "in_school_training")
        rows = self.types()
        client, core = rows["client"], rows["core"]
        self.assertEqual(client["trainings_partner"], 1)
        self.assertEqual(client["trainings_planned"], 2)
        self.assertEqual(client["trainings_planned_share"], 67)
        self.assertEqual(core["trainings_partner"], 1)
        self.assertEqual(core["trainings_planned"], 1)

    def test_completed_and_verified_is_green_and_remaining_is_the_rest(self):
        green(
            self.staff_visit(
                self.clients[0], "in_school_training", status="ia_verified"
            ),
            form="attendance_form",
        )
        # Verified with the visit form, not the attendance register: not green.
        green(
            self.staff_visit(
                self.clients[1], "in_school_training", status="ia_verified"
            )
        )
        client = self.types()["client"]
        self.assertEqual(
            (client["trainings_verified"], client["training_share"]), (1, 33)
        )
        self.assertEqual(
            (client["trainings_left"], client["trainings_left_share"]), (2, 67)
        )


# ── By Programme Lead and CCEO ───────────────────────────────────────────────
class RequirementByPeopleTest(RequirementWorld):
    def test_each_lead_opens_onto_their_people_with_the_same_columns(self):
        self.school("client", self.cceo3)
        green(self.staff_visit(self.core1, status="ia_verified"))
        leads = {row["key"]: row for row in esvc.people_rows(self.snapshot())}
        lead_a = leads[self.pl.id]
        self.assertEqual(lead_a["label"], "Lead A")
        people = {row["key"]: row for row in lead_a["owners"]}
        officer = people[self.cceo.id]
        self.assertEqual(officer["label"], "Officer One")
        self.assertEqual(officer["visit_slots"], 8 + 3)
        self.assertEqual(officer["staff_target"], 4 + 3)
        self.assertEqual(officer["staff_verified"], 1)
        self.assertEqual(officer["training_slots"], 8 + 3)
        # A Lead's row is their people's together.
        self.assertEqual(
            lead_a["visit_slots"], sum(row["visit_slots"] for row in lead_a["owners"])
        )
        self.assertEqual(leads[self.pl2.id]["visit_slots"], 1)


# ── Execution timeliness ─────────────────────────────────────────────────────
class TimelinessTest(RequirementWorld):
    def test_in_progress_is_started_work_that_is_not_green_yet(self):
        green(self.staff_visit(self.core1, status="ia_verified"))
        # Done by its status, but the Salesforce ID is missing.
        self.staff_visit(self.core1, status="ia_verified")
        self.staff_visit(self.core2, "school_visit", status="submitted_to_pl")
        self.staff_visit(self.core2, "school_visit", status="completion_started")
        self.staff_visit(self.clients[0], "school_visit")
        snapshot = self.snapshot()
        cells = next(
            row["cells"]
            for row in esvc.owner_rows(snapshot, self.pl.id, {})
            if row["key"] == self.cceo.id
        )
        self.assertEqual(cells["due"], 5)
        self.assertEqual(cells["in_progress"], 3)
        self.assertEqual(cells["complete"], 1)

    def test_a_partner_reads_from_assignment_to_payment(self):
        self.handover(self.clients[2], self.partner)
        self.partner_visit(self.clients[0], status="partner_scheduled")
        self.partner_visit(self.core1, status="awaiting_ia_verification")
        green(
            self.partner_visit(self.core2, status="ia_verified", payment_status="paid")
        )
        row = next(
            row
            for row in esvc.partner_rows(self.snapshot())
            if row["key"] == self.partner.id
        )
        self.assertEqual(row["assigned"], 3 + 1)
        self.assertEqual(row["due"], 3)
        self.assertEqual(row["awaiting_verification"], 1)
        self.assertEqual(row["verified"], 1)
        self.assertEqual((row["paid"], row["awaiting_payment"]), (1, 0))


# ── The page ─────────────────────────────────────────────────────────────────
class PageTest(RequirementWorld):
    def body(self, path=f"/country-planning-oversight/?{QUERY}"):
        return self.as_user(self.cd_user).get(path).content.decode()

    def test_the_tables_are_named_as_the_owner_asked(self):
        body = self.body()
        for text in (
            "Total Visits Expected",
            "Total Visits Verified",
            "Visits Remaining",
            "Total Expected",
            "Total Planned",
            "Planned by Partners",
            "Completed &amp; Verified",
            "Verified Against the Requirement by Programme Lead and CCEO",
            "Execution Timeliness",
            "In-Progress",
            "Completed &amp; PL Verified",
        ):
            with self.subTest(text=text):
                self.assertIn(text, body)
        for gone in ("Visits Needed", "Trainings Needed", "Visits Completed"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        # The breakdown sits between the type table and the timeliness table.
        self.assertLess(body.index("cxo-types-name"), body.index("cxo-people-name"))
        self.assertLess(body.index("cxo-people-name"), body.index("cxo-table-name"))

    def test_the_partner_view_reads_from_assignment_to_payment(self):
        self.partner_visit(self.clients[0], status="partner_scheduled")
        body = self.body(
            f"/country-planning-oversight/execution/table?table=partner&{QUERY}"
        )
        for text in (
            "Assigned",
            "Scheduled",
            "Started",
            "Evidence Submitted",
            "Awaiting Verification",
            "Payment",
            "Overdue",
        ):
            with self.subTest(text=text):
                self.assertIn(f">{text}</th>", body)
