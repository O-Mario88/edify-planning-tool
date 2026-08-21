# Edify design token report — 21 August 2026

The canonical token source is `static/css/design-system.css`. Tailwind aliases and legacy bridges must resolve to this layer; templates may not introduce colours or presentation with raw hex values or `<style>` blocks.

## Typography

| Tier | Token | Size | Intended use |
|---|---|---:|---|
| Display | `--edify-text-display-size` | 1.75rem | page title |
| Heading | `--edify-text-heading-size` | 1.25rem | major section |
| Title | `--edify-text-title-size` | 1rem | card/record title |
| Body | `--edify-text-body-size` | 0.9375rem | operational copy |
| Label | `--edify-text-label-size` | 0.875rem | fields, table headings, metadata |
| Micro | `--edify-text-micro-size` | 0.75rem floor | eyebrows, badges, compact status only |

Geist Sans is the single product family. Tables explicitly use the label tier; numeric content uses tabular figures. Tests reject CSS below 12px, unnamed CSS below 14px, tiny one-off template utilities, and micro-sized table structure.

## Spacing and grid

The base scale is 0, 4, 8, 12, 16, 20, 24, 32, 40, 48, and 64px through `--edify-space-*`. Semantic aliases are `xs`, `sm`, `md`, `lg`, `xl`, and `2xl`. Page canvases, headers, cards, content rows, and drawers use these values or fluid `clamp()` expressions anchored to them.

Responsive rules use content-first breakpoints: phone below 48rem, tablet/intermediate through 64rem, desktop from 64rem, plus container queries for KPI trays. The mobile control standard is 48px for text-entry controls and at least 44px for interactive targets; checkboxes/radios keep native geometry while their labels own the touch target.

## Radius

| Surface | Canonical radius |
|---|---:|
| Small/detail | 6px |
| Controls | 8px |
| Cards/surfaces | 12px |
| Drawers/modals/overlays | 16px |
| Badges, avatars, pills | full/pill only |

Arbitrary 2xl/3xl/template radii fail the page scanner.

## Colour and themes

Semantic groups cover canvas, surfaces, text, borders, brand, success, warning, danger, information, disabled, selection, charts, backdrops, focus, and inverse content. Light, Blue, and Dark are actual palettes; System resolves to Light or Dark and follows OS changes. Theme colour for browser chrome is read from computed `--edify-bg` after tokens load.

Raw values are permitted only inside token declarations, the generated Tailwind utility bundle, and documented browser/third-party boundaries. Product templates are held to zero raw hex colours, zero opaque `bg-white` theme leaks, and zero unsafe static inline styles.

## Elevation

The governed scale is `--edify-shadow-sm`, `--edify-shadow-md`, `--edify-shadow-lg`, and `--edify-shadow-drawer`. Blue and Dark themes intentionally flatten selected elevations. The undefined legacy `--edify-shadow-xl` use was removed.

## Motion

`--edify-transition-fast` (150ms) and `--edify-transition-all` (200ms) use the shared standard easing. Motion communicates state rather than decorating navigation. `prefers-reduced-motion` disables component animation and map transforms. Cross-document view transitions remain disabled to prevent shell flashes.

## Focus and accessibility

Brand-primary owns focus through `--brand-primary-focus`, `--edify-focus-ring`, and the shared outline contract. Keyboard focus is visible, pointer-only persistent rings are suppressed without suppressing keyboard rings, and forced-colours fallbacks are present. Critical information may not depend on hover or colour alone.

## Deprecated values

- Template `<style>` blocks: prohibited; current count **0**.
- Raw template colours and opaque white surfaces: prohibited; current findings **0**.
- `rounded-2xl`, `rounded-3xl`, arbitrary large radii: prohibited except scanner-approved overlay primitives.
- `--edify-shadow-xl`: undefined and removed.
- Micro typography for table rows/headers: prohibited.
- Side-specific, theme-forced drawer overrides: removed in favour of the base drawer.
- Per-page KPI/card visual systems: deprecated; the shared executive KPI tray is canonical.

