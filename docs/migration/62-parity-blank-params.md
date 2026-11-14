# 62. Parity asks the existing feed what the gateway's pages see

The parity tool (`cmd/parity -screen page`) asks the Go gateway and the
existing feed (`/api/mobile/v1/page`) the same question and compares the two
answers. A blank parameter (`q=`) was not the same question on both sides:

- the gateway reads every page query through `pageQuery`
  (`internal/screens/my_plan.go`), which drops a blank value before any page,
  Go's or the feed's behind it, sees it;
- the parity tool put every parameter into its request to the existing feed,
  blank ones included.

The feed keeps a blank parameter in what it draws, so the two answers
differed for a reason the app never meets (agent 35, doc 60: Core School
Oversight 27 and Staff Activity 4 differing answers, all the `q=` question).
Asked directly through the feed on the development database:

| Reader, page | With `q=` | Without |
|---|---|---|
| pl1, `/staff-activity` | `redirect: /dashboard?sa=q%3D#staff-activity` | `redirect: /dashboard#staff-activity` |
| cceo, `/core-schools-oversight/` | strip link `?q=&trajectory=not_comparable` | `?&trajectory=not_comparable` |

## 62.1 What changed

| Piece | Change |
|---|---|
| `internal/screens/plain_query.go` (new) | `PlainQuery(map[string]string) url.Values`: every key with a value, a blank value dropped |
| `internal/screens/my_plan.go` | `pageQuery` validates the keys and values as before and returns `PlainQuery(given)` (behaviour unchanged) |
| `cmd/parity/page.go` | `existingPageURL` builds the existing feed's request from `screens.PlainQuery`, then sets `path`; `existingPage` (and Calendar's, which calls it) uses it |
| `cmd/parity/page_with_blank_params.go` (new) | Core School Oversight and Staff Activity are also asked `q=` alone and beside a value (`tab=core_visits`; `role=CCEO`) |

One helper serves both sides, so the gateway and the tool cannot drift apart.
A value of spaces is a value on both (kept). The school directory
(`-screen directory`) and the profile (`-screen profile`) send typed
parameters of their own and are unchanged.

## 62.2 Tests

- `internal/screens/plain_query_test.go`: `PlainQuery` (nil, empty, blank,
  blank beside a value, spaces, every value kept) and that `pageQuery`
  returns exactly `PlainQuery` once the query passes.
- `cmd/parity/page_test.go`: the existing feed's URL drops `q=` alone and
  beside a value, keeps a search with a space, and always carries `path`.

Both were written first and failed to build (`undefined: PlainQuery`,
`r.existingPageURL undefined`) before the code was added.

## 62.3 Parity (29 accounts, Go-only gateway 8085 against Django 8185 on `edify_gorn_dev`, `-pause 20s`)

```
/core-schools-oversight/
3509 answers compared, 25 differing
85 answers held rows with the same name, compared in School ID order (the existing page gives them none)

/staff-activity
1429 answers compared, 18 differing
```

No blank-parameter question differs on either page.

- Staff Activity's 18 are the known pass-ons of doc 41 (admin 9, cd 9:
  `go error: unavailable` on the week, month, quarter, FY twice,
  2026-11-12, 2026-W46-1, the follow-up week and 1890). pl1–pl4, which
  differed on `q=` in doc 60's run, are 0 differing.
- Core School Oversight's 25 are not blank parameters: all are
  `tab=recommendations` (admin, cceo, cd, ia, pl1 × five questions),
  `.blocks[5].panel.items: go 9 items, existing 6 items`. The development
  database gained its first `ssa_recommendation` rows on 2026-11-12 (one
  generated, one accepted, one deferred). Go's `recommendationBlocks` writes
  the intervention line and the reason as two items, while the template's
  first `<span>` is read as one text (intervention, score and band, then
  ` · ` and the recommended training's name or `No mapped training[: reason]`,
  then the reason), and Go never writes the ` · …` part. Left as BACKLOG
  item `core-recommendations`.

## 62.4 What is left

- Core School Oversight's recommendations panel (above).
- The Staff Activity pass-ons remain doc 41's (`staff-activity-2`).
