# Frontend remediation log — 21 August 2026

| Finding | Principal files | Shared contract changed | Route family | Verification |
|---|---|---|---|---|
| UI-20260821-001 | `templates/base.html`, `static/css/design-system.css` | document/form/table/focus foundation | all authenticated pages | design-system quality + shell/mobile tests |
| UI-20260821-002 | cluster drawer partials, `static/css/drawers.css` | base drawer and themed surface | `/clusters/*drawer*` | cluster workflow + drawer tests |
| UI-20260821-003 | canonical document template, `static/css/pages/document-agreement.css` | scoped document contract | `/documents/*` agreement | agreement contrast tests |
| UI-20260821-004 | upload center template, `static/css/components.css` | native dialog/drawer | documents upload center | documents tests |
| UI-20260821-005 | help print templates, `static/css/help-center.css` | print typography/theme | `/help/*print*`, `/help/export/*` | type-scale and template scans |
| UI-20260821-006 | priority configuration template, `static/css/pages.css` | responsive priority grid | HR priority configuration | mobile workflow and design tests |
| UI-20260821-007 | planning template, `static/css/calendar-workspace.css` | semantic FullCalendar states | planning/calendar | calendar workspace tests |
| UI-20260821-008 | regional performance partial, `static/css/components.css` | map focus/theme/motion | analytics/project analytics | regional tooltip and analytics decision tests |
| UI-20260821-009 | `static/css/components.css` | elevation scale | filter drawers | design-system tests |
| UI-20260821-010 | `static/css/design-system.css` | table typography | all tables | type-scale floor tests |
| UI-20260821-011 | page inventory module/command/tests | stable page/component audit schema | 565 surfaces | manifest drift and completeness tests |

Focused remediation verification: **253 tests passed**. Platform UI verification subsequently exercised **1,017 tests** and found two stale evidence-test references; both were corrected and their generated manifests refreshed. Final counts are recorded after the rerun and full application suite in the executive report/evidence manifest.

Business logic, arithmetic, role authority, queryset scope, and workflow transition ownership were not moved into the browser or weakened by these changes.

