# Live interaction coverage report

## Scope and accounting

| Measure | Result |
|---|---:|
| Registered routes | 1,043 |
| API routes | 359 |
| Routed surfaces | 575 |
| Full pages | 203 |
| Browser-visited distinct argument-free pages | 159 |
| Authenticated role-route visits | 879 |
| Rendered control instances inventoried | 97,699 |
| Visible control instances inventoried | 47,554 |
| Browser crawl errors | 0 |
| Active roles tested locally | 14 |

The Django route crawl exercises resolver, method, authentication, and permission behavior over the full registered route set. The browser crawl opens every permitted, argument-free page listed by the generated page inventory for each role. Parameterized record routes and mutation-only endpoints are covered by Django tests where fixtures exist, but they were not all operated through a real browser.

The 97,699 figure counts repeated shell controls each time a page is rendered for a role. It is not a unique-control count and it is not evidence that every control was clicked. The browser audit validates status, render completion, DOM bounds, horizontal overflow, console/page errors, and accessible names. Under the requested stricter definition, exhaustive interaction coverage is **blocked and below 100%**.

## Coverage by role

| Role | Pages opened | Control instances | Visible controls | Crawl errors |
|---|---:|---:|---:|---:|
| CCEO | 63 | 7,399 | 3,375 | 0 |
| Program Lead | 79 | 11,240 | 5,196 | 0 |
| Country Director | 89 | 11,534 | 5,229 | 0 |
| Regional Vice President | 68 | 1,490 | 930 | 0 |
| Impact Assessment | 75 | 8,270 | 4,121 | 0 |
| Accountant | 70 | 6,463 | 2,991 | 0 |
| HR | 60 | 7,707 | 3,695 | 0 |
| Project Coordinator | 56 | 1,475 | 971 | 0 |
| Partner Administrator | 38 | 1,169 | 773 | 0 |
| Partner Field Officer | 38 | 3,918 | 2,265 | 0 |
| Business Transformation | 32 | 781 | 405 | 0 |
| Lending Partner Administrator | 28 | 761 | 393 | 0 |
| Lending Partner Loan Officer | 28 | 761 | 393 | 0 |
| Administrator | 155 | 34,731 | 16,817 | 0 |

## Browser and device coverage

| Profile | Authenticated full role crawl | Public smoke | Freeze regression |
|---|---|---|---|
| Chromium desktop | Pass, all 14 roles | Pass | Pass |
| Firefox desktop | Not run | Pass | Pass |
| WebKit desktop (Safari engine) | Not run | Pass | Pass |
| Android 360 emulation | Not run | Pass | Pass |
| iPhone 390 emulation | Not run | Pass | Pass |
| iPad/tablet 768 emulation | Not run | Pass | Pass |
| Native Microsoft Edge | Not run | Not run | Not run |
| Physical low-end Android/iPhone/tablet | Not run | Not run | Not run |

## Production-safe validation

The live production URL `https://www.edifyplanning.app` passed public login and liveness/readiness smoke checks across the configured browser/viewport matrix. No production credentials, synthetic isolation facility, or approved test records were available, so authenticated and mutating live controls were not exercised.

## Blocked coverage

- Every visible control clicked with success and validation-failure paths.
- Every state-dependent workflow action through Draft, Submitted, Returned, Approved, Paid, Canceled, and other required states.
- Destructive actions against isolated production-equivalent records.
- Every download/export content opened and semantically validated.
- Notification and To-Do deep links in all workflow states.
- Browser double-click, back-submit, stale-page, two-session, and network-interruption scenarios for every mutation.
- Authenticated Firefox/WebKit/mobile/tablet role crawls and physical-device accessibility/keyboard testing.
