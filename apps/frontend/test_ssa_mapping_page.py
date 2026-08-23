"""Who may say what an activity is measured against, from the page down."""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    MappingStatus,
)
from apps.core.rbac import EdifyRole

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
CB = "christlike_behaviour"


def _user(role, email):
    user = User.objects.create_user(
        email=email, name=email, roles=[role], active_role=role, password="x"
    )
    StaffProfile.objects.create(user=user, title=role)
    return user


class SsaMappingPageTest(TestCase):
    def setUp(self):
        self.ia = _user(EdifyRole.IMPACT_ASSESSMENT.value, "ia-page@t.org")
        self.cd = _user(EdifyRole.COUNTRY_DIRECTOR.value, "cd-page@t.org")
        self.item = ActivityCatalogueItem.objects.create(
            stable_code="MAP_PAGE_ITEM",
            source_name="Character Training",
            display_name="Character Training",
            activity_type="training",
            status="active",
            requires_school=True,
            # An active item must be costable and evidenced — the catalogue
            # refuses to publish one that cannot be planned.
            costing_profile="IN_SCHOOL_TRAINING",
            evidence_profile="TRAINING_ATTENDANCE",
            salesforce_record_type="TRAINING",
        )

    def _client(self, user):
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client

    def test_an_unmapped_school_activity_appears_in_the_queue(self):
        body = self._client(self.ia).get("/priorities/ssa-mapping").content.decode()

        self.assertIn("Character Training", body)
        self.assertIn("Link intervention", body)

    def test_impact_assessment_gets_the_control_and_the_country_director_does_not(self):
        ia_body = self._client(self.ia).get("/priorities/ssa-mapping").content.decode()
        cd_body = self._client(self.cd).get("/priorities/ssa-mapping").content.decode()

        self.assertIn("Link intervention", ia_body)
        # Authority over a country target is not authority over what counts as
        # that target having worked.
        self.assertNotIn("Link intervention", cd_body)
        self.assertIn("Impact Assessment", cd_body)

    def test_the_drawer_is_refused_to_the_country_director(self):
        response = self._client(self.cd).get(
            f"/priorities/ssa-mapping/{self.item.id}/drawer"
        )

        self.assertEqual(response.status_code, 403)

    def test_saving_a_mapping_publishes_it_and_clears_the_queue(self):
        response = self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {"intervention": CB, "publish": "1", "follow_up_min_days": "90"},
        )

        self.assertEqual(response.status_code, 204)
        mapping = ActivityInterventionMapping.objects.get(
            catalogue_item=self.item, active=True
        )
        self.assertEqual(mapping.intervention, CB)
        self.assertEqual(mapping.status, MappingStatus.PUBLISHED)
        self.assertEqual(mapping.follow_up_min_days, 90)

        body = self._client(self.ia).get("/priorities/ssa-mapping").content.decode()
        self.assertNotIn("Link intervention", body)

    def test_the_country_director_cannot_save_one(self):
        response = self._client(self.cd).post(
            f"/priorities/ssa-mapping/{self.item.id}/save", {"intervention": CB}
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ActivityInterventionMapping.objects.filter(
                catalogue_item=self.item
            ).exists()
        )

    def test_an_administrative_activity_can_be_recorded_as_not_measured(self):
        self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {
                "not_ssa_measured": "1",
                "not_ssa_measured_reason": "Internal planning; moves no school score.",
            },
        )

        mapping = ActivityInterventionMapping.objects.get(
            catalogue_item=self.item, active=True
        )
        self.assertIsNone(mapping.intervention)
        self.assertIn("Internal planning", mapping.not_ssa_measured_reason)

    def test_an_unexplained_exemption_is_refused(self):
        response = self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {"not_ssa_measured": "1", "not_ssa_measured_reason": "  "},
        )

        self.assertEqual(response.status_code, 400)
