# 136. The monthly CCE reports, read by Go

Owner, 2026-11-13: "I want django completely replaced by Go". The monthly
CCE reports register (`/cce-leadership/reports`,
`cce_leadership_views.reports_view`, `pages/cce_leadership/workspace.html`)
is answered by `platform/backend/internal/ccelead`, the first of the CCE
leadership registers. Starting, writing, submitting and reviewing a report
stay with the existing application.

| Part | Existing rule it ports |
|---|---|
| Who may open it | `require_page_permission("cce_reports")` and `can_open_url` (Admin, Impact Assessment, the Regional Programme Lead, the RVP), exported with strips and the "Start a monthly report" drawer by `manage.py export_cce_leadership_rules` |
| Whose reports | `reports_visible_to`: Admin every report; the Regional Lead their own; the RVP every report sent (not a draft), of the countries their regions hold when they are assigned regions (`_rvp_countries`: summary-only scope with regions); anyone else none. The latest month first, then the newest; at most 240 |
| A row | The month ("%B %Y"); for everyone but the lead, the author's name; the countries; the status's label (its tone sits in a span the feed does not read); the day submitted and "reviewer · day" reviewed ("%-d %b %Y" of the stored UTC time; "RVP" for an unknown reviewer); and the record's drawer button: "Write" for the lead's draft or returned report, "Review" for anyone else's submitted one, else "Open" |
| Figures | Drafts, Awaiting Review ("with the RVP" for the lead), Returned, Acknowledged; the line under each is a sentence, read as the note |
| The lead's notice | `report_state`: once the tenth of this month has passed and last month's report is missing, a draft or returned (from September 2026, `REPORTING_STARTS`), "The <Month YYYY> report was due by 10 <Month>. Start it or finish it and submit it." |
| Pages | 50 a page (`register_page`, the shared pager); with no report the feed reads the empty card as a one-cell table carrying the empty title |

`deploy/db/roles.sql` grants a report's author, month, countries, status
and submission and review times and reviewer — never its written sections,
figures or review note.

Proof: `cmd/parity -screen page -path /cce-leadership/reports` for all 29
accounts; `internal/ccelead/testdata/golden.py` files 58 reports and
`internal/integration/cce_leadership_test.go` compares Go's answers whole
(`EDIFY_CCE_LEADERSHIP_GOLDEN`, the same day).

## 136.2 Training Feedback

`feedback_view` (`/cce-leadership/feedback`), in the same package and shell:
the training observations `feedback_visible_to` gives the reader — Admin
every one, the Regional Lead their own, and of those shared, a Programme
Lead's those shared with them (`program_lead_ids`), a Country Director's and
Impact Assessment's those of their own country (none without a country on
file) — the latest day first, at most 500. Each row: the training
(`training_label`: "%-d %b" of its day or "Undated", its name or type, its
school or cluster) or the observation's subject; the day observed; for the
Programme Lead who delivered it (`delivered_by`: "<partner> · partner",
"Training partner", or the officer's name), for anyone else the country; the
Regional Lead; the rating (the non-empty ratings' mean, Python's half-to-even
rounding, "N.N of 4"); the recommendation's label; the state (Not shared yet;
Awaiting the Programme Lead, or "your acknowledgement" for the PL;
Acknowledged, and "· passed to the officer" once a coaching record carries it
on). The record's "Open" drawer, and for the Programme Lead also "Open
training": two actions, which the feed reads as the row's menu. Figures:
Awaiting Acknowledgement, Acknowledged, and the mean of the ratings shown
("N.N / 4", "across N observation(s)"). A `?open=` record link changes nothing
the feed reads. `deploy/db/roles.sql` grants an observation's people, day,
place, recommendation, ratings and sharing times — never its notes, feedback
or the lead's response — and whether a coaching record passed it on.

The golden files three training activities of its own (partner and staff
delivery, one undated) for the observations to name, and nine observations.
