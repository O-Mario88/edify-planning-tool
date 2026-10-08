"""What a partner's profile lists, its calendar, and who on its team delivers.

Owner, 2026-10-08: "The partner profile should show a comprensive details
(profile and basic info or Bio data, List of schools they have been assigned
for visits, list of trainings they are going to facilitate. the partner should
also be able to have a calendar of trainings and visits but their calendar
should show activities of the day and who is executing them from among the
onboarded partner team member."
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region
from apps.partners import delivery_team, profile_lists
from apps.partners.models import Partner, PartnerAssignment, PartnerMember
from apps.schools.models import School

User = get_user_model()


def _user(key: str, role: str, name: str):
    return User.objects.create(
        id=f"pp-{key}",
        email=f"pp-{key}@test.org",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )


class _Fixture(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.region = Region.objects.create(name="PP Region")
        self.district = District.objects.create(
            name="PP District", region=self.region, district_type="primary"
        )
        self.login = _user("partner", "PartnerAdmin", "Grace Nakato")
        self.partner = Partner.objects.create(
            id="pp-partner",
            name="Literacy Works",
            active_status=True,
            user=self.login,
            contact_person="Grace Nakato",
        )
        self.member = PartnerMember.objects.create(
            partner=self.partner, name="Peter Okello", role="staff", title="Trainer"
        )
        PartnerMember.objects.create(
            partner=self.partner, name="Gone Away", role="volunteer", active=False
        )
        self.cceo = _user("cceo", "CCEO", "Nick Officer")
        self.cceo_sp = StaffProfile.objects.create(
            id="pp-cceo-sp", user=self.cceo, title="CCEO"
        )
        self.admin = _user("admin", "Admin", "Ada Admin")
        self.schools = [self._school(code) for code in ("A", "B", "C", "D")]

    def _school(self, code: str):
        return School.objects.create(
            school_id=f"PP-{code}",
            name=f"PP School {code}",
            region=self.region,
            district=self.district,
        )

    def _when(self, days: int):
        day = self.today + datetime.timedelta(days=days)
        return timezone.make_aware(datetime.datetime(day.year, day.month, day.day, 9))

    def _activity(self, school, days: int, **fields):
        fields.setdefault("activity_type", "school_visit")
        fields.setdefault("delivery_type", "partner")
        fields.setdefault("assigned_partner_id", self.partner.id)
        fields.setdefault("status", "partner_scheduled")
        fields.setdefault("monitored_by_staff_id", self.cceo_sp.id)
        when = self._when(days)
        return Activity.objects.create(
            school=school,
            fy="2027",
            scheduled_date=when,
            planned_date=when.date(),
            **fields,
        )

    def _handover(self, school, *, activity=None, **fields):
        fields.setdefault("purpose_of_visit", "training_follow_up")
        fields.setdefault("expected_activity_type", "school_visit")
        return PartnerAssignment.objects.create(
            partner=self.partner,
            school=school,
            monitoring_staff_id=self.cceo_sp.id,
            assigning_staff_id=self.cceo_sp.id,
            status="partner_scheduled" if activity else "pending_scheduling",
            scheduled_activity=activity,
            **fields,
        )


class ProfileListsTest(_Fixture):
    def test_schools_assigned_for_visits_from_handover_to_delivery(self):
        waiting = self.schools[0]
        coming = self.schools[1]
        done = self.schools[2]
        taken_back = self.schools[3]
        self._handover(waiting)
        self._handover(
            coming,
            activity=self._activity(coming, 5, delivery_contact_name="Peter Okello"),
        )
        self._handover(
            done,
            activity=self._activity(
                done, -9, status="ia_verified", delivery_contact_name="Grace Nakato"
            ),
        )
        self._handover(taken_back).__class__.objects.filter(school=taken_back).update(
            status="returned_to_staff"
        )

        rows = profile_lists.visit_schools(self.partner)

        self.assertEqual(
            [(r["school"].name, r["status"], r["visited_by"]) for r in rows],
            [
                ("PP School A", "Waiting for a date", ""),
                ("PP School B", "Scheduled", "Peter Okello"),
                ("PP School C", "Completed", "Grace Nakato"),
            ],
        )
        self.assertEqual(rows[0]["visit"], "Training Follow Up")
        self.assertEqual(rows[0]["officer"], "Nick Officer")
        self.assertEqual(rows[0]["district"], "PP District")
        self.assertIsNone(rows[0]["date"])
        self.assertEqual(rows[1]["date"], self.today + datetime.timedelta(days=5))
        self.assertEqual(rows[2]["tone"], "success")

    def test_a_visit_called_off_is_not_an_assigned_school(self):
        school = self.schools[0]
        self._handover(school, activity=self._activity(school, 4, status="cancelled"))
        self.assertEqual(profile_lists.visit_schools(self.partner), [])

    def test_trainings_it_delivers_and_trainings_it_facilitates(self):
        school = self.schools[0]
        self._handover(
            school,
            purpose_of_visit="in_school_training",
            expected_activity_type="in_school_training",
            activity=self._activity(
                school,
                6,
                activity_type="in_school_training",
                delivery_contact_name="Peter Okello",
            ),
        )
        # An officer's group training with this organisation as facilitator.
        facilitated = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            responsible_staff_id=self.cceo_sp.id,
            facilitating_partner_id=self.partner.id,
            status="scheduled",
            fy="2027",
            scheduled_date=self._when(2),
            planned_date=self._when(2).date(),
            activity_name_snapshot="Literacy Champions",
        )
        # Another organisation's is not listed.
        Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            facilitating_partner_id="someone-else",
            status="scheduled",
            fy="2027",
            scheduled_date=self._when(3),
        )

        rows = profile_lists.trainings(self.partner)

        self.assertEqual(
            [(r["kind"], r["status"], r["facilitator"]) for r in rows],
            [
                ("Group training", "Scheduled", ""),
                ("In-school training", "Scheduled", "Peter Okello"),
            ],
        )
        self.assertEqual(rows[0]["training"], "Literacy Champions")
        self.assertEqual(rows[0]["officer"], "Nick Officer")
        self.assertEqual(rows[0]["activity_id"], facilitated.id)
        self.assertEqual(rows[1]["place"], "PP School A")
        # A training is not also a school assigned for a visit.
        self.assertEqual(profile_lists.visit_schools(self.partner), [])


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class ProfilePageTest(_Fixture):
    def test_the_profile_carries_both_lists_and_the_organisations_details(self):
        school = self.schools[0]
        self._handover(school)
        self.partner.coverage_districts = ["PP District", "Gulu"]
        self.partner.contract_status = "active"
        self.partner.phone = "+256700000002"
        self.partner.save()
        self.client.force_login(self.admin)

        body = self.client.get(f"/partners/{self.partner.id}").content.decode()

        self.assertIn("Schools assigned for visits", body)
        self.assertIn("Trainings to facilitate", body)
        self.assertIn("PP School A", body)
        self.assertIn("Waiting for a date", body)
        self.assertIn("No trainings to facilitate.", body)
        self.assertIn("PP District, Gulu", body)
        self.assertIn("grace nakato".title(), body)

    def test_the_organisation_reads_its_own_profile(self):
        self._handover(self.schools[0])
        self.client.force_login(self.login)
        body = self.client.get(f"/partners/{self.partner.id}").content.decode()
        self.assertIn("Schools assigned for visits", body)
        self.assertIn("PP School A", body)


class DeliveryTeamTest(_Fixture):
    def test_the_team_is_the_active_roster_and_the_person_signed_in(self):
        self.assertEqual(
            delivery_team.team_names(self.partner, self.login),
            ["Peter Okello", "Grace Nakato"],
        )

    def test_a_team_member_is_named_and_the_change_is_on_the_record(self):
        visit = self._activity(self.schools[0], 3, delivery_contact_name="Grace Nakato")
        result = delivery_team.name_member(visit.id, "peter okello", self.login)
        visit.refresh_from_db()
        self.assertEqual(visit.delivery_contact_name, "Peter Okello")
        self.assertEqual(result["previous"], "Grace Nakato")
        row = AuditLog.objects.get(
            action="partner.delivery_member_named", subject_id=visit.id
        )
        self.assertEqual(row.payload["new"], "Peter Okello")

    def test_someone_off_the_team_is_refused(self):
        visit = self._activity(self.schools[0], 3)
        for name in ("Stranger Danger", "Gone Away", ""):
            with self.subTest(name=name), self.assertRaises(BadRequest):
                delivery_team.name_member(visit.id, name, self.login)
        visit.refresh_from_db()
        self.assertEqual(visit.delivery_contact_name, "")

    def test_a_facilitated_training_takes_a_team_member_too(self):
        training = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            responsible_staff_id=self.cceo_sp.id,
            facilitating_partner_id=self.partner.id,
            status="scheduled",
            fy="2027",
            scheduled_date=self._when(2),
        )
        delivery_team.name_member(training.id, "Peter Okello", self.login)
        training.refresh_from_db()
        self.assertEqual(training.delivery_contact_name, "Peter Okello")

    def test_finished_work_keeps_its_name(self):
        done = self._activity(
            self.schools[0],
            -3,
            status="ia_verified",
            delivery_contact_name="Grace Nakato",
        )
        with self.assertRaises(BadRequest):
            delivery_team.name_member(done.id, "Peter Okello", self.login)

    def test_another_organisations_work_and_staff_are_refused(self):
        other_login = _user("other", "PartnerAdmin", "Other Person")
        Partner.objects.create(id="pp-partner-2", name="Other Org", user=other_login)
        visit = self._activity(self.schools[0], 3)
        with self.assertRaises(Forbidden):
            delivery_team.name_member(visit.id, "Other Person", other_login)
        with self.assertRaises(Forbidden):
            delivery_team.name_member(visit.id, "Peter Okello", self.cceo)


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerCalendarTest(_Fixture):
    """The calendar a partner opens: its visits and the trainings it
    facilitates, each with the team member who delivers it, and today's on
    top."""

    def setUp(self):
        super().setUp()
        self.visit = self._activity(
            self.schools[0], 0, delivery_contact_name="Peter Okello"
        )
        self.unnamed = self._activity(self.schools[1], 0)
        self.training = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            responsible_staff_id=self.cceo_sp.id,
            facilitating_partner_id=self.partner.id,
            status="scheduled",
            fy="2027",
            scheduled_date=self._when(0),
            planned_date=self.today,
            activity_name_snapshot="Literacy Champions",
            delivery_contact_name="Grace Nakato",
        )
        self.client.force_login(self.login)

    def _calendar(self):
        return self.client.get(
            f"/calendar?year={self.today.year}&month={self.today.month}"
        )

    def test_it_shows_visits_and_the_trainings_it_facilitates(self):
        response = self._calendar()
        self.assertEqual(response.status_code, 200)
        shown = {a.id for a in response.context["activities"]}
        self.assertEqual(shown, {self.visit.id, self.unnamed.id, self.training.id})

    def test_each_entry_names_who_delivers_it(self):
        body = self._calendar().content.decode()
        self.assertIn("Peter Okello · PP School A", body)
        self.assertIn("Grace Nakato · Edify activity", body)
        self.assertIn("Nobody named yet · PP School B", body)

    def test_todays_work_is_listed_with_who_delivers_it(self):
        response = self._calendar()
        today = response.context["partner_today"]
        self.assertEqual(
            sorted((row["place"], row["who"]) for row in today["rows"]),
            [
                # The fixture's group training names no cluster.
                ("Edify activity", "Grace Nakato"),
                ("PP School A", "Peter Okello"),
                ("PP School B", ""),
            ],
        )
        body = response.content.decode()
        self.assertIn("Today", body)
        self.assertIn(
            f'hx-get="/partner/activities/{self.unnamed.id}/delivered-by"', body
        )

    def test_a_member_of_staff_s_calendar_is_as_it_was(self):
        self.client.force_login(self.cceo)
        response = self._calendar()
        self.assertNotIn("partner_today", response.context)
        self.assertNotIn("Nobody named yet", response.content.decode())

    def test_the_team_member_is_changed_from_the_drawer(self):
        drawer = self.client.get(
            f"/partner/activities/{self.unnamed.id}/delivered-by",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(drawer.status_code, 200)
        body = drawer.content.decode()
        self.assertIn('<option value="Peter Okello"', body)
        self.assertIn('<option value="Grace Nakato"', body)
        self.assertNotIn("Gone Away", body)

        saved = self.client.post(
            f"/partner/activities/{self.unnamed.id}/delivered-by",
            {"delivery_contact_name": "Peter Okello"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(saved.status_code, 200)
        self.unnamed.refresh_from_db()
        self.assertEqual(self.unnamed.delivery_contact_name, "Peter Okello")

        refused = self.client.post(
            f"/partner/activities/{self.unnamed.id}/delivered-by",
            {"delivery_contact_name": "Stranger Danger"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(refused.status_code, 400)

    def test_scheduling_offers_the_team_not_a_blank_box(self):
        handover = self._handover(self.schools[2])
        body = self.client.get(
            f"/partner/assignments/{handover.id}/schedule-drawer",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn('id="partner-delivery-contact"', body)
        self.assertIn('<option value="Peter Okello"', body)
        self.assertIn('<option value="Grace Nakato" selected', body)
        self.assertNotIn("Gone Away", body)
        self.assertNotIn('type="text" maxlength="255" required', body)

    def test_scheduling_refuses_a_name_that_is_not_on_the_team(self):
        handover = self._handover(self.schools[2])
        day = self.today + datetime.timedelta(days=9)
        response = self.client.post(
            f"/partner/assignments/{handover.id}/schedule-action",
            {
                "scheduled_date": day.isoformat(),
                "delivery_contact_name": "Stranger Danger",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not on your organisation", response.content.decode())
        handover.refresh_from_db()
        self.assertEqual(handover.status, "pending_scheduling")
