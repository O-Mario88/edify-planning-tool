"""Impact Assessment's collection worklist, "Ask owner to collect" and the
grouped collection To-Dos (IA review, owner, 2026-09-13)."""

from __future__ import annotations

from datetime import date

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.analytics import ia_collection as C
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-collection-worklist",
    }
}


def _user(email, role, country="Uganda", name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return user


class CollectionFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.prev = str(int(cls.fy) - 1)
        cls.ug = Region.objects.create(name="CW Central", country="Uganda")
        cls.ke = Region.objects.create(name="CW Rift", country="Kenya")
        cls.d1 = District.objects.create(name="CW Wakiso", region=cls.ug)
        cls.d2 = District.objects.create(name="CW Mukono", region=cls.ug)
        cls.ke_d = District.objects.create(name="CW Nakuru", region=cls.ke)
        cls.ia = _user("cw-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value, name="Ida")
        cls.cd = _user("cw-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value, name="Dan")
        cls.cceo = _user("cw-cceo@t.org", EdifyRole.CCEO.value, name="Cara Owner")
        cls.cceo2 = _user("cw-cceo2@t.org", EdifyRole.CCEO.value, name="Carl Other")

    def _school(self, code, *, district=None, owner=None, **kw):
        district = district or self.d1
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=district.region,
            district=district,
            school_type=kw.pop("school_type", "client"),
            account_owner_id=owner.staff_profile.id if owner else None,
            **kw,
        )
        if owner:
            StaffSchoolAssignment.objects.create(
                staff_id=owner.staff_profile.id, school_id=school.id
            )
        return school

    def _ssa(self, school, status="confirmed", fy=None, collector="staff", day=1):
        fy = fy or self.fy
        return SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.make_aware(timezone.datetime(int(fy) - 1, 11, day)),
            fy=fy,
            quarter="Q1",
            average_score=6,
            collector_type=collector,
            verification_status=status,
            uploaded_by=self.cceo.id,
            collected_by_user_id=self.cceo.id,
        )

    def _collection_visit(self, school, **kw):
        return Activity.objects.create(
            activity_type="school_visit_ssa_collection",
            school=school,
            fy=self.fy,
            planned_date=date.today(),
            responsible_staff_id=self.cceo.staff_profile.id,
            ssa_collection_expected=True,
            **kw,
        )


@override_settings(CACHES=LOCMEM)
class WorklistStatesTest(CollectionFixture):
    def test_every_school_in_the_country_gets_one_state_and_closed_or_foreign_none(
        self,
    ):
        never = self._school("CW-NEVER", owner=self.cceo)
        follow = self._school("CW-FOLLOW", owner=self.cceo)
        self._ssa(follow, fy=self.prev)
        current = self._school("CW-CURRENT")
        self._ssa(current)
        pending = self._school("CW-PENDING")
        self._ssa(pending, status="pending")
        returned = self._school("CW-RETURNED")
        self._ssa(returned, fy=self.prev)
        self._ssa(returned, status="returned", day=5)
        partner = self._school("CW-PARTNER")
        self._ssa(partner, status="pending", collector="partner")
        scheduled = self._school("CW-SCHEDULED")
        self._collection_visit(scheduled, status="scheduled")
        closed_visit = self._school("CW-NOSCORES")
        self._collection_visit(
            closed_visit,
            status="awaiting_ia_verification",
            ssa_not_collected_reason="Closed",
        )
        self._school("CW-CLOSED", operational_status="permanently_closed")
        self._school("CW-KE", district=self.ke_d)

        data = C.collection_worklist(self.ia, {})
        by_code = {row["school_id"]: row["state"] for row in data["rows"]}
        self.assertEqual(
            by_code,
            {
                never.school_id: C.NEVER_ASSESSED,
                follow.school_id: C.FOLLOW_UP_DUE,
                pending.school_id: C.PENDING_VERIFICATION,
                returned.school_id: C.RETURNED,
                partner.school_id: C.PARTNER_PENDING,
                scheduled.school_id: C.COLLECTION_SCHEDULED,
                closed_visit.school_id: C.VISIT_WITHOUT_SCORES,
            },
        )
        self.assertEqual(data["counts"][C.UP_TO_DATE], 1)
        self.assertEqual(data["counts"]["needs_work"], 7)
        self.assertNotIn(current.school_id, by_code)
        # The first rows are the ones someone can fix today.
        self.assertEqual(data["rows"][0]["state"], C.RETURNED)

    def test_filters_reach_the_rows_and_empty_filters_offer_nothing(self):
        mine = self._school("CW-F1", owner=self.cceo)
        other = self._school("CW-F2", owner=self.cceo2, district=self.d2)
        data = C.collection_worklist(self.ia, {"owner": self.cceo.staff_profile.id})
        self.assertEqual([r["school_id"] for r in data["rows"]], [mine.school_id])
        data = C.collection_worklist(self.ia, {"district": str(self.d2.id)})
        self.assertEqual([r["school_id"] for r in data["rows"]], [other.school_id])
        data = C.collection_worklist(self.ia, {"state": C.UP_TO_DATE})
        self.assertEqual(data["rows"], [])
        # A value nobody can choose is dropped, not silently applied.
        data = C.collection_worklist(self.ia, {"district": "not-a-district"})
        self.assertEqual(data["filters"]["chosen"]["district"], "")
        self.assertEqual(data["filters"]["options"]["projects"], [])

    def test_row_actions_never_plan_into_a_portfolio(self):
        self._school("CW-ACT", owner=self.cceo)
        row = C.collection_worklist(self.ia, {})["rows"][0]
        labels = {a["label"]: a for a in row["actions"]}
        self.assertEqual(labels["Add SSA"]["href"], "/ssa/manual/?school_id=CW-ACT")
        self.assertEqual(labels["Ask owner to collect"]["method"], "post")
        self.assertTrue(
            labels["Request SSA visit"]["href"].startswith("/planning/schedule-modal?")
        )
        cd_row = C.collection_worklist(self.cd, {})["rows"][0]
        self.assertNotIn(
            "Ask owner to collect", {a["label"] for a in cd_row["actions"]}
        )

    def test_the_worklist_is_paged_in_the_database_at_a_constant_cost(self):
        for index in range(3):
            self._school(f"CW-Q{index}", owner=self.cceo)
        with CaptureQueriesContext(connection) as small:
            C.collection_worklist(self.ia, {})
        for index in range(3, 40):
            school = self._school(
                f"CW-Q{index}", owner=self.cceo if index % 2 else self.cceo2
            )
            if index % 3 == 0:
                self._ssa(school, fy=self.prev)
        with CaptureQueriesContext(connection) as large:
            data = C.collection_worklist(self.ia, {})
        self.assertEqual(len(large), len(small))
        self.assertEqual(len(data["rows"]), C.PAGE_SIZE)
        self.assertEqual(data["page"]["total"], 40)
        second = C.collection_worklist(self.ia, {C.PAGE_PARAM: "2"})
        self.assertEqual(len(second["rows"]), 15)

    def test_tiles_come_from_the_registry(self):
        self._school("CW-T1")
        data = C.collection_worklist(self.ia, {})
        tiles = C.collection_tiles(self.ia, data)
        self.assertEqual(len(tiles), 4)


@override_settings(CACHES=LOCMEM)
class AskOwnerToCollectTest(CollectionFixture):
    def test_ia_sends_the_owner_a_no_ssa_action_that_closes_itself(self):
        from apps.planning.action_models import TeamAction
        from apps.planning.action_service import condition_still_holds

        school = self._school("CW-ASK", owner=self.cceo)
        self.client.force_login(self.ia)
        response = self.client.post(f"/ia/collection/{school.id}/ask-owner")
        self.assertEqual(response.status_code, 302)
        action = TeamAction.objects.get(school_id=school.id)
        self.assertEqual(action.issue_type, "no_ssa")
        self.assertEqual(action.recipient_id, self.cceo.id)
        self.assertEqual(action.sender_id, self.ia.id)
        self.assertTrue(condition_still_holds(action))
        # Nothing was scheduled into the owner's portfolio.
        self.assertFalse(Activity.objects.filter(school=school).exists())

        # A second ask is refused with the reason, not duplicated.
        self.client.post(f"/ia/collection/{school.id}/ask-owner")
        self.assertEqual(TeamAction.objects.filter(school_id=school.id).count(), 1)

        self._ssa(school)
        self.assertFalse(condition_still_holds(action))

    def test_the_director_and_other_countries_are_refused(self):
        from apps.planning.action_models import TeamAction

        school = self._school("CW-ASK2", owner=self.cceo)
        ke_school = self._school("CW-ASK-KE", district=self.ke_d, owner=self.cceo2)
        self.client.force_login(self.cd)
        response = self.client.post(f"/ia/collection/{school.id}/ask-owner")
        self.assertNotEqual(response.status_code, 302)
        self.client.force_login(self.ia)
        self.assertEqual(
            self.client.post(f"/ia/collection/{ke_school.id}/ask-owner").status_code,
            404,
        )
        self.client.force_login(self.cceo)
        self.assertNotEqual(
            self.client.post(f"/ia/collection/{school.id}/ask-owner").status_code, 302
        )
        self.assertFalse(TeamAction.objects.exists())

    def test_a_school_with_a_confirmed_ssa_is_not_asked(self):
        from apps.planning.action_models import TeamAction

        school = self._school("CW-ASK3", owner=self.cceo)
        self._ssa(school)
        self.client.force_login(self.ia)
        self.client.post(f"/ia/collection/{school.id}/ask-owner")
        self.assertFalse(TeamAction.objects.exists())


@override_settings(CACHES=LOCMEM)
class CollectionTodosTest(CollectionFixture):
    def test_schools_are_grouped_per_owner_and_link_the_filtered_worklist(self):
        from apps.ssa.collection_todos import collection_todos

        for index in range(3):
            self._school(f"CW-G{index}", owner=self.cceo)
        self._school("CW-G9", owner=self.cceo2)
        self._school("CW-UNOWNED", district=self.d2)
        self._school("CW-G-KE", district=self.ke_d, owner=self.cceo)
        rows = collection_todos(self.ia, self.ia.active_role, timezone.localdate())
        titles = {row["id"]: row for row in rows}
        owner_row = titles[f"ssa-collect-owner-{self.cceo.staff_profile.id}"]
        self.assertTrue(owner_row["title"].startswith("3 schools"))
        self.assertIn("owner=", owner_row["action_url"])
        self.assertIn(f"ssa-collect-unowned-{self.d2.id}", titles)
        self.assertEqual(collection_todos(self.cceo, "CCEO", timezone.localdate()), [])

    def test_the_builder_cost_does_not_grow_with_schools_or_owners(self):
        from apps.ssa.collection_todos import collection_todos

        self._school("CW-B0", owner=self.cceo)
        with CaptureQueriesContext(connection) as small:
            collection_todos(self.ia, self.ia.active_role, timezone.localdate())
        extra = [_user(f"cw-o{i}@t.org", EdifyRole.CCEO.value) for i in range(4)]
        for index in range(1, 30):
            self._school(f"CW-B{index}", owner=extra[index % 4])
        with CaptureQueriesContext(connection) as large:
            collection_todos(self.ia, self.ia.active_role, timezone.localdate())
        self.assertEqual(len(large), len(small))
