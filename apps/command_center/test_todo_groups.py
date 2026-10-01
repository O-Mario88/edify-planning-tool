"""Identical To-Dos read as one entry (owner, 2026-09-30)."""

from django.test import SimpleTestCase

from apps.command_center.todo_groups import (
    GROUP_PREVIEW,
    GROUP_SIZE,
    group_identical,
    limit_entries,
)


def _todo(todo_id, title="Plan Activities for Newly Added Project School", **extra):
    return {
        "id": todo_id,
        "title": title,
        "category": extra.pop("category", "Projects"),
        "priority": extra.pop("priority", "medium"),
        **extra,
    }


class GroupIdenticalTests(SimpleTestCase):
    def test_three_or_more_identical_to_dos_are_one_entry_where_the_first_stood(self):
        todos = [
            _todo("fix-1", title="Fix School Contact"),
            _todo("plan-1"),
            _todo("ssa-1", title="Schedule SSA Visit"),
            _todo("plan-2"),
            _todo("plan-3"),
        ]
        entries = group_identical(todos)
        self.assertEqual(
            [e["title"] if e["group"] else e["todo"]["id"] for e in entries],
            ["fix-1", "Plan Activities for Newly Added Project School", "ssa-1"],
        )
        group = entries[1]
        self.assertEqual(group["count"], 3)
        self.assertEqual(
            [t["id"] for t in group["items"]], ["plan-1", "plan-2", "plan-3"]
        )

    def test_two_alike_stay_rows_of_their_own(self):
        entries = group_identical([_todo("plan-1"), _todo("plan-2")])
        self.assertEqual([e["group"] for e in entries], [False, False])

    def test_a_different_priority_or_category_is_a_different_to_do(self):
        todos = [
            _todo("a"),
            _todo("b"),
            _todo("c", priority="high"),
            _todo("d", category="SSA"),
        ]
        self.assertFalse(any(e["group"] for e in group_identical(todos)))

    def test_a_bounded_list_draws_a_groups_first_rows_and_no_more_than_before(self):
        todos = [_todo(f"plan-{n}") for n in range(20)]
        todos += [_todo(f"other-{n}", title=f"Other {n}") for n in range(10)]
        rows = limit_entries(todos, 8)
        # The group's first rows, then others: eight rows, as before grouping.
        self.assertEqual(len(rows), 8)
        self.assertEqual(
            [r["id"] for r in rows[: GROUP_PREVIEW + 1]],
            ["plan-0", "plan-1", "plan-2", "other-0"],
        )
        self.assertEqual({r[GROUP_SIZE] for r in rows[:GROUP_PREVIEW]}, {20})

    def test_a_cut_group_still_says_how_many_it_stands_for(self):
        todos = [_todo(f"plan-{n}") for n in range(20)]
        entry = group_identical(limit_entries(todos, 8))[0]
        self.assertTrue(entry["group"])
        self.assertEqual(entry["count"], 20)
        self.assertEqual(len(entry["items"]), GROUP_PREVIEW)
        self.assertEqual(entry["more"], 20 - GROUP_PREVIEW)

    def test_many_groups_never_draw_more_rows_than_the_limit(self):
        todos = [
            _todo(f"{kind}-{n}", title=f"Task {kind}")
            for kind in "abcdefgh"
            for n in range(12)
        ]
        rows = limit_entries(todos, 8)
        self.assertEqual(len(rows), 8)
        entries = group_identical(rows)
        # Three groups: 3 + 3 + 2 rows, each counted whole.
        self.assertEqual([len(e["items"]) for e in entries], [3, 3, 2])
        self.assertEqual([e["count"] for e in entries], [12, 12, 12])

    def test_the_whole_list_keeps_every_row_of_a_group(self):
        entry = group_identical([_todo(f"plan-{n}") for n in range(20)])[0]
        self.assertEqual(
            (entry["count"], len(entry["items"]), entry["more"]), (20, 20, 0)
        )
