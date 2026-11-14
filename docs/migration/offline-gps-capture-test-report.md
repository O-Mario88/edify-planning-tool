# Offline school GPS capture — performance and data-integrity test report

Branch `agent/native-build-batch`. All runs on this Mac against the local test database `edify_gorn_test` (seeded test data; never production). Local gateway, local OSRM. Figures are what was measured here, not projections. Brief and decisions: `next-offline-gps-capture.md`.

## What was tested automatically

| Suite | Result |
|---|---|
| Go `internal/routeplan` (policy: accept/flag rules, check rules, roles, ids) with `-race` | pass |
| Go `field_routes` migration lint (0001, 0002) | pass |
| App: GPS reading rules (stale fix dropped, median of best readings, spread, accuracy bands, Uganda bounds) | 6 tests pass |
| App: sync queue (oldest first, answer written down, lost connection waits with backoff, expired sign-in kept, refusal stops, conflict marked, crash mid-send resent under the same id, another account's captures never sent, concurrent syncs joined) | 8 tests pass |
| App whole suite | 216 pass |
| Web whole suite, types, lint | 188 pass, clean |

## API checks against the test database

| Case | Expected | Seen |
|---|---|---|
| CCEO first location, GPS 9 m | accepted at once, version 1 | accepted, v1 |
| Same capture id sent again | first answer, nothing filed twice | accepted, v1, one row |
| Same capture id from another person | refused | refused |
| First location at 35 m | waits for review (`accuracy_fair`) | pending |
| Correction sent against the old version | waits, `correction` + `version_conflict` | pending, both flags |
| "Location is correct" | noted, moves nothing | noted |
| Entrance point | waits for review (`entrance`) | pending; approved → entrance v1; road routes use it |
| School not in the sender's reach | refused | not_found |
| Country Director sends a GPS capture | refused (not a capture role) | permission_denied |
| Malformed capture id | refused | invalid_argument |
| PL approves the late correction | version 2, history keeps v1 | v2; change feed lists v1 then v2 |
| Existing `school` / `school_geo_point` rows | never written | unchanged after every case |

## Concurrency (data integrity)

Ten first captures of one school without a location, sent at the same moment by two accounts (5 each):

- exactly **1 accepted** (version 1), **9 held for review** flagged `correction`, `version_conflict`, `competing` (and `large_move` where far apart);
- exactly **one** `location_change` row for version 1; `school_location` at version 1.

The per-school advisory lock serializes them; no lost or doubled write.

## Timings (local gateway, warm, 3 runs each)

| Call | Seconds |
|---|---|
| Offline pack, CCEO (700 schools + 4 planned visits; 190 KB JSON, 18 KB gzip) | 0.44 (first), 0.16, 0.12 |
| Submit a capture | 0.04, 0.03, 0.08 |
| Change feed | 0.02, 0.02, 0.01 |

Not measured: a real mobile network in the field.

## Device tests

Native development builds (`expo run:ios` / `run:android`, SQLCipher on), against the local test gateway. Simulators and emulators only: **no real phone and no iOS release build were tested** (both need the owner's devices / signing).

### iPhone 18 Pro simulator (iOS 27)

| Case | Result |
|---|---|
| Phone database encrypted | pass: file header random, plain `sqlite3` says "file is not a database", no school names in the file or its WAL |
| Offline pack on sign-in | pass: 700 schools + planned visits stored |
| No coordinates → "GPS Location Not Captured" → Capture School Location | pass: permission asked only on press; reading shown live; accuracy 5 m "Good"; accepted at once, version 1 |
| Existing coordinates → Verify / Replace → reason → Save, with Edify unreachable | pass: "1 to sync" chip; orange "Not yet accepted (Waiting to sync)" pin beside the blue point on record; "No connection to Edify" |
| App closed and reopened while unreachable | pass: offline field app (Today / My schools 700 / Sync 1); the capture survived the restart |
| Edify back → Try again | pass: signed back in, capture sent once (captured 18:15:39, received 18:17:43), "Synced: waiting for review" |
| Visit-day prompt offline (seeded visit today) | pass: "Is this school's location correct?" Yes / Correct Location / Not now; Yes saved offline, synced as `noted` |
| Profile while unreachable | pass: offline copy of the school with Capture |

Found and fixed during these runs:
- **Two keys for one database.** On first launch the store could be opened twice at once (React's dev double mount); each made a key, so the file was encrypted with one and the keychain kept the other ("file is not a database"). Fixed: one open per process; the file is named after a hash of its key, so a lost key never meets the wrong file (the old file is left, never deleted).
- **Exclusive transactions open an unkeyed connection.** expo-sqlite's `withExclusiveTransactionAsync` uses a second connection without the SQLCipher key. Fixed: transactions on the keyed connection, every store call queued one at a time.
- **The "Saved" sheet could close by itself** when the profile beneath it re-rendered into its offline view. Fixed: the capture sheet is drawn at the app's root.
- Status bar unreadable above the offline banner; "Online" shown when the phone had internet but Edify did not answer. Both fixed.

Seen once, not reproduced: on the first capture (school 1004) the result was saved without a deliberate Save press while the Mac was heavily loaded by an Android build (simulator input lag is the likely cause). Repeating the flow without any input left the result screen waiting for Save, as designed (school 1130, nothing saved until Save).

### Android Pixel 9 emulator

| Case | Result |
|---|---|
| Native development build with SQLCipher | built; installed directly (Expo's installer timed out asking the overloaded emulator for device properties) |
| Program Lead signs in; airplane mode on | top bar shows **Offline**; it leads to Offline schools & sync with the saved schools and a search |
| Open a saved school with no connection | pass: "School ID 1006 · Mukono · Offline: showing what this phone saved", GPS Location Not Captured, Capture School Location |
| Approximate location only | pass: capture refused with "Only approximate location is allowed for Edify. Allow precise location in Settings…" |
| Precise location, GPS fix | pass: 3 readings, 5 m, Good |
| Save offline | pass: "Saved on this phone" stays until Done (the root-level sheet); "1 to sync" |
| Airplane mode off | pass: sent by itself, no button: captured 18:48:42, received 18:49:23, accepted (PL first location, v1) |
| Review list shows why a report waits | added during the run ("Replaces the point on record · The location changed after this was captured · …") |

Emulator notes: while the iOS and Android builds ran, the Mac's load reached 134 and the emulator's own apps (Phone, Gmail, Play services) stopped responding; Edify's two "not responding" reports came from that (the trace shows the system server restarting). With the load down, the app ran normally. A debug build on an emulator says little about speed; a release build on a real phone is needed for that.

On the emulator, `adb reverse` tunnels the local gateway through adb, so airplane mode does not cut it: for a strict test the gateway was stopped as well.

### Duplicate capture seen on the simulator

School 1130 received a second, identical correction (same point, same reason, one reading) at 18:21, when nothing was being done on the iPhone. It replays the 18:15 taps exactly, which points at the simulator replaying input under heavy load. The server flagged it `competing` and held it for review (approved the first, rejected the second as a duplicate); nothing was overwritten. As a guard, the app now refuses to queue a capture that repeats one made in the last ten minutes for the same school (same point within 10 m, or a second confirmation). Tested in the app suite.

## Not done

- Real Android phones and an iOS release (TestFlight) build: need the owner's devices and signing.
- Field accuracy (GPS under trees, indoors, poor reception): simulators report the accuracy they are given; only a phone at a school measures it.
- Background sync while the app is closed: not promised; sync runs on opening, on reconnection, on returning to the app, after a capture and each minute while something waits.
