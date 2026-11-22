# Google Maps Platform Integration & Provider Architecture

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22

---

## 1. Supported APIs & Multi-Stage Routing Compliance

Edify's Go routing client (`platform/backend/internal/routeplan/google.go`) implements the modern **Google Maps Routes API v2** (never deprecated Directions/Distance Matrix legacy APIs) with strict adherence to Google API constraints:

| Capability | Endpoint / SDK | Implementation File | Constraint Compliance |
|---|---|---|---|
| **Road Distance Matrix** | `POST /distanceMatrix/v2:computeRouteMatrix` | `internal/routeplan/google.go` | Uses `routingPreference: "TRAFFIC_AWARE"`, `travelMode: "DRIVE"`, minimal `X-Goog-FieldMask`, bounded `<= 625` elements. |
| **Stage 1 Waypoint Ordering** | `POST /directions/v2:computeRoutes` (`OptimizeWaypointOrder`) | `internal/routeplan/google.go` | Uses `optimizeWaypointOrder: true` paired strictly with `routingPreference: "TRAFFIC_AWARE"`. **Never combines `optimizeWaypointOrder` with `TRAFFIC_AWARE_OPTIMAL`.** |
| **Stage 2 Traffic-Optimal Geometry, Steps & Alternatives** | `POST /directions/v2:computeRoutes` (`RouteDetailed`) | `internal/routeplan/google.go` | Uses `routingPreference: "TRAFFIC_AWARE_OPTIMAL"`, `extraComputations: ["TRAFFIC_ON_POLYLINE"]`, `computeAlternativeRoutes: true` (when no intermediates), and full step `navigationInstruction` field masks. |
| **Web Interactive Map** | Google Maps JS API (when `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` set) + MapLibre/OSM road fallback | `platform/web/src/components/route/RouteMap.tsx` | Official attribution preserved; traffic toggle discloses when Google JS key is unconfigured rather than fabricating congestion. |
| **Mobile Embedded Navigation** | Embedded `InAppNavigationModal` (`expo-location` + Go road directions) + `@googlemaps/react-native-navigation-sdk` compatibility path | `platform/mobile/src/screens/route/InAppNavigationModal.tsx` | Keeps navigation 100% inside Edify. See Section 4 below for native SDK build prerequisites. |

## 2. Automated Multi-Stage Verification

`TestGoogleRoutesV2_MultiStageCompliance` in `platform/backend/internal/routeplan/smart_optimize_test.go` verifies against an `httptest` Google Routes v2 mock server:
1. Stage 1 fails the test immediately if `optimizeWaypointOrder: true` is ever sent with `TRAFFIC_AWARE_OPTIMAL`.
2. Stage 2 asserts `routingPreference == "TRAFFIC_AWARE_OPTIMAL"`, `navigationInstruction` in `X-Goog-FieldMask`, `TRAFFIC_JAM` speed interval parsing (`900s` delay), turn-by-turn instruction decoding (`"Turn right onto Jinja Road"`), and alternative route extraction (`"Northern Bypass"`).

## 3. Local Development Keyless Road Provider (OSRM)

When no Google server key is provisioned in local development, Go supports `EDIFY_ROUTING_PROVIDER=osrm` (`platform/backend/internal/routeplan/osrm.go`), requesting `overview=full&geometries=geojson&steps=true&alternatives=true` from an OSRM server (tested live against `https://router.project-osrm.org`). Because OSRM has no live traffic feed, it honestly sets `traffic_state: "unavailable"` and never fabricates congestion.

## 4. Mobile Native Google Navigation SDK (`@googlemaps/react-native-navigation-sdk`) Compatibility Assessment

- **Installed Mobile Stack:** Expo `~58.0.26`, React Native `0.88.1`, React `19.3.0`.
- **Compatibility Honesty:** `@googlemaps/react-native-navigation-sdk` embeds native Android (`NavigationApi`) and iOS (`GMSNavigator`) binaries and **does not run inside Expo Go**. Deploying full native voice-guided turn-by-turn navigation requires:
  1. Custom Expo prebuild / EAS Native Development Builds (`expo run:android` / `expo run:ios`),
  2. Licensed Google Navigation SDK credentials & billing agreement enabled on the GCP project,
  3. Platform-restricted Android SHA-1 and iOS Bundle ID API keys.
- **What Is Live & Verified Today:** Edify's embedded `InAppNavigationModal` provides road-following geometry, live debounced `expo-location` GPS tracking, next-maneuver card, step list, ETA, and rerouting across Expo, iOS, Android, and Web without ever launching Google Maps, Apple Maps, or Waze.

## 5. Production Activation Checklist (Pending Credentials)

- Provision server-restricted `EDIFY_GOOGLE_ROUTES_KEY` (IP-restricted, Routes API only) and set `EDIFY_ROUTING_PROVIDER=google`.
- Provision HTTP-referrer-restricted `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` (Maps JavaScript API only) for live Google Traffic Layer & vector tiles in production.
- Never commit API keys to Git or expose the server Routes key to browser/mobile bundles.
