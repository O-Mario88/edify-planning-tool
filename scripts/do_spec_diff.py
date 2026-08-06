#!/usr/bin/env python3
"""Print every leaf that differs between two App Platform specs.

`doctl apps update --spec` replaces the whole spec rather than merging, so the
only safe way to change a running app is to export what is live, edit a copy,
and read the complete difference before applying. "It looks right" is not a
review: the dangerous edits are the ones that are absent from the file rather
than wrong in it — a missing secret, a renamed database, a component that is
simply not mentioned.

This walks both documents to their leaves and prints each disagreement with a
full path. No summarising, no truncating the list: a spec review is only worth
anything if it is exhaustive.

    scripts/do_spec_diff.py live.yaml proposed.yaml

Exit status is 1 when the specs differ, so it can gate a deploy script.
Secret-shaped values are masked — the point is to see *that* a secret changed,
and printing an encrypted blob into a terminal buffer helps nobody.
"""

from __future__ import annotations

import re
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML is required: pip install pyyaml")

SECRET_KEYISH = re.compile(r"SECRET|KEY|PASSWORD|TOKEN|CREDENTIAL|DSN", re.I)


def _mask(path: str, value):
    text = str(value)
    if text.startswith("EV[") or SECRET_KEYISH.search(path):
        return f"<masked, len={len(text)}>"
    return text if len(text) <= 160 else text[:157] + "..."


def diff(a, b, path=""):
    """Leaf-level differences. Lists compare by index, and a length change is
    reported as one difference rather than a cascade of shifted entries."""
    if type(a) is not type(b):
        return [(path or ".", a, b)]
    if isinstance(a, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            here = f"{path}.{key}"
            if key not in a:
                out.append((here, "<absent>", b[key]))
            elif key not in b:
                out.append((here, a[key], "<absent>"))
            else:
                out += diff(a[key], b[key], here)
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [(path, f"<{len(a)} items>", f"<{len(b)} items>")]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [(path, a, b)]


def main(argv):
    if len(argv) != 3:
        sys.exit(f"usage: {argv[0]} <live.yaml> <proposed.yaml>")
    live = yaml.safe_load(open(argv[1]))
    proposed = yaml.safe_load(open(argv[2]))

    differences = diff(live, proposed)
    if not differences:
        print("No differences. Applying this would be a no-op.")
        return 0

    print(f"{len(differences)} difference(s) — read all of them:\n")
    for path, old, new in differences:
        print(f"  {path.lstrip('.')}")
        print(f"      live: {_mask(path, old)}")
        print(f"      new : {_mask(path, new)}\n")

    # Anything that removes a component or blanks a secret is the class of
    # change that took production down before, so it is called out separately
    # rather than left for the reader to spot in a long list.
    alarming = [
        (p, o, n)
        for p, o, n in differences
        if str(n) == "<absent>"
        or "REPLACE_ME" in str(n)
        or (str(o).startswith("EV[") and not str(n).startswith("EV["))
    ]
    if alarming:
        print("!! REVIEW THESE FIRST — removals, placeholders, or lost secrets:")
        for path, _old, new in alarming:
            print(f"   {path.lstrip('.')} -> {_mask(path, new)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
