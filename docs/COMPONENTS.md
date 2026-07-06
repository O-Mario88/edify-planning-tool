# Edify Component Library

Shared template partials that enforce design-system consistency. **Every new
page should use these instead of inlining Tailwind soup.** This is how the app
stays visually coherent as it grows — change a component here, every screen
updates.

All components live in `templates/components/` and are loaded via
`{% include %}`. They build on the `.btn` / `.card` CSS classes in
`static/css/components.css` and the tokens in `static/css/design-system.css`.

---

## Quick reference

### Button
```django
{% include "components/button.html" with variant="primary" label="Save" %}
{% include "components/button.html" with variant="ghost" size="sm" label="Cancel" href="/back" %}
{% include "components/button.html" with variant="danger" label="Delete" type="submit" %}
```
| Prop | Values | Default |
|---|---|---|
| `label` | (required) button text | — |
| `variant` | `primary` \| `ghost` \| `success` \| `danger` \| `warning` \| `smooth` | `primary` |
| `size` | `sm` \| `md` \| `lg` | `md` |
| `href` | renders `<a>` instead of `<button>` | — |
| `type` | `button` \| `submit` | `button` |
| `icon` | Heroicons SVG path data (16px) | — |
| `full` | `"true"` → full width | — |
| `disabled` | `"true"` | — |

### Card (header)
```django
<div class="card p-5">
  {% include "components/card.html" with title="Budget Snapshot" subtitle="Q3 portfolio" action_label="View all" action_href="/finance" divider="true" %}
  <!-- body content -->
</div>
```
| Prop | Values | Default |
|---|---|---|
| `title` | (required) | — |
| `subtitle` | muted secondary line | — |
| `action_label` + `action_href` | renders a header link | — |
| `tone` | `info` \| `success` \| `warning` \| `danger` (tints title) | — |
| `divider` | `"true"` → border-bottom after header | — |

### Badge / Pill
```django
{% include "components/badge.html" with tone="success" label="Active" %}
{% include "components/badge.html" with tone="danger" label="Overdue" dot="true" %}
```
| Prop | Values | Default |
|---|---|---|
| `label` | (required) | — |
| `tone` | `success` \| `warning` \| `danger` \| `info` \| `neutral` \| `purple` | `neutral` |
| `size` | `sm` \| `md` | `sm` |
| `dot` | `"true"` → prepend a status dot | — |

### KPI Card
```django
{% include "components/kpi_card.html" with label="Completed Visits" value="1,243" delta="+12%" delta_tone="success" tone="info" %}
```
| Prop | Values | Default |
|---|---|---|
| `label` + `value` | (required) | — |
| `delta` | e.g. `"+12%"`, `"-3"`, `"vs last week"` | — |
| `delta_tone` | `success` \| `danger` \| `neutral` | `neutral` |
| `tone` | `info` \| `success` \| `warning` \| `danger` (tints value) | — |
| `icon` | Heroicons SVG path data | — |
| `hint` | tiny caption under delta | — |

### Empty State
```django
{% include "components/empty_state.html" with title="No activities yet" message="Schedule your first visit to get started." cta_label="Schedule" cta_href="/planning" %}
```
| Prop | Values | Default |
|---|---|---|
| `title` | (required) | — |
| `message` | explanatory line | — |
| `cta_label` + `cta_href` | action button | — |
| `tone` | `neutral` \| `success` \| `info` (tints icon) | `neutral` |
| `compact` | `"true"` → for inside cards | — |

### Form Input
```django
{% include "components/input.html" with label="Email" name="email" type="email" placeholder="you@org.org" required="true" %}
{% include "components/input.html" with label="Amount" name="amount" type="number" hint="UGX" error="Required" %}
```
| Prop | Values | Default |
|---|---|---|
| `label` + `name` | (required) | — |
| `type` | `text` \| `email` \| `number` \| `password` \| `date` \| `tel` | `text` |
| `placeholder`, `value` | — | — |
| `hint` | helper text | — |
| `error` | error message (renders error state) | — |
| `required` | `"true"` → asterisk + required attr | — |
| `inputmode` | `numeric` \| `decimal` \| `tel` \| `email` | — |
| `extra_attrs` | raw HTML attrs (e.g. `hx-post="/x" hx-target="#y"`) | — |

---

## Rules for new components

1. **One source per pattern.** If a button exists, every button uses it. No
   one-off Tailwind buttons.
2. **Props, not HTML.** Components accept `{% include %}` params, never require
   the caller to know their internal classes.
3. **Token-driven.** Internal styling uses `var(--edify-*)` or the `.btn`/`.card`
   classes — never raw hex.
4. **Documented here.** Every new component gets a usage block in this file.
5. **Default to safe.** Every optional prop has a sensible default so the
   minimal include (`{% include "components/button.html" with label="OK" %}`)
   renders correctly.

## Migration guide

Pages don't need to be refactored all at once. When you touch a page for any
reason, swap its inline patterns for components:

- `bg-blue-600 ... rounded-xl ... text-[14px]` → `{% include "components/button.html" %}`
- `bg-white rounded-2xl border ... <h3>title</h3>` → `.card` + `{% include "components/card.html" %}`
- `bg-emerald-50 text-emerald-700 rounded-full ...` → `{% include "components/badge.html" %}`
- `<p class="text-center text-slate-400">No items</p>` → `{% include "components/empty_state.html" %}`

Each migration makes the next one easier and the app more consistent.
