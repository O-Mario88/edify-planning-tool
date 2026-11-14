# Next task: Smart Field Routing (owner brief, 2026-11-14)

Queued by the owner on 2026-11-14 ("Add this to the next task"). It starts as soon as the
remaining native pages are built (countdown in the session), before batch testing. Same
constraints as the whole migration: protected migration branch only, no production database
writes, no merge or deploy without explicit approval, no invented measurements.

The owner's brief, verbatim:

---

SMART FIELD ROUTING — PERFORMANCE AND INTELLIGENCE UPGRADE

Objective
Improve the existing proposed School Map and Routing feature into a fast, cost-efficient, intelligent field-planning system for CCEOs, PLs and other authorized field staff.
Use:

* Next.js, TypeScript and Tailwind CSS for web.
* React Native with Expo for mobile.
* Go for all operational logic, routing integration, eligibility, scheduling and authoritative writes.
* Python only for historical travel analytics, forecasting and strategic recommendations where justified.
* The existing authoritative School Directory for GPS coordinates.

Do not modify the production database during development.
Work only on the protected migration branch. Do not merge or deploy without explicit approval.

1. Intelligent loading

* Automatically retrieve school GPS coordinates from the School Directory.
* Query only schools the user is authorized to access.
* Use spatial indexing where supported by the database.
* Load school pins by map viewport and zoom level.
* Cluster nearby map markers at lower zoom levels.
* Avoid retrieving the entire national school dataset for one field officer.
* Load the primary My Plan list without waiting for the map provider.
* Lazy-load map libraries and rendering code.
* Support a functional List View when maps cannot load.
* Separate GPS/location errors from ordinary activity-loading errors.

2. School coordinate quality
Maintain location quality information:

* Latitude and longitude.
* Coordinate source.
* Verification status.
* Last verified date.
* Reported device accuracy, where available.
* Proposed road entrance/access point, where relevant.
* Optional landmark/access note.

Never overwrite authoritative school coordinates automatically from an uncertain map search.
Provide a Verify Location workflow for authorized users, with review and audit history.
Flag missing or suspicious coordinates without hiding the corresponding school from list-based planning.

3. Two-stage recommendation engine
First, use Edify's own school coordinates and spatial queries to generate a shortlist.
Filter candidates by:

* Staff portfolio.
* School eligibility.
* Current-FY activity rules.
* Existing plans and partner assignments.
* Relevant SSA support exceptions.
* Outstanding Cluster Actions.
* Training follow-up needs.
* Available field time.

Only then request road routing data for the selected shortlist.
Clearly label straight-line proximity separately from provider-estimated road travel time.
Do not fabricate road estimates if routing data is unavailable.

4. Constrained route optimization
Account for:

* Selected schools.
* Starting location.
* Optional ending location.
* Transport mode.
* Existing appointment times.
* Expected visit duration.
* Staff working hours.
* Scheduled cluster activities.
* Remaining available field time.
* Practical detour limits.
* Overnight field-day constraints where applicable.

Allow users to lock fixed appointments and manually reorder flexible visits.
A simple waypoint optimizer must not be treated as a complete solution for appointment time windows.
Use an appropriate constrained route-planning approach in Go or through a suitable routing optimization service.
Preserve the user's approved activities when recalculating.

5. Cost-aware planning
Integrate with Edify's existing approved cost catalog and field-day budget logic.
Respect existing distinctions between Primary and Secondary/overnight field days.
Never create a competing transport-cost calculation in the routing module.
Do not reveal hidden staff transport cost information to CCEOs.
Authorized financial roles may compare route and operational-cost implications where current permissions allow it.
Route suggestions must not change approved budgets or commitments without passing existing approval controls.

6. Smart Field Day interface
Add to My Plan:

* List View / Map View.
* Today's planned school pins.
* Selected route.
* Suggested nearby eligible schools.
* Simple explanation of recommendations.
* Optimize Route action.
* Add to Plan action.
* Open School Profile action.
* Get Directions action.
* Missing-coordinate warning.
* Estimated travel distance and duration where verified by provider output.

Keep the mobile experience task-first and uncluttered.
Use consistent Planned and Completed statuses from the authoritative activity records.
Completed visits must disappear from pending planning views according to the existing business rules without removing their history.

7. Replanning during the day
Allow users to:

* Mark the current official activity started through the existing workflow.
* Complete the activity using existing evidence requirements.
* See remaining planned stops.
* Recalculate the remaining route on request.
* Report an inaccessible road or school.
* Propose rescheduling or changing visit order.
* Return to navigation without losing their activity state.

Distinguish changing suggested route order from modifying the official activity schedule.
Any schedule change must use the authoritative Go planning service and preserve the Activity ID, approvals and audit history.
Do not automatically mark a visit completed based on device location.

8. Provider efficiency
Build an interchangeable routing-provider interface in Go.
Initially evaluate Google Maps Routes API against suitable alternatives using representative Ugandan school locations.
Measure:

* Road coverage and reliability.
* Estimated route quality.
* API latency.
* Cost per route request.
* Waypoint and matrix limits.
* Mobile map performance.
* Licensing and caching restrictions.

Require:

* Rate limiting.
* Budget quotas.
* Restricted API credentials.
* Request deduplication.
* Minimal response field masks.
* Fallback to manual school ordering.
* Provider error monitoring.
* No prohibited persistence of provider content.

Do not call the paid optimization API on every render, pan, zoom or minor UI interaction.

9. Permissions and privacy

* Go enforces role and school-level access.
* CCEO sees authorized portfolio schools.
* PL sees appropriate personal and Team Oversight scopes.
* CD, IA and other roles see only authorized geographic and operational data.
* Do not expose unrestricted school GPS datasets through public endpoints.
* Request current device location only when the user chooses a location-based feature.
* Do not continuously track staff movements.
* Never reveal location-history data to managers without a separately justified, disclosed and authorized feature.

10. Testing and measurable acceptance
Test against isolated databases and representative school coordinates.
Verify:

1. Pins appear at the stored school coordinates.
2. Invalid coordinates are flagged.
3. Map and list views show the same authorized schools.
4. Cross-district cluster membership works.
5. School eligibility rules remain enforced.
6. Suggested schools do not become scheduled automatically.
7. Route optimization respects fixed appointments.
8. Visit durations and field-day limits are respected.
9. Multiple planned visits can be grouped safely.
10. Actual travel estimates come from valid provider responses.
11. Provider failures leave the list and planning workflows usable.
12. Replanning preserves official Activity IDs.
13. Concurrent planning does not create duplicate activities.
14. Completed visits update the relevant map and list.
15. CCEO transport-cost visibility restrictions remain intact.
16. API request volume and cost are monitored.
17. Common map and route operations are benchmarked on representative mobile networks.
18. Development and staging have no write access to production.
19. Existing planning, budgets and evidence workflows do not regress.

Deliver a measured performance report comparing baseline and optimized:

* School-pin loading time.
* Route-generation time.
* Routing API calls per planning session.
* Estimated provider cost.
* Payload sizes.
* Mobile rendering performance.
* Route feasibility.
* Scheduling conflicts prevented.

Do not claim percentage improvements unless measured.

Final directive
Edify Smart Routing must help staff accomplish more meaningful school visits with less unnecessary travel and less planning effort.
It must combine school location, program priorities, eligible activities, travel feasibility and operational constraints into one intuitive field-planning experience.
Preserve the production database and all existing business rules.
Simple → Healthy → Focused.

---

# Addendum 1 (owner, 2026-11-14): Smart Route Intelligence brief and the screens to build

The owner then sent a second brief, "SMART ROUTE INTELLIGENCE — NAMED SCHOOL PINS,
AUTOMATIC DISTANCE CALCULATION & ADVANCED VISIT RECOMMENDATIONS", with two screen designs,
and said: "This is the UI design for web route page and mobile Route page. I want it built
exactly like that."

## What the second brief adds (summary of its 17 sections; the owner's words govern)

- Stack: web Next.js + TypeScript + Tailwind; mobile React Native + Expo + Expo Router; Go owns
  school retrieval, authorization, the map-provider abstraction (Google Maps Platform evaluated
  first), distances, route optimization, eligibility, scheduling and every write; Python only
  for historical field-efficiency analytics. Coordinates come from the existing School
  Directory, never a second directory.
- Branch safety: feature/edify-go-rn-migration or a subordinate branch; no production DB, no
  coordinate changes in production, no migrations against production, no load tests on
  production, no merge to main, no deploy without approval; synthetic or sanitized data.
- Automatic named pins: authorized coordinates through Go, validated lat/lng, the real school
  name beside each pin, linked to the School ID; selected/scheduled highlighted; fit-to-pins.
  Pin info: name, School ID, district, cluster, planning status, category, coordinate
  verification. Tap → compact panel: View School, Select for Route, Add to Plan (if eligible),
  Get Directions. Collision-aware labels, planned/selected labels first, cluster dense
  unselected markers, never a bare number for a school. Status colours: orange Planned, green
  Completed, distinct labelled Suggested / Selected / Unverified Location; map selection is
  never an official plan.
- Distances (Go): straight-line (Haversine) labelled "Straight-line distance"; road distance
  from the provider labelled "Estimated road distance" returning origin/destination School
  IDs, metres, km, duration, mode, availability, provider status, timestamp; an unavailable
  state instead of invented numbers. Pairwise panel for any two authorized schools, drawn
  route; a route matrix for shortlists within provider limits.
- Multi-school itinerary: start, ordered schools, optional end; per leg from/to, road
  distance, travel time, arrival, visit duration, departure; totals (distance, travel, time at
  schools, field-day duration, selected vs feasible visits, conflicts) summed from real legs
  only; partial routes shown as partial.
- Two modes: A Fastest Route (order selected schools; start/end, fixed appointments, locked
  positions, mode). B Recommended Field Day (planned schools, FY eligibility, portfolio, SSA
  support needs, outstanding Cluster Actions, training follow-ups, appointments, visit
  durations, working-day limits, road time, detours) — may suggest extra schools but never
  creates an activity; only the user's confirmed scheduling through Go does.
- "Schools Near My Route": authorized, eligible candidates near the route; extra distance and
  time from inserting each candidate (not straight-line rank, no unexplained AI scores);
  feasibility; plain-language reason; accept or dismiss; already-planned schools flagged so no
  duplicate visit.
- Constrained optimization with time windows, service durations, start/end, fixed vs flexible,
  breaks, required vs optional; manual reorder with consequences shown; infeasible days explain
  the conflict and offer alternatives.
- School Profile: Location & Directions section (GPS, verification status, named pin, access
  point, landmark note, Get Directions, Find Nearby Schools); report inaccurate coordinates
  through a controlled verification workflow; missing coordinates never hide a school.
- Route execution: current school, Get Directions, next stop, remaining sequence, official
  status, back to My Plan, completion through the existing workflow; completion reflected
  after the backend confirms; no proximity auto-complete; no background tracking by default.
- Real-time sync with My Plan via Go events/refresh after commit; stale and conflicting
  changes handled explicitly.
- Performance/cost: >500 concurrent users; viewport loading, server-side filtering, spatial
  lookup, clustering, lazy map code, routing only on meaningful actions, dedupe, throttling,
  quotas, billing alerts, field masks, timeouts, monitoring, list fallback; geographic
  shortlist before road matrices; honour provider storage/attribution terms.
- Security: Go authorizes location reads, route selection, nearby discovery, schedule edits,
  coordinate corrections, exports; no national coordinate endpoint; server keys never in
  client bundles; device GPS only on explicit choice.
- Tests (16 in the brief) and 20 deliverables, including a Current-vs-New UI comparison and a
  final implementation report.
- Final requirement: a CCEO opening My Plan sees scheduled schools named on a map, road
  distances between them, a recommended order, nearby eligible schools with added distance and
  time, and why — with every official change through Go's existing workflows.

## Web design: "Smart Route Planner" (build exactly as drawn)

- Top bar: search "Search schools, clusters…", notification bell with count, country picker
  (Uganda flag).
- Breadcrumb "My Plan > Smart Route Planner". Title with a blue map-pin icon: "Smart Route
  Planner"; subtitle "Optimise your field visits with the most efficient route". Right: date
  picker ("Tue, Apr 29, 2025" style, calendar icon, chevron) and a primary blue "Save Plan"
  button.
- KPI row of four cards: "5 Schools — Selected for today" (school icon, green tick);
  "56.8 km — Total Distance" (route icon, car icon); "2h 15min — Total Travel Time" (clock,
  info icons); "5h 30min — Total Field Time" (green calendar-tick icon, info icon).
- Main row, three columns:
  - Left: segmented "Map View" (active, blue) / "List View"; Filters card with "Clear All":
    District select "All Districts", Cluster select "All Clusters", Status checkboxes
    Planned (on), Suggested (on), Nearby (off).
  - Centre: the interactive map with numbered blue pins 1–4 and a green pin 5 for the
    suggested school, each with a white label card carrying the school name; the blue route
    line through them; current-location dot; legend top right (Planned blue, Suggested green,
    Other grey); zoom +/− and locate buttons bottom right; a bottom-left chip
    "car 56.8 km | 2h 15min".
  - Right: "Recommended Route" card (trophy icon, green "Recommended" pill) listing numbered
    stops (blue 1–4, green 5) with school name, "12.4 km • 32 min" under it and "Arr. 09:00"
    on the right; then "Route Summary": Total Distance, Travel Time, Total Time with icons;
    buttons "Optimize Route" (outlined) and "Get Directions" (filled blue).
- Bottom row: "Schools Near Your Route" card (lightbulb icon, "View All →") with a school row:
  photo, name, green "Eligible" pill, "+6.2 km • 14 min | SSA Support Needed", outlined
  "Add to Plan"; beside it a green "Great route!" card: "You can visit 5 schools efficiently
  in one field day." with a route illustration.

## Mobile design: two screens (build exactly as drawn)

- App header: dark teal bar, menu, Edify logo, bell with count, profile; bottom tab bar Home,
  My Plan (active, highlighted), Schools, Clusters, More.
- Screen 1 "Smart Route Planner": pin icon, title, "Plan, optimise and navigate your school
  visits"; date picker and district picker side by side; segmented Map View (active, dark
  teal) / List View; map with zoom +/−, locate, layers buttons; top-right card "Recommended
  Route 44.1 km • 1 hr 25 min ›" with green tick; numbered pins with label cards
  "Nakasero P/S (8.8 km • 18 min)", orange pin for the recommended extra school, green
  "Start (Kampala Office)" pin; legend Planned School blue / Recommended orange / Start-End
  green; summary strip: Distance, Travel Time, Schools, Recommended (star); full-width dark
  teal "Optimise Route" button with sparkle icon.
- Screen 2 "Route Details": back arrow, title, "Tue, 24 Jun 2025 • Kampala District", overflow
  menu; green "Recommended Field Day" banner ("An efficient and feasible route based on your
  planned schools, school priorities and travel time."); segmented Itinerary (active) / Map /
  Options; four stat tiles Total Distance, Total Travel, Visit Time, Visits; "Visit Sequence
  (Recommended)" timeline: numbered stops with name, status pill (green Planned, orange
  Recommended), "Visit: 30 min", "From Start: 12.5 km • 22 min" / "From 1: 8.8 km • 18 min",
  chevron; "Schools Near My Route" (star, View All →) with photo, name, purple "High
  Priority" pill, "2.8 km (≈ 8 min detour)", "Needs SSA support", outlined "Add to Plan";
  footer buttons "Get Directions" (outlined) and "Start Field Day" (dark teal, play icon).

The figures in the designs (km, minutes, school names, dates) are illustrations only: the
built screens show real Edify schools and real provider results, and an unavailable state
where the provider gives none.

---

# Addendum 2 (owner, 2026-11-14): no map login

Owner: "I want the universal map api that does not require logging in or it should use the
staff login to automatically use any map, google, apple or anyother".

Decision taken from it:

- Map display, web and mobile: MapLibre GL with OpenFreeMap vector tiles — open source, no
  key, no account. Mobile shows the same map inside the app, so Android needs no Google key.
- Road distance and time: OSRM (open source) on OpenStreetMap's Uganda road data, run by
  Edify (no key, no per-request fee, school coordinates stay in-house). Google Routes stays
  an optional provider behind the same Go interface, off unless a key is configured.
  Public demo OSRM servers are for light development testing only, with synthetic
  coordinates.
- Get Directions hands the destination to the phone's own maps app (Google Maps, Apple
  Maps, Waze — whichever the staff member uses and is signed in to) through standard
  keyless links.
- With no routing server reachable, the planner still works on straight-line distances,
  labelled as such, and says road figures are unavailable.
