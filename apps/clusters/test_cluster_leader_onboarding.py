"""Staff onboard Cluster Leaders (owner, 2026-11-11: "add cluster leader user
category so the staff can onboard them").

The cluster's CCEO, a Programme Lead or an Admin creates the account; it only
ever holds the Cluster Leader role, carries no staff profile, and starts with
an invitation so nobody but the leader knows the password.
"""

from __future__ import annotations

from rest_framework.test import APITestCase

from apps.accounts.models import StaffProfile, User, UserInvitation
from apps.clusters.leader_onboarding import onboard_cluster_leader
from apps.clusters.test_eligibility import EligibilityFixture
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.rbac import EdifyRole

LEADER = EdifyRole.CLUSTER_LEADER.value


class ClusterLeaderOnboardingTest(EligibilityFixture, APITestCase):
    def _onboard(self, principal, cluster=None, **data):
        payload = {
            "name": "Grace Nakato",
            "email": "grace@school.test",
            "phone": "0772 000 111",
            **data,
        }
        with self.captureOnCommitCallbacks(execute=True):
            return onboard_cluster_leader(
                (cluster or self.chegere_north).id, payload, principal
            )

    def test_the_clusters_cceo_onboards_a_leader_with_that_role_alone(self):
        answer = self._onboard(self.james)
        leader = User.objects.get(id=answer["user"]["id"])
        self.assertEqual(leader.roles, [LEADER])
        self.assertEqual(leader.active_role, LEADER)
        self.assertEqual(leader.status, "pending_invited")
        self.assertFalse(leader.is_active)
        self.assertFalse(leader.has_usable_password())
        self.assertFalse(StaffProfile.objects.filter(user=leader).exists())
        self.assertTrue(UserInvitation.objects.filter(user_id=leader.id).exists())
        self.assertFalse(answer["existing"])

    def test_a_cluster_filed_under_the_cceos_profile_id_is_theirs_too(self):
        self.chegere_north.responsible_staff_id = self.james_profile.id
        self.chegere_north.save(update_fields=["responsible_staff_id"])
        self._onboard(self.james)

    def test_another_cceo_cannot_onboard_for_a_cluster_that_is_not_theirs(self):
        with self.assertRaises(Forbidden):
            self._onboard(self.mary)
        self.assertFalse(User.objects.filter(email="grace@school.test").exists())

    def test_a_programme_lead_and_an_admin_onboard_for_any_cluster(self):
        for role, email in (
            (EdifyRole.COUNTRY_PROGRAM_LEAD.value, "pl@school.test"),
            (EdifyRole.ADMIN.value, "ad@school.test"),
        ):
            self.mary.roles, self.mary.active_role = [role], role
            self.mary.save(update_fields=["roles", "active_role"])
            self._onboard(self.mary, email=email)

    def test_other_roles_cannot_onboard(self):
        for role in ("Accountant", LEADER, "PartnerAdmin"):
            self.mary.roles, self.mary.active_role = [role], role
            self.mary.save(update_fields=["roles", "active_role"])
            with self.assertRaises(Forbidden):
                self._onboard(self.mary, cluster=self.chegere_central)

    def test_a_staff_or_partner_email_is_never_turned_into_a_leader(self):
        with self.assertRaises(ConflictError):
            self._onboard(self.james, email="mary@edify.test")
        self.mary.refresh_from_db()
        self.assertEqual(self.mary.roles, [EdifyRole.CCEO.value])

    def test_an_existing_leader_is_found_not_duplicated(self):
        first = self._onboard(self.james)
        again = self._onboard(self.james, email="GRACE@school.test")
        self.assertTrue(again["existing"])
        self.assertEqual(again["user"]["id"], first["user"]["id"])
        self.assertEqual(User.objects.filter(email="grace@school.test").count(), 1)

    def test_the_form_is_checked(self):
        for bad in ({"name": ""}, {"email": ""}, {"email": "not-an-email"}):
            with self.assertRaises(BadRequest):
                self._onboard(self.james, **bad)

    def test_the_endpoint_answers_as_the_signed_in_person(self):
        self.client.force_authenticate(self.james)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/clusters/{self.chegere_north.id}/leaders",
                {"name": "Peter Okello", "email": "peter@school.test"},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(User.objects.get(email="peter@school.test").roles, [LEADER])
        self.client.force_authenticate(self.mary)
        response = self.client.post(
            f"/api/clusters/{self.chegere_north.id}/leaders",
            {"name": "Someone", "email": "someone@school.test"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
