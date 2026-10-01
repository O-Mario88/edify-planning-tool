"""Identical To-Dos read as one line (owner, 2026-09-30: "group identical
to-dos ('8 new project schools need activities planned → Plan')").

The queue derives one To-Do per record, so eight schools newly added to a
project are eight rows that say "Plan Activities for Newly Added Project
School", the school — the only part that differs — in small grey type. Three
or more To-Dos with the same title, category and priority become one entry
that holds them; each keeps its own decisions inside the entry.

Order is kept: a group stands where its first To-Do stood, and every other
To-Do where it was.
"""

from __future__ import annotations

from django.utils.text import slugify

#: How many identical To-Dos make a group.
GROUP_MIN = 3
#: How many of a group's To-Dos a bounded list draws. Every row carries its
#: own decisions menu (about 5 KB), so a group that drew all of its rows made
#: the field officer's Today panel four times its size; the To-Do page holds
#: the rest.
GROUP_PREVIEW = 3
#: Set by limit_entries on the rows it keeps: the size of the whole group, so
#: a group cut to its preview still says how many To-Dos it stands for.
GROUP_SIZE = "group_size"


def _key(todo: dict) -> tuple:
    return (
        todo.get("title") or "",
        todo.get("category") or "",
        todo.get("priority") or "",
    )


def group_identical(todos: list[dict]) -> list[dict]:
    """The To-Dos as entries: {"group": False, "todo": t} for a To-Do on its
    own, {"group": True, "title", "category", "priority", "priority_label",
    "count", "items", "more", "key"} for identical ones. `count` is the whole
    group, `items` the To-Dos given here and `more` the ones that are not."""
    counts: dict[tuple, int] = {}
    for todo in todos:
        counts[_key(todo)] = counts.get(_key(todo), 0) + 1

    entries: list[dict] = []
    groups: dict[tuple, dict] = {}
    for todo in todos:
        key = _key(todo)
        size = max(counts[key], todo.get(GROUP_SIZE) or 0)
        if size < GROUP_MIN:
            entries.append({"group": False, "todo": todo})
            continue
        group = groups.get(key)
        if group is None:
            group = {
                "group": True,
                "title": todo.get("title") or "",
                "category": todo.get("category") or "",
                "priority": todo.get("priority") or "",
                "priority_label": todo.get("priority_label") or "",
                "count": size,
                "items": [],
                "more": 0,
                "key": slugify(f"{key[0]}-{key[1]}-{key[2]}")[:60] or "group",
            }
            groups[key] = group
            entries.append(group)
        group["items"].append(todo)
    for group in groups.values():
        group["more"] = max(group["count"] - len(group["items"]), 0)
    return entries


def limit_entries(todos: list[dict], limit: int) -> list[dict]:
    """A bounded list in which identical To-Dos count once: the To-Dos of the
    first entries, in entry order, at most `limit` of them in all and
    GROUP_PREVIEW from any one group. The list is no longer than the `limit`
    rows it was before grouping; it only says more with them. Each kept row
    of a group carries the group's whole size (GROUP_SIZE)."""
    rows: list[dict] = []
    for entry in group_identical(todos):
        room = limit - len(rows)
        if room <= 0:
            break
        if entry["group"]:
            rows.extend(
                {**todo, GROUP_SIZE: entry["count"]}
                for todo in entry["items"][: min(GROUP_PREVIEW, room)]
            )
        else:
            rows.append(entry["todo"])
    return rows
