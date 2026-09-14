"""Read-only inventory of template controls; wiring evidence is not a functional pass."""

import csv
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/audits/controls-2026-09-14"
VOID = {
    "input",
    "img",
    "br",
    "hr",
    "meta",
    "link",
    "source",
    "area",
    "base",
    "embed",
    "param",
    "wbr",
}


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {
            "tag": tag,
            "attrs": dict(attrs),
            "line": self.getpos()[0],
            "parent": self.stack[-1] if self.stack else None,
            "text": [],
        }
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"].append(data)


def ancestor(node, tag):
    node = node["parent"]
    while node:
        if node["tag"] == tag:
            return node
        node = node["parent"]


def quiet(match):
    return "".join("\n" if c == "\n" else " " for c in match.group())


def compact(value):
    return re.sub(r"\s+", " ", value or "").strip()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    files = 0
    for path in sorted((ROOT / "templates").rglob("*.html")):
        files += 1
        source = path.read_text()
        source = re.sub(
            r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->",
            quiet,
            source,
            flags=re.S,
        )
        source = re.sub(r"{%.*?%}", quiet, source, flags=re.S)
        parser = Parser()
        parser.feed(source)
        for n in parser.nodes:
            a = n["attrs"]
            tag = n["tag"]
            if tag not in {"button", "a", "input", "select", "textarea", "summary"}:
                continue
            if tag == "input" and a.get("type") == "hidden":
                continue
            form = ancestor(n, "form")
            fa = form["attrs"] if form else {}
            typ = a.get("type") or ("submit" if tag == "button" and form else "")
            label = compact(
                a.get("aria-label")
                or a.get("title")
                or "".join(n["text"])
                or a.get("placeholder")
                or a.get("value")
            )[:250]
            kind = (
                "tab"
                if a.get("role") == "tab"
                else "field"
                if tag in {"select", "textarea", "input"}
                and typ not in {"submit", "button", "reset"}
                else "disclosure"
                if tag == "summary"
                else "link"
                if tag == "a"
                else "button"
            )
            handlers = {
                k: v for k, v in a.items() if k.startswith(("@", "x-on:", "hx-", "on"))
            }
            destination = a.get("href") or next(
                (
                    a[k]
                    for k in ("hx-get", "hx-post", "hx-put", "hx-delete", "hx-patch")
                    if k in a
                ),
                "",
            )
            notes = []
            if (
                tag == "a"
                and a.get("href") in {"", "#", "javascript:void(0)"}
                and not handlers
            ):
                notes.append("Placeholder destination; check delegated binding")
            if (
                kind == "button"
                and not handlers
                and typ not in {"submit", "reset"}
                and not any(k.startswith(("data-", ":")) for k in a)
                and not a.get("id")
                and "disabled" not in a
            ):
                notes.append("No direct binding; check ancestor/delegated binding")
            if kind in {"button", "tab"} and not label:
                notes.append("No static label; check rendered accessible name")
            if (
                kind == "field"
                and not a.get("name")
                and not any("model" in k or k.startswith(("@", "x-on:")) for k in a)
            ):
                notes.append("No submitted name or direct model; check JS binding")
            rows.append(
                {
                    "control_id": f"CONTROL-{len(rows)+1:05d}",
                    "template": str(path.relative_to(ROOT)),
                    "line": n["line"],
                    "kind": kind,
                    "tag": tag,
                    "label_or_expression": label,
                    "element_id": a.get("id", ""),
                    "name": a.get("name", ""),
                    "type": typ,
                    "destination_or_expression": destination,
                    "form_action": fa.get("action")
                    or fa.get("hx-get")
                    or fa.get("hx-post", ""),
                    "form_method": fa.get("method", "get") if form else "",
                    "handlers": json.dumps(handlers, ensure_ascii=False),
                    "explicit_disabled": "disabled" in a,
                    "review_candidates": "; ".join(notes),
                    "functional_status": "Not individually executed",
                }
            )
    with (OUT / "control-inventory.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "templates_scanned": files,
        "control_declarations": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "declarations_needing_binding_review": sum(
            bool(r["review_candidates"]) for r in rows
        ),
        "method": "Static declarations, including shared components and template branches. Counts are not unique rendered controls or passed tests.",
    }
    (OUT / "control-inventory-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
