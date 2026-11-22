# Notification, Messaging & Action Queue Audit

**Audit Date:** 2026-11-22

---

## 1. Notification Ecosystem (`internal/notificationcenter`)

- **Endpoints Audited:**
  - ConnectRPC `NotificationCenterService` (`GetUnreadNotificationCount`, inbox listing, mark-read) — verified live under 1,000-user ramp benchmark (`HTTP 200`, `0` errors).
  - REST `POST /api/v1/notifications/preferences` — authenticated via `auther.Authenticate`.
- **Web Surface (`/notifications`):** Verified live in Playwright (`HTTP 200`, `0px` overflow, `0` console errors, top-bar unread badge synced in `ShellLayout`).
- **Outbox & Worker Resilience:** School Loans (`loans.Worker`, `loans.SMSWorker`) and Cluster Actions (`ClusterActionFollowUp`) run inside the Go gateway with transactional outbox delivery (`school_loans.notification`, `cluster_leadership.cluster_action_notice`) and retry safety when external mail/SMS providers are offline.

---

## 2. Direct Messaging (`internal/messaging`)

- **Endpoints Audited:**
  - `GET /api/v1/messages/recipients` — live test as `CCEO` returned `HTTP 200` with role-scoped recipients.
  - `POST /api/v1/messages/threads`, `GET /api/v1/messages/threads/{id}`, `POST /api/v1/messages/threads/{id}/reply`, `POST /api/v1/messages/threads/{id}/state` — all strictly authenticated via Bearer token.
  - ConnectRPC `MessagingService/GetUnreadCount` — verified live under 1,000-user ramp benchmark (`HTTP 200`, `0` errors).
  - Web Surface (`/messages`) — verified live in Playwright (`HTTP 200`, `0px` overflow, `0` console errors).
- **Finding Noted (`P3`):** `POST /api/v1/messages/threads` enforces strict recipient/payload validation (`400` on invalid payload schema; verified rejecting malformed input rather than creating partial threads). Recommend adding a dedicated E2E Playwright messaging send/reply/privacy test on staging once message recipient fixtures are standardized.

---

## 3. To-Do & My Actions Queues (`/actions/mine`, `/actions/sent`, `/todos`)

- Verified live in Playwright:
  - `/actions/mine` → `HTTP 200`, H1 `"My Actions"`, `0px` overflow, single active sidebar item.
  - `/actions/sent` → `HTTP 200`, H1 `"Actions Sent"`, `0px` overflow, single active sidebar item.
  - `/todos` → `HTTP 200`, H1 `"Action queue"`, `0px` overflow, single active sidebar item.
- `workforceops.TransitionTeamAction` enforces role guards (`ClusterLeader` refused), writes SHA-256 `audit.Append` in the same transaction, and unit tests in `internal/myactions/...` pass cleanly.
