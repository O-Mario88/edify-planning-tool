"""A finished monitor row works each figure out once (2026-10-08).

Every figure on a Planning Monitor row is a property folded from the row's
schools. The country's page asked one row for its Core schools 2,500 times
and walked the schools every time: 2.2 million school reads to draw one
table. A row now remembers a figure once `planning_monitor` has finished
counting, and only then: the counting functions fill rows in place.
"""

from __future__ import annotations

from django.test import SimpleTestCase, TestCase

from apps.planning.planning_monitor import (
    LeadMonitor,
    OfficerMonitor,
    SchoolState,
    _settle,
)


def _school(n: int, school_type: str = "core", **facts) -> SchoolState:
    return SchoolState(
        id=f"s{n}",
        code=f"C{n}",
        name=f"School {n}",
        school_type=school_type,
        district="District",
        cluster_id="",
        cluster_name="",
        clustered=False,
        officer_id="o1",
        officer_name="Officer",
        lead_id="l1",
        lead_name="Lead",
        **facts,
    )


def _officer(*schools) -> OfficerMonitor:
    return OfficerMonitor(
        key="o1", name="Officer", lead_id="l1", lead_name="Lead", schools=list(schools)
    )


class RowBeingBuiltTest(SimpleTestCase):
    def test_a_row_still_being_counted_answers_from_its_schools(self):
        officer = _officer(_school(1))
        self.assertEqual(officer.core_schools, 1)
        officer.schools.append(_school(2))
        self.assertEqual(officer.core_schools, 2)
        officer.schools[0].staff_visits = 1
        self.assertEqual(officer.schools_with_visit, 1)


class FinishedRowTest(SimpleTestCase):
    def test_a_finished_row_reads_its_schools_once_for_a_figure(self):
        reads = []

        class Counted(SchoolState):
            @property
            def is_core(self):
                reads.append(self.id)
                return True

        officer = _officer(*(Counted(**_school(n).__dict__) for n in range(3)))
        _settle([officer])
        for _ in range(50):
            self.assertEqual(officer.core_schools, 3)
        self.assertEqual(len(reads), 3)

    def test_figures_built_on_other_figures_agree_with_an_unfinished_row(self):
        def build():
            return _officer(
                _school(1, staff_visits=2, group_training=True),
                _school(2, "client", partner_visits=1),
                _school(3, "client"),
            )

        fresh, settled = build(), build()
        _settle([settled])
        figures = [
            name
            for name, attr in vars(OfficerMonitor).items()
            if isinstance(attr, property)
        ]
        self.assertGreater(len(figures), 30)
        for name in figures:
            with self.subTest(figure=name):
                # Twice: the second read is the remembered one.
                self.assertEqual(getattr(settled, name), getattr(fresh, name))
                self.assertEqual(getattr(settled, name), getattr(fresh, name))

    def test_a_team_still_adds_its_people_up(self):
        one, two = _officer(_school(1), _school(2, "client")), _officer(_school(3))
        _settle([one, two])
        team = LeadMonitor(key="l1", name="Lead", officers=[one, two])
        self.assertEqual(team.core_schools, 2)
        self.assertEqual(team.school_count, 3)
        with self.assertRaises(AttributeError):
            team.not_a_figure

    def test_two_rows_do_not_share_what_they_remember(self):
        one, two = _officer(_school(1)), _officer(_school(2), _school(3))
        _settle([one, two])
        self.assertEqual((one.core_schools, two.core_schools), (1, 2))


class TheMonitorSettlesItsRowsTest(TestCase):
    def test_every_row_the_monitor_hands_back_is_finished(self):
        from apps.accounts.models import (
            StaffProfile,
            StaffSchoolAssignment,
            StaffSupervisorAssignment,
            User,
        )
        from apps.core.fy import get_operational_fy
        from apps.core.rbac import EdifyRole
        from apps.geography.models import District, Region
        from apps.planning.planning_monitor import planning_monitor
        from apps.schools.models import School

        def person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="pw12345678",
                is_active=True,
            )
            return user, StaffProfile.objects.create(
                user=user, title=role, country="Uganda"
            )

        region = Region.objects.create(name="Settle Region")
        district = District.objects.create(name="Settle District", region=region)
        ia, _ = person("ia@settle.test", "Ines", EdifyRole.IMPACT_ASSESSMENT.value)
        _, lead = person(
            "lead@settle.test", "Lena", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        _, officer = person("cceo@settle.test", "Otim", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisor=lead, supervisee=officer)
        for n in range(3):
            school = School.objects.create(
                name=f"Settle Primary {n}",
                school_id=f"SET-{n}",
                region_id=region.id,
                district_id=district.id,
                school_type="client",
                account_owner_id=officer.id,
            )
            StaffSchoolAssignment.objects.create(staff=officer, school_id=school.id)

        monitor = planning_monitor(ia, fy=get_operational_fy())

        rows = monitor["totals"].officers
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("_settled", row.__dict__, row.name)
        held = next(row for row in rows if row.key == officer.id)
        self.assertEqual(held.school_count, 3)
        self.assertEqual(monitor["totals"].school_count, 3)
