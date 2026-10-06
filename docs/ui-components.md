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
  hand-over to a partner and a school's place in a project. After the change
  commits it sends a `plan.changed` event, carrying only the time, to the
  people whose pages show that record: the owner and the monitor, the people
  they report to, the holder of the school or cluster, the partner, the
  project's coordinator and the country readers.
- `static/js/live-regions.js` opens the stream the server already had
  (`/api/realtime/stream`) on a page that has a live region. On the event it
  fetches the page it is on and replaces each marked region with the fresh
  one of the same id, then lets htmx, Alpine and the table scripts take it up.
- It never swaps under an open drawer, a ticked activity, an open Actions
  menu or a field in use: it waits until they are done. A hidden tab closes
  its stream; when it is looked at again the stream says whether anything
  changed meanwhile, and only then is the page read again.

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
rebuild (`freshness.live_read`) and never marks the person as present in the
Staff Activity Log (`SlidingSessionMiddleware`).

The settled hooks run a moment after the swap, as htmx's own do: fired at
once, the table scripts moved rows before Alpine had seen them and every menu
inside the region was left dead.

Production needs the ASGI workers and Redis the stream was built for
(`Procfile`). `LIVE_UPDATES_ENABLED=false` switches the announcements off
without a deploy; under the test runner they are off unless a test turns
them on, so they add nothing to the suite's query counts. Locally the stream
needs `manage.py runserver` without `--noasgi`.
