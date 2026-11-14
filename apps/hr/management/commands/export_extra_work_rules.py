"""Write the Extra Assigned Work page's rules for the Go gateway.

Go builds Extra Assigned Work (/extra-work, apps.frontend.views.
extra_work_views.extra_work_page and apps.hr.extra_work.performance_summary,
drawn by pages/hr/extra_work.html) from the vocabularies this command writes
to platform/backend/internal/extrawork/rules.json: who may open the page, the
workspace strip each role is shown above it and who may assign, each status's
label, the statuses that are still open, how many rows each section reads,
the lengths the template cuts text to, the count past which the summary says
it shows only some, the table's page parameter and page size and the query
keys the app's feed never passes to a page. A change to any of them must be
exported again; apps/hr/test_extra_work_rules_export.py fails until it is, so
the two can never drift.

The doors and the strip are not restated: each role's answer is computed here
by the gates the page itself asks, and the strip is the workspace template
rendered for that role and read by the feed's own reader. The section limits
are read from the view's own slices and the cut lengths from the template.

    python manage.py export_extra_work_rules
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import textwrap
from pathlib import Path

from django.core.management.base import BaseCommand
from django.template.loader import get_template

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/extrawork/rules.json")

PAGE_PATH = "/extra-work"

TEMPLATE = "pages/hr/extra_work.html"

#: The sections the view reads, in the order it slices them.
SECTIONS = ("mine", "assigned_by_me", "to_review", "monitoring")


def roles() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.hr import extra_work

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("extra_work") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "extra_work")
            and bool(can_open_url(user, PAGE_PATH)),
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html"),
            "can_assign": role.value in extra_work.ASSIGNER_ROLES,
        }
    return out


def section_limits() -> dict:
    """The upper bound of each section's slice in extra_work_page, in order."""
    from apps.frontend.views import extra_work_views

    source = textwrap.dedent(
        inspect.getsource(inspect.unwrap(extra_work_views.extra_work_page))
    )
    bounds = [
        node.slice.upper.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Slice)
        and isinstance(node.slice.upper, ast.Constant)
    ]
    if len(bounds) != len(SECTIONS):
        raise ValueError(f"extra_work_page slices {len(bounds)} sections, not 4")
    return dict(zip(SECTIONS, bounds))


def template_numbers() -> dict:
    """The lengths the template cuts text to, in the order it writes them
    (instruction, return reason, outcome, evidence note), the count past
    which the summary says it shows only some, and the table's page
    parameter."""
    source = Path(get_template(TEMPLATE).origin.name).read_text(encoding="utf-8")
    cuts = [int(n) for n in re.findall(r"truncatechars:(\d+)", source)]
    if len(cuts) != 4:
        raise ValueError(f"{TEMPLATE} cuts {len(cuts)} texts, not 4")
    shown = re.search(r"mine\|length > (\d+)", source)
    param = re.search(r'\{% paginate mine "(\w+)"', source)
    if shown is None or param is None:
        raise ValueError(f"{TEMPLATE} no longer says how many it shows")
    return {
        "cuts": dict(
            zip(("instruction", "return_reason", "outcome", "evidence"), cuts)
        ),
        "summary_shows": int(shown.group(1)),
        "page_param": param.group(1),
    }


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.hr.models import ExtraAssignment
    from apps.mobile_feed.views import NOT_PASSED

    numbers = template_numbers()
    return {
        "roles": roles(),
        "status_labels": dict(ExtraAssignment.STATUSES),
        "open_statuses": list(ExtraAssignment.OPEN_STATUSES),
        "limits": section_limits(),
        "cuts": numbers["cuts"],
        "summary_shows": numbers["summary_shows"],
        "page_param": numbers["page_param"],
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Extra Assigned Work page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
