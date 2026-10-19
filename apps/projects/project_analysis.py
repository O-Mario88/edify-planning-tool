"""Project Monitoring's Analysis: every project the reader watches, analysed.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... oversights (... project monitoring ...)". A
project's row is its profile's read (`profile_intelligence.project_scope`,
apps.analytics.oversight_analysis), narrowed to the enrolments the reader's
Monitoring lens shows (`monitoring._visible_assignments`): the whole project
for Impact Assessment, the Country Director, Admin and the coordinator, and
for a CCEO or a Programme Lead "only the schools they added" (owner,
2026-09-21). The projects are the ones Monitoring lists for the reader.
"""

from __future__ import annotations

from apps.analytics import oversight_analysis as analysis
from apps.analytics import profile_intelligence as engine

summarise = analysis.summarise


def project_rows(principal, *, fy, period: str = engine.PERIOD_YEAR) -> list[dict]:
    """One row per watched project holding a school in the reader's lens."""
    from apps.projects import monitoring

    whole = monitoring.sees_whole_project(
        principal
    ) or monitoring.controls_project_work(principal)

    def scope_of(project):
        scope = engine.project_scope(project)
        if whole:
            return scope
        return analysis.narrowed(
            scope,
            monitoring._visible_assignments(principal, [project.id]).values(
                "school_id"
            ),
            "The project schools you added",
        )

    return analysis.read(
        (
            (p.id, p.name, f"/projects/{p.id}?tab=overview", scope_of(p))
            for p in monitoring._projects_for(principal)
        ),
        fy=fy,
        period=period,
    )
