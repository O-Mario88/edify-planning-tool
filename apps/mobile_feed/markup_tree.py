"""A part of the existing page carried as its own element structure, for the
web app to draw with the existing stylesheets.

Some parts are a dozen bespoke cards (the Admin dashboard's workspace:
column charts, two-year SSA bars, mini tiles, a quick-action grid) that the
page's blocks cannot say. On a desktop reading such a part is carried as
its elements, and only what is safe to draw again:

* elements from ALLOWED_TAGS (layout, text, tables, links and SVG shapes);
  nothing that runs, loads or posts (script, style, form, input, iframe, img)
  is carried, nor anything inside it;
* class names, and the few attributes the stylesheets and screen readers
  read (ARIA, data-*, id, title, role, table spans, SVG drawing);
* links within the app only (a path, a query or a fragment);
* sizes only as width, height or --w, in percent or pixels.

The web app checks it all again as it draws (lib/markupTree.ts).
"""

from __future__ import annotations

import re

#: The parts carried this way, by their outer class (desktop readings only).
ROOTS = ("admin-workspace",)

ALLOWED_TAGS = frozenset(
    {
        "div", "section", "article", "aside", "header", "footer", "nav", "figure", "figcaption",
        "h2", "h3", "h4", "p", "span", "strong", "b", "em", "i", "small", "time", "a",
        "ul", "ol", "li", "dl", "dt", "dd", "br",
        "table", "caption", "thead", "tbody", "tfoot", "tr", "th", "td",
        "svg", "path", "circle", "rect", "line", "polyline", "polygon", "g", "ellipse",
    }
)  # fmt: skip
#: Attributes carried as they are written.
PLAIN_ATTRS = frozenset(
    {"id", "title", "role", "scope", "colspan", "rowspan", "datetime"}
)
#: SVG drawing attributes; the parser lowers their names, the drawing needs some cased.
SVG_ATTRS = {
    "viewbox": "viewBox", "fill": "fill", "stroke": "stroke", "stroke-width": "stroke-width",
    "stroke-linecap": "stroke-linecap", "stroke-linejoin": "stroke-linejoin", "d": "d",
    "cx": "cx", "cy": "cy", "r": "r", "rx": "rx", "ry": "ry", "x": "x", "y": "y",
    "x1": "x1", "x2": "x2", "y1": "y1", "y2": "y2", "points": "points",
    "width": "width", "height": "height", "transform": "transform",
}  # fmt: skip
SVG_TAGS = frozenset(
    {"svg", "path", "circle", "rect", "line", "polyline", "polygon", "g", "ellipse"}
)
#: An attribute name for screen readers or stylesheets (aria-*, data-*).
NAMED_ATTR = re.compile(r"^(?:aria|data)-[a-z0-9-]{1,40}$")
#: Values a style may carry: a number, in percent or pixels.
SIZE = re.compile(r"^\d+(?:\.\d+)?(?:%|px)?$")
STYLE_PROPS = frozenset({"width", "height", "--w"})
#: An SVG value: numbers, letters for path commands, spaces and punctuation.
SVG_VALUE = re.compile(r"^[A-Za-z0-9 .,#()\-]{0,4000}$")
#: Longest attribute value carried.
MAX_VALUE = 500
#: Most elements one part carries.
MAX_NODES = 6000
#: Table parts, where HTML allows no text of their own (whitespace included).
NO_TEXT = frozenset({"table", "thead", "tbody", "tfoot", "tr"})


def is_root(node) -> bool:
    return any(node.has(root) for root in ROOTS)


def _href(value: str) -> str:
    """A link within the app: a path (not //host), a query or a fragment."""
    value = value.strip()
    if value.startswith("//") or value[:1] not in ("/", "?", "#"):
        return ""
    return value if len(value) <= MAX_VALUE else ""


def _style(value: str) -> dict:
    out = {}
    for part in value.split(";"):
        prop, _, val = part.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        if prop in STYLE_PROPS and SIZE.match(val):
            out[prop] = val
    return out


def _attrs(node) -> dict:
    out = {}
    svg = node.tag in SVG_TAGS
    for name, value in node.attrs.items():
        if name == "href" and node.tag == "a":
            if href := _href(value):
                out["href"] = href
        elif name in PLAIN_ATTRS or NAMED_ATTR.match(name):
            if len(value) <= MAX_VALUE:
                out[name] = value
        elif svg and name in SVG_ATTRS and SVG_VALUE.match(value):
            out[SVG_ATTRS[name]] = value
    return out


def _hidden(node) -> bool:
    """Not drawn when the page opens: the hidden attribute or display: none."""
    if "hidden" in node.attrs:
        return True
    style = node.attrs.get("style", "").replace(" ", "").lower()
    return "display:none" in style


def read(node) -> dict:
    """``node`` as a markup tree (PageMarkupNode as JSON)."""
    budget = [MAX_NODES]
    return _node(node, budget) or {"tag": "div"}


def _node(node, budget: list[int]) -> dict | None:
    if budget[0] <= 0 or node.tag not in ALLOWED_TAGS or _hidden(node):
        return None
    budget[0] -= 1
    out: dict = {"tag": node.tag}
    if classes := " ".join(node.attrs.get("class", "").split()):
        out["className"] = classes
    if attrs := _attrs(node):
        out["attrs"] = attrs
    if style := _style(node.attrs.get("style", "")):
        out["style"] = style
    children = []
    for child in node.children:
        if isinstance(child, str):
            text = " ".join(child.split())
            if not text and node.tag in NO_TEXT:
                continue
            if text or (child and children):
                children.append({"text": text or " "})
        elif (read_child := _node(child, budget)) is not None:
            children.append(read_child)
    if children:
        out["children"] = children
    return out
