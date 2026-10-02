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
