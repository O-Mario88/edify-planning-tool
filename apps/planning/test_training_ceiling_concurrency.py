"""Two people cannot both take the last place under a training ceiling.

``training_ceilings.reserve`` says it locks the ceiling row before it counts,
so a second save waits for the first and then counts the first one's schools.
That claim is run here against PostgreSQL with real threads on their own
connections, released together on a barrier: with one place left and two
sessions each adding a school, exactly one is saved, the other is refused
with the reason, and the plans never hold more schools than the ceiling.

TransactionTestCase, not TestCase: the threads have to see each other's
committed rows, which one shared outer transaction would hide — and hiding it
is how this kind of bug passes a test suite.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from django.db import connections

from apps.accounts.models import StaffProfile, User
from apps.activities.cluster_attendance import set_invited_schools
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.test_seed_utils import ReferenceDataTransactionTestCase
from apps.geography.models import District, Region
from apps.planning import training_ceilings
from apps.planning.models import TrainingCeiling
from apps.schools.models import School

FY = "2027"


def _race(calls):
    """Run each call on its own connection, all released at once."""
    barrier = threading.Barrier(len(calls))
    outcomes: list = [None] * len(calls)

    def worker(index: int):
        try:
            barrier.wait(timeout=30)
            outcomes[index] = ("saved", calls[index]())
        except Exception as exc:  # noqa: BLE001 — the refusal IS the result
            outcomes[index] = ("refused", exc)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        list(pool.map(worker, range(len(calls))))
    return outcomes


class TheLastPlaceIsTakenOnce(ReferenceDataTransactionTestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Ceiling Race Region")
        self.district = District.objects.create(
            name="Ceiling Race District", region=self.region
        )
        self.cluster = Cluster.objects.create(
            name="Ceiling Race Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )
        user = User.objects.create_user(
            email="ceiling-race@edify.org",
            name="Race Officer",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=user, country="Uganda")
        self.training = ActivityCatalogueItem.objects.get(
            stable_code="SCHOOL_LEADERSHIP"
        )
        self.schools = [
            School.objects.create(
                school_id=f"RACE-{index:02d}",
                name=f"Race School {index:02d}",
                region=self.region,
                district=self.district,
                school_type="client",
                cluster_id=self.cluster.id,
                cluster_status="clustered",
            )
            for index in range(24)
        ]
        TrainingCeiling.objects.create(
            staff=self.staff, training=self.training, fy=FY, ceiling=20
        )
        self.held = self.session()
        set_invited_schools(self.held, [s.id for s in self.schools[:19]])

    def session(self) -> Activity:
        return Activity.objects.create(
            activity_type="cluster_training",
            catalogue_item=self.training,
            cluster=self.cluster,
            responsible_staff_id=self.staff.id,
            delivery_type="staff",
            status="scheduled",
            fy=FY,
            quarter="Q1",
            teachers_per_school=2,
        )

    def scheduled(self) -> int:
        return training_ceilings.scheduled_count(self.staff, self.training.id, FY)[
            "total"
        ]

    def test_two_sessions_adding_the_last_school_at_once(self):
        first, second = self.session(), self.session()
        self.assertEqual(self.scheduled(), 19)

        outcomes = _race(
            [
                lambda: set_invited_schools(first, [self.schools[20].id]),
                lambda: set_invited_schools(second, [self.schools[21].id]),
            ]
        )

        self.assertEqual(sorted(kind for kind, _ in outcomes), ["refused", "saved"])
        refusal = next(result for kind, result in outcomes if kind == "refused")
        self.assertIsInstance(refusal, BadRequest)
        self.assertIn("Training ceiling reached", str(refusal.detail))
        self.assertEqual(self.scheduled(), 20)
        # The refused session attached no school at all.
        attached = [
            ClusterActivityAttendance.objects.filter(activity=a, invited=True).count()
            for a in (first, second)
        ]
        self.assertEqual(sorted(attached), [0, 1])

    def test_two_edits_of_two_sessions_cannot_share_the_remaining_two(self):
        """Two places left, and two sessions each asking for both."""
        ClusterActivityAttendance.objects.filter(
            activity=self.held, school=self.schools[18]
        ).delete()
        first, second = self.session(), self.session()
        self.assertEqual(self.scheduled(), 18)

        outcomes = _race(
            [
                lambda: set_invited_schools(first, [s.id for s in self.schools[19:21]]),
                lambda: set_invited_schools(
                    second, [s.id for s in self.schools[21:23]]
                ),
            ]
        )

        self.assertEqual(sorted(kind for kind, _ in outcomes), ["refused", "saved"])
        self.assertEqual(self.scheduled(), 20)

    def test_several_in_school_places_are_never_oversold(self):
        """Six saves for one remaining place, through the same reservation an
        in-school training makes."""
        from django.db import transaction

        def take(index):
            def call():
                with transaction.atomic():
                    training_ceilings.reserve_for_activity(
                        activity_type="in_school_training",
                        staff_id=self.staff.id,
                        course_id=self.training.id,
                        fy=FY,
                        school_id=self.schools[index].id,
                    )
                    return Activity.objects.create(
                        activity_type="in_school_training",
                        training_course=self.training,
                        school=self.schools[index],
                        responsible_staff_id=self.staff.id,
                        delivery_type="staff",
                        status="scheduled",
                        fy=FY,
                        quarter="Q1",
                    ).id

            return call

        outcomes = _race([take(index) for index in range(18, 24)])

        self.assertEqual([kind for kind, _ in outcomes].count("saved"), 1)
        self.assertEqual(self.scheduled(), 20)
