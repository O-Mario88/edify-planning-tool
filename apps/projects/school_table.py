"""The project table: its columns, and the workbook they are exported as.

Owner, 2026-10-05:

  "on project table here are the columns (Project name, School ID, School
  Name, District, Training, Purpose of assignment, SSA intervention ("General"
  for Alumni), Previous SSA Score, Current SSA Score, SSA Improvement (Current
  SSA score - Previous SSA Score), Status, Activity date, Enrolled on,
  Planning Stage (Awaiting {Partner Name}), Planned By (Partner Name),
  Execution, Activity Status (Scheduled, Completed, Canceled, rescheduled),
  Activity Cost (Only fetch if scheduled). The IA, project coordinator or CD
  needs to export either all projects in 1 file or select a project to
  export"

One row an enrolled school, as ``apps.projects.monitoring`` builds it for the
reader — the page and the workbook read the same rows, so a file cannot say
something the screen it was taken from did not. This module only names the
columns and spells each cell; it computes nothing.

The words in the owner's brackets are what a cell shows: General for a project
no SSA intervention measures, "Awaiting {Partner Name}" while a Partner holds
the work undated, the Partner's name under Planned By once the Partner has
scheduled it, and one of four words under Activity Status. An activity is
priced when it is scheduled, so Activity Cost is empty until then.
"""

from __future__ import annotations

__all__ = [
    "AWAITING_SCHEDULING",
    "CHANGE_FORMAT",
    "COLUMNS",
    "DATE_FORMAT",
    "FIELDS",
    "MONEY_FORMAT",
    "SCORE_FORMAT",
    "cells",
    "filename_stem",
    "sheets",
    "values",
]

#: The table's columns, in the owner's order: each one's key and its heading.
#: Project Monitoring and Planning Oversight's Special Projects tab draw these
#: headings and then their Actions; the workbook's first sheet is exactly
#: these; and the consolidated Project Schools table on Country Planning
#: Oversight draws them after where each school sits.
FIELDS = (
    ("project", "Project Name"),
    ("school_id", "School ID"),
    ("school", "School Name"),
    ("district", "District"),
    ("course", "Training"),
    ("purpose", "Purpose of Assignment"),
    ("intervention", "SSA Intervention"),
    ("previous_score", "Previous SSA Score"),
    ("current_score", "Current SSA Score"),
    ("improvement", "SSA Improvement"),
    ("status", "Status"),
    ("date", "Activity Date"),
    ("enrolled_on", "Enrolled On"),
    ("stage", "Planning Stage"),
    ("by_name", "Planned By"),
    ("execution", "Execution"),
    ("activity_status", "Activity Status"),
    ("cost", "Activity Cost (UGX)"),
)
COLUMNS = tuple(label for _key, label in FIELDS)

#: What the Activity Date says while a Partner holds the work undated.
AWAITING_SCHEDULING = "Awaiting scheduling"

DATE_FORMAT = "d mmm yyyy"
SCORE_FORMAT = "0.0#"
#: Green for a score that rose, red for one that fell, plain for no change
#: (owner, 2026-10-05), as the page colours it. Colour 10 is Excel's dark
#: green; its "[Green]" is too pale to read on white.
CHANGE_FORMAT = "[Color10]+0.0#;[Red]-0.0#;0.0#"
MONEY_FORMAT = "#,##0"
#: Number formats by key, for the cells that are not text.
_FORMATS = {
    "previous_score": SCORE_FORMAT,
    "current_score": SCORE_FORMAT,
    "improvement": CHANGE_FORMAT,
    "date": DATE_FORMAT,
    "enrolled_on": DATE_FORMAT,
    "cost": MONEY_FORMAT,
}


def values(row) -> dict:
    """One school's row, a value per key of ``FIELDS``.

    A cell with nothing to say is None, never a nought or a dash. The
    Activity Date is the day, or ``AWAITING_SCHEDULING`` while a Partner
    holds the work undated.
    """
    if row.activity_date:
        activity_date = row.activity_date
    else:
        activity_date = AWAITING_SCHEDULING if row.awaiting_date else None
    return {
        "project": row.project_name,
        "school_id": row.school_code or "",
        "school": row.school_name or "",
        "district": row.district or "",
        "course": row.training_name or "",
        "purpose": row.purpose_label or "",
        "intervention": row.intervention_label or "",
        "previous_score": row.previous_score,
        "current_score": row.current_score,
        "improvement": row.ssa_improvement,
        "status": row.status_label,
        "date": activity_date,
        "enrolled_on": row.enrolled_on,
        "stage": row.planning_stage,
        "by_name": row.planned_by_name,
        "execution": row.execution_summary,
        "activity_status": row.activity_state_label,
        "cost": row.activity_cost,
    }


def cells(row) -> list:
    """One school's row for the workbook, a cell per column of ``COLUMNS``."""
    said = values(row)
    return ["" if said[key] is None else said[key] for key, _label in FIELDS]


#: The second sheet: a line a project, as the export has carried it since
#: 2026-10-04.
_SUMMARY = (
    "Project ID",
    "Project Code",
    "Project Name",
    "Coordinator",
    "Status",
    "Partners",
    "Total Schools",
    "Schools Planned",
    "Schools Awaiting Partner",
    "Schools Delivered",
    "Trainings Scheduled",
    "Trainings Completed",
    "Visits Scheduled",
    "Visits Completed",
    "Other Scheduled",
    "Other Completed",
    "Staff Delivered",
    "Partner Delivered",
)


def _summary(project) -> list:
    return [
        project.id,
        project.code or "",
        project.name,
        project.coordinator,
        project.status_label,
        ", ".join(project.partners) if project.partners else "None",
        project.schools,
        project.schools_planned,
        project.schools_awaiting_partner,
        project.schools_delivered,
        project.trainings_scheduled,
        project.trainings_completed,
        project.visits_scheduled,
        project.visits_completed,
        project.other_scheduled,
        project.other_completed,
        project.staff_delivered,
        project.partner_delivered,
    ]


def sheets(projects) -> list[dict]:
    """The workbook for these projects: every school in one sheet, whichever
    project it is in, and a line a project on a second.

    ``projects`` are ``monitoring.ProjectMonitoringRow``s; their
    ``school_rows`` are the rows the reader's page shows, filters applied.
    """
    return [
        {
            "title": "Project Schools",
            "headers": list(COLUMNS),
            "rows": [cells(row) for project in projects for row in project.school_rows],
            "number_formats": {
                index: _FORMATS[key]
                for index, (key, _label) in enumerate(FIELDS, start=1)
                if key in _FORMATS
            },
        },
        {
            "title": "Project Summary",
            "headers": list(_SUMMARY),
            "rows": [_summary(project) for project in projects],
        },
    ]


def filename_stem(projects, fy: str, *, single: bool) -> str:
    """``project-<code>-schools-FY2027`` for one project, and
    ``special-projects-schools-FY2027`` for every project in one file."""
    if single and projects:
        project = projects[0]
        name = "".join(
            ch if ch.isalnum() or ch in "-_" else "-"
            for ch in (project.code or project.id).lower()
        )
        return f"project-{name}-schools-FY{fy}"
    return f"special-projects-schools-FY{fy}"
