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
