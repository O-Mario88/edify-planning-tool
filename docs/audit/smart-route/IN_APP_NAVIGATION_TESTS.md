# In-App Navigation & Zero External Redirect Verification

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22

---

## 1. Zero External Maps Audit (Web & Mobile)

Every external map redirect (`google.com/maps`, `maps.apple.com`, `waze.com`, `Linking.openURL` to map apps) was audited and eliminated:

| File | Previous Behavior | Upgraded In-App Behavior |
|---|---|---|
| `platform/web/src/lib/routePlanner.ts` | `directionsUrl()` built external Google/Apple/Waze URLs | Replaced with `inAppDirectionsPath()` returning `/my-plan/smart-route?navigate=<schoolIds>` |
| `platform/web/src/components/route/RoutePlanner.tsx` | `<a href={directions} target="_blank">` | Opens embedded `InAppNavigationPanel` inside right panel synced to center map |
| `platform/web/src/components/route/LocationCard.tsx` | External `<a target="_blank">` on School Profile | Internal Next.js `<Link href="/my-plan/smart-route?navigate=...">` |
| `platform/mobile/src/screens/route/directions.ts` | `Alert` + `Linking.openURL` to Google/Apple/Waze | Publishes internal in-app navigation request; zero `Linking.openURL` |
| `platform/mobile/src/screens/route/RouteFlow.tsx` | Called external launcher | Renders embedded `InAppNavigationModal` |
| `platform/mobile/src/offline/LocationPanel.tsx` | Called external launcher | Renders embedded `InAppNavigationModal` |

**Automated Grep Proof (`platform/web/src` & `platform/mobile/src`):** `0` production references to `google.com/maps`, `maps.apple.com`, or `waze.com` (only negative `.not.toContain(...)` unit test assertions remain).

## 2. Live Web Acceptance Test H (Real Chromium Playwright)

Executed on `http://127.0.0.1:3091/my-plan/smart-route?date=2026-11-17`:

| Assertion | Measured Result | Status |
|---|---|---|
| Click **Get Directions (In-App)** | Opens `[data-block="in-app-navigation"]` inside Edify | PASS |
| Browser stays on Edify origin | `still_on_edify: true` (`http://127.0.0.1:3091/my-plan/smart-route?...`) | PASS |
| External tab / popup opened | `external_popup_opened: false` | PASS |
| External map links anywhere in DOM | `external_map_links_in_dom: 0` | PASS |
| Road-following geometry rendered | `data-path-is-road="true"` (`381` road vertices) | PASS |
| Turn-by-turn road steps rendered | `18` steps on Leg 1 (`"Depart on Kampala Road"`, `"Turn right"`, `"Turn left"`) | PASS |
| Live GPS tracking & debounced reroute | `navigator.geolocation.watchPosition` with `30m / 10s` debounce + `180m` deviation prompt | PASS |
| Runtime page/console errors | `0` page errors, `0` console errors | PASS |
| Screenshot evidence | `sr-in-app-directions.png`, `sr-mobile-bottom-sheet.png` | Captured |

## 3. Mobile Platform Verification & Scope Honesty

- **Verified Today:** TypeScript `tsc --noEmit` (`0` errors) and Jest (`35/35` suites, `277/277` tests including `routeData.test.ts` asserting zero external map URLs). `InAppNavigationModal.tsx` implements embedded map, `expo-location` debounced GPS (`30m` / `15s`), next maneuver hero banner, steps, ETA, and rerouting.
- **Pending Native Device Testing:** Physical Android and iOS native development build tests (and `@googlemaps/react-native-navigation-sdk` voice-guided turn-by-turn navigation once licensed Google Navigation SDK credentials are provisioned) cannot be executed in this headless macOS CLI environment and are explicitly tracked as pre-production release gates in `SMART_ROUTE_RELEASE_READINESS.md`.
