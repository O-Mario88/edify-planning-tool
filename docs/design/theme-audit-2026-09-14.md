# Blue and night theme audit — 14 September 2026

Scope: shared theme tokens, dashboard lists and progress tracks, work-plan tables,
neutral dividers, links, navigation and form surfaces. This is a shared-component
review, not a certification of every individual screen.

## Findings and changes

- Blue mode inherited the light `--edify-divider`, producing bright rules in
  Training and delivery, Spiritual transformation and other divider consumers.
  Blue now supplies a low-contrast decorative divider independently of its
  stronger field boundary. Table body and header dividers have separate values.
- Blue hover, selected, disabled and control-border tokens were inherited from
  light mode. They now have explicit dark-surface values.
- Several shared links and labels used primary-fill colour as text. They now
  use the theme's text accent; primary button fills remain unchanged.
- Legacy neutral divide utilities and table borders now resolve to theme tokens
  in both blue and night mode. Status colours and focus indicators remain distinct.

## Contract

Use `--edify-divider` for decorative separation, `--edify-table-divider` for rows,
`--edify-control-border` for interactive field boundaries and
`--edify-accent-text` for links. Do not brighten separators to meet control
contrast requirements: decorative rules are not controls.

## Validation

The regression test reads actual theme declarations: decorative divider contrast
is below 2:1, text accents meet 4.5:1 and control boundaries meet 3:1 against the
base surface. Existing blue/night theme checks also pass. Browser inspection
covered the work-plan tables, navigation, controls and surfaces in both themes.
