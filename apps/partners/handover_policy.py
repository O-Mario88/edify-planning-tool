"""Which school rules a project hand-over goes past.

Owner, 2026-10-05: "all projects schools added to a project can be assigned to
any partner". Five earlier rules still left project schools out of a hand-over:

* a Champion school is delivered by staff and never assigned to a partner
  (owner, 2026-09-21);
* a Core package's partner half is two visits and two trainings (owner,
  2026-09-30);
* a school already supported by two partners takes no third (kept by the
  owner on 2026-09-30);
* a partner is handed only the trainings it is recorded as delivering (audit
  follow-up, 2026-10-01);
* a partner outside the project's own list needs a reason (audit follow-up,
  2026-10-01).

Asked whether a project hand-over should go past them, the owner said "yes for
now". So each of those doors asks here first. Nothing changes for a hand-over
that names no project, a closed school still takes no new work, and the rules
have one switch to come back through.
"""

from __future__ import annotations

#: True puts the five rules above back on project hand-overs.
PROJECT_HANDOVERS_KEEP_SCHOOL_RULES = False


def past_school_rules(project=None, project_id=None) -> bool:
    """Whether a hand-over is a project's and goes past the rules above."""
    return not PROJECT_HANDOVERS_KEEP_SCHOOL_RULES and bool(project or project_id)
