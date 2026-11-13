# 68. Intended differences: Go fixes the existing application's defects

Owner, 2026-11-13: "Can you fix those from the go side" (the defects the
migration's comparisons found in the existing application). Go does the
correct thing instead of copying a defect. A corrected answer no longer
matches the existing one, so the comparison tools would report it; this
piece lets them accept exactly those differences and nothing else.

## 68.1 The list

`platform/backend/internal/parity/intended.json`, embedded in the tools. Each
entry names:

| Field | What |
|---|---|
| `id` | the name printed beside an accepted difference |
| `tool` | `page`, `profile`, `navigation`, `directory`, `notifications` or `shadow` |
| `where` | the page path (as the tool prints it) or the save scenario (`-scenario`) |
| `questions` | the questions it shows on, each exactly: a page's query as printed (`(as it opens)` for none), or a shadow table |
| `fields` | the field paths (`.blocks[1].filters[0].options[1].selected`, `error` for a refused or failed side) or shadow columns, each exactly |
| `existing`, `go` | patterns the two values must each match whole |
| `defect` | what is wrong in the existing application |
| `decision` | the owner's decision, quoted and dated |
| `test` | the unit test proving Go's corrected behaviour, `<package dir>.<TestName>` |

`parity.Load` refuses an entry with a field missing, an unknown tool, the same
two patterns, a pattern that does not compile, an unknown key, or an id listed
twice. `TestTheCheckedInListLoadsAndEveryEntryHasItsTest` fails when an
entry's test does not exist.

## 68.2 How the tools use it

- `cmd/parity -screen page`: a difference is accepted only when its tool,
  path, question and field are listed and both values match their patterns
  whole. The answer is printed `INTENDED` with the entry's id; every other
  difference in the same answer still prints `DIFFERS` and fails the run. The
  summary adds `N answers held only intended differences`.
- `cmd/shadow -scenario <name>`: a row only one copy holds is paired with a
  row only the other holds when they differ only in listed columns; such a
  table prints `same but as intended`. Unpaired rows still differ. Without
  `-scenario` no entry applies.
- Not wired yet: `-screen profile`, `navigation`, `directory` and
  `cmd/notificationparity` (they print and fail as before). Wire each when the
  first fix needs it.

## 68.3 Adding a fix

1. Write the unit test of the corrected behaviour first, then the fix.
2. Add the entry, as narrow as the difference: the exact questions and
   fields, patterns that match only the defect and the correction.
3. Run the comparison; the difference prints `INTENDED`, nothing else moves.

Proved by `internal/parity` (exact match, near misses on question, field,
page, tool, direction and partial pattern, shadow row pairing, refused
entries, every entry's test exists) and
`cmd/parity.TestComparePagesSetsAsideOnlyAListedDifference`.
