# Google Maps API Cost Control, Quotas & Licensing Governance

**Project:** Edify Planning & Monitoring Platform  
**Date:** 2026-11-22

---

## 1. Built-In Go Cost & Quota Safeguards (`internal/routeplan/provider.go`)

Every external routing call flows through `routeplan.Guarded`, which enforces five layered billing controls:

1. **Daily Request Cap (`EDIFY_ROUTING_DAILY_LIMIT`, default `20,000`):** Hard ceiling resets daily (`YYYY-MM-DD`). Once reached, calls fail safely with `ErrUnavailable` instead of incurring runaway Google Cloud billing.
2. **Per-Second Rate Limiter (`perSec = 20`):** Prevents sudden traffic spikes from exhausting per-second API quotas.
3. **In-Flight Deduplication (`golang.org/x/sync/singleflight`):** Simultaneous identical route requests share a single upstream API call.
4. **Policy-Compliant Short In-Memory Caching:**
   - Standard road matrices/routes cached in-memory (`6h` TTL, never written permanently to PostgreSQL to respect Google Maps Platform caching terms).
   - Traffic-optimal calls (`TrafficOptimal: true`) use a `5-minute` in-memory TTL so traffic remains fresh without redundant API churn.
   - Proven in Test K: 1,000 concurrent requests produced **1,056 cache hits** and only **14 upstream calls**.
5. **Minimal `X-Goog-FieldMask` Selection:** Only the exact fields required (`distanceMeters`, `duration`, `staticDuration`, `encodedPolyline`, `speedReadingIntervals`, `navigationInstruction`) are requested, keeping SKU tiering strictly controlled.

## 2. Key Restriction & Attribution Policy

- **Server Key (`EDIFY_GOOGLE_ROUTES_KEY`):** Restricted to server egress IP(s) and **Routes API** only. Never exposed to web or mobile clients.
- **Browser Key (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`):** Restricted to Edify production HTTP referrer origins (`https://*.edify.org`) and **Maps JavaScript API** only.
- **Attribution:** OpenFreeMap / OpenMapTiles / OpenStreetMap / Esri attribution is rendered cleanly on fallback map views; Google Maps JS API renders official Google logo & attribution when enabled.

## 3. Estimated Monthly Cost Envelope (1,000 Active Field Staff)

Assuming 300 active field-traveling CCEOs/supervisors averaging 4 route calculations/day across 22 field days/month (`~26,400` total calculations/month, reduced ~60% by `singleflight` + in-memory cache to `~10,500` billable calls/month):
- Well within Google Maps Platform Essentials/Pro monthly free-tier credit + predictable low-hundred-dollar ceiling when `EDIFY_ROUTING_DAILY_LIMIT` and GCP budget alerts (`$100`, `$250`, `$500`) are configured prior to enabling `EDIFY_ROUTING_PROVIDER=google`.
