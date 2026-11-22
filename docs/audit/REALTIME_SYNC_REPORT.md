# Real-Time Synchronization & Event Propagation Report

**Audit Date:** 2026-11-22  
**Remediation Implemented:** `ECO-002` & `ECO-004` — Native Go SSE Real-Time Broker + Next.js Authenticated SSE Proxy + Client `<RealtimeBridge />`.

---

## 1. Architecture Delivered

1. **Go SSE Event Broker ([`platform/backend/internal/realtime/broker.go`](../../platform/backend/internal/realtime/broker.go)):**
   - Mounted at `GET /api/v1/realtime/stream` (authenticated via `auth.Authenticator`) and `GET /api/v1/realtime/stats` (Admin-only observability).
   - **Middleware Streaming Fix (`ECO-004`):** Uses `http.NewResponseController(w)` (`SetWriteDeadline(time.Time{})` + `Flush()`) and added `Flush()` to `httpmw.statusRecorder` (`platform/backend/internal/httpmw/httpmw.go`) so long-lived SSE connections survive `http.Server.WriteTimeout` and flush cleanly through logging middleware.
   - **Post-Commit Publication:** Events are published strictly after PostgreSQL transaction commit (`withRW` returning `nil`) with monotonic `seq`, `event_id`, `type`, `entity_type`, `entity_id`, `country_code`, `actor_user_id`, and `occurred_at`.
   - **Strict Authorization & Tenant Isolation:** `matches(subscriber, event)` enforces country-code boundaries (`UG` events never reach `KE` subscribers), direct user targeting (`TargetUserID`), and explicit role allowlists (`TargetRoles`).
   - **Reconnect Replay & Deduplication:** 512-event ring buffer replays missed authorized events strictly after HTTP `Last-Event-ID` (or `?last_event_id=`).
   - **Backpressure Safety:** Per-subscriber buffered channel (`cap = 64`) with non-blocking `select` ensures slow clients never stall database writes or other connected users.
2. **Next.js Authenticated Proxy ([`platform/web/src/app/api/realtime/route.ts`](../../platform/web/src/app/api/realtime/route.ts)):**
   - Reads the `HttpOnly` `edify_at` cookie server-side and proxies the SSE stream + `Last-Event-ID` header without exposing raw JWT tokens to browser JavaScript.
3. **Browser Live Sync ([`platform/web/src/components/shell/RealtimeBridge.tsx`](../../platform/web/src/components/shell/RealtimeBridge.tsx)):**
   - Mounted in [`platform/web/src/app/(app)/layout.tsx`](../../platform/web/src/app/(app)/layout.tsx).
   - Listens for committed operational events (`escalation.raised`, `escalation.resolved`, `leave.requested`, `leave.decided`, `finance.*`, `message.sent`, `activity.updated`), dispatches `edify:realtime` CustomEvents for live client widgets, and triggers a debounced (`350ms`) `router.refresh()` so screens stay synchronized without manual page reloads.

---

## 2. Live Verification Evidence

| Test | Measured Result | Target | Status |
|---|---|---|---|
| Unit isolation (`TestBrokerRoleUserAndCountryIsolation`) | UG PL received event; KE PL & UG CCEO received `0` leaked events; direct message reached target user only | `0` leaks | **Pass** |
| Reconnect replay (`TestBrokerLastEventIDReplay`) | `Last-Event-ID` replayed only missed authorized events in subscriber's country | Exact replay | **Pass** |
| Auth & stats RBAC (`TestRegisterHTTPRequiresAuth`) | Unauthenticated `/stream` → `401`; non-Admin `/stats` → `403` | `401` / `403` | **Pass** |
| Live 250-concurrent-client SSE fan-out (`SSE_250_CHECK`) | **250 / 250 clients connected & received `event: ready` in `281 ms`**, `active_subscribers: 250`, `dropped_total: 0` | `< 2,000 ms`, `0` drops | **Pass** |

---

## 3. Multi-Instance Scaling Note (Production Roadmap)

- Single-instance Go deployments use the in-process ring buffer + fan-out broker (`< 1ms` publish latency).
- For multi-replica horizontal scaling behind a load balancer, bridge `Broker.Publish` across instances using PostgreSQL `LISTEN/NOTIFY` or Redis Pub/Sub (`internal/cache`) so events committed on Replica A fan out to SSE subscribers connected to Replica B.
