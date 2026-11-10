"""Reads a web drawer (components base_drawer) into what the native app draws.

A drawer is read from the HTML the web renders for the same person: its
title, the line under it, its notes, headings, figures and fields, in order,
and the buttons in its footer. A field keeps its label, value, choices, help
line and error, and the few things the drawer's own script does that change
what is shown — a field shown only for one choice (``x-show``), a choice
list that another field reloads (``hx-get``), and choices that belong to
another field's choice (``data-*`` on an option). An ``x-show`` the reader
cannot follow leaves its field shown, never hidden.

What a drawer sends back is its own fields and hidden values only
(``field_names``, ``hidden_values``): the save never takes a field the drawer
does not have.
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import SILENT, Node, parse

CONTROLS = ("input", "select", "textarea")
#: Inputs that are not fields the person fills.
NOT_FIELDS = {"hidden", "submit", "button", "reset", "image"}
REQUIRED_MARK = re.compile(r"\s*\*\s*$")
SIMPLE_VALUE = re.compile(r"(\w+)\s*:\s*('([^']*)'|true|false)")
EQUALS = re.compile(r"(\w+)\s*===\s*'([^']*)'")
FLAG = re.compile(r"(!?)\s*(\w+)")


def _is_control(node: Node) -> bool:
    if node.tag not in CONTROLS:
        return False
    return node.tag != "input" or node.get("type").lower() not in NOT_FIELDS


def _number(raw: str):
    try:
        value = float(raw)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _label_text(label: Node | None) -> str:
    return REQUIRED_MARK.sub("", label.text()) if label else ""


def _scope_of(node: Node) -> tuple[dict, dict]:
    """The constants and field names an ``x-show`` at ``node`` can read: the
    nearest simple ``x-data`` object above it and the fields bound to that
    object with ``x-model``."""
    holder = node
    while holder is not None:
        data = holder.get("x-data")
        if data and "(" not in data:
            constants = {
                key: (quoted if raw.startswith("'") else raw == "true")
                for key, raw, quoted in SIMPLE_VALUE.findall(data)
            }
            models = {
                control.get("x-model"): control.get("name")
                for control in holder.find_all(
                    lambda n: n.tag in CONTROLS and bool(n.get("x-model"))
                )
            }
            return constants, models
        holder = holder.parent
    return {}, {}


def _show_when(node: Node, root: Node) -> list[dict] | None:
    """When ``node`` is shown: [] for always, a list of {field, values} for
    "while any of these fields holds one of its values", None for never.
    Read from the nearest ``x-show`` at or above ``node`` inside ``root``."""
    holder = node
    while holder is not None and holder is not root:
        expression = holder.get("x-show")
        if expression:
            return _condition(expression, *_scope_of(holder))
        holder = holder.parent
    return []


def _condition(expression: str, constants: dict, models: dict) -> list[dict] | None:
    if "&&" in expression or "(" in expression:
        return []
    shown: dict[str, list[str]] = {}
    for alternative in (part.strip() for part in expression.split("||")):
        equals = EQUALS.fullmatch(alternative)
        flag = FLAG.fullmatch(alternative)
        if equals:
            name, value = equals.groups()
            if name in models:
                shown.setdefault(models[name], []).append(value)
            elif name in constants and constants[name] == value:
                return []
        elif flag and flag.group(2) in constants:
            if bool(constants[flag.group(2)]) != (flag.group(1) == "!"):
                return []
        else:
            return []
    if not shown:
        return None
    return [{"field": field, "values": values} for field, values in shown.items()]


def _option_group(option: Node) -> tuple[str, str]:
    """The ``data-*`` an option carries: its attribute and value."""
    for key, value in option.attrs.items():
        if key.startswith("data-") and value:
            return key.removeprefix("data-"), value
    return "", ""


def _value(control: Node) -> str:
    if control.tag == "textarea":
        return "".join(c for c in control.children if isinstance(c, str)).strip()
    if control.tag == "select":
        options = control.find_all(lambda n: n.tag == "option")
        chosen = next((o for o in options if "selected" in o.attrs), None)
        chosen = chosen or (options[0] if options else None)
        return chosen.get("value") if chosen else ""
    kind = control.get("type").lower()
    if kind in ("checkbox", "radio"):
        return (control.get("value") or "on") if "checked" in control.attrs else ""
    return control.get("value")


def _messages(holder: Node) -> tuple[list[str], list[str]]:
    """The help lines and the error lines a field's holder prints."""
    errors, helps = [], []
    for line in holder.find_all(lambda n: n.tag == "p"):
        if line.has("text-rose-700"):
            errors.append(line.text())
        elif "edify-note" not in line.get("class"):
            helps.append(line.text())
    return helps, errors


def _choices(control: Node, field: dict) -> None:
    options, group_key = [], ""
    for option in control.find_all(lambda n: n.tag == "option"):
        key, group = _option_group(option)
        group_key = group_key or key
        options.append(
            {
                "value": option.get("value"),
                "label": option.text(),
                "group": group,
                "disabled": "disabled" in option.attrs,
            }
        )
    field["options"] = options
    if group_key:
        field["_groupKey"] = group_key


def _field(holder: Node, control: Node, root: Node) -> dict | None:
    when = _show_when(control, root)
    if when is None:
        return None
    label = None
    if control.get("id"):
        label = root.find(
            lambda n: n.tag == "label" and n.get("for") == control.get("id")
        )
    label = label or holder.find(lambda n: n.tag == "label")
    helps, errors = _messages(holder)
    kind = (
        control.tag
        if control.tag != "input"
        else (control.get("type") or "text").lower()
    )
    field = {
        "name": control.get("name"),
        "label": _label_text(label) or control.get("aria-label"),
        "kind": kind,
        "value": _value(control),
        "required": "required" in control.attrs
        or (bool(when) and ":required" in control.attrs),
        "help": helps[0] if helps else "",
        "error": " ".join(errors),
        "placeholder": control.get("placeholder"),
        "readOnly": "readonly" in control.attrs or "disabled" in control.attrs,
    }
    for key in ("min", "max", "step"):
        number = _number(control.get(key)) if control.get(key) else None
        if number is not None:
            field[key] = number
    if control.get("maxlength").isdigit():
        field["maxLength"] = int(control.get("maxlength"))
    if when:
        field["showWhen"] = when
    if control.tag == "select":
        _choices(control, field)
    if control.get("hx-get"):
        field["reloadsPath"] = control.get("hx-get")
        field["_reloadsId"] = control.get("hx-target").lstrip("#")
    return field


def _lines(items: list[Node]) -> dict | None:
    """A list whose every line is "label  value" (two spans)."""
    lines = []
    for item in items:
        spans = [c for c in item.children if isinstance(c, Node) and c.tag == "span"]
        if len(spans) != 2:
            return None
        lines.append({"label": spans[0].text(), "value": spans[1].text(), "href": ""})
    return {"facts": lines} if lines else None


def _facts(definition: Node) -> dict:
    facts = []
    for term in definition.children:
        if not isinstance(term, Node):
            continue
        if term.tag == "dt":
            facts.append({"label": term.text(), "value": "", "href": ""})
        elif term.tag == "dd" and facts:
            facts[-1]["value"] = term.text()
    return {"facts": facts}


def _holds_one_field(node: Node) -> Node | None:
    if node.tag not in ("div", "label"):
        return None
    controls = node.find_all(_is_control)
    if len(controls) != 1:
        return None
    if node.tag == "div" and not node.find(lambda n: n.tag == "label"):
        return None
    return controls[0]


def _with_condition(item: dict, node: Node, root: Node) -> dict | None:
    when = _show_when(node, root)
    if when is None:
        return None
    if when:
        item["showWhen"] = when
    return item


def _skipped(child: Node) -> bool:
    return (
        child.tag in SILENT
        or child.tag in ("button", "legend")
        or (child.tag == "input" and not _is_control(child))
        or child.has("sr-only")
        or child.has("drawer-required-note")
        or child.has("drawer-footer")
        or child.has("drawer-discard")
        or child.has("drawer-header")
    )


def _list(child: Node) -> list[dict]:
    lines = _lines([c for c in child.children if isinstance(c, Node) and c.tag == "li"])
    if lines:
        return [{"lines": lines}]
    return [{"text": li.text()} for li in child.find_all(lambda n: n.tag == "li")]


def _fieldset(child: Node, root: Node, out: list[dict]) -> None:
    legend = child.find(lambda n: n.tag == "legend")
    if legend is not None and not legend.has("sr-only"):
        heading = _with_condition({"heading": _label_text(legend)}, child, root)
        if heading is not None:
            out.append(heading)
    _items(child, root, out)


def _add(out: list[dict], item: dict, node: Node, root: Node) -> None:
    """Add ``item`` with the condition of the part it sits in; leave it out
    when that part is never shown."""
    if (conditioned := _with_condition(item, node, root)) is not None:
        out.append(conditioned)


def _items(node: Node, root: Node, out: list[dict]) -> list[dict]:
    for child in node.children:
        if isinstance(child, str) or _skipped(child):
            continue
        control = _holds_one_field(child)
        if "edify-note" in child.get("class"):
            _add(
                out,
                {"note": {"text": child.text(), "tone": child.get("data-tone")}},
                child,
                root,
            )
        elif control is not None:
            if (field := _field(child, control, root)) is not None:
                out.append({"field": field})
        elif child.tag == "fieldset":
            _fieldset(child, root, out)
        elif child.tag in ("h2", "h3", "h4", "h5"):
            if child.get("id") != "drawer-title":
                _add(out, {"heading": child.text()}, child, root)
        elif child.tag in ("ul", "ol"):
            for item in _list(child):
                _add(out, item, child, root)
        elif child.tag == "dl":
            _add(out, {"facts": _facts(child)}, child, root)
        elif child.tag == "p":
            if child.text():
                _add(out, {"text": child.text()}, child, root)
        elif _is_control(child):
            if (field := _field(child.parent or child, child, root)) is not None:
                out.append({"field": field})
        else:
            _items(child, root, out)
    return out


def _resolve(items: list[dict], root: Node) -> None:
    """Name, by field, what each field's script refers to by id or attribute."""
    names = {item["field"]["name"] for item in items if "field" in item}
    by_id = {
        control.get("id"): control.get("name")
        for control in root.find_all(lambda n: _is_control(n) and bool(n.get("id")))
    }
    for item in items:
        field = item.get("field")
        if not field:
            continue
        target = field.pop("_reloadsId", None)
        if target is not None:
            field["reloadsTarget"] = by_id.get(target, "")
        key = field.pop("_groupKey", None)
        if key:
            base = key.replace("-", "_")
            field["groupBy"] = next(
                (name for name in (f"{base}_id", base) if name in names), ""
            )


def _drawer(root: Node) -> Node:
    return root.find(lambda n: "data-edify-drawer" in n.attrs) or root


def read(html: str) -> dict:
    """The drawer as the native app draws it."""
    root = _drawer(parse(html))
    title = root.find(lambda n: n.get("id") == "drawer-title")
    subtitle = root.find(lambda n: n.get("id") == "drawer-subtitle")
    body = root.find(lambda n: n.has("drawer-body")) or root
    form = body.find(lambda n: n.tag == "form")
    submit = body.find(
        lambda n: n.tag == "button" and n.get("type").lower() == "submit"
    )
    cancel = body.find(
        lambda n: n.tag == "button"
        and n.get("type").lower() != "submit"
        and "requestClose" in n.get("@click")
    )
    items = _items(body, root, [])
    _resolve(items, root)
    return {
        "title": title.text() if title else "",
        "subtitle": subtitle.text() if subtitle else "",
        "hasRequired": body.find(lambda n: n.has("drawer-required-note")) is not None,
        "items": items,
        "submitLabel": submit.text() if submit else "",
        "cancelLabel": cancel.text() if cancel else "Cancel",
        "canSubmit": form is not None and submit is not None,
    }


def _form(html: str) -> Node | None:
    return _drawer(parse(html)).find(lambda n: n.tag == "form")


def field_names(html: str) -> set[str]:
    """The fields the drawer's form sends, hidden inputs aside."""
    form = _form(html)
    if form is None:
        return set()
    return {node.get("name") for node in form.find_all(_is_control) if node.get("name")}


def hidden_values(html: str) -> dict[str, str]:
    """The hidden inputs the drawer's form sends, its CSRF token aside."""
    form = _form(html)
    if form is None:
        return {}
    return {
        node.get("name"): node.get("value")
        for node in form.find_all(
            lambda n: n.tag == "input" and n.get("type").lower() == "hidden"
        )
        if node.get("name") and node.get("name") != "csrfmiddlewaretoken"
    }


def form_data(html: str, values: dict) -> dict[str, str]:
    """What a save posts: the drawer's hidden values as the web rendered them,
    and the person's values for the drawer's own fields only."""
    names = field_names(html)
    hidden = hidden_values(html)
    return {
        **{
            name: str(value)
            for name, value in values.items()
            if name in names and name not in hidden
        },
        **hidden,
    }


def options(html: str) -> list[dict]:
    """The <option> list a field's reload answers with."""
    return [
        {
            "value": option.get("value"),
            "label": option.text(),
            "group": _option_group(option)[1],
            "disabled": "disabled" in option.attrs,
        }
        for option in parse(html).find_all(lambda n: n.tag == "option")
    ]
