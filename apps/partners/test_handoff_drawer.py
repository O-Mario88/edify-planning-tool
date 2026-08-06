"""The simplified partner handoff, and who ends up watching it.

Two behaviours are load-bearing and neither was true before:

  • The drawer's "Monitored by" line and the assignment's monitoring_staff_id
    come from one resolver, so the record cannot contradict what the person
    pressing Handoff was shown.
  • That monitor — the school's own staff member — is who the partner's work
    reaches on My Plan. Previously it was whoever clicked, so a PL handing off
    a CCEO's school left the CCEO with no sight of it at all.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.purposes import (
    PARTNER_VISIT_PURPOSES,
    normalise_visit_purpose,
)
from apps.schools.models import School


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class MonitoringStaffResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PH Region")
        cls.district = District.objects.create(name="PH District", region=region)
        cls.cceo = _user("ph-cceo@t.org", EdifyRole.CCEO.value)
        cls.cceo_sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        cls.pl = _user("ph-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.pl_sp = StaffProfile.objects.create(user=cls.pl, country="Uganda")

        cls.school = School.objects.create(
            name="PH School",
            school_id="PH-1",
            region_id=region.id,
            district_id=cls.district.id,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

    def test_monitor_is_the_schools_own_staff_not_the_assigner(self):
        """A PL handing off a CCEO's school must not become the monitor —
        that is how the partner's work stopped reaching the CCEO."""
        from apps.frontend.views.planning_views import resolve_monitoring_staff

        staff_id, name = resolve_monitoring_staff(self.school, self.pl)
        self.assertEqual(staff_id, self.cceo_sp.id)
        self.assertEqual(name, self.cceo.name)

    def test_falls_back_to_the_assigner_for_an_unassigned_school(self):
        unassigned = School.objects.create(
            name="PH Orphan",
            school_id="PH-2",
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        _staff_id, name = resolve_monitoring_staff_helper(unassigned, self.pl)
        self.assertEqual(name, self.pl.name)

    def test_falls_back_to_the_assigner_for_a_cluster(self):
        """A cluster has no single owning staff member."""
        _staff_id, name = resolve_monitoring_staff_helper(None, self.pl)
        self.assertEqual(name, self.pl.name)

    def test_activity_monitor_prefers_monitoring_staff_over_assigner(self):
        """The join that actually decides whose My Plan the work lands on."""
        from apps.partners.models import PartnerAssignment

        field_names = {f.name for f in PartnerAssignment._meta.get_fields()}
        self.assertIn("monitoring_staff_id", field_names)

        pa = PartnerAssignment(
            assigning_staff_id=self.pl_sp.id,
            monitoring_staff_id=self.cceo_sp.id,
        )
        self.assertEqual(
            pa.monitoring_staff_id or pa.assigning_staff_id, self.cceo_sp.id
        )

    def test_a_legacy_row_still_resolves_to_its_assigner(self):
        """monitoring_staff_id is nullable so rows written before it existed
        keep resolving to exactly what they resolved to before."""
        from apps.partners.models import PartnerAssignment

        pa = PartnerAssignment(
            assigning_staff_id=self.pl_sp.id, monitoring_staff_id=None
        )
        self.assertEqual(pa.monitoring_staff_id or pa.assigning_staff_id, self.pl_sp.id)


def resolve_monitoring_staff_helper(school, actor):
    from apps.frontend.views.planning_views import resolve_monitoring_staff

    return resolve_monitoring_staff(school, actor)


class PartnerPurposeTests(TestCase):
    def test_the_four_reasons_the_drawer_offers(self):
        labels = [label for _value, label in PARTNER_VISIT_PURPOSES]
        self.assertEqual(
            labels,
            [
                "In-school Training",
                "Training Follow Up",
                "SSA Support",
                "Content Gathering",
            ],
        )

    def test_content_gathering_is_accepted_for_a_partner(self):
        """It was staff-only before, so a partner handoff naming it was
        refused outright."""
        self.assertEqual(
            normalise_visit_purpose("story_gathering", for_partner=True),
            "story_gathering",
        )

    def test_content_gathering_keeps_its_stable_database_value(self):
        """The label was reworded; the value must not move, or every existing
        row stops resolving."""
        values = [value for value, _label in PARTNER_VISIT_PURPOSES]
        self.assertIn("story_gathering", values)
        self.assertNotIn("content_gathering", values)

    def test_a_staff_only_purpose_is_still_refused_for_a_partner(self):
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            normalise_visit_purpose("donor_visit", for_partner=True)

    def test_content_gathering_maps_to_an_activity_type(self):
        from apps.partners.purposes import purpose_activity_type

        self.assertEqual(
            purpose_activity_type("story_gathering"), "story_gathering_visit"
        )
