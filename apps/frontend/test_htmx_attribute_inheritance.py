"""htmx inherits attributes, and two of them break child requests silently.

Both bugs guarded here shipped, and both presented as "the feature does not
work" with nothing in the UI to explain why:

* `hx-target` — the cluster planner's cost-preview div inherited the planner
  form's target, `#drawer-container`. Its own load-triggered preview therefore
  replaced the drawer that contained it: the drawer flashed open, vanished, and
  pasted a cost preview onto the Clusters page, leaving no form to submit, so
  cluster meetings and group trainings could not be scheduled at all.

* `hx-disabled-elt` — a form declaring `find button[type=submit]` is correct
  for its own submit and fatal for a child. `find` searches inside the
  REQUESTING element, so an inheriting <select> resolves nothing and htmx
  dereferences null ("Cannot read properties of null (reading
  'htmx-internal-data')") BEFORE sending. Every live cost preview in the
  affected drawer was dead.

Neither is visible by reading the element on its own — that is the point of
testing it here rather than trusting review. A control that issues its own
request must state the inherited attributes that cannot resolve from it.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

# Attribute values that are resolved relative to the element making the
# request. Inherited by a descendant, each re-resolves from that descendant.
RELATIVE_PREFIXES = ("find", "closest", "next", "previous")

REQUEST_ATTRIBUTE = re.compile(r"hx-(get|post|put|patch|delete)=")
ELEMENT = re.compile(r"<(?!/)([a-zA-Z0-9-]+)\b((?:[^>\"]|\"[^\"]*\")*?)/?>")


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'{name}="([^"]*)"', attrs)
    return match.group(1) if match else None


def _offenders(attribute: str, only_relative: bool) -> list[str]:
    """Descendants that issue their own request under an ancestor declaring
    `attribute`, without restating it."""
    found: list[str] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(errors="replace")
        if attribute not in text:
            continue
        for opener in ELEMENT.finditer(text):
            tag, attrs = opener.group(1), opener.group(2)
            value = _attr(attrs, attribute)
            if value is None:
                continue
            if only_relative and not value.strip().startswith(RELATIVE_PREFIXES):
                continue
            closing = text.find(f"</{tag}>", opener.end())
            body = text[opener.end() : closing if closing != -1 else len(text)]
            for child in ELEMENT.finditer(body):
                child_attrs = child.group(2)
                if not REQUEST_ATTRIBUTE.search(child_attrs):
                    continue
                if f"{attribute}=" in child_attrs:
                    continue
                line = text[: opener.end() + child.start()].count("\n") + 1
                found.append(
                    f"{path.relative_to(TEMPLATES.parent)}:{line} "
                    f"<{child.group(1)}> inherits {attribute}=\"{value}\""
                )
    return found


class HtmxInheritedAttributeTests(SimpleTestCase):
    def test_no_child_request_inherits_an_unresolvable_disabled_elt(self):
        offenders = _offenders("hx-disabled-elt", only_relative=True)
        self.assertEqual(
            offenders,
            [],
            "These controls issue their own htmx request while inheriting an "
            "hx-disabled-elt that resolves relative to the requesting element, "
            "so htmx throws on null before sending. Add hx-disabled-elt=\"this\" "
            "to each:\n  " + "\n  ".join(offenders),
        )

    def test_no_child_request_inherits_a_form_hx_target(self):
        """A form posting to one target must not silently retarget the
        previews and pickers inside it."""
        offenders = _offenders("hx-target", only_relative=False)
        self.assertEqual(
            offenders,
            [],
            "These controls issue their own htmx request while inheriting an "
            "ancestor's hx-target, so their response is swapped somewhere they "
            "did not ask for. State hx-target on each:\n  "
            + "\n  ".join(offenders),
        )

    def test_the_cluster_planner_preview_targets_itself(self):
        """The specific regression: the drawer-eating cost preview."""
        planner = (
            TEMPLATES / "partials" / "clusters" / "cluster_action_planner_drawer.html"
        ).read_text()
        block = planner[planner.index('id="planner-cost-preview-container"') :][:400]
        self.assertIn(
            'hx-target="this"',
            block,
            "The cluster planner's cost preview must target itself; without it "
            "the response replaces #drawer-container and destroys the drawer.",
        )
