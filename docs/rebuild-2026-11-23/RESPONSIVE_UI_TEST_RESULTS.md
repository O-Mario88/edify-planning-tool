# Responsive UI test results

Automated Chromium check at 320, 375, 390, 430, 768, 1024, 1280, 1440, 1600 and 1920 px for page overflow, clipped tiles and headings, HTTP errors and page errors.

| Page | Views | Result |
|---|---|---|
| School Profile | Overview, Core, SSA, Details | 0 failures after fixes |
| Cluster Profile | Overview, Analytics, Attendance | 0 failures after fixes |
| Smart Route Planner | Day view | 0 failures |

Accessibility (axe, WCAG A/AA) at 1440 and 390 px: clean on School Profile, Cluster Profile, Route Planner, Schools, Core Oversight, Debriefs and Leave.

**Not tested:** Safari and Firefox, real devices, the iOS and Android native apps, dark mode on the rebuilt pages.
