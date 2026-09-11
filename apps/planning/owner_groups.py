"""Schools grouped by the people responsible for them: Program Lead, then CCEO.

Owner, 2026-09-11: "IA is supposed to have access to all the schools but
grouped by PL and CCEO." A country role reads the whole portfolio, and seven
hundred schools sorted by name is a directory, not a plan. Sorted by the lead
and the officer who hold them it becomes the same page the organisation is
built on — and the same order the target distribution runs in.

``School.account_owner_id`` is the canonical owner column and holds either a
StaffProfile id or, on some imported rows, that profile's user id (see the
planning service). Everything here resolves both, once, for a page.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Value, When

NO_LEAD = "No Program Lead"
UNASSIGNED = "Unassigned"


def owner_directory(owner_ids) -> dict[str, dict]:
    """owner id (either id space) → {profile_id, name, pl_name, sort_key}."""
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
    from django.db.models import Q

    ids = {str(i) for i in owner_ids if i}
    if not ids:
        return {}
    profiles = list(
        StaffProfile.objects.filter(Q(id__in=ids) | Q(user_id__in=ids))
        .filter(deleted_at__isnull=True)
        .select_related("user")
    )
    leads = {}
    for link in (
        StaffSupervisorAssignment.objects.filter(
            supervisee_id__in=[p.id for p in profiles],
            supervisor__deleted_at__isnull=True,
        )
        .select_related("supervisor__user")
        .order_by("supervisor__user__name")
    ):
        # A Program Lead is the lead we group under; any other supervisor is
        # a reporting line, not a portfolio.
        role = getattr(link.supervisor.user, "active_role", "")
        if role == "Program Lead" and link.supervisee_id not in leads:
            leads[link.supervisee_id] = link.supervisor.user.name
    out = {}
    for profile in profiles:
        name = (profile.user.name if profile.user_id else "") or profile.id
        pl_name = leads.get(profile.id, "")
        # A Program Lead who holds schools directly is their own group.
        if not pl_name and getattr(profile.user, "active_role", "") == "Program Lead":
            pl_name = name
        entry = {
            "profile_id": profile.id,
            "name": name,
            "pl_name": pl_name,
            "sort_key": (pl_name or "￿", name),
        }
        out[profile.id] = entry
        if profile.user_id:
            out[str(profile.user_id)] = entry
    return out


def group_label(entry: dict | None) -> str:
    if not entry:
        return UNASSIGNED
    return f"{entry['pl_name'] or NO_LEAD} · {entry['name']}"


def owner_order(queryset):
    """Annotate `_owner_rank` so the queryset sorts lead → officer → school."""
    owner_ids = list(
        queryset.exclude(account_owner_id__isnull=True)
        .exclude(account_owner_id="")
        .values_list("account_owner_id", flat=True)
        .distinct()
    )
    directory = owner_directory(owner_ids)
    ranked = sorted(
        {oid: directory.get(oid) for oid in owner_ids}.items(),
        key=lambda kv: (kv[1]["sort_key"] if kv[1] else ("￿", "￿")),
    )
    whens = [
        When(account_owner_id=oid, then=Value(rank)) for rank, (oid, _) in enumerate(ranked)
    ]
    annotated = queryset.annotate(
        _owner_rank=Case(*whens, default=Value(len(whens)), output_field=IntegerField())
        if whens
        else Value(0, output_field=IntegerField())
    )
    return annotated.order_by("_owner_rank", "name"), directory


def owner_filter_groups(schools_qs) -> list[dict]:
    """The Staff filter's options: one group per Program Lead, their officers
    inside it, then the owners with no lead — only people who hold schools."""
    owner_ids = list(
        schools_qs.exclude(account_owner_id__isnull=True)
        .exclude(account_owner_id="")
        .values_list("account_owner_id", flat=True)
        .distinct()
    )
    directory = owner_directory(owner_ids)
    seen, groups = set(), {}
    for entry in sorted(
        (e for e in directory.values()), key=lambda e: e["sort_key"]
    ):
        if entry["profile_id"] in seen:
            continue
        seen.add(entry["profile_id"])
        label = entry["pl_name"] or NO_LEAD
        groups.setdefault(label, []).append(
            {"id": entry["profile_id"], "name": entry["name"]}
        )
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == NO_LEAD, kv[0]))
    return [{"label": label, "owners": owners} for label, owners in ordered]


def owner_id_variants(staff_id: str) -> set[str]:
    """Both id spaces for one chosen owner, so a filter matches every row."""
    from apps.accounts.models import StaffProfile
    from django.db.models import Q

    variants = {str(staff_id)}
    for profile in StaffProfile.objects.filter(
        Q(id=staff_id) | Q(user_id=staff_id)
    ).values_list("id", "user_id"):
        variants.update(str(v) for v in profile if v)
    return variants
