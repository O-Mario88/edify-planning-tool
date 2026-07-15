"""Safety net for TransactionTestCase classes against a Django/`--keepdb`
interaction gap: `TransactionTestCase._fixture_teardown()` truncates every
table at the end of each test, and `serialized_rollback=True` only restores
that migration-seeded data transiently, in `_fixture_setup()` — i.e. *before*
that test's own body runs. Nothing restores it after the final flush, so a
kept (`--keepdb`) database is left with the migration-seeded rows physically
gone once the process exits. The next `manage.py test --keepdb` invocation
then starts from that already-empty state, and stays empty indefinitely: the
migrations are already marked applied, so their RunPython seed steps never
re-run.

Any TransactionTestCase must call `reseed_migration_data()` from an
overridden `_post_teardown()` (after `super()._post_teardown()` performs the
flush) to leave the physical database in the same state it found it in.
"""

from __future__ import annotations

# Mirrors apps/targets/migrations/0003_seed_target_areas.py -- the official
# personal target areas. Duplicated (not imported) because migration modules
# are not meant to be imported as regular app code.
_TARGET_AREAS = [
    ("school_visits", "School Visits", 30, 1),
    ("cluster_meetings", "Cluster Meetings", 15, 2),
    ("cluster_trainings", "Cluster Trainings", 20, 3),
    ("ssa_completed", "SSA Completed", 25, 4),
    ("mscs", "MSCS", 10, 5),
]


def reseed_migration_data() -> None:
    """Idempotent: only creates rows that are missing. Safe to call after
    every TransactionTestCase flush, and a no-op on a database that was
    never flushed (rows already exist)."""
    _reseed_target_areas()
    _reseed_cost_catalogue()


def _reseed_target_areas() -> None:
    from apps.targets.models import TargetArea

    for key, label, weight, sort in _TARGET_AREAS:
        TargetArea.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "weight": weight,
                "sort_order": sort,
                "active": True,
            },
        )


def _reseed_cost_catalogue() -> None:
    # Mirrors apps/budget/migrations/0003_costcatalogue_costsetting_catalogue.py
    # _seed_active_catalogue -- skips entirely if any catalogue already
    # exists (matches the migration's own idempotency guard).
    from apps.budget.models import CostCatalogue, CostSetting

    if CostCatalogue.objects.exists():
        return

    from django.conf import settings

    fy = getattr(settings, "OPERATIONAL_FY", None)
    if not fy:
        try:
            from apps.core.fy import get_operational_fy

            fy = get_operational_fy()
        except Exception:  # noqa: BLE001
            fy = "2026"
    country = getattr(settings, "COUNTRY", "Uganda")
    catalogue = CostCatalogue.objects.create(
        country=country,
        fy=str(fy),
        version=1,
        is_active=True,
        label=f"{country} FY{fy} Country Cost Catalogue",
    )
    CostSetting.objects.filter(catalogue__isnull=True).update(catalogue=catalogue)
