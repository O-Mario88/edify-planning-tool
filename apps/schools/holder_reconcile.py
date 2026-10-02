"""Make the portfolio say what the school record says about who holds a school.

``School.account_owner_id`` names the holder. ``StaffSchoolAssignment`` is the
same fact as the scoping chain reads it: a person's schools and, through the
reporting line, their Programme Lead's team schools. Four paths that named a
new holder (the school upload, the directory's match and bulk match, staff
setup) added the new holder's row and left the previous holder's, so a school
sat in two people's scope — and in two Programme Leads' — while every list
filed it under one. Those paths now replace the row
(`apps.schools.ownership_transfer.hold_schools`); this repairs what they left
behind (owner, 2026-10-02: "Repair the old school holder mismatches").

Every path that writes a portfolio row writes the holder with it, so the
school record is the newer statement wherever the two disagree. The repair
therefore only ever moves the portfolio toward the school record:

* a row naming anybody but the holder is removed;
* the holder's own row is added where it is missing.

A school with no holder, or a holder that resolves to no staff profile, is
left exactly as it is: there is nothing to reconcile it to.

The functions take the model classes, so the deploy migration
(schools 0023) passes the historical ones and
``manage.py reconcile_school_holders`` the live ones. Nothing here reads a
column added after schools 0022 / accounts 0035.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Rows per statement. Postgres takes far more; this keeps one statement's
#: parameter list short on a portfolio of any size.
BATCH = 1000


@dataclass
class HolderPlan:
    """What disagrees, and what making it agree would change."""

    schools_with_holder: int = 0
    #: Schools whose holder resolves to no staff profile: left alone.
    unresolved: int = 0
    #: (assignment row id, school pk, staff id named) to remove.
    stray: list[tuple[str, str, str]] = field(default_factory=list)
    #: (school pk, holder staff id) to add.
    missing: list[tuple[str, str]] = field(default_factory=list)
    #: school pk -> the holder's staff id, for every school the plan touches.
    holder_of: dict[str, str] = field(default_factory=dict)
    #: staff id -> name, and school pk -> (school ID, name), for the log.
    staff_names: dict[str, str] = field(default_factory=dict)
    school_labels: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def schools_changed(self) -> int:
        return len(self.holder_of)

    @property
    def schools_also_assigned_elsewhere(self) -> int:
        return len({school_id for _row, school_id, _staff in self.stray})

    def __bool__(self) -> bool:
        return bool(self.stray or self.missing)

    def lines(self) -> list[str]:
        """Every change, one line each: what a deploy log or a dry run prints
        so that a removed row can be put back by hand."""
        out = []
        for _row, school_id, staff_id in self.stray:
            code, name = self.school_labels.get(school_id, ("", school_id))
            out.append(
                f"removed: school {code or school_id} ({name}) from "
                f"{self.staff_names.get(staff_id, staff_id)} [{staff_id}]; "
                f"holder is {self._holder_label(school_id)}"
            )
        for school_id, staff_id in self.missing:
            code, name = self.school_labels.get(school_id, ("", school_id))
            out.append(
                f"added: school {code or school_id} ({name}) to its holder "
                f"{self.staff_names.get(staff_id, staff_id)} [{staff_id}]"
            )
        return out

    def _holder_label(self, school_id: str) -> str:
        holder = self.holder_of.get(school_id, "")
        return f"{self.staff_names.get(holder, holder)} [{holder}]"


def plan_holder_repair(School, StaffProfile, StaffSchoolAssignment) -> HolderPlan:
    """Read every held school and every portfolio row once and compare them."""
    plan = HolderPlan()
    owners: dict[str, str] = {}
    labels: dict[str, tuple[str, str]] = {}
    for pk, owner_id, code, name in (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(account_owner_id__isnull=True)
        .exclude(account_owner_id="")
        .values_list("id", "account_owner_id", "school_id", "name")
        .iterator(chunk_size=5000)
    ):
        owners[pk] = owner_id
        labels[pk] = (code or "", name or "")
    plan.schools_with_holder = len(owners)
    if not owners:
        return plan

    # A holder is stamped as a staff profile id or as the person's user id.
    canonical: dict[str, str] = {}
    names: dict[str, str] = {}
    for staff_id, user_id, name in StaffProfile.objects.values_list(
        "id", "user_id", "user__name"
    ):
        canonical[staff_id] = staff_id
        names[staff_id] = name or staff_id
        if user_id:
            canonical.setdefault(user_id, staff_id)

    assigned: dict[str, dict[str, str]] = {}
    for row_id, school_id, staff_id in StaffSchoolAssignment.objects.values_list(
        "id", "school_id", "staff_id"
    ).iterator(chunk_size=5000):
        if school_id in owners:
            assigned.setdefault(school_id, {})[staff_id] = row_id

    for school_id, owner_id in owners.items():
        holder = canonical.get(owner_id)
        if holder is None:
            plan.unresolved += 1
            continue
        rows = assigned.get(school_id, {})
        changed = False
        for staff_id, row_id in rows.items():
            if staff_id != holder:
                plan.stray.append((row_id, school_id, staff_id))
                changed = True
        if holder not in rows:
            plan.missing.append((school_id, holder))
            changed = True
        if changed:
            plan.holder_of[school_id] = holder
            plan.school_labels[school_id] = labels[school_id]
    named = {staff for _r, _s, staff in plan.stray} | set(plan.holder_of.values())
    plan.staff_names = {staff: names.get(staff, staff) for staff in named}
    return plan


def apply_holder_repair(plan: HolderPlan, StaffSchoolAssignment) -> None:
    """Carry the plan out: the caller owns the transaction."""
    row_ids = [row_id for row_id, _school, _staff in plan.stray]
    for start in range(0, len(row_ids), BATCH):
        StaffSchoolAssignment.objects.filter(
            id__in=row_ids[start : start + BATCH]
        ).delete()
    StaffSchoolAssignment.objects.bulk_create(
        [
            StaffSchoolAssignment(staff_id=staff_id, school_id=school_id)
            for school_id, staff_id in plan.missing
        ],
        batch_size=BATCH,
        ignore_conflicts=True,
    )
