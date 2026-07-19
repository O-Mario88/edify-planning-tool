"""Canonical district -> UBOS sub-region grouping.

The sub-region is a UBOS *statistical* grouping used in survey reporting
(UNHS/UDHS). It sits between region (adm1) and district (adm2) but is not an
administrative level, so it carries no boundary geometry and appears in no
common operational dataset -- it cannot be derived from the COD-AB files the
rest of the geography is built from. That is why it lives here as controlled
reference data rather than being imported.

Each sub-region nests wholly inside one region, so the lists below partition
the 135 UBOS districts exactly. check() enforces that; the migration and
the test suite both call it.
"""

# name -> (parent region, districts)
SUBREGIONS: dict[str, tuple[str, list[str]]] = {
    "West Nile": (
        "Northern",
        [
        "Adjumani", "Arua", "Koboko", "Madi Okollo", "Maracha", "Moyo",
        "Nebbi", "Obongi", "Pakwach", "Yumbe", "Zombo"
        ],
    ),
    "Acholi": (
        "Northern",
        [
        "Agago", "Amuru", "Gulu", "Kitgum", "Lamwo", "Nwoya", "Omoro",
        "Pader"
        ],
    ),
    "Lango": (
        "Northern",
        [
        "Alebtong", "Amolatar", "Apac", "Dokolo", "Kole", "Kwania",
        "Lira", "Otuke", "Oyam"
        ],
    ),
    "Karamoja": (
        "Northern",
        [
        "Abim", "Amudat", "Kaabong", "Karenga", "Kotido", "Moroto",
        "Nabilatuk", "Nakapiripirit", "Napak"
        ],
    ),
    "Teso": (
        "Eastern",
        [
        "Amuria", "Budaka", "Bukedea", "Butebo", "Kaberamaido", "Kalaki",
        "Kapelebyong", "Katakwi", "Kibuku", "Kumi", "Ngora", "Pallisa",
        "Serere", "Soroti"
        ],
    ),
    "Elgon": (
        "Eastern",
        [
        "Bududa", "Bukwo", "Bulambuli", "Kapchorwa", "Kween", "Manafwa",
        "Mbale", "Namisindwa", "Sironko"
        ],
    ),
    "East Central": (
        "Eastern",
        [
        "Bugiri", "Bugweri", "Busia", "Butaleja", "Buyende", "Iganga",
        "Jinja", "Kaliro", "Kamuli", "Luuka", "Mayuge", "Namayingo",
        "Namutumba", "Tororo"
        ],
    ),
    "Central": (
        "Central",
        [
        "Buikwe", "Bukomansimbi", "Butambala", "Buvuma", "Gomba",
        "Kalangala", "Kalungu", "Kampala", "Kassanda", "Kayunga",
        "Kiboga", "Kyankwanzi", "Kyotera", "Luwero", "Lwengo",
        "Lyantonde", "Masaka", "Mityana", "Mpigi", "Mubende", "Mukono",
        "Nakaseke", "Nakasongola", "Rakai", "Ssembabule", "Wakiso"
        ],
    ),
    "Western": (
        "Western",
        [
        "Buliisa", "Bundibugyo", "Bunyangabu", "Hoima", "Kabarole",
        "Kagadi", "Kakumiro", "Kamwenge", "Kasese", "Kibaale", "Kikuube",
        "Kiryandongo", "Kitagwenda", "Kyegegwa", "Kyenjojo", "Masindi",
        "Ntoroko"
        ],
    ),
    "South Western": (
        "Western",
        [
        "Buhweju", "Bushenyi", "Ibanda", "Isingiro", "Kabale", "Kanungu",
        "Kazo", "Kiruhura", "Kisoro", "Mbarara", "Mitooma", "Ntungamo",
        "Rubanda", "Rubirizi", "Rukiga", "Rukungiri", "Rwampara", "Sheema"
        ],
    ),
}


def district_to_subregion() -> dict[str, str]:
    """Flat lookup: district name -> sub-region name."""
    return {d: s for s, (_r, ds) in SUBREGIONS.items() for d in ds}


def check() -> None:
    """Raise if the grouping stops being a clean partition.

    Guards the property the whole thing rests on: no district in two
    sub-regions, and no sub-region straddling two regions.
    """
    seen: dict[str, str] = {}
    for name, (_region, districts) in SUBREGIONS.items():
        for d in districts:
            if d in seen:
                raise ValueError(
                    f"district {d!r} is in both {seen[d]!r} and {name!r}"
                )
            seen[d] = name
    if len(seen) != 135:
        raise ValueError(f"expected 135 districts, mapping has {len(seen)}")


def sync(apps=None) -> dict[str, int]:
    """Create the sub-regions and attach every district to one. Idempotent.

    Callable from a migration (pass the historical ``apps`` registry) or from
    the management command after a geography import. It is a no-op on a
    database whose geography has not been loaded yet -- migrations run before
    any bootstrap, so it must survive finding zero districts.

    Districts absent from the mapping are left with ``sub_region = NULL``
    rather than being guessed at: a name this does not recognise is either a
    new district that needs adding here deliberately, or test residue.
    """
    check()
    if apps is None:  # pragma: no cover - runtime path
        from django.apps import apps as django_apps

        apps = django_apps
    Region = apps.get_model("geography", "Region")
    SubRegion = apps.get_model("geography", "SubRegion")
    District = apps.get_model("geography", "District")

    from apps.core.geography import normalize_uganda_admin_name as norm

    regions = {norm(r.name): r for r in Region.objects.all()}
    stats = {"subregions": 0, "districts": 0, "unmatched": 0, "no_region": 0}
    if not regions:
        return stats

    sub_by_name: dict[str, object] = {}
    for name, (region_name, _districts) in SUBREGIONS.items():
        region = regions.get(norm(region_name))
        if region is None:
            # The parent region is missing, so this sub-region has nothing to
            # hang off. Skip rather than inventing a Region row.
            stats["no_region"] += 1
            continue
        sub, _created = SubRegion.objects.update_or_create(
            name=name,
            defaults={
                "region": region,
                "normalized_name": norm(name),
                "source": "UBOS_STATISTICAL",
                "confidence": "VERIFIED",
                "notes": "UBOS survey sub-region; partitions the parent region.",
            },
        )
        sub_by_name[name] = sub
        stats["subregions"] += 1

    lookup = {}
    for district_name, sub_name in district_to_subregion().items():
        if sub_name in sub_by_name:
            lookup[norm(district_name)] = sub_by_name[sub_name]

    for district in District.objects.all().only("id", "name", "sub_region"):
        sub = lookup.get(norm(district.name))
        if sub is None:
            stats["unmatched"] += 1
            continue
        if district.sub_region_id != sub.id:
            district.sub_region = sub
            district.save(update_fields=["sub_region"])
        stats["districts"] += 1
    return stats
