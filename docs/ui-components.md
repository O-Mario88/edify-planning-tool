# Page components

The UI audit of 2026-10-01 traced most of the visual drift on the platform to
one cause. A page is hand-written markup, and the stylesheets work out what
each piece is by guessing: a substring of a class name, a `:has()` chain, an
id in a list of twenty. They then override the guess with `!important`. Every
new page is a new guess, so every sweep that fixes the look of one thing
breaks it somewhere else.

A component turns that round. The page says what it has, one template decides
the markup, and the stylesheet selects the component's own class.

This is being done in stages. This document describes stage 1 and what is
left.

## The components

They are template tags in `apps/frontend/templatetags/components.py`. Load
them with `{% load components %}`.

### Page header

```django
{% page_header eyebrow="Finance" title="Cost Catalogue" description=intro %}
  <a href="{{ add_url }}" class="edify-action-button primary h-9">Add cost</a>
{% endpage_header %}
```

| Part | How to pass it |
| --- | --- |
| `title` | Argument or slot. Becomes the page's `<h1>`. |
| `eyebrow`, `description` | Argument or slot. Left out when empty. |
| Controls | The body of the tag. The wrapper is left out when the body renders nothing, for example behind a role check. |
| `aside` | Slot. Anything else the header carries, drawn after the controls as written. |
| `element` | `"div"` to keep a wrapper that was a `<div>`. The default is `<header>`. |

### Filter bar

```django
{% filter_bar action="/loans" label="Loan register filters" form_id="bt-loan-filters" %}
  <label>…<select name="mfi">…</select></label>
{% endfilter_bar %}
```

The fields are the body. The form applies itself when a field changes, which
has been the platform's one filter model since 2026-10-01. It keeps a submit
button only inside `<noscript>`. Pass `reset_url` to draw a Clear link, and
`extra_class` for a layout class the page still needs.

### Data table

```django
{% data_table name="monitor-list" %}
  {% slot title %}{{ monitor_gap_label }}{% endslot %}
  {% slot summary %}{{ pager.total }} schools{% endslot %}
  {% slot caption %}Schools with the staff who hold them.{% endslot %}
  {% slot empty %}{% include "components/empty_state.html" with message="No schools." %}{% endslot %}
  {% slot footer %}{% include "components/table_pager.html" with pager=pager %}{% endslot %}
  <thead>…</thead>
  <tbody>…</tbody>
{% enddata_table %}
```

It writes the card, the title band, the scroll region and the `<table>`. The
body is the table's rows. A body that renders nothing draws the `empty` slot
in the table's place, so wrap the rows in the `{% if %}` that decides whether
there is anything to show.

## Arguments and slots

An argument is a template expression: a quoted string, a variable, or a
variable with filters. A part that needs logic, or mixes words with a
variable, is a slot:

```django
{% page_header eyebrow="Planning" %}
  {% slot title %}{% if lens == "country" %}Country{% else %}Team{% endif %} Oversight{% endslot %}
  {% slot description %}{{ total }} visits · {{ completed }} completed{% endslot %}
{% endpage_header %}
```

A misspelt argument or slot name is an error when the template loads, not a
part that silently goes missing.

## Where the platform stands

Counts are held by `apps/frontend/test_component_adoption.py`. Each ceiling is
the current count of the thing being replaced. Lower a ceiling when a change
lowers its count; never raise one. The two stylesheet ceilings sit ten above
their counts so that branches in flight on 2026-10-02 can land.

| | On the component | Still hand-written |
| --- | --- | --- |
| Page headers | 105 on the tag, 7 on the include | 112 |
| Filter forms that apply on change | 7 | 12 |
| Tables (counted, not held) | 4 | 333 |

| Guesswork in the stylesheets | Count |
| --- | --- |
| `!important` declarations | 3,959 |
| Selectors that match a substring of a class name | 567 |

## What is left

1. **The remaining headers.** They differ from the canonical anatomy: a
   wrapper between the header and its lead, a width utility that has an
   effect, a second row of content. Each needs a decision about the page, not
   a script.
2. **Filter forms.** The twelve hand-wired forms use four different class
   sets (`platform-filter-bar`, `edify-filter-bar`, bare flex utilities,
   `data-component="filter-toolbar"`). Moving one changes which stylesheet
   rules reach it, so move them one page at a time and look at the result.
3. **Tables.** About a hundred class combinations across 333 tables. Move a
   table when its page is next worked on.
4. **The stylesheets.** The components do not yet own their CSS. The step
   that pays off is to give each component one stylesheet that selects its
   class, then delete the heuristic rules that component no longer needs. The
   two counts above are the measure of that work.

## Adding a page

Use the three tags. Do not write `class="edify-page-header"` or a `<form>` with
its own `requestSubmit()` by hand: the ratchet will fail. A table that fits the
card anatomy uses `{% data_table %}`.

## Column headings

Owner, 2026-10-08: "On every table in the platform can we add a line under the
column header and instead of all upper case column header, Capitalise Case for
the column head, increase the font size and make it bold and don't change the
font color to blue. You can keep the font color same as the table body font
color only make it bold and elegant." Then, the same day, on the size: "just
slightly bigger not large. It is the Table Header (table name) that should be
larger since it is not in any column."

So a table reads in three steps of the one type scale, largest first:

| Part | Step | At a 1440px window |
| --- | --- | --- |
| The table's name, in the band over it | `--edify-text-table-title-size` (the title step), bold | 16.4px |
| The column names | `--edify-text-table-heading-size` (the body step), bold | 14.7px |
| The cells | `--edify-text-table-size` (the label step) | 13.7px |

The name's rule is the title band's (`.edify-table-titlebar`, in
`consistency.css`); it covers the `h2`–`h5` that names the table and leaves
the band as slim as it was (the 2026-09-27 rule that the band must not
dominate still holds for its height). A caption beside the name stays on the
label step.

One rule in `consistency.css` (COLUMN HEADINGS) covers the column names of
every table in a page, a drawer or a dialog, in every theme:

| | Before | Now |
| --- | --- | --- |
| Case | capitals in the light theme, as typed in the others | Title Case (`text-transform: capitalize`) |
| Ink | blue `#285b96` in the light theme, muted elsewhere | the cells' own ink (`--edify-text-muted`, which is what a cell is drawn in) |
| Size | one step below the cells (`--edify-text-micro-size`) | one step above the cells (`--edify-text-table-heading-size` is `--edify-text-body-size`) |
| Weight | 600 | 700 (`--edify-table-header-weight`) |
| Line | none (the plain-table rule takes every border off) | 2px in `--edify-border-strong` under the heading row |

Write a heading as words in the template ("Visit date", "Delivered by") and
let the rule set the case. An abbreviation typed in capitals stays as typed
("CCEO", "SF ID"). Do not add `uppercase`, a text colour or a size class to a
`th`: the rule outranks them.

Checked by crawl on 2026-10-08: 4,654 headings on 546 tables across the 470
pages nine roles reach, in the light theme, and a sample in dark and blue.
What does not match is a screen-reader-only label, and the fund breakdown
ledger, whose cells are a step larger than a standard table's.

**What a larger column name costs in width.** A column is as wide as the wider
of its heading and its cells, and a table that no longer fits its card wraps
its headings or scrolls (micro-ux.js, `wrapLongText` and `columnPlan`). So
the size was measured before it was kept: 294 tables at 1440px and 1280px,
drawn three ways. Title Case at 14.7px bold is *narrower* than what it
replaced — capitals at 12.7px with 0.05em letter-spacing — so every table
that changed behaves as it did or scrolls less (Loans 78px → 28px, CPD
Learning 81px → 20px). One table needed a change: Planning fixes its column
widths, and "Responsible" was cut by 5px at 6rem, so that column is 6.5rem.
A table that sets a column's width by hand must leave room for its heading
at this size.

## A click is answered at once

Owner, 2026-10-08: "when you click on live website it takes too long to switch
from the current page to the page clicked from the side bar menu", then
"investigate all the click related response issue system wide".

What was measured:

- **The live site, from Kampala.** A request that does no work takes about
  0.37 s there and back; the sign-in page 0.45 s. Stylesheets and scripts are
  not the cost: they are content-hashed, `immutable`, and served from the edge
  cache in under 10 ms.
- **Every kind of control** (`click` to first change on screen): a drawer
  button 4-10 ms and a row's Actions menu 1-2 ms; a save relabels its button;
  a link that leaves the page (sidebar, tab, row, pager) and a filter form
  showed **nothing** until the next page replaced the old one.
- **Why nothing.** Each of those loads a whole document, and the page the
  reader came from stays on screen until the new one can be drawn whole
  (`rel="expect"` in `base.html`, kept on 2026-10-05 so there is no blank or
  black frame between pages). So the wait is the network, the server and the
  browser added together, with no sign the click was taken.
- **The server, at production size** (a 16,700-school copy, local machine,
  under other load): a Programme Lead's pages answer in 0.2 s at the median and
  0.8 s at the 90th percentile, a CCEO's 0.35 s and 0.9 s, the Country
  Director's 0.3 s and 2.9 s. The heaviest: Country Director Analytics 4.6 s,
  Country Map 3.5-4.2 s (3.5 MB of HTML), Clusters 3.6 s, SSA 3.4 s, the
  portfolio view of Planning Oversight 3.4 s; Core Schools' oversight lens 4.7 s
  for a Lead; To-Do 1.5-1.8 s for everyone (176 small queries, kept for 15 s).

`static/js/click-feedback.js` answers the click in the frame after it. It does
not make the next page arrive sooner.

| Click | What shows at once |
| --- | --- |
| A link that leaves the page | a line across the top of the window (`:root[data-edify-loading]::after`, `interactions.css`) |
| A sidebar or bottom-bar entry | the line, and the entry takes the chosen look |
| A form the browser submits (filters) | the line |
| An htmx GET started by a click (a tab or panel fetched into the page) | the line, until the answer is in |

Left alone: a new tab, a download or export, a link to the same page, a save
(its button already says "Saving…"), typing in a search box. The line gives up
after 12 seconds, and when "Leave this page?" is answered No.

Not done, and why:

- **Fetching on hover.** Sidebar links are fetched at pointer-down already
  (speculation rules). Fetching on hover would save a further 0.2-0.4 s, but a
  page fetched is a page the Staff Activity Log counts as opened, and it was
  turned off for the analytics menus on 2026-09-23 for the renders it started.
- **The heavy pages themselves.** Each needs its own query work, measured at
  production size; the list above is where to start.

## Tick boxes

Owner, 2026-10-05: "all the places with checkboxes can you add Select All
Checkbox", and "use checkboxes to mark all the cluster meetings or group
training, or school visits ... and then select reschedule in the action
buttons". One script, `static/js/group-select.js`, loaded by the shell, does
both. It reads attributes and keeps no state of its own, so a list swapped in
by htmx or drawn by Alpine works without being registered.

**Select all.** A checkbox carrying `data-select-all` ticks every enabled box
that can be seen in its scope: the nearest `[data-select-scope]`, else the
table, fieldset or form it sits in. Give it a selector as its value where the
scope holds other boxes too (`data-select-all="input[name=staffIds]"`). Each
box gets its own `change` event, so a list bound with `x-model` or counted by
an `@change` handler keeps up, and the box reads back ticked, part-ticked or
clear as the list changes. For a list in a form:

```django
{% include "partials/components/select_all.html" with boxes="input[name=staffIds]" %}
```

A table's tick column puts the box in its header cell instead.

A list where ticking everything is not a choice anyone makes has none: a set
of return reasons, the nine attestations of an IA review, a list of roles to
grant. `SelectAllContract` in `apps/frontend/test_group_select.py` names each
one and why, and fails when a template repeats a tick box without a Select
all.

**Ticked activities.** A planned activity the reader may move or cancel
carries `input[data-activity-pick]` with the activity's id as its value:

```django
{% include "partials/activities/pick_head.html" %}   {# the header cell #}
{% include "partials/activities/pick_cell.html" with pick_id=row.id pick_kind=row.activity_type_label pick_name=row.school_name pick_day=row.planned_date %}
{% include "partials/activities/selection_bar.html" %}  {# once per page #}
```

Ticking one shows the bar with Reschedule, Cancel and Clear. The two buttons
open `/activity-selection/reschedule` and `/activity-selection/cancel`, which
list what will change and what will be left, and why
(`apps/activities/group_actions.py`). The same activity drawn twice (a
calendar's month grid and its agenda) is one tick. Draw the tick column only
where a row on the page can be ticked (`|any_attr:"can_pick"`), and put the
bar where it is always rendered: not inside a folded `<details>`.

It is on My Plan, the Work Plan, the Dashboard's past-due tables, a Program
Lead's week tables, the Planned table of every profile, the Calendar and
Planning's Calendar View.

**Ticked schools.** A list of schools ticks by business id into an Alpine
`selectedSchools` list, and `partials/schools/bulk_bar.html` is the bar over
it (owner, 2026-10-06: the Core school list and a cluster's roster "get the
bulk assign, schedule, bulk add to project just like these other schools"):

```django
<div x-data="{ selectedSchools: [] }" @planning-saved.window="selectedSchools = []" data-select-scope>
  {% include "partials/schools/bulk_bar.html" with boxes="input[data-core-pick]" bar_next="/core-schools" %}
  … <input type="checkbox" value="{{ school.school_id }}" x-model="selectedSchools" data-core-pick> …
</div>
```

Its three buttons are the doors the single row action opens, for the ticked
set: Assign to partner (`/planning/bulk-assign-partner-drawer`), Schedule
(`/planning/bulk-schedule-drawer`, one purpose and date, each school its own
costed activity, refusals named) and Add to project
(`/schools/bulk-assign-project-drawer`, the directory's save, `next` bringing
the planner back). Each shows only for a role its door opens for; a school a
door refuses is named in the drawer and left out, so every school has a box.
Pass `with_select_all=False` where the table head already carries the
Select-all box. On the school's own profile the same three are page-header
buttons, since there is one school to act on.

## Live regions

Owner, 2026-10-05: "Every event should update (schedules, school withdrawal
from the partner or project, training schedules, activity completion etc)
should update in real time and fast."

A page that shows the plan keeps up with it without being refreshed. Mark the
part that shows it:

```django
<div id="my-plan-workspace" data-live-region>…</div>
```

The region needs an id, and its state (filters, tab, page) belongs in the
address bar, because the page is read again from the address it is at.

How it works:

- `apps/activities/live.py` hangs on the save and delete of an activity, a
  hand-over to a partner, a school's place in a project and somebody's leave
  (the Calendar draws it and planned work on that day is marked). After the change
  commits it sends a `plan.changed` event, carrying only the time, to the
  people whose pages show that record: the owner and the monitor, the people
  they report to, the holder of the school or cluster, the partner, the
  project's coordinator and the country readers.
- `static/js/live-regions.js` opens the stream the server already had
  (`/api/realtime/stream`) on a page that has a live region. On the event it
  fetches the page it is on and replaces each marked region with the fresh
  one of the same id, then lets htmx, Alpine and the table scripts take it up.
- It never swaps under an open drawer, a ticked activity or school, a ticked
  row of any region's table, an open Actions menu or a field in use: it waits
  until they are done. A hidden tab closes its stream; when it is looked at
  again the stream says whether anything changed meanwhile, and only then is
  the page read again.
- After a read the page rests a second, or as long as the read took. A
  change that arrives while it rests is read when the rest ends, and the
  next rest is twice as long, up to sixteen seconds; a rest that ends with
  nothing waiting starts again at one. So one save, or a save in several
  steps, is on the page at once, and changes that keep coming cost the
  server one read per rest, not one per change (owner, 2026-10-06: the app
  froze when many people were on).

Everything a reader counts from belongs inside a region: the tabs with their
numbers, the table and the summary (owner, 2026-10-07: "make sure the table
pill counters are also accurate and refreshes with changing data ... and
should apply to the tables and summaries as well"). A summary strip that sits
outside its page's live part takes an id of its own:

```django
{% include "components/context_metrics.html" with items=kpis live_id="planning-context" %}
{% kpi_strip live_id="programme-schools-context" %}…{% endkpi_strip %}
```

Not live, on purpose: the role dashboards' headline strips (their payload is
kept five minutes, `cached_role_dashboard`), maps, and pages whose records do
not announce themselves (budgets, HR, analytics). A public holiday or an
organisation event is not announced either: it would be read by every open
page in the country at the same instant.

A region that holds state the address does not (rows opened, a tab chosen in
the page) looks after it itself, as Country Planning Oversight's two tables
do (`partials/country_oversight/_table.html`, `_types.html`):

- a tab chosen with Alpine is kept in a `window` variable and read back when
  the region is drawn again;
- while a reader has rows open the region gives up its mark
  (`:data-live-region="open ? false : ''"`), notes that it missed a change
  (`@edify:live-refreshed.document`), and calls `window.EdifyLive.refresh()`
  once the rows are closed. A region whose view cannot be recovered at all
  (the execution lens's table of five views) is left unmarked.

A page that serves kept figures tells the reader when to ask again. Country
Oversight rebuilds its fold no more often than its settle window, so a read
inside the window includes `partials/country_oversight/_settle.html`, which
asks once more when newer figures are due (`freshness.settles_in`). The page's
own re-read names itself (`X-Requested-With: EdifyLive`): it is never a forced
rebuild (`freshness.live_read`), never marks the person as present in the
Staff Activity Log and never keeps their session open
(`SlidingSessionMiddleware`; docs/session-and-mfa-policy.md, "What counts as
activity").

The settled hooks run a moment after the swap, as htmx's own do: fired at
once, the table scripts moved rows before Alpine had seen them and every menu
inside the region was left dead.

Production needs the ASGI workers and Redis the stream was built for
(`Procfile`). `LIVE_UPDATES_ENABLED=false` switches the announcements off
without a deploy; under the test runner they are off unless a test turns
them on, so they add nothing to the suite's query counts. Locally the stream
needs `manage.py runserver` without `--noasgi`.
