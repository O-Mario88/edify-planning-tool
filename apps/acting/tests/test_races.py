"""Two requests at the same instant.

Real threads on their own connections, the way two request handlers run. One
seat and one month hold one acting leader however the requests interleave,
and a person in the acting capacity and the leader they act for each keep
their own scope while working at the same time.
"""

from __future__ import annotations

import threading
from unittest import mock

from django.db import connections
from django.test import TransactionTestCase

from apps.accounts.models import StaffSchoolAssignment, StaffSupervisorAssignment
from apps.acting import services
from apps.acting.models import ActingAssignment
from apps.core.scoping import resolve_user_scope
from apps.geography.models import District, Region
from apps.schools.models import School

from .fixtures import OCTOBER, OCTOBER_15, SEPTEMBER_15, fresh, person


def _clock(day):
    """Patched for every thread: ``mock.patch`` swaps the module attribute."""
    return (
        mock.patch("apps.acting.models.today", return_value=day),
        mock.patch("apps.acting.services.today", return_value=day),
    )


class RaceCase(TransactionTestCase):
    reset_sequences = False

    def setUp(self):
        region = Region.objects.create(name="Race Acting Region", country="Uganda")
        district = District.objects.create(name="Race Acting District", region=region)
        self.john, self.john_sp = person("rjohn", "Program Lead", "John Lead")
        self.peter, self.peter_sp = person("rpeter", "Program Lead", "Peter Lead")
        self.officers = []
        for key, lead in (
            ("rsarah", self.john_sp),
            ("rdavid", self.john_sp),
            ("ragnes", self.peter_sp),
        ):
            user, profile = person(key, "CCEO", f"{key} Officer")
            StaffSupervisorAssignment.objects.create(
                supervisor=lead, supervisee=profile
            )
            school = School.objects.create(
                school_id=f"RACT-{key}",
                name=f"{key} School",
                region=region,
                district=district,
                account_owner_id=profile.id,
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
            self.officers.append((user, profile, school))

    def _race(self, *calls):
        results = [None] * len(calls)
        barrier = threading.Barrier(len(calls))

        def runner(index, fn):
            try:
                barrier.wait(timeout=10)
                results[index] = (True, fn())
            except Exception as exc:  # noqa: BLE001
                results[index] = (False, exc)
            finally:
                for conn in connections.all():
                    conn.close()

        threads = [
            threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(calls)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        alive = [t.name for t in threads if t.is_alive()]
        if alive:
            raise AssertionError(f"race threads never finished: {alive}")
        return results


class AppointmentRaceTests(RaceCase):
    def test_two_appointments_for_one_seat_and_month_leave_one(self):
        (_, sarah_sp, _), (_, david_sp, _), _ = self.officers
        models_clock, services_clock = _clock(SEPTEMBER_15)
        with models_clock, services_clock:
            results = self._race(
                lambda: services.appoint(
                    fresh(self.john), appointee_staff_id=sarah_sp.id, month=OCTOBER
                ),
                lambda: services.appoint(
                    fresh(self.john), appointee_staff_id=david_sp.id, month=OCTOBER
                ),
            )
        won = [r for r in results if r[0]]
        lost = [r for r in results if not r[0]]
        self.assertEqual((len(won), len(lost)), (1, 1), results)
        self.assertEqual(type(lost[0][1]).__name__, "ConflictError")
        self.assertEqual(ActingAssignment.objects.standing().count(), 1)

    def test_the_same_appointment_sent_twice_is_made_once(self):
        (_, sarah_sp, _), _, _ = self.officers
        models_clock, services_clock = _clock(SEPTEMBER_15)
        call = lambda: services.appoint(  # noqa: E731
            fresh(self.john), appointee_staff_id=sarah_sp.id, month=OCTOBER
        )
        with models_clock, services_clock:
            results = self._race(call, call, call)
        self.assertEqual(sum(1 for ok, _ in results if ok), 1, results)
        self.assertEqual(ActingAssignment.objects.count(), 1)


class SimultaneousAccessTests(RaceCase):
    def test_everyone_keeps_their_own_scope_at_the_same_moment(self):
        (
            (sarah, sarah_sp, sarah_school),
            (david, david_sp, david_school),
            (agnes, agnes_sp, agnes_school),
        ) = self.officers
        models_clock, services_clock = _clock(SEPTEMBER_15)
        with models_clock, services_clock:
            services.appoint(
                fresh(self.john), appointee_staff_id=sarah_sp.id, month=OCTOBER
            )

        def scope_of(user):
            def read():
                loaded = fresh(user)
                services.attach(loaded)
                scope = resolve_user_scope(loaded)
                return (
                    loaded.active_role,
                    frozenset(scope.school_ids),
                    frozenset(scope.supervised_staff_ids),
                )

            return read

        models_clock, services_clock = _clock(OCTOBER_15)
        with models_clock, services_clock:
            for _ in range(3):
                results = self._race(
                    scope_of(self.john),
                    scope_of(sarah),
                    scope_of(david),
                    scope_of(self.peter),
                    scope_of(agnes),
                    scope_of(sarah),
                )
                self.assertTrue(all(ok for ok, _ in results), results)
                john, acting, officer, other_lead, other_officer, again = (
                    value for _, value in results
                )
                team = frozenset({sarah_school.id, david_school.id})
                self.assertEqual(
                    john, ("Program Lead", team, frozenset({sarah_sp.id, david_sp.id}))
                )
                self.assertEqual(
                    acting,
                    ("Program Lead", team, frozenset({david_sp.id, self.john_sp.id})),
                )
                self.assertEqual(acting, again)
                self.assertEqual(
                    officer, ("CCEO", frozenset({david_school.id}), frozenset())
                )
                self.assertEqual(
                    other_lead,
                    (
                        "Program Lead",
                        frozenset({agnes_school.id}),
                        frozenset({agnes_sp.id}),
                    ),
                )
                self.assertEqual(
                    other_officer, ("CCEO", frozenset({agnes_school.id}), frozenset())
                )

    def test_a_cancellation_lands_between_two_requests_not_inside_one(self):
        (sarah, sarah_sp, _), _, _ = self.officers
        models_clock, services_clock = _clock(SEPTEMBER_15)
        with models_clock, services_clock:
            appointment = services.appoint(
                fresh(self.john), appointee_staff_id=sarah_sp.id, month=OCTOBER
            )

        def role_now():
            loaded = fresh(sarah)
            services.attach(loaded)
            return loaded.active_role

        models_clock, services_clock = _clock(OCTOBER_15)
        with models_clock, services_clock:
            self.assertEqual(role_now(), "Program Lead")
            results = self._race(
                lambda: services.cancel(fresh(self.john), appointment.id).id,
                role_now,
                role_now,
            )
            self.assertTrue(results[0][0], results)
            for ok, role in results[1:]:
                self.assertTrue(ok)
                self.assertIn(role, ("Program Lead", "CCEO"))
            # Once the cancellation has committed, every request sees it.
            self.assertEqual(role_now(), "CCEO")
