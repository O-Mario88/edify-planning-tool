"""Staff register a school that turned up, and record that it attended.

2026-10-14. The Add School drawer already let the field chain in
(`Permission.SCHOOL_CREATE_SINGLE`: CCEO, Programme Lead, Country Director,
Impact Assessment, Admin) while the directory's button asked for the bulk
upload permission, so only Impact Assessment and the Admin ever saw it. From a
training's or a meeting's completion drawer the same form is drawn in place,
so what was already ticked survives, and the saved school joins the register
unticked. A school from outside the cluster attends as a visiting school and
never becomes a member by attending. Schools left unticked at completion go
back to unplanned (owner, same day).
"""

from __future__ import annotations

import datetime
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.audit.models import AuditLog
from apps.clusters.models import Cluster
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


def _person(uid, role, *, profile=True):
    user = User.objects.create(
        id=uid,
        email=f"{uid}@edify.test",
        name=uid.replace("-", " ").title(),
        roles=[role],
        active_role=role,
        is_active=True,
        status="active",
    )
    sp = (
        StaffProfile.objects.create(
            user=user, staff_number=uid.upper(), country="Uganda", title=role
        )
        if profile
        else None
    )
    return user, sp


class RegistrationFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Reg Region")
        cls.home = District.objects.create(name="Home District", region=cls.region)
        cls.next_door = District.objects.create(name="Next District", region=cls.region)
        cls.home_sub = SubCounty.objects.create(name="Home Sub", district=cls.home)

        cls.cceo, cls.cceo_sp = _person("reg-cceo", "CCEO")
        cls.other_cceo, cls.other_sp = _person("reg-other-cceo", "CCEO")
        cls.pl, cls.pl_sp = _person("reg-pl", "Program Lead")
        cls.ia, _ = _person("reg-ia", "ImpactAssessment")
        cls.pc, _ = _person("reg-pc", "ProjectCoordinator")
        cls.accountant, _ = _person("reg-accountant", "Accountant")

        cls.own_cluster = Cluster.objects.create(
            name="Own Home Cluster",
            region=cls.region,
            district=cls.home,
            responsible_staff_id=cls.cceo_sp.id,
            status="active",
        )
        cls.border_cluster = Cluster.objects.create(
            name="Own Border Cluster",
            region=cls.region,
            district=cls.next_door,
            responsible_staff_id=cls.cceo_sp.id,
            status="active",
        )
        cls.own_sub = SubCounty.objects.create(name="Own Sub", district=cls.home)
        cls.covering_cluster = Cluster.objects.create(
            name="Own Covering Cluster",
            region=cls.region,
            district=cls.home,
            sub_county=cls.own_sub,
            responsible_staff_id=cls.cceo_sp.id,
            status="active",
        )
        cls.others_cluster = Cluster.objects.create(
            name="Someone Else's Cluster",
            region=cls.region,
            district=cls.home,
            sub_county=cls.home_sub,
            responsible_staff_id=cls.other_sp.id,
            status="active",
        )

    def _payload(self, **overrides):
        payload = {
            "school_id": "REG-100",
            "name": "Brand New Learning Centre",
            "salesforce_account_id": "0011a00000RegAbc",
            "district_id": self.home.id,
            "sub_county_id": "",
            "account_owner_id": self.cceo_sp.id,
            "school_type": "client",
            "enrollment": "",
            "cluster_id": "",
        }
        payload.update(overrides)
        return payload

    def _post(self, user, **overrides):
        self.client.force_login(user)
        return self.client.post(
            reverse("frontend:school_onboard_drawer"), self._payload(**overrides)
        )


class WhoMayRegisterTest(RegistrationFixture):
    def test_ia_cceo_and_pl_register_a_school(self):
        for n, user in enumerate((self.ia, self.cceo, self.pl)):
            with self.subTest(role=user.active_role):
                response = self._post(
                    user,
                    school_id=f"REG-WHO-{n}",
                    name=(
                        "Alpha Hill Academy",
                        "Kibuye Mango Grove",
                        "Zebra Crossing Day",
                    )[n],
                    salesforce_account_id=f"0011A0000WHO{n}",
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(
                    School.objects.filter(school_id=f"REG-WHO-{n}").exists()
                )

    def test_roles_without_the_permission_cannot_create_by_posting(self):
        for user in (self.pc, self.accountant):
            with self.subTest(role=user.active_role):
                response = self._post(user)
                self.assertIn(response.status_code, (302, 403))
                self.assertFalse(School.objects.filter(school_id="REG-100").exists())

    def test_the_directory_button_follows_the_drawers_permission(self):
        for user, shown in ((self.cceo, True), (self.ia, True), (self.pc, False)):
            with self.subTest(role=user.active_role):
                self.client.force_login(user)
                page = self.client.get("/schools").content.decode()
                self.assertEqual('hx-get="/schools/create-drawer"' in page, shown)

    def test_creating_grants_no_edit_rights(self):
        # A CCEO may add a school but still not edit school details.
        from apps.core.permissions import has_permission
        from apps.core.rbac import Permission

        self.assertFalse(has_permission(self.cceo, Permission.SCHOOL_EDIT.value))
        self.assertFalse(has_permission(self.cceo, Permission.SCHOOL_UPLOAD.value))


class SalesforceIdAndDuplicatesTest(RegistrationFixture):
    def test_the_salesforce_id_is_stored_as_entered_normalised(self):
        self._post(self.cceo, salesforce_account_id="  0011a00000RegAbc ")
        school = School.objects.get(school_id="REG-100")
        self.assertEqual(school.salesforce_account_id, "0011A00000REGABC")

    def test_a_salesforce_id_already_used_is_refused_whatever_its_case(self):
        School.objects.create(
            school_id="OLD-1",
            name="Older School",
            region=self.region,
            district=self.next_door,
            salesforce_account_id="0011a00000regabc",
        )
        response = self._post(self.cceo)
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "already belongs to Older School", status_code=400
        )
        self.assertFalse(School.objects.filter(school_id="REG-100").exists())

    def test_a_collision_at_the_database_is_a_message_not_a_server_error(self):
        # A soft-deleted school still holds its Salesforce id at the unique
        # constraint; the live-only check above passes, the insert collides —
        # the shape two simultaneous registrations take.
        School.all_objects.create(
            school_id="GONE-1",
            name="Gone School",
            region=self.region,
            district=self.next_door,
            salesforce_account_id="0011A00000REGABC",
            deleted_at=timezone.now(),
        )
        response = self._post(self.cceo)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "already belongs to Gone School", status_code=400)
        self.assertFalse(School.objects.filter(school_id="REG-100").exists())

    def test_a_similar_name_in_the_district_is_shown_before_anything_is_saved(self):
        School.objects.create(
            school_id="NEAR-1",
            name="Brand New Learning Centre",
            region=self.region,
            district=self.home,
        )
        response = self._post(self.cceo, name="Brand New Learning Center")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "data-possible-duplicate", status_code=400)
        self.assertContains(response, "NEAR-1", status_code=400)
        self.assertFalse(School.objects.filter(school_id="REG-100").exists())

        confirmed = self._post(
            self.cceo, name="Brand New Learning Center", confirm_distinct="1"
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(School.objects.filter(school_id="REG-100").exists())

    def test_a_refusal_lands_in_the_form_so_nothing_typed_is_lost(self):
        self.client.force_login(self.cceo)
        drawer = self.client.get(
            reverse("frontend:school_onboard_drawer")
        ).content.decode()
        self.assertIn('hx-target="#onboard-school-errors"', drawer)
        self.assertNotIn('hx-target="#drawer-container"', drawer)

    def test_registration_is_audited(self):
        self._post(self.cceo)
        school = School.objects.get(school_id="REG-100")
        entry = AuditLog.objects.get(action="school.registered", subject_id=school.id)
        self.assertEqual(entry.actor_id, self.cceo.id)
        self.assertEqual(entry.payload["salesforce_account_id"], "0011A00000REGABC")


class ClusterChoiceTest(RegistrationFixture):
    def test_a_school_joins_its_owners_cluster_in_its_own_district(self):
        self._post(self.cceo, cluster_id=self.own_cluster.id)
        school = School.objects.get(school_id="REG-100")
        self.assertEqual(school.cluster_id, self.own_cluster.id)

    def test_a_school_may_join_a_cluster_across_the_district_line(self):
        self._post(self.cceo, cluster_id=self.border_cluster.id)
        school = School.objects.get(school_id="REG-100")
        self.assertEqual(school.cluster_id, self.border_cluster.id)
        # Its own district is where it is; the cluster does not move it.
        self.assertEqual(school.district_id, self.home.id)

    def test_a_school_can_be_left_unassigned_and_no_cluster_is_made(self):
        clusters_before = Cluster.objects.count()
        self._post(self.cceo, cluster_id="")
        school = School.objects.get(school_id="REG-100")
        self.assertIsNone(school.cluster_id)
        self.assertEqual(Cluster.objects.count(), clusters_before)

    def test_another_officers_cluster_is_refused_and_nothing_is_saved(self):
        response = self._post(self.cceo, cluster_id=self.others_cluster.id)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(School.objects.filter(school_id="REG-100").exists())

    def test_the_sub_county_does_not_silently_join_another_officers_cluster(self):
        # Someone else's cluster covers this sub-county; School.save would
        # derive it. Left unassigned on the form, the school stays unassigned.
        self._post(self.cceo, sub_county_id=self.home_sub.id, cluster_id="")
        school = School.objects.get(school_id="REG-100")
        self.assertIsNone(school.cluster_id)

    def test_the_options_follow_the_owner_across_districts(self):
        self.client.force_login(self.cceo)
        body = self.client.get(
            "/schools/cluster-options",
            {"account_owner_id": self.cceo_sp.id, "district_id": self.home.id},
        ).content.decode()
        self.assertIn("No cluster", body)
        self.assertIn("Own Home Cluster", body)
        self.assertIn("Own Border Cluster", body)
        self.assertIn("another district", body)
        self.assertNotIn("Someone Else", body)

    def _session_options(self, **extra):
        self.client.force_login(self.cceo)
        params = {
            "account_owner_id": self.cceo_sp.id,
            "district_id": self.home.id,
            "first_cluster_id": self.border_cluster.id,
        }
        params.update(extra)
        return self.client.get("/schools/cluster-options", params).content.decode()

    def _line(self, body, name):
        return next(line for line in body.splitlines() if name in line)

    def test_the_sessions_cluster_is_listed_first_and_chosen_by_default(self):
        # Owner, 2026-10-14: "it should by default select the cluster where
        # the training was scheduled".
        body = self._session_options()
        self.assertLess(
            body.index("Own Border Cluster"), body.index("Own Home Cluster")
        )
        self.assertIn("this session", body)
        self.assertIn("selected", self._line(body, "Own Border Cluster"))

    def test_the_sessions_cluster_stays_chosen_when_the_sub_county_changes(self):
        body = self._session_options(
            sub_county_id=self.own_sub.id, cluster_id=self.border_cluster.id
        )
        self.assertIn("selected", self._line(body, "Own Border Cluster"))
        self.assertNotIn("selected", self._line(body, "Own Covering Cluster"))

    def test_an_explicit_no_cluster_survives_a_refresh(self):
        body = self._session_options(
            sub_county_id=self.own_sub.id, cluster_id="", cluster_touched="1"
        )
        self.assertNotIn(" selected", body)

    def test_the_drawer_opened_from_a_session_chooses_its_cluster(self):
        activity = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            cluster=self.border_cluster,
            responsible_staff_id=self.cceo_sp.id,
        )
        self.client.force_login(self.cceo)
        panel = self.client.get(
            "/schools/create-drawer", {"embed": "1", "activity_id": activity.id}
        ).content.decode()
        self.assertIn("selected", self._line(panel, "Own Border Cluster"))


class SubCountyBringsItsClusterTest(RegistrationFixture):
    """Owner, 2026-10-14: the district and sub-county bring the cluster the
    sub-county is attached to, so the school is attached from the drawer."""

    def _options(self, user, **params):
        self.client.force_login(user)
        return self.client.get("/schools/cluster-options", params).content.decode()

    def _option(self, body, name):
        line = next(line for line in body.splitlines() if name in line)
        return line

    def test_the_sub_countys_cluster_comes_first_and_is_chosen(self):
        body = self._options(
            self.cceo,
            account_owner_id=self.cceo_sp.id,
            district_id=self.home.id,
            sub_county_id=self.own_sub.id,
        )
        option = self._option(body, "Own Covering Cluster")
        self.assertIn("selected", option)
        self.assertIn("covers the sub-county", option)
        self.assertIn(self.cceo.name, option)
        self.assertLess(
            body.index("Own Covering Cluster"), body.index("Own Home Cluster")
        )

    def test_saving_with_it_chosen_attaches_the_school(self):
        self._post(
            self.cceo,
            sub_county_id=self.own_sub.id,
            cluster_id=self.covering_cluster.id,
        )
        school = School.objects.get(school_id="REG-100")
        self.assertEqual(school.cluster_id, self.covering_cluster.id)
        self.assertEqual(school.sub_county_id, self.own_sub.id)

    def test_another_officers_cluster_is_named_but_cannot_be_chosen(self):
        body = self._options(
            self.cceo,
            account_owner_id=self.cceo_sp.id,
            district_id=self.home.id,
            sub_county_id=self.home_sub.id,
        )
        option = self._option(body, "Someone Else")
        self.assertIn("disabled", option)
        self.assertNotIn("selected", option)
        self.assertIn(self.other_cceo.name, option)

    def test_with_its_officer_as_owner_it_is_chosen(self):
        self.client.force_login(self.ia)
        body = self._options(
            self.ia,
            account_owner_id=self.other_sp.id,
            district_id=self.home.id,
            sub_county_id=self.home_sub.id,
        )
        option = self._option(body, "Someone Else")
        self.assertIn("selected", option)
        self.assertNotIn("disabled", option)

    def test_before_a_staff_name_is_chosen_the_cluster_still_comes(self):
        body = self._options(
            self.ia, district_id=self.home.id, sub_county_id=self.own_sub.id
        )
        self.assertIn("selected", self._option(body, "Own Covering Cluster"))


class CompletionFixture(RegistrationFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.members = [
            School.objects.create(
                school_id=f"MEM-{n}",
                name=f"Member School {n}",
                region=cls.region,
                district=cls.home,
                cluster_id=cls.own_cluster.id,
                account_owner_id=cls.cceo_sp.id,
            )
            for n in (1, 2, 3)
        ]
        for school in cls.members:
            StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)
        cls.visitor = School.objects.create(
            school_id="VIS-1",
            name="Visiting School",
            region=cls.region,
            district=cls.next_door,
            cluster_id=cls.others_cluster.id,
        )

    def _session(self, activity_type="cluster_training", ref="TS-REG-0001"):
        from apps.activities.cluster_attendance import set_invited_schools

        when = timezone.now() + datetime.timedelta(days=3)
        activity = Activity.objects.create(
            activity_type=activity_type,
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            cluster=self.own_cluster,
            responsible_staff_id=self.cceo_sp.id,
            scheduled_date=when,
            planned_date=when.date(),
            salesforce_activity_id=ref,
            teachers_per_school=2,
            leaders_per_school=1,
        )
        set_invited_schools(activity, [s.id for s in self.members])
        return activity

    def _complete(self, activity, attended, *, visiting=None):
        from apps.activities.services import complete, start_completion

        start_completion(activity.id, {}, self.cceo)
        data = {
            "salesforceId": activity.salesforce_activity_id,
            "teachersAttended": 9,
            "leadersAttended": 3,
            "attendedSchoolIds": [s.id for s in attended],
        }
        if visiting is not None:
            data["visitingSchoolIds"] = [s.id for s in visiting]
        complete(activity.id, data, self.cceo)
        activity.refresh_from_db()
        return activity

    def _row(self, activity, school):
        return ClusterActivityAttendance.objects.filter(
            activity=activity, school=school
        ).first()


class RegisterFromTheCompletionDrawerTest(CompletionFixture):
    def test_the_drawer_offers_add_school_and_draws_the_form_in_place(self):
        activity = self._session()
        self.client.force_login(self.cceo)
        drawer = self.client.get(
            f"/my-plan/{activity.id}/complete-drawer"
        ).content.decode()
        self.assertIn("+ Add School", drawer)
        self.assertIn(f"/my-plan/{activity.id}/register-school-search", drawer)
        self.assertIn(
            f"/schools/create-drawer?embed=1&amp;activity_id={activity.id}", drawer
        )
        # The registration form opens inside this drawer, never in its place.
        self.assertNotIn('hx-target="#drawer-container"', drawer)
        self.assertIn('name="visiting_register"', drawer)

        panel = self.client.get(
            "/schools/create-drawer", {"embed": "1", "activity_id": activity.id}
        ).content.decode()
        self.assertIn('name="embed" value="1"', panel)
        self.assertIn(f'name="activity_id" value="{activity.id}"', panel)
        self.assertIn("Back to the activity", panel)
        self.assertNotIn("drawer-surface", panel)

    def test_a_school_registered_from_a_session_is_handed_back_not_joined(self):
        activity = self._session()
        self.client.force_login(self.cceo)
        response = self.client.post(
            reverse("frontend:school_onboard_drawer"),
            self._payload(embed="1", activity_id=activity.id),
        )
        self.assertEqual(response.status_code, 200)
        event = json.loads(response["HX-Trigger"])["edify-school-registered"]
        school = School.objects.get(school_id="REG-100")
        self.assertEqual(event["id"], school.id)
        self.assertEqual(event["clusterId"], "")
        # Attending this cluster's session does not make it a member.
        self.assertIsNone(school.cluster_id)
        # Nor does registering record attendance.
        self.assertFalse(
            ClusterActivityAttendance.objects.filter(school=school).exists()
        )
        entry = AuditLog.objects.get(action="school.registered", subject_id=school.id)
        self.assertEqual(entry.payload["activity_id"], activity.id)

    def test_search_finds_existing_schools_for_the_person_delivering_only(self):
        activity = self._session()
        self.client.force_login(self.cceo)
        body = self.client.get(
            f"/my-plan/{activity.id}/register-school-search", {"q": "Visiting"}
        ).content.decode()
        self.assertIn("VIS-1", body)
        self.assertIn("Someone Else", body)

        self.client.force_login(self.other_cceo)
        refused = self.client.get(
            f"/my-plan/{activity.id}/register-school-search", {"q": "Visiting"}
        )
        self.assertEqual(refused.status_code, 403)

    def test_a_member_added_after_the_invitations_opens_unticked(self):
        activity = self._session()
        late = School.objects.create(
            school_id="MEM-LATE",
            name="Late Member",
            region=self.region,
            district=self.home,
            cluster_id=self.own_cluster.id,
        )
        self.client.force_login(self.cceo)
        response = self.client.get(f"/my-plan/{activity.id}/complete-drawer")
        ticked = {s["id"]: s["ticked"] for s in response.context["cluster_schools"]}
        self.assertTrue(ticked[self.members[0].id])
        self.assertFalse(ticked[late.id])


class VisitingSchoolsAtCompletionTest(CompletionFixture):
    def test_a_visiting_school_is_recorded_without_becoming_a_member(self):
        activity = self._session()
        self._complete(
            activity, [self.members[0], self.visitor], visiting=[self.visitor]
        )
        row = self._row(activity, self.visitor)
        self.assertTrue(row.attended and row.is_guest and not row.invited)
        self.visitor.refresh_from_db()
        self.assertEqual(self.visitor.cluster_id, self.others_cluster.id)
        from apps.activities.cluster_attendance import trained_school_ids

        # Submitted is not verified: no training is credited yet.
        self.assertEqual(trained_school_ids([self.visitor.id], fy="2026"), set())
        Activity.objects.filter(id=activity.id).update(status="ia_verified")
        self.assertEqual(
            trained_school_ids([self.visitor.id], fy="2026"), {self.visitor.id}
        )

    def test_a_visiting_school_left_unticked_is_not_recorded(self):
        activity = self._session()
        self._complete(activity, [self.members[0]], visiting=[self.visitor])
        self.assertIsNone(self._row(activity, self.visitor))

    def test_a_form_without_the_visiting_list_leaves_recorded_guests_alone(self):
        # Completion used to reset every guest to "did not attend": a guest is
        # not a member, so it was never among the confirmed ids.
        from apps.activities.cluster_attendance import add_guest_school

        activity = self._session()
        add_guest_school(activity, self.visitor.id, teachers=4)
        self._complete(activity, [self.members[0]])
        self.assertTrue(self._row(activity, self.visitor).attended)

    def test_unticking_a_recorded_guest_records_that_it_did_not_attend(self):
        from apps.activities.cluster_attendance import add_guest_school

        activity = self._session()
        add_guest_school(activity, self.visitor.id)
        self._complete(activity, [self.members[0]], visiting=[self.visitor])
        self.assertFalse(self._row(activity, self.visitor).attended)

    def test_an_unknown_school_on_the_visiting_list_is_refused(self):
        from apps.activities.services import complete, start_completion
        from apps.core.exceptions import BadRequest

        activity = self._session()
        start_completion(activity.id, {}, self.cceo)
        with self.assertRaises(BadRequest):
            complete(
                activity.id,
                {
                    "salesforceId": activity.salesforce_activity_id,
                    "attendedSchoolIds": ["no-such-school"],
                    "visitingSchoolIds": ["no-such-school"],
                },
                self.cceo,
            )

    def test_one_school_attends_two_sessions_as_two_rows_never_twice_in_one(self):
        first = self._session(ref="TS-REG-0001")
        second = self._session(activity_type="cluster_meeting", ref="TS-REG-0002")
        self._complete(first, [self.visitor, self.visitor], visiting=[self.visitor])
        self._complete(second, [self.visitor], visiting=[self.visitor, self.visitor])
        self.assertEqual(
            ClusterActivityAttendance.objects.filter(school=self.visitor).count(), 2
        )
        self.assertEqual(School.objects.filter(school_id="VIS-1").count(), 1)

    def test_the_reviewer_sees_the_visiting_school(self):
        activity = self._session()
        self._complete(
            activity, [self.members[0], self.visitor], visiting=[self.visitor]
        )
        self.client.force_login(self.ia)
        page = self.client.get(
            reverse("frontend:ia_review_workspace", args=[activity.id])
        )
        self.assertContains(page, "visiting, not invited")


class UntickedSchoolsGoBackToUnplannedTest(CompletionFixture):
    """Owner, 2026-10-14: schools unticked at a training's or a meeting's
    completion go back to unplanned and untrained."""

    def test_an_invited_school_left_unticked_loses_its_invitation(self):
        activity = self._session()
        absent = self.members[2]
        self._complete(activity, self.members[:2])

        self.assertIsNone(self._row(activity, absent))
        self.assertTrue(self._row(activity, self.members[0]).attended)
        from apps.activities.cluster_attendance import trained_school_ids
        from apps.planning.training_ceilings import schools_of

        self.assertNotIn(absent.id, schools_of(activity))
        self.assertNotIn(absent.id, trained_school_ids([absent.id], fy="2026"))
        entry = AuditLog.objects.get(
            action="activity.absent_schools_released", subject_id=str(activity.id)
        )
        self.assertEqual(entry.payload["schoolIds"], [absent.id])

    def test_the_planned_head_count_is_kept(self):
        activity = self._session()
        planned = activity.expected_participants
        activity = self._complete(activity, self.members[:1])
        self.assertEqual(activity.expected_participants, planned)

    def test_a_meeting_releases_the_same_way(self):
        activity = self._session(activity_type="cluster_meeting", ref="TS-REG-0003")
        self._complete(activity, self.members[:1])
        self.assertEqual(
            set(
                ClusterActivityAttendance.objects.filter(activity=activity).values_list(
                    "school_id", flat=True
                )
            ),
            {self.members[0].id},
        )

    def test_reopening_after_nobody_was_ticked_shows_nobody_ticked(self):
        activity = self._session()
        self._complete(activity, [])
        activity.status = "returned"
        activity.save(update_fields=["status", "updated_at"])
        self.client.force_login(self.cceo)
        response = self.client.get(f"/my-plan/{activity.id}/complete-drawer")
        self.assertFalse(any(s["ticked"] for s in response.context["cluster_schools"]))


class FollowUpListsEverySessionAttendedTest(CompletionFixture):
    """Owner, 2026-10-14: a follow-up visit's training field lists the
    sessions the school attended — submitted or verified, as a member or a
    visitor — within the visit's fiscal year (kept, at the owner's word)."""

    def _options(self, school, fy="2026"):
        from apps.activities.training_history import follow_up_options

        return {o["id"]: o["label"] for o in follow_up_options(school, fy=fy)}

    def test_a_submitted_session_is_offered_and_marked_awaiting_verification(self):
        session = self._complete(self._session(), self.members[:2])
        self.assertEqual(session.status, "submitted_to_pl")
        options = self._options(self.members[0])
        self.assertIn(session.id, options)
        self.assertIn("awaiting verification", options[session.id])

    def test_a_visiting_school_is_offered_the_session_it_attended(self):
        session = self._complete(
            self._session(), [self.members[0], self.visitor], visiting=[self.visitor]
        )
        self.assertIn(session.id, self._options(self.visitor))
        from apps.activities.training_history import follow_up_source_problem

        self.assertIsNone(follow_up_source_problem(session, self.visitor, "2026"))

    def test_a_school_left_unticked_is_not_offered_it(self):
        session = self._complete(self._session(), self.members[:1])
        self.assertNotIn(session.id, self._options(self.members[2]))

    def test_another_fiscal_years_session_is_not_offered(self):
        session = self._complete(self._session(), self.members[:1])
        self.assertNotIn(session.id, self._options(self.members[0], fy="2027"))

    def test_a_session_still_being_completed_is_not_offered(self):
        session = self._session()
        self.assertNotIn(session.id, self._options(self.members[0]))
