"""The official personal target areas — reference data, not user data.

These five rows are not something anyone creates in the interface; the platform
does not work without them. Every personal target, the weighted Overall
Progress, and the targets HR writes when it approves an agreement all resolve
through `TargetArea.key`, so an empty table does not raise — it silently
produces no targets at all.

They were seeded once by a data migration, which is enough for a database that
is only ever migrated forward. It is not enough for one that gets flushed: a
`TransactionTestCase` truncates every table and migration-seeded rows do not
come back, so the reference data vanished for the rest of that database's life
and HR approval quietly wrote nothing. `ensure_target_areas` is idempotent and
runs on `post_migrate`, which Django also emits after a flush — so the rows are
restored the moment they are removed.
"""

from __future__ import annotations

# key, label, weight (% of Overall Progress), sort order.
# Weights must total 100 across active areas; `test_reference.py` pins that.
OFFICIAL_TARGET_AREAS: tuple[tuple[str, str, int, int], ...] = (
    ("school_visits", "School Visits", 30, 1),
    ("cluster_meetings", "Cluster Meetings", 15, 2),
    ("cluster_trainings", "Cluster Trainings", 20, 3),
    ("ssa_completed", "SSA Completed", 25, 4),
    ("mscs", "MSCS", 10, 5),
)


def ensure_target_areas(model=None) -> int:
    """Create any missing official area. Returns how many were created.

    Only ever creates: a label or weight edited by an administrator is their
    decision, and this must not walk it back on the next deploy. `model` is
    injectable so a migration can pass its historical model.
    """
    if model is None:
        from apps.targets.models import TargetArea as model

    created = 0
    for key, label, weight, sort_order in OFFICIAL_TARGET_AREAS:
        _, was_created = model.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "weight": weight,
                "sort_order": sort_order,
                "active": True,
            },
        )
        created += int(was_created)
    return created


def target_areas_are_complete() -> bool:
    """Read-only counterpart to ``ensure_target_areas``."""
    from apps.targets.models import TargetArea

    expected = {key for key, _label, _weight, _sort_order in OFFICIAL_TARGET_AREAS}
    present = set(
        TargetArea.objects.filter(key__in=expected).values_list("key", flat=True)
    )
    return present == expected
