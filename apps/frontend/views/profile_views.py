"""The pages of the profile engine (apps.analytics.profile_intelligence).

One helper builds what every profile page draws (`profile_context`), so a
District, a Sub-region, a Programme Lead's team, a staff member, a Partner, a
Cluster and the Country are the same sections over a different scope; and two
pages that are nothing but those sections live here: the Sub-region profile
and the Country profile.

Owner, 2026-10-09: "Work on all profiles in a sequential order ... Don't
forget country profile which includes all analysis."
"""

from __future__ import annotations

from urllib.parse import quote

from django.shortcuts import get_object_or_404, render

from apps.analytics import profile_intelligence as engine
from apps.analytics import profile_records
from apps.core.permissions import RolePermissionService, require_page_permission

#: Every section a profile can have, in the order of the tab strip.
SECTIONS = (
    ("overview", "Overview"),
    ("ssa", "SSA"),
    ("sub_regions", "Sub-regions"),
    ("districts", "Districts"),
    ("sub_counties", "Sub-counties"),
    ("staff", "Staff"),
    ("clusters", "Clusters"),
    ("schools", "Schools"),
    ("activities", "Activities"),
    ("projects", "Projects"),
    # A school's own two: its learners' numbers and results, and its stories.
    ("academic", "Academic"),
    ("stories", "Stories"),
)
_LABELS = dict(SECTIONS)

#: The sections of each kind of profile. A part a scope does not have is not
#: a tab: a district is not read by district, a person's own portfolio not by
#: staff.
SECTIONS_OF = {
    "country": (
        "overview",
        "ssa",
        "sub_regions",
        "districts",
        "staff",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "sub_region": (
        "overview",
        "ssa",
        "districts",
        "staff",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "district": (
        "overview",
        "ssa",
        "sub_counties",
        "staff",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "program_lead": (
        "overview",
        "ssa",
        "staff",
        "districts",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "staff": (
        "overview",
        "ssa",
        "districts",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "partner": (
        "overview",
        "ssa",
        "districts",
        "clusters",
        "schools",
        "activities",
        "projects",
    ),
    "cluster": ("overview", "schools", "activities", "projects"),
    # School 360 (the brief, 2026-10-10): the same sections over one school.
    "school": ("overview", "ssa", "activities", "academic", "stories", "projects"),
}

#: Where a row of a part opens.
_PART_URL = {
    "sub_regions": "/sub-regions/",
    "districts": "/districts/",
    "staff": "/staff/",
}
#: What a Programme Lead's team tab is called.
_TEAM_LABEL = "Team"


def fy_choices() -> list[dict]:
    """The running year and the two before it."""
    from apps.core.fy import get_operational_fy
    from apps.ssa.year_comparison import fy_label

    running = int(str(get_operational_fy()))
    return [
        {"value": str(year), "label": fy_label(year)}
        for year in range(running, running - 3, -1)
    ]


def profile_context(
    request,
    scope: engine.Scope,
    base_url: str,
    *,
    param: str = "tab",
    lead: tuple = (),
    trail: tuple = (),
    activities=None,
    activities_param: str = "profile_acts",
    activities_caption: str = "",
    keep: dict | None = None,
    labels: dict | None = None,
    keys: dict | None = None,
    subject=None,
) -> dict:
    """Everything the shared profile sections draw for ``scope``.

    ``param`` is the query parameter that names the open section; ``lead``
    are the page's own tabs drawn before the engine's (``(key, label)``), the
    first of them the one a page opens on, and ``trail`` those drawn after
    them; ``activities`` is the queryset of
    the Activities tab's list (already narrowed to what the reader may see);
    ``keep`` are query values every link of the profile carries (a page with
    its own tab parameter); ``labels`` renames a section for this page, and
    ``keys`` gives a section another key in the address where the page
    already has a tab of that name (a cluster's own "overview");
    ``subject`` is the record the profile is about (the school, the cluster,
    the district), for the header's facts.

    A figure opens its records with ``what=`` (`profile_records.RECORDS`):
    the page then draws those tables under the tab the figure lives on.
    """
    options = fy_choices()
    fy = request.GET.get("fy", "")
    if fy not in {option["value"] for option in options}:
        # The running year is the lens a profile opens on (the brief,
        # point 29); an earlier one is a choice.
        fy = options[0]["value"]
    # The part of the year the work is read for (the brief, point 30).
    period = request.GET.get("period", "")
    if period not in dict(engine.period_options()):
        period = engine.PERIOD_YEAR
    names = {**_LABELS, **(labels or {})}
    if scope.kind == "program_lead":
        names["staff"] = (labels or {}).get("staff", _TEAM_LABEL)
    keys = keys or {}
    sections = [(keys.get(key, key), names[key]) for key in SECTIONS_OF[scope.kind]]
    section_of = {keys.get(key, key): key for key in SECTIONS_OF[scope.kind]}
    tabs = [*lead, *sections, *trail]
    tab = request.GET.get(param, "")
    if tab not in dict(tabs):
        tab = tabs[0][0]
    section = section_of.get(tab, "")
    # The records behind a figure (the brief, 2026-10-10: "Summary →
    # Breakdown → Actual Records"), drawn under the figure's own tab.
    what = request.GET.get("what", "")
    if what in profile_records.RECORDS:
        home = profile_records.RECORDS[what][0]
        home = home if home in SECTIONS_OF[scope.kind] else "overview"
        tab, section = keys.get(home, home), "records"
    else:
        what = ""
    show = request.GET.get("show", "")
    if show not in engine.SHOW_LABELS:
        show = "all"

    context = {
        "scope": scope,
        "base_url": base_url,
        "param": param,
        "tabs": tabs,
        "tab": tab,
        # The engine's section the open tab is; blank on a tab of the page's.
        "section": section,
        "fy": fy,
        "fy_options": options,
        "show": show,
        "show_label": engine.SHOW_LABELS[show],
        "show_options": list(engine.SHOW_LABELS.items()),
        "keep": keep or {},
        "is_engine_tab": bool(section),
        # Where a figure about visits, trainings and meetings opens.
        "work_tab": keys.get("activities", "activities"),
        "names": names,
        # Every link of the profile starts here, so a page with its own
        # query (a tab of its own) keeps it.
        "href": base_url
        + "?"
        + "".join(
            f"{quote(str(k))}={quote(str(v))}&"
            for k, v in {
                **(keep or {}),
                **({"period": period} if period else {}),
            }.items()
        ),
        "period": period,
        "period_options": engine.period_options(),
        "what": what,
        # The sections this kind of profile has, for a figure that opens one.
        "has": dict.fromkeys(SECTIONS_OF[scope.kind], True),
        # What each section is called in this page's address.
        "at": {key: keys.get(key, key) for key in SECTIONS_OF[scope.kind]},
    }
    # Where a figure's records open: the address up to the figure's name.
    context["records"] = f"{context['href']}fy={fy}&what="
    if not context["is_engine_tab"]:
        # The page's own tab: the engine is not read at all.
        return context

    profile = engine.build(scope, fy, period)
    context["profile"] = profile
    may_open_staff = RolePermissionService.can_view_page(request.user, "staff")
    context["identity"] = profile_records.identity(
        profile, subject, may_open_staff=may_open_staff
    )
    if section == "records":
        context["record_tables"] = profile_records.records(
            profile, what, key=request.GET.get("key", ""), principal=request.user
        )
        context["record_title"] = profile_records.RECORDS[what][1]
        context["record_back"] = f"{context['href']}{param}={tab}&fy={fy}"
    elif section == "overview":
        # What the profile covers, level by level, each line opening the tab
        # that lists it (owner, 2026-10-09: "country should have summary of
        # all the sub-region, district, clusters, schools, and their
        # performance"), and what changed for learners.
        open_tabs = dict(tabs)
        context["summary"] = [
            {
                **line,
                "label": names.get(line["level"], line["label"])
                if line["level"] == "staff"
                else line["label"],
                "tab": keys.get(line["level"], line["level"])
                if keys.get(line["level"], line["level"]) in open_tabs
                else "",
            }
            for line in engine.summary(profile)
        ]
        context["students"] = engine.students(profile)
        # Teachers and school leaders trained, and — for a reader of the loan
        # register — loans and Business Transformation.
        context["people"] = engine.people(profile)
        context["finance"] = engine.finance(profile, request.user)
        context["stories"] = profile_records.stories(profile)
        context["online"] = profile_records.channels(profile)[-1]
        context["focus_work"] = profile_records.focus_work(profile)
        # How many of each geographic part the scope has.
        context["levels"] = {
            "sub_regions": len(
                {s["sub_region"] for s in profile["_schools"] if s["sub_region"]}
            ),
            "sub_counties": len(
                {s["sub_county_id"] for s in profile["_schools"] if s["sub_county_id"]}
            ),
        }
        context["partners"] = (
            profile_records._handover_queryset(profile)
            .values("partner_id")
            .distinct()
            .count()
        )
    elif section == "schools":
        # A sub-county's row opens its schools here.
        where = None
        sub_county = request.GET.get("sub_county", "")
        if sub_county:
            where = ("sub_county_id", sub_county)
            context["keep_filters"] = {"sub_county": sub_county}
        context["school_rows"] = engine.school_rows(profile, show, where=where)
        context["many_districts"] = profile["portfolio"]["districts"] > 1
    elif section in engine.GROUPS:
        tab = section
        context["group"] = engine.groups(profile, tab)
        context["group_label"] = names[tab]
        part = "team members" if names[tab] == _TEAM_LABEL else names[tab].lower()
        context["group_best_title"] = f"Best performing {part}"
        context["group_worst_title"] = f"{names[tab]} needing the most support"
        context["group_improving_title"] = f"Improving {part}"
        context["group_declining_title"] = f"Declining {part}"
        # A sub-county has no page of its own: its row opens its schools.
        context["group_url"] = _PART_URL.get(tab, "")
        context["may_open_group"] = tab != "staff" or may_open_staff
    elif section == "clusters":
        # Cluster Management's reads, for the clusters of this scope.
        context["cluster_totals"] = engine.cluster_management(profile)
        context["may_open_cluster_management"] = RolePermissionService.can_view_page(
            request.user, "cluster_management"
        )
    elif section == "ssa":
        from apps.ssa.services import get_ssa_progress_by_fy

        context["progress"] = get_ssa_progress_by_fy(scope.schools)
    elif section == "academic":
        # The learners' numbers and results, record by record.
        context["record_tables"] = [
            *profile_records.records(profile, "enrolment"),
            *profile_records.records(profile, "learning"),
        ]
        context["students"] = engine.students(profile)
    elif section == "stories":
        context["record_tables"] = profile_records.records(profile, "stories")
        context["stories"] = profile_records.stories(profile)
    elif section == "projects":
        context["may_open_projects"] = RolePermissionService.can_view_page(
            request.user, "project_monitoring"
        )
    elif section == "activities":
        context["execution_rows"] = [
            ("School visits", profile["execution"]["visits"], "visits"),
            ("Trainings", profile["execution"]["trainings"], "trainings"),
            ("Cluster meetings", profile["execution"]["meetings"], "meetings"),
        ]
        # Training by the way it is delivered — online a channel of its own —
        # and the year's cluster meetings.
        context["channels"] = profile_records.channels(profile)
        context["meetings"] = profile_records.meetings(profile)
        if activities is not None:
            from apps.activities import profile_activities as profile_acts

            context["activities"] = profile_acts.profile_activities(
                request, activities, param=activities_param, subject="auto"
            )
            context["activities_caption"] = activities_caption
    return context


# ── Pages that are a profile and nothing else ───────────────────────────────
@require_page_permission("planning")
def sub_region_profile_view(request, sub_region_id):
    """A sub-region: its districts, staff, clusters and schools."""
    from apps.geography.models import SubRegion

    sub_region = get_object_or_404(SubRegion, id=sub_region_id)
    scope = engine.sub_region_scope(sub_region)
    return render(
        request,
        "pages/profiles/profile.html",
        {
            "pi": profile_context(
                request, scope, f"/sub-regions/{sub_region.id}", subject=sub_region
            ),
            "profile_title": scope.name,
            "profile_lead": sub_region.region.name if sub_region.region_id else "",
            "back_href": "/country-profile?tab=sub_regions",
            "back_label": "Country profile",
        },
    )


@require_page_permission("country_planning_oversight")
def country_profile_view(request):
    """The country: every school, read by sub-region, district, staff and
    cluster — every analysis the other profiles hold, at the widest scope."""
    from apps.planning.training_ceilings import country_of

    country = country_of(request.user)
    scope = engine.country_scope(country)
    return render(
        request,
        "pages/profiles/profile.html",
        {
            "pi": profile_context(request, scope, "/country-profile"),
            "profile_title": f"{country or 'Country'} Profile",
            "profile_lead": "Edify Operations",
            "back_href": "",
            "back_label": "",
        },
    )
