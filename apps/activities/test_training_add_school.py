"""Adding a school to a scheduled training from its Edit drawer (owner, 2026-10-27).

"Make sure that add new school to the training has option to enter new school
direct. It should allow the staff to enter new school using enter new school
drawer, save and add to the cluster and training immediately, and all new
schools should be counted as new schools in the priority. It should also allow
users to add already existing school."

What is pinned here: a school found in Edify, or typed in through the Add New
School form, joins the session's cluster and is invited to the session the
moment it is saved; the portfolio and Champion rules still hold; and a school
typed in this way counts as a New School for the officer who holds it.
"""

from __future__ import annotations

import datetime
import json

from django.utils import timezone

from apps.activities import invite_school
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activities.test_activity_editing import EditingFixture
from apps.activities.test_profile_activities import PASSWORD
from apps.accounts.models import StaffProfile, User
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.schools.models import School


class TrainingFixture(EditingFixture):
    def setUp(self):
        super().setUp()
        day = timezone.localdate() + datetime.timedelta(8)
        self.training = Activity.objects.create(
            activity_type="cluster_training",
            status="scheduled",
            fy=get_operational_fy(day),
            planned_date=day,
            cluster=self.cluster,
            responsible_staff_id=str(self.cceo_staff.id),
            schools_invited=1,
        )
        ClusterActivityAttendance.objects.create(
            activity=self.training, school=self.school, invited=True
        )
        other_user = User.objects.create_user(
            email="add-school-other@edify.org",
            name="Other CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password=PASSWORD,
            is_active=True,
        )
        self.other_staff = StaffProfile.objects.create(
            user=other_user, staff_number="ST-ADD-OTHER", country="Uganda"
        )
        self.someone_elses = School.objects.create(
            school_id="ADD-OTHER-1",
            name="Profile Elsewhere Academy",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=self.other_staff.id,
        )
        self.champion = School.objects.create(
            school_id="ADD-CHAMP-1",
            name="Profile Champion School",
            region=self.region,
            district=self.district,
            school_type="champion",
            account_owner_id=self.cceo_staff.id,
        )

    def _invited(self, activity=None) -> set[str]:
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=activity or self.training, invited=True
            ).values_list("school_id", flat=True)
        )


class AddingAnExistingSchool(TrainingFixture):
    def test_an_unclustered_school_joins_the_cluster_and_the_training(self):
        with self.captureOnCommitCallbacks(execute=True):
            invite_school.add_school_to_session(
                self.training.id, self.fresh.id, self.cceo
            )

        self.fresh.refresh_from_db()
        self.assertEqual(self.fresh.cluster_id, self.cluster.id)
        self.assertEqual(self._invited(), {self.school.id, self.fresh.id})
        self.training.refresh_from_db()
        self.assertEqual(self.training.schools_invited, 2)

    def test_a_member_not_yet_invited_is_invited(self):
        with self.captureOnCommitCallbacks(execute=True):
            invite_school.add_school_to_session(
                self.training.id, self.member.id, self.cceo
            )

        self.assertEqual(self._invited(), {self.school.id, self.member.id})

    def test_a_school_already_invited_changes_nothing(self):
        invite_school.add_school_to_session(self.training.id, self.school.id, self.cceo)

        self.assertEqual(self._invited(), {self.school.id})

    def test_another_officers_school_is_refused_and_stays_where_it_was(self):
        with self.assertRaises(BadRequest):
            invite_school.add_school_to_session(
                self.training.id, self.someone_elses.id, self.cceo
            )

        self.someone_elses.refresh_from_db()
        self.assertIsNone(self.someone_elses.cluster_id)
        self.assertEqual(self._invited(), {self.school.id})

    def test_a_champion_school_is_refused_and_does_not_join(self):
        with self.assertRaises(BadRequest):
            invite_school.add_school_to_session(
                self.training.id, self.champion.id, self.cceo
            )

        self.champion.refresh_from_db()
        self.assertIsNone(self.champion.cluster_id)

    def test_a_delivered_training_takes_no_new_school(self):
        self.training.status = "submitted_to_pl"
        self.training.save(update_fields=["status"])

        with self.assertRaises(BadRequest):
            invite_school.add_school_to_session(
                self.training.id, self.fresh.id, self.cceo
            )
        self.fresh.refresh_from_db()
        self.assertIsNone(self.fresh.cluster_id)

    def test_a_single_school_visit_takes_no_school(self):
        with self.assertRaises(BadRequest):
            invite_school.add_school_to_session(
                self.planned.id, self.fresh.id, self.cceo
            )


class TheEditDrawer(TrainingFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))

    def test_the_drawer_offers_existing_and_new_schools(self):
        body = self.client.get(
            f"/my-plan/{self.training.id}/edit-drawer"
        ).content.decode()

        self.assertIn("data-edit-add-school", body)
        self.assertIn(
            f'hx-get="/my-plan/{self.training.id}/invite-school-search"', body
        )
        self.assertIn(
            f'hx-get="/schools/create-drawer?embed=1&amp;invite=1&amp;'
            f'activity_id={self.training.id}"',
            body,
        )

    def test_a_single_school_visit_has_no_add_school(self):
        body = self.client.get(
            f"/my-plan/{self.planned.id}/edit-drawer"
        ).content.decode()

        self.assertNotIn("data-edit-add-school", body)

    def test_the_search_finds_the_officers_schools_outside_the_cluster(self):
        found = self.client.get(
            f"/my-plan/{self.training.id}/invite-school-search", {"q": "Profile"}
        ).content.decode()

        self.assertIn(self.fresh.name, found)
        self.assertIn(self.other.name, found)
        # Already in this cluster and invited: nothing to add.
        self.assertNotIn(f">{self.school.name}<", found)
        # Not the officer's to put in this cluster, or never invited.
        self.assertNotIn(self.someone_elses.name, found)
        self.assertNotIn(self.champion.name, found)

    def test_add_joins_the_cluster_and_the_training_at_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{self.training.id}/invite-school",
                {"invite_school_id": self.fresh.id},
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        added = json.loads(response["HX-Trigger"])["edify-school-invited"]
        self.assertEqual(added["id"], self.fresh.id)
        self.assertTrue(added["invited"])
        self.assertEqual(self._invited(), {self.school.id, self.fresh.id})
        self.fresh.refresh_from_db()
        self.assertEqual(self.fresh.cluster_id, self.cluster.id)

    def test_a_refusal_is_a_message_and_nothing_moves(self):
        response = self.client.post(
            f"/my-plan/{self.training.id}/invite-school",
            {"invite_school_id": self.someone_elses.id},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("another staff member", response.content.decode())
        self.assertEqual(self._invited(), {self.school.id})

    def test_someone_who_may_not_edit_the_training_cannot_add(self):
        self.client.logout()
        self.assertTrue(self.client.login(email=self.pl.email, password=PASSWORD))
        response = self.client.post(
            f"/my-plan/{self.training.id}/invite-school",
            {"invite_school_id": self.fresh.id},
            HTTP_HX_REQUEST="true",
        )

        self.assertIn(response.status_code, (400, 403))
        self.assertEqual(self._invited(), {self.school.id})


class EnteringANewSchool(TrainingFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))

    def _payload(self, **overrides):
        payload = {
            "embed": "1",
            "invite": "1",
            "activity_id": self.training.id,
            "school_id": "ADD-NEW-1",
            "name": "Kabuyanda Sunrise Nursery",
            "salesforce_account_id": "0011a00000AddNew1",
            "district_id": self.district.id,
            "sub_county_id": "",
            "account_owner_id": self.cceo_staff.id,
            "school_type": "client",
            "enrollment": "",
            "cluster_id": self.cluster.id,
        }
        payload.update(overrides)
        return payload

    def test_the_form_opens_on_the_trainings_cluster(self):
        body = self.client.get(
            "/schools/create-drawer",
            {"embed": "1", "invite": "1", "activity_id": self.training.id},
        ).content.decode()

        self.assertIn('name="invite" value="1"', body)
        self.assertIn(f'name="activity_id" value="{self.training.id}"', body)
        self.assertIn("invited to this training", body)

    def test_saving_adds_the_school_to_the_cluster_and_the_training(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post("/schools/create-drawer", self._payload())

        self.assertEqual(response.status_code, 200, response.content)
        school = School.objects.get(school_id="ADD-NEW-1")
        self.assertEqual(school.cluster_id, self.cluster.id)
        self.assertEqual(self._invited(), {self.school.id, school.id})
        added = json.loads(response["HX-Trigger"])["edify-school-invited"]
        self.assertEqual(added["id"], school.id)
        self.assertTrue(added["invited"])

    def test_a_school_put_in_another_cluster_is_saved_but_not_invited(self):
        elsewhere = Cluster.objects.create(
            name="Profile Second Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id=self.cceo_staff.id,
        )
        response = self.client.post(
            "/schools/create-drawer", self._payload(cluster_id=elsewhere.id)
        )

        self.assertEqual(response.status_code, 200, response.content)
        school = School.objects.get(school_id="ADD-NEW-1")
        self.assertEqual(school.cluster_id, elsewhere.id)
        self.assertEqual(self._invited(), {self.school.id})
        added = json.loads(response["HX-Trigger"])["edify-school-invited"]
        self.assertFalse(added["invited"])
        self.assertIn("Profile Second Cluster", added["notice"])

    def test_a_new_school_counts_as_a_new_school_for_its_officer(self):
        from apps.team_performance.ledger import Ledger

        fy = get_operational_fy()
        window_end = timezone.localdate() + datetime.timedelta(1)
        officer = {str(self.cceo_staff.id)}
        ledger = Ledger.load(fy)
        before = ledger.count("new_schools", officer, ledger.fy_start, window_end)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/schools/create-drawer", self._payload())

        ledger = Ledger.load(fy)
        after = ledger.count("new_schools", officer, ledger.fy_start, window_end)
        self.assertEqual(after, (before or 0) + 1)
        school = School.objects.get(school_id="ADD-NEW-1")
        self.assertEqual(school.account_owner_id, self.cceo_staff.id)
