"""A training is edited from its own record in the catalogue (owner, 2026-10-06).

"Existing trainings must be editable from their existing Training Profile …
Do not corrupt historical scheduled training records." What is pinned here:
who may edit and what, that each edit is a new catalogue version with its
reason, that a training already scheduled keeps what it was scheduled with,
that the governed seed re-installed on every deploy does not undo an edit, and
that the SSA intervention is shown and not edited.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.activity_catalogue.authoring import update_training
from apps.activity_catalogue.models import (
    ActivityCatalogueAlias,
    ActivityCatalogueItem,
)
from apps.activity_catalogue.seeding import normalize_alias, seed_activity_catalogue
from apps.activity_catalogue.training_intervention import intervention_for
from apps.core.exceptions import BadRequest

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
EDIT = "/settings/activity-catalogue/{}/edit"


class TrainingEditFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = User.objects.create_user(
            email="cd.training-edit@edify.org",
            name="CD Training Edit",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        cls.cceo = User.objects.create_user(
            email="cceo.training-edit@edify.org",
            name="CCEO Training Edit",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )

    def setUp(self):
        self.training = ActivityCatalogueItem.objects.get(
            stable_code="SCHOOL_LEADERSHIP"
        )
        self.visit = ActivityCatalogueItem.objects.get(
            stable_code="STANDARD_SCHOOL_VISIT"
        )

    def client_for(self, user) -> Client:
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client

    def edit(self, **changes):
        data = {"reason": "Programme renamed the course for FY2027."}
        data.update(changes)
        return update_training(self.training.id, data, actor_id="cd_edit")


class EditingATraining(TrainingEditFixture):
    def test_an_edit_changes_the_definition_and_is_kept_as_a_version(self):
        versions = self.training.versions.count()

        item = self.edit(
            name="School Leadership Essentials",
            trainingCategory="Leadership",
            targetAudience="Head teachers and proprietors",
            description="Leading a school that improves.",
        )

        item.refresh_from_db()
        self.assertEqual(item.display_name, "School Leadership Essentials")
        self.assertEqual(item.training_category, "Leadership")
        self.assertEqual(item.target_audience, "Head teachers and proprietors")
        self.assertEqual(item.description, "Leading a school that improves.")
        # Its identity is unchanged: the same record, the same stable code.
        self.assertEqual(item.id, self.training.id)
        self.assertEqual(item.stable_code, "SCHOOL_LEADERSHIP")
        self.assertEqual(item.versions.count(), versions + 1)
        latest = item.versions.order_by("-version").first()
        self.assertEqual(
            latest.change_reason, "Programme renamed the course for FY2027."
        )
        self.assertEqual(latest.created_by, "cd_edit")
        self.assertEqual(latest.snapshot["displayName"], "School Leadership Essentials")
        self.assertTrue(
            ActivityCatalogueAlias.objects.filter(
                normalized_alias=normalize_alias("School Leadership Essentials"),
                catalogue_item=item,
            ).exists()
        )

    def test_the_ssa_intervention_is_not_changed_by_an_edit(self):
        before = intervention_for(training_course_id=self.training.id)

        self.edit(name="School Leadership Essentials", intervention="enrolment")

        self.assertEqual(intervention_for(training_course_id=self.training.id), before)
        self.assertEqual(before, "leadership")

    def test_a_reason_a_name_and_a_real_change_are_required(self):
        with self.assertRaises(BadRequest):
            update_training(self.training.id, {"name": "Renamed"}, actor_id="cd_edit")
        with self.assertRaises(BadRequest):
            self.edit(name="   ")
        with self.assertRaises(BadRequest):
            self.edit(name=self.training.display_name)
        other = ActivityCatalogueItem.objects.get(stable_code="TAM_I")
        with self.assertRaises(BadRequest):
            self.edit(name=other.display_name.upper())

    def test_only_a_training_is_edited_here(self):
        with self.assertRaises(BadRequest):
            update_training(
                self.visit.id,
                {"name": "Another Visit", "reason": "not a training"},
                actor_id="cd_edit",
            )

    def test_a_training_already_scheduled_keeps_what_it_was_scheduled_with(self):
        scheduled = Activity.objects.create(
            activity_type="cluster_training",
            catalogue_item=self.training,
            catalogue_version=1,
            activity_name_snapshot=self.training.display_name,
            focus_intervention="leadership",
            purpose_intervention="leadership",
            fy="2026",
            quarter="Q3",
            status="closed",
        )

        self.edit(name="School Leadership Essentials")

        scheduled.refresh_from_db()
        self.assertEqual(scheduled.activity_name_snapshot, "Leadership")
        self.assertEqual(scheduled.catalogue_version, 1)
        self.assertEqual(scheduled.focus_intervention, "leadership")
        self.assertEqual(scheduled.status, "closed")
        # Still the same training: the record it points at was edited, not
        # replaced.
        self.assertEqual(scheduled.catalogue_item_id, self.training.id)

    def test_the_seed_run_on_every_deploy_does_not_undo_an_edit(self):
        self.edit(name="School Leadership Essentials", trainingCategory="Leadership")

        seed_activity_catalogue(actor_id="reference_data")

        self.training.refresh_from_db()
        self.assertEqual(self.training.display_name, "School Leadership Essentials")
        self.assertEqual(self.training.training_category, "Leadership")
        self.assertEqual(
            sorted(self.training.edited_fields), ["display_name", "training_category"]
        )
        # A field nobody edited is still the seed's to repair.
        ActivityCatalogueItem.objects.filter(id=self.training.id).update(
            ssa_indicator_label="drifted"
        )
        seed_activity_catalogue(actor_id="reference_data")
        self.training.refresh_from_db()
        self.assertEqual(self.training.ssa_indicator_label, "Leadership Practices")


class TheTrainingsRecordInTheCatalogue(TrainingEditFixture):
    def test_the_catalogue_still_lists_every_training(self):
        response = self.client_for(self.cd).get("/settings/activity-catalogue/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for name in ("Leadership", "SSA Training", "School Visit"):
            self.assertIn(name, body)
        self.assertIn("New activity", body)

    def test_a_training_carries_an_edit_button_and_other_items_do_not(self):
        body = (
            self.client_for(self.cd)
            .get("/settings/activity-catalogue/")
            .content.decode()
        )

        self.assertIn(f'hx-get="{EDIT.format(self.training.id)}"', body)
        self.assertNotIn(f'hx-get="{EDIT.format(self.visit.id)}"', body)

    def test_a_reader_without_the_catalogue_sees_no_edit_button(self):
        response = self.client_for(self.cceo).get("/settings/activity-catalogue/")

        if response.status_code == 200:
            self.assertNotIn("data-edit-training", response.content.decode())
        else:
            self.assertEqual(response.status_code, 403)

    def test_the_drawer_shows_the_training_and_its_intervention_read_only(self):
        response = self.client_for(self.cd).get(
            EDIT.format(self.training.id), HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Edit Leadership", body)
        self.assertIn('name="name"', body)
        self.assertIn('value="Leadership"', body)
        self.assertIn("data-training-intervention", body)
        self.assertNotIn('name="intervention"', body)
        self.assertIn('name="reason"', body)

    def test_the_drawer_says_which_training_is_universal(self):
        """Owner, 2026-10-06: SSA Training (school improvement planning) is
        the training every school may attend on top of its own."""
        universal = ActivityCatalogueItem.objects.get(stable_code="SSA_TRAINING")
        client = self.client_for(self.cd)

        self.assertContains(
            client.get(EDIT.format(universal.id), HTTP_HX_REQUEST="true"),
            "data-universal-training",
        )
        self.assertNotContains(
            client.get(EDIT.format(self.training.id), HTTP_HX_REQUEST="true"),
            "data-universal-training",
        )

    def test_saving_the_drawer_edits_the_training(self):
        response = self.client_for(self.cd).post(
            EDIT.format(self.training.id),
            {
                "name": "School Leadership Essentials",
                "description": "",
                "training_category": "Education",
                "ssa_indicator_label": "Leadership Practices",
                "target_audience": "School staff",
                "reason": "Renamed for FY2027.",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["HX-Redirect"],
            f"/settings/activity-catalogue/#item-{self.training.id}",
        )
        self.training.refresh_from_db()
        self.assertEqual(self.training.display_name, "School Leadership Essentials")

    def test_a_refused_save_says_why_and_changes_nothing(self):
        response = self.client_for(self.cd).post(
            EDIT.format(self.training.id),
            {
                "name": "School Leadership Essentials",
                "training_category": "Education",
                "ssa_indicator_label": "Leadership Practices",
                "target_audience": "School staff",
                "reason": "",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Say why the training is changing.", response.content.decode())
        self.assertNotIn("HX-Redirect", response)
        self.training.refresh_from_db()
        self.assertEqual(self.training.display_name, "Leadership")

    def test_nobody_without_the_catalogue_edits_a_training(self):
        client = self.client_for(self.cceo)

        self.assertEqual(client.get(EDIT.format(self.training.id)).status_code, 403)
        refused = client.post(
            EDIT.format(self.training.id),
            {"name": "Mine Now", "target_audience": "x", "reason": "because"},
        )
        self.assertEqual(refused.status_code, 403)
        self.training.refresh_from_db()
        self.assertEqual(self.training.display_name, "Leadership")

    def test_an_item_that_is_not_a_training_has_no_edit_drawer(self):
        response = self.client_for(self.cd).get(EDIT.format(self.visit.id))

        self.assertEqual(response.status_code, 404)

    def test_a_scheduled_plan_reads_the_new_name_only_for_what_is_scheduled_next(self):
        """The catalogue's own list follows the edit; the scheduling drawers
        offer the new name from then on."""
        from apps.activity_catalogue.availability import (
            CLUSTER,
            training_activity_options,
        )

        self.edit(name="School Leadership Essentials")

        labels = {
            o["label"] for o in training_activity_options(planning_context=CLUSTER)
        }
        self.assertIn("School Leadership Essentials", labels)
        self.assertNotIn("Leadership", labels)
