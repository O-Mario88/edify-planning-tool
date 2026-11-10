"""Tick-box lists in a drawer (sub-counties, member schools, invited schools):
the boxes that share one name read as one field of kind ``checklist``, whose
value is the ticked boxes' values joined by commas.

The web draws some lists itself and has its script draw others from the
drawer's own data — an Alpine ``x-for`` over a list in ``x-data``, often
filtered by another field ("the chosen district's sub-counties"). Both read
the same way: each box's value and words, which field picks the ones that
apply, and which are ticked.
"""

from __future__ import annotations

import json
import re

from apps.mobile_feed.page_blocks import SILENT, Node

#: ``x-for="subCounty in visibleSubCounties"`` / ``"(p, i) in pages"``.
FOR = re.compile(r"^\(?\s*(\w+)\s*(?:,\s*\w+\s*)?\)?\s+(?:in|of)\s+(.+)$", re.S)
#: ``subCounties`` or ``subCounties.filter(sc => …)``.
SOURCE = re.compile(
    r"^(?:this\.)?(\w+)(?:\.filter\(\s*\(?\s*(\w+)\s*\)?\s*=>\s*(.+)\))?$", re.S
)
#: ``String(sc.district_id) === String(this.selectedDistrictId)``.
COMPARE = re.compile(
    r"^(?:String\()?\s*(\w+)\.(\w+)\s*\)?\s*===?\s*(?:String\()?\s*(?:this\.)?(\w+)\s*\)?$"
)
#: ``subCounty.name``.
MEMBER = re.compile(r"^(\w+)\.(\w+)$")
#: ``\`Also in ${subCounty.covered_by}\``` : words around one of the item's keys.
PHRASE = re.compile(r"^`([^`$]*)\$\{\s*(\w+)\.(\w+)\s*\}([^`$]*)`$")
#: A live counter left empty once its number is taken out: "( selected)".
EMPTIED_COUNT = re.compile(r"\s*\([^()]*\)\s*$")
GETTER = r"get\s+{name}\s*\(\)\s*\{{\s*return\s+(.+?);?\s*\}}"


def is_box(node: Node) -> bool:
    """A tick box the form sends; a Select all box is the list's own."""
    return (
        node.tag == "input"
        and node.get("type").lower() == "checkbox"
        and bool(node.get("name"))
        and "data-select-all" not in node.attrs
    )


def _is_select_all(node: Node) -> bool:
    return node.tag == "input" and "data-select-all" in node.attrs


def _in_template(node: Node) -> Node | None:
    holder = node.parent
    while holder is not None:
        if holder.tag == "template" and holder.get("x-for"):
            return holder
        holder = holder.parent
    return None


def group_names(form: Node) -> set[str]:
    """The names a form sends as a list of ticked boxes."""
    counts: dict[str, int] = {}
    for box in form.find_all(is_box):
        name = box.get("name")
        counts[name] = counts.get(name, 0) + (2 if _in_template(box) else 1)
    return {name for name, count in counts.items() if count >= 2}


def read(node: Node, controls: list[Node], root: Node) -> dict | None:
    """``node`` as one checklist field when every field in it is a box of one
    name; None otherwise."""
    boxes = [control for control in controls if not _is_select_all(control)]
    if not boxes or not all(is_box(box) for box in boxes):
        return None
    if len({box.get("name") for box in boxes}) != 1:
        return None
    template = _in_template(boxes[0])
    if template is None and len(boxes) < 2:
        return None
    label, marked = _label(node)
    field = {
        "name": boxes[0].get("name"),
        "label": label,
        "kind": "checklist",
        "required": marked
        or node.get("aria-required") == "true"
        or any("required" in box.attrs for box in boxes),
        "help": _help(node),
        "error": "",
        "placeholder": "",
        "readOnly": False,
    }
    if template is None:
        ticked = [box.get("value") for box in boxes if "checked" in box.attrs]
        options = [_rendered_option(box, root) for box in boxes]
        return {**field, "options": options, "value": ",".join(ticked)}
    scripted = _scripted(template, boxes[0], root)
    return {**field, **scripted} if scripted is not None else None


def _label(node: Node) -> tuple[str, bool]:
    """The list's words, its live counter taken out, and whether they carry
    the required mark."""
    holder = node.find(lambda n: n.tag == "legend") or next(
        (
            child
            for child in node.children
            if isinstance(child, Node)
            and child.tag in ("label", "h3", "h4", "h5")
            and child.find(is_box) is None
        ),
        None,
    )
    if holder is None:
        return "", False
    parts: list[str] = []
    counted = _static_text(holder, parts)
    words = " ".join("".join(parts).split())
    if counted:
        words = EMPTIED_COUNT.sub("", words)
    return words, "*" in holder.text()


def _static_text(node: Node, parts: list[str]) -> bool:
    """Collect the words that do not change as boxes are ticked; True when a
    live counter (``x-text``) was left out."""
    counted = False
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.get("x-text") or child.find(lambda n: bool(n.get("x-text"))):
            counted = True
        elif not (
            child.tag in SILENT
            or child.has("sr-only")
            or child.get("aria-hidden") == "true"
        ):
            counted = _static_text(child, parts) or counted
    return counted


def _help(node: Node) -> str:
    """The list's own help line: a plain paragraph, not an error."""
    for line in node.find_all(lambda n: n.tag == "p"):
        if line.get("role") == "alert" or line.get("x-show") or line.find(is_box):
            continue
        if line.text():
            return line.text()
    return ""


def _rendered_option(box: Node, root: Node) -> dict:
    label = box.parent
    while label is not None and label.tag != "label":
        label = label.parent
    if label is None and box.get("id"):
        label = root.find(lambda n: n.tag == "label" and n.get("for") == box.get("id"))
    pieces = _pieces(label) if label is not None else []
    return {
        "value": box.get("value") or "on",
        "label": pieces[0] if pieces else "",
        "detail": " · ".join(pieces[1:]),
        "group": "",
        "disabled": "disabled" in box.attrs,
    }


def _pieces(node: Node) -> list[str]:
    """A box's words, line by line: "Alpha Primary", "SCH-1"."""
    parts = [
        child
        for child in node.children
        if (isinstance(child, str) and child.strip())
        or (
            isinstance(child, Node)
            and child.tag not in SILENT
            and child.tag != "input"
            and child.text()
        )
    ]
    if any(isinstance(part, str) for part in parts):
        return [node.text()]
    if len(parts) == 1:
        return _pieces(parts[0])
    return [part.text() for part in parts]


def _scripted(template: Node, box: Node, root: Node) -> dict | None:
    """The choices a script draws from its data: each item's value and words,
    the field that picks the ones that apply, and the ticked ones."""
    loop = FOR.match(template.get("x-for").strip())
    holder = _data_holder(template)
    if loop is None or holder is None:
        return None
    item, expression = loop.groups()
    data = holder.get("x-data")
    source = _source(expression.strip(), data)
    if source is None:
        return None
    name, group_key, picked_by = source
    items = data_value(data, name)
    value_key = _member(box.get(":value") or box.get("x-bind:value"), item)
    words = template.find(lambda n: bool(_member(n.get("x-text"), item)))
    label_key = _member(words.get("x-text"), item) if words is not None else ""
    detail = _phrase(template, item)
    if not isinstance(items, list) or not value_key or not label_key:
        return None
    ticked = data_value(data, box.get("x-model")) if box.get("x-model") else None
    picker = (
        root.find(lambda n: n.get("x-model") == picked_by and bool(n.get("name")))
        if picked_by
        else None
    )
    options = [
        {
            "value": str(entry.get(value_key, "")),
            "label": str(entry.get(label_key, "")),
            "detail": detail(entry),
            "group": str(entry.get(group_key, "")) if group_key else "",
            "disabled": False,
        }
        for entry in items
        if isinstance(entry, dict)
    ]
    return {
        "options": options,
        "value": ",".join(map(str, ticked)) if isinstance(ticked, list) else "",
        "groupBy": picker.get("name") if picker is not None else "",
    }


def _data_holder(node: Node) -> Node | None:
    holder = node.parent
    while holder is not None and not holder.get("x-data"):
        holder = holder.parent
    return holder


def _source(expression: str, data: str, depth: int = 0) -> tuple[str, str, str] | None:
    """The data list an ``x-for`` walks, the item key its filter compares,
    and the value it compares that key with: through one getter at most."""
    found = SOURCE.match(expression)
    if found is None:
        return None
    name, parameter, condition = found.groups()
    getter = re.search(GETTER.format(name=re.escape(name)), data, re.S)
    if getter is not None and depth == 0 and condition is None:
        return _source(getter.group(1).strip(), data, depth + 1)
    if condition is None:
        return name, "", ""
    compared = COMPARE.match(condition.strip())
    if compared is None or compared.group(1) != parameter:
        return None
    return name, compared.group(2), compared.group(3)


def _phrase(template: Node, item: str):
    """The line a script prints under an item's words, when it has one:
    "Also in Goma Cluster" for an item whose ``covered_by`` is set."""
    for node in template.find_all(lambda n: bool(n.get("x-text"))):
        found = PHRASE.match(node.get("x-text").strip())
        if found and found.group(2) == item:
            before, _, key, after = found.groups()
            return (
                lambda entry: f"{before}{entry[key]}{after}" if entry.get(key) else ""
            )
    return lambda entry: ""


def _member(expression: str, item: str) -> str:
    found = MEMBER.match((expression or "").strip())
    return found.group(2) if found and found.group(1) == item else ""


def data_value(data: str, name: str):
    """The value ``name`` holds in an ``x-data`` object, when it is JSON."""
    found = re.search(rf"(?<![\w.]){re.escape(name)}\s*:\s*", data)
    if found is None:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(data, found.end())
    except ValueError:
        return None
    return value
