# Next task (high priority): Offline school GPS capture, location correction and Smart Route sync

Owner brief, 2026-11-14. Priority: **high** — "accurate school coordinates are foundational to every future routing, school coverage and geographic recommendation feature."

Builds on Verify Location (Addendum 3 of `next-smart-field-routing.md`, commit b0188105c): report / review / verified location in Go's `field_routes` schema; reviewers Program Lead, CountryDirector, Admin (owner confirmed 2026-11-14).

## Owner's addition (verbatim)

> make GPS Capture part of normal school visits rather than requiring a separate nationwide coordinate-collection exercise.
>
> When a user starts a school visit and Edify detects that the school has no saved coordinates, the app could display a small prompt: "This school has no GPS location. Capture it now?"
>
> For a school with existing coordinates, the user could see "Is this school's location correct?" and select Yes or Correct Location. Where offline, the answer and any new coordinates would be saved locally until synchronization.
>
> This would gradually improve the quality of Edify's school-location database as ordinary fieldwork continues. Over time, the Smart Route Planner would become more reliable without putting a large additional workload on staff.

## Brief (summary of the owner's pasted text; the full text is in the session transcript of 2026-11-14)

1. Architecture: web Next.js; mobile Expo + TypeScript; backend Go; Python analytics only. The School Directory is the authoritative school location. Expo: `expo-location`, `expo-sqlite`, `expo-network`, `expo-secure-store`; SQLCipher (or validated equivalent) for offline SQLite; no large records in SecureStore; verify native config and release builds.
2. Profile Location section: no coordinates → "GPS Location Not Captured" + **Capture School Location**; with coordinates → current location, lat, lng, verification status, date last verified, map pin, **Verify / Replace Location**, Get Directions; correction reason + optional landmark/access note; no manual typing when GPS is available.
3. Capture workflow: confirm School ID → permission (request if needed) → services on → fresh high-accuracy readings → "Capturing GPS" → check accuracy + timestamp, refuse stale cached fixes → retry → stop sampling → show coords + accuracy → confirm → save locally → queue. No background permission, no continuous tracking. Thresholds (configurable): ≤20 m Good, 21–50 m Needs confirmation, >50 m Recommend recapture; fresh timestamp, plausible stable readings; handle approximate-only permission, services off, errors, poor reception; never claim accuracy is guaranteed.
4. Offline school availability: sync assigned schools before fieldwork (School ID, name, coordinates, coordinate version, verification status, district, cluster, offline-access metadata); reopen offline; capture never needs the network.
5. Durable offline queue: client capture id / idempotency key, School ID, type New / Correction / Entrance, lat, lng, accuracy, timestamp, user, previous coordinate version and coordinates, reason, access note, status (Saved Offline, Pending Sync, Syncing, Synced, Awaiting Review, Conflict, Failed — Action Needed), retries; transactional; delete only after server-confirmed and recorded; survives restarts; visible Pending Sync count.
6. Automatic sync on connectivity: valid session → pending records → Go API with idempotency key → server re-checks authorization, School ID, coordinates, capture age, reason, coordinate version → transactional apply → returns authoritative version → local update → refresh profile and map. Backoff retries; expired auth keeps the record; revoked access is never bypassed; no promise of background sync while suspended.
7. New vs correction: new captures may auto-accept where policy permits; corrections keep history, measure displacement, flag large moves, poor accuracy, conflicts, low authority, inconsistency with administrative location → review. Never auto-reject a genuinely relocated school.
8. Audit history: previous/new coordinates, capture date, accuracy, user, reason, decision, reviewer, server date, version, status history; controlled viewer; no device travel exposed.
9. Optional school entrance / road-access coordinate, separate from the physical location; planner prefers a verified entrance for navigation; never overwrite one with the other.
10. Smart Route: on accept — commit, audit, durable School Location Updated event, invalidate stored recommendations, update projections, notify clients, bounded road recalculation, refresh pins, show version; dedup events; no country-wide recompute; respect provider licensing. Offline: pending coordinates shown locally; straight-line only offline; no offline road/turn-by-turn claims.
11. Permissions (starting policy): CCEO capture/propose for assigned schools; PL capture, propose, review in scope; IA review data quality where authorized; CD/Admin oversight and exceptions; Cluster Leader and Partner propose only if explicitly granted. Define what auto-accepts.
12. UX: Open School → Capture GPS → Confirm → Saved Offline / Synced; correction adds Confirm Reason. Large buttons, short labels, visible accuracy, easy retry, clear offline and sync state; never imply the server was updated when only saved locally.
13. Edge cases: offline, airplane mode with GNSS, GPS unavailable, services off, denied, approximate, poor reception, indoors, stale fix, inconsistent readings, app closed/reopened offline, restart, internet restored, interrupted upload, duplicate retry, expired auth, revoked access, two staff on one school, server change while offline, version conflict, clock skew, failed upload kept, stale route recommendations, large corrections, unauthorized sync. Real Android devices; iOS release builds.
14. Deliverables 1–19 (capture, replace, accuracy, offline profile, queue, auto sync, Go API, version conflicts, permission-aware verification, audit history, entrance, offline pending map state, route cache invalidation, real-time pin refresh, failed-sync recovery, permission/error handling, device tests, current-vs-new UI comparison, performance and integrity report).
15. Production protection: migration branch, isolated dev/staging DBs, no production writes or endpoints, no merge/deploy without approval.

Acceptance: at a school with no signal, open a previously synced profile, capture accurate GPS, save securely; survives restart; on reconnection Edify syncs, checks authorization, updates the authoritative location if accepted, and the planner uses it. History kept, no silent overwrites. Simple enough for a CCEO or Cluster Leader on an ordinary phone. SIMPLE → HEALTHY → FOCUSED.

## Owner decisions (2026-11-14)

1. **Write target:** accepted points, versions and history live in Go's `field_routes` as the School Directory's location record; Go's profile, directory and planner read it. Django's `school` / `school_geo_point` are not written; the record is promoted with reconciliation at cutover. No dual writes.
2. **Auto-accept:** only a *first* location (school had none) captured by GPS at ≤20 m by its CCEO or PL. Every correction of an existing point, and every entrance point, goes to review (reviewers: Program Lead, CountryDirector, Admin).
3. **Cluster Leaders and Partners:** not yet. Staff only (CCEO, PL capture; IA/CD/Admin review/oversight per the reviewer list).
4. **Visit prompt:** on the visit day — opening a school with planned work that day (Route Details, Start Field Day, the profile) shows "This school has no GPS location. Capture it now?" or "Is this school's location correct? Yes / Correct Location", once per school per day, offline from the cached field day.

## Build notes

- The app keeps its own navigation (App.tsx), not Expo Router; the brief's Expo Router line is not a change to make here.
- Encrypted offline store: `expo-sqlite` with SQLCipher (config plugin), key generated on the device and held in SecureStore. Needs the native development build (`expo run:ios` / `run:android`), not Expo Go.
- Device tests here are the iOS simulator and the Android emulator; real Android phones and iOS release builds need the owner's devices / signing.
