# Smart Route Planner rebuild

The Go optimizer is unchanged. Layout: `RoutePlanner.tsx`, `RouteInsights.tsx`, `route.css`, `lib/routeView.ts`.

**Delivered:** six KPIs; configuration, dominant map, and Itinerary / Directions / SSA & Coverage panels; Route Options, Optimization Insights and Road Conditions; on a phone, compact KPIs, date and place filters, Map/List switch and a draggable itinerary sheet with Optimize and Start Field Day.

**Measured road route (local OSRM, 5 schools):** balanced and fastest 23.1 km / 34 min; shortest 22.6 km / 36 min.

**Honesty rules:** Fastest and Shortest are awarded only from measured figures among routes reaching the same schools; ties name no winner. Traffic reads Unavailable without provider data. Road conditions show only real reports. No external map links.

**Limits**
- No Terrain layer: no terrain tiles are configured.
- Live traffic needs a Google Routes key, which is not configured here.
- Route Options runs on request, because each optimization writes an audit record.
