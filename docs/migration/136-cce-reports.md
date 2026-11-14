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

## 136.3 CCE Engagement Log

`engagements_view` (`/cce-leadership/engagements`): the engagements
`engagements_visible_to` gives (Admin every one, the Regional Lead their own,
anyone else none), narrowed by `kind` when it names a kind and by `country`
when it is in reach, the latest day first, at most 500. Each row: the
subject, the kind's label, the day held, the Programme Leads it was with (by
name among those in reach, else "Programme Lead"; else its country), where a
shareable kind (training observation, PL coaching) stands with the lead; the
"Open" drawer and, for the lead's own unshared shareable engagement with
Programme Leads, "Share" (two actions read as the row's menu). The reach
(`lead_reach`): Admin every country the regions name; the Regional Lead the
countries of the regions assigned to them (through a district when no region
is), else every country with the notice that none is assigned; anyone else
none; the Programme Leads are the active accounts holding the role with a
People record in those countries. The filters are a Kind select and, when the
reach has countries, a Country select. Figures over the reader's own
engagements, unfiltered: coaching conversations of the last 30 days ("with N
Programme Lead(s) in reach"), trainings observed and country reviews this
quarter ("of N countr(y|ies)"), and the rhythm's overdue or missed rows.

The Regional Lead's page adds the Engagement rhythm card
(`partials/dashboards/rpl/rhythm.html` over `cadence.evaluate`, ported in
`ccelead/cadence.go` from the exported rules): each rule per region, per
Programme Lead or per country, rolling (due a set number of days after the
last), quarterly (this quarter) or yearly (before the next year's budget goes
to the RVP: missed once `country_annual_budget` shows it submitted or
approved), worst first, the twelve most urgent. The feed reads the card's
three counts one place off (OWNER_DEFECTS); Go copies it.

## 136.4 My Coaching

`coaching_views.my_coaching_view` (`/my-coaching`), on the same workspace
template: the coaching `coaching_visible_to` gives (Admin every record; of
those shared, a CCEO's own by account or People record; the page opens to
Admin, the CCEO and Impact Assessment, who reads none), narrowed by a kind it
offers and by "awaiting" (shared, not acknowledged) or "acknowledged", the
latest first, at most 500. Each row: the subject; for everyone but the
officer, the officer's name; the kind's label; the day held; who it is from;
the follow-up day; the state (`state_of`: "Follow-up due" once its day has
come and it is not followed up, for everyone but the officer; Acknowledged;
"Awaiting the officer", "your acknowledgement" for the officer; Not shared
yet); and the record's drawer, "Acknowledge" for the officer's unacknowledged
records, else "Open". Figures over everything visible, unfiltered: awaiting
acknowledgement, acknowledged, agreed actions open (a follow-up day not yet
followed up). `deploy/db/roles.sql` grants a coaching record's people, days,
kind, subject and states — never its strengths, growth areas, agreed actions
or the officer's response.
