"""Who may say what an activity is measured against, from the page down.

IA review (2026-09-13): the register lives in the Measurement Framework, a
save keeps a draft, and a second officer publishes it — these tests used to
pin publish-on-save.
"""

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
        self.ia2 = _user(EdifyRole.IMPACT_ASSESSMENT.value, "ia2-page@t.org")
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

    def test_an_unmapped_school_activity_appears_in_the_framework_register(self):
        # The register moved into the Measurement Framework (IA review,
        # 2026-09-13); the old URL sends IA there.
        client = self._client(self.ia)
        response = client.get("/priorities/ssa-mapping")
        self.assertRedirects(
            response, "/ia/framework/?tab=rules", fetch_redirect_response=False
        )
        body = client.get("/ia/framework/?tab=rules").content.decode()

        self.assertIn("Character Training", body)
        self.assertIn("Link intervention", body)

    def test_impact_assessment_gets_the_control_and_the_country_director_does_not(self):
        ia_body = self._client(self.ia).get("/ia/framework/?tab=rules").content.decode()
        cd_body = self._client(self.cd).get("/ia/framework/?tab=rules").content.decode()

        self.assertIn("Link intervention", ia_body)
        # Authority over a country target is not authority over what counts as
        # that target having worked.
        self.assertNotIn("Link intervention", cd_body)
        self.assertIn("History", cd_body)

    def test_the_drawer_is_refused_to_the_country_director(self):
        response = self._client(self.cd).get(
            f"/priorities/ssa-mapping/{self.item.id}/drawer"
        )

        self.assertEqual(response.status_code, 403)

    def test_saving_keeps_a_draft_and_a_second_officer_publishes_it(self):
        response = self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {
                "intervention": CB,
                "follow_up_min_days": "90",
                "submit": "1",
                "change_reason": "First rule.",
            },
        )

        self.assertEqual(response.status_code, 204)
        mapping = ActivityInterventionMapping.objects.get(catalogue_item=self.item)
        self.assertEqual(mapping.status, MappingStatus.IN_REVIEW)
        self.assertFalse(mapping.active)

        # The author cannot publish it; a second officer can.
        self._client(self.ia).post(
            f"/priorities/ssa-mapping/rules/{mapping.id}/review/save",
            {"decision": "approve"},
        )
        mapping.refresh_from_db()
        self.assertEqual(mapping.status, MappingStatus.IN_REVIEW)
        self._client(self.ia2).post(
            f"/priorities/ssa-mapping/rules/{mapping.id}/review/save",
            {"decision": "approve"},
        )
        mapping.refresh_from_db()
        self.assertEqual(mapping.status, MappingStatus.PUBLISHED)
        self.assertTrue(mapping.active)
        self.assertEqual(mapping.follow_up_min_days, 90)

        body = self._client(self.ia).get("/ia/framework/?tab=rules").content.decode()
        self.assertNotIn("Link intervention", body)

    def test_submitting_without_a_reason_is_refused_with_the_message(self):
        response = self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {"intervention": CB, "submit": "1"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("what changed and why", response.content.decode())

    def test_the_drawer_prefills_every_saved_field_and_round_trips_them(self):
        client = self._client(self.ia)
        client.post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {
                "intervention": CB,
                "relationship": "primary",
                "measurement_role": "outcome_only",
                "expected_direction": "maintain_strong",
                "eligible_bands": ["Improving", "Strong"],
                "eligibility_note": "Schools already holding Strong.",
                "follow_up_min_days": "90",
                "follow_up_expected_days": "180",
                "follow_up_max_days": "400",
                "min_meaningful_change": "0.5",
            },
        )
        body = client.get(
            f"/priorities/ssa-mapping/{self.item.id}/drawer"
        ).content.decode()

        self.assertIn('<option value="outcome_only" selected>', body)
        self.assertIn('<option value="maintain_strong" selected>', body)
        self.assertIn('value="Strong" checked', body)
        self.assertIn('value="Improving" checked', body)
        self.assertNotIn('value="Critical" checked', body)
        self.assertIn("Schools already holding Strong.", body)
        self.assertIn('value="180"', body)
        self.assertIn('value="0.50"', body)

        # Re-saving only the window keeps every other field as it was.
        client.post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {
                "intervention": CB,
                "relationship": "primary",
                "measurement_role": "outcome_only",
                "expected_direction": "maintain_strong",
                "eligible_bands": ["Improving", "Strong"],
                "eligibility_note": "Schools already holding Strong.",
                "follow_up_min_days": "120",
                "follow_up_expected_days": "180",
                "follow_up_max_days": "400",
                "min_meaningful_change": "0.5",
            },
        )
        mapping = ActivityInterventionMapping.objects.get(catalogue_item=self.item)
        self.assertEqual(mapping.follow_up_min_days, 120)
        self.assertEqual(mapping.expected_direction, "maintain_strong")
        self.assertEqual(mapping.measurement_role, "outcome_only")
        self.assertEqual(sorted(mapping.eligible_bands), ["Improving", "Strong"])
        self.assertEqual(mapping.eligibility_note, "Schools already holding Strong.")

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

        mapping = ActivityInterventionMapping.objects.get(catalogue_item=self.item)
        self.assertIsNone(mapping.intervention)
        self.assertIn("Internal planning", mapping.not_ssa_measured_reason)
        self.assertEqual(mapping.status, MappingStatus.DRAFT)

    def test_an_unexplained_exemption_is_refused(self):
        response = self._client(self.ia).post(
            f"/priorities/ssa-mapping/{self.item.id}/save",
            {"not_ssa_measured": "1", "not_ssa_measured_reason": "  "},
        )

        self.assertEqual(response.status_code, 400)

    def test_other_ssa_mapping_readers_keep_a_read_only_register(self):
        pl = _user(EdifyRole.COUNTRY_PROGRAM_LEAD.value, "pl-page@t.org")
        response = self._client(pl).get("/priorities/ssa-mapping")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Character Training", body)
        self.assertNotIn(f"/priorities/ssa-mapping/{self.item.id}/drawer", body)
        self.assertEqual(
            self._client(pl)
            .get(f"/priorities/ssa-mapping/{self.item.id}/drawer")
            .status_code,
            403,
        )

    def test_a_field_role_without_the_page_is_refused(self):
        cceo = _user(EdifyRole.CCEO.value, "cceo-page@t.org")
        response = self._client(cceo).get("/priorities/ssa-mapping")

        self.assertNotIn("Character Training", response.content.decode())
