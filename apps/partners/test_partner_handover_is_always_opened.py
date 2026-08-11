"""Partner-delivered work always has a handover record behind it.

Partner Oversight reads PartnerAssignment. An activity that names a partner
and that no assignment points at is invisible there: the work happened, the
money moved, and the person answerable for partner delivery sees neither.

There are two ways partner work comes into being and only one of them was
covered. A staff member who *hands a school over* creates the assignment
first, and the partner's later scheduling turns it into an activity. A staff
member who *schedules with a partner in one step* — the school-visit drawer,
the core-schools drawers, the work plan, the API — created only the activity.
The cluster planner alone remembered to write a handover, in its own copy,
which is why the school-level paths never had one.

`activities.services.create` now opens it for every caller, so the answer
cannot be right in one path and missing in five.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School


class PartnerHandoverIsAlwaysOpenedTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="PH Region")
        self.district = District.objects.create(name="PH District", region=self.region)
        self.sub = SubCounty.objects.create(name="PH Sub", district=self.district)
        self.user = User.objects.create(
            email="ph-cceo@edify.org",
            name="PH Field",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
            status="active",
        )
        self.profile = StaffProfile.objects.create(user=self.user, title="CCEO")
        self.school = School.objects.create(
            school_id="PH-001",
            name="PH School",
            region=self.region,
            district=self.district,
            sub_county=self.sub,
            school_type="client",
            account_owner_id=self.profile.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.profile, school_id=self.school.id
        )
        self.partner = Partner.objects.create(
            name="PH Partner", active_status=True, contract_status="active"
        )

    def _activity(self, **overrides):
        from apps.activities.models import Activity

        defaults = dict(
            school=self.school,
            activity_type="school_visit",
            fy="2026",
            status="scheduled",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            responsible_staff_id=self.profile.id,
        )
        defaults.update(overrides)
        return Activity.objects.create(**defaults)

    def test_an_activity_that_names_a_partner_gets_its_handover(self):
        from apps.activities.services import _ensure_partner_handover

        activity = self._activity()
        self.assertFalse(PartnerAssignment.objects.exists())

        _ensure_partner_handover(activity, {})

        assignment = PartnerAssignment.objects.get()
        self.assertEqual(assignment.scheduled_activity_id, activity.id)
        self.assertEqual(assignment.partner_id, self.partner.id)
        self.assertEqual(assignment.school_id, self.school.id)
        self.assertEqual(assignment.status, "partner_scheduled")

    def test_the_handover_records_who_watches_the_delivery(self):
        """The monitor is the person who knows the school, not whoever asked.

        `monitored_by_staff_id` is set by the handoff resolver precisely so the
        partner's work reaches the owning CCEO's My Plan; the assignment has to
        carry it through or the same defect reappears one record downstream.
        """
        from apps.activities.services import _ensure_partner_handover

        activity = self._activity(monitored_by_staff_id=self.profile.id)
        _ensure_partner_handover(activity, {})
        self.assertEqual(
            PartnerAssignment.objects.get().monitoring_staff_id, self.profile.id
        )

    def test_it_is_idempotent(self):
        from apps.activities.services import _ensure_partner_handover

        activity = self._activity()
        _ensure_partner_handover(activity, {})
        _ensure_partner_handover(activity, {})
        self.assertEqual(PartnerAssignment.objects.count(), 1)

    def test_staff_delivery_opens_nothing(self):
        from apps.activities.services import _ensure_partner_handover

        activity = self._activity(delivery_type="staff", assigned_partner_id=None)
        _ensure_partner_handover(activity, {})
        self.assertFalse(PartnerAssignment.objects.exists())

    def test_no_partner_named_invents_none(self):
        """The line the repair command will not cross either.

        An activity marked partner-delivered with no partner is a malformed
        row. Manufacturing an assignment against some partner to satisfy a
        health check would put real work — and real money — against an
        organisation that never did it.
        """
        from apps.activities.services import _ensure_partner_handover

        activity = self._activity(assigned_partner_id=None)
        _ensure_partner_handover(activity, {})
        self.assertFalse(PartnerAssignment.objects.exists())

    def test_the_health_board_separates_the_two_conditions(self):
        from apps.system_health.planning_oversight_health import (
            _partner_activities_no_assignment_claims,
            _partner_delivery_with_no_partner_named,
        )

        self._activity()  # names a partner, no handover → linkable
        self._activity(assigned_partner_id=None)  # names nobody → malformed

        linkable = _partner_activities_no_assignment_claims()
        malformed = _partner_delivery_with_no_partner_named()

        self.assertEqual(linkable["count"], 1)
        self.assertEqual(malformed["count"], 1)
        self.assertEqual(malformed["severity"], "error")

    def test_two_unslotted_assignments_at_one_school_are_not_a_double_booking(self):
        """A slot clash needs a slot.

        Support slots are a Core-package concept — Visit 1..4, Training 1..4 —
        and ordinary partner work names none. Keying the clash detector on the
        empty triple made two perfectly normal assignments at one school read
        as two partners claiming the same piece of support, which would put
        every busy school on the board as an error.
        """
        from apps.system_health.planning_oversight_health import (
            _two_live_assignments_on_one_slot,
        )

        for _ in range(2):
            PartnerAssignment.objects.create(
                school=self.school,
                partner=self.partner,
                assigning_staff_id=self.profile.id,
                status="partner_scheduled",
            )
        self.assertEqual(_two_live_assignments_on_one_slot()["count"], 0)

    def test_two_assignments_on_the_same_named_slot_still_clash(self):
        from apps.system_health.planning_oversight_health import (
            _two_live_assignments_on_one_slot,
        )

        for _ in range(2):
            PartnerAssignment.objects.create(
                school=self.school,
                partner=self.partner,
                assigning_staff_id=self.profile.id,
                status="assigned",
                support_type="Visit",
                visit_number="1",
            )
        self.assertEqual(_two_live_assignments_on_one_slot()["count"], 1)

    def test_the_repair_command_links_what_it_can_and_leaves_the_rest(self):
        from io import StringIO

        from django.core.management import call_command

        linkable = self._activity()
        malformed = self._activity(assigned_partner_id=None)

        out = StringIO()
        call_command("repair_partner_handovers", "--repair", stdout=out, stderr=out)

        self.assertEqual(PartnerAssignment.objects.count(), 1)
        self.assertEqual(
            PartnerAssignment.objects.get().scheduled_activity_id, linkable.id
        )
        malformed.refresh_from_db()
        self.assertEqual(malformed.delivery_type, "partner")
        self.assertIsNone(malformed.assigned_partner_id)

    def test_attributing_a_partner_needs_the_operator_to_name_one(self):
        from io import StringIO

        from django.core.management import call_command

        malformed = self._activity(assigned_partner_id=None)

        out = StringIO()
        call_command(
            "repair_partner_handovers",
            "--attribute-partner",
            self.partner.id,
            stdout=out,
            stderr=out,
        )

        malformed.refresh_from_db()
        self.assertEqual(malformed.assigned_partner_id, self.partner.id)
        self.assertEqual(
            PartnerAssignment.objects.get().scheduled_activity_id, malformed.id
        )

    def test_an_unknown_partner_id_changes_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        malformed = self._activity(assigned_partner_id=None)
        out = StringIO()
        call_command(
            "repair_partner_handovers",
            "--attribute-partner",
            "not-a-partner",
            stdout=out,
            stderr=out,
        )
        malformed.refresh_from_db()
        self.assertIsNone(malformed.assigned_partner_id)
        self.assertFalse(PartnerAssignment.objects.exists())
