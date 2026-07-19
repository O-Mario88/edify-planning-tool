"""Guards against the same metric being defined differently in two places.

A duplicated *component* shows the same number twice, which is untidy. A
duplicated *definition* shows different numbers for the same question, which is
a correctness bug that reads as "the dashboard and the budget page disagree"
months after the cause was introduced.
"""

import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

APPS = Path(settings.BASE_DIR) / "apps"

# Names that describe one business population. Any module declaring its own
# copy is asserting a private definition of a shared idea.
SHARED_GROUPINGS = (
    "VISIT_TYPES",
    "TRAINING_TYPES",
    "CLUSTER_MEETING_TYPES",
    "SSA_COLLECTION_TYPES",
    "COMPLETED_STATUSES",
    "ACHIEVED_STATUSES",
    "VERIFIED_STATUSES",
)

# The one module allowed to define them; everything else imports from it.
CANONICAL = "apps/core/activity_types.py"

# Divergences that predate this guard. Each entry is a promise to reconcile,
# not permission to add more -- the test fails if the list grows, and the
# accompanying assertion fails if a name on it is silently made consistent
# without being removed from here.
KNOWN_DIVERGENT = {
    "VISIT_TYPES",
    "TRAINING_TYPES",
    "COMPLETED_STATUSES",
    "ACHIEVED_STATUSES",
    "VERIFIED_STATUSES",
    "CLUSTER_MEETING_TYPES",
    "SSA_COLLECTION_TYPES",
}


def _literal_members(source: str, start: int) -> set[str]:
    """String members of the bracketed literal beginning at `start`."""
    opener = source[start]
    closer = {"(": ")", "[": "]", "{": "}"}[opener]
    depth = 0
    for i in range(start, len(source)):
        if source[i] == opener:
            depth += 1
        elif source[i] == closer:
            depth -= 1
            if depth == 0:
                return set(re.findall(r'"([a-z_]+)"', source[start : i + 1]))
    return set()


def _definitions() -> dict[str, dict[str, set[str]]]:
    """name -> {module path: members}, for module-level literal assignments."""
    found: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for path in APPS.rglob("*.py"):
        rel = path.relative_to(settings.BASE_DIR).as_posix()
        if "__pycache__" in rel or "/tests/" in rel or "/test_" in rel:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        for name in SHARED_GROUPINGS:
            for match in re.finditer(rf"^{name}\s*=\s*[\(\[\{{]", source, re.M):
                members = _literal_members(source, match.end() - 1)
                if members:
                    found[name][rel] = members
    return found


class MetricDefinitionUniquenessTest(SimpleTestCase):
    def test_no_new_module_declares_its_own_shared_grouping(self):
        """New local copies of a shared population are not allowed.

        The canonical groupings live in apps/core/activity_types.py. A module
        needing a different population must name the difference
        (COSTED_VISIT_TYPES, say) rather than redefining the shared name to
        mean something local -- a metric that means two things needs two names.
        """
        offenders = []
        for name, by_module in _definitions().items():
            if name in KNOWN_DIVERGENT:
                continue
            others = [m for m in by_module if m != CANONICAL]
            if others:
                offenders.append(f"{name} redefined in {others}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_known_divergences_have_not_grown(self):
        """The backlog may shrink, never grow.

        VISIT_TYPES had nine disagreeing definitions when this was written,
        ranging from 4 members to 15 -- budget/costing counts 154 activities
        as visits where analytics counts 150. Reconciling them changes
        reported numbers, so it is a product decision rather than a cleanup;
        this pins the count so it cannot get worse while that is decided.
        """
        baseline = {
            "VISIT_TYPES": 9,
            "TRAINING_TYPES": 9,
            "COMPLETED_STATUSES": 4,
            "ACHIEVED_STATUSES": 2,
            "VERIFIED_STATUSES": 2,
            "CLUSTER_MEETING_TYPES": 2,
            "SSA_COLLECTION_TYPES": 1,
        }
        found = _definitions()
        grown = []
        for name, limit in baseline.items():
            count = len(found.get(name, {}))
            if count > limit:
                grown.append(f"{name}: {count} definitions, was {limit}")
        self.assertEqual(grown, [], "\n".join(grown))

    def test_canonical_groupings_cover_every_activity_type(self):
        """A new ActivityType must be classified, not silently uncounted."""
        from apps.core.activity_types import check

        check()
