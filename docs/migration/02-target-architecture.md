# 2. Target architecture

## 2.1 One picture

```
 React Native app (iOS, Android)
        |  HTTPS, Connect protocol, messages generated from platform/proto
        v
 +---------------------------------------------------------------+
 |  Go gateway  (one deployable, modular inside)                 |
 |  tracing -> structured errors -> authentication -> handlers   |
 |                                                               |
 |  identity | schools | geography | planning | activities | ... |
 |  each module: contract handlers, rules, store (SQL)           |
 +--------------------+----------------------+-------------------+
                      | SQL (pgx)            | gRPC, internal network only
                      v                      v
            existing PostgreSQL       Python workers (analytics, exports)
            schema unchanged          no database writes; no rules
```

The existing Django application keeps running beside this, on the same
database, until each domain's cutover is approved.

## 2.2 Decisions

**A modular monolith in Go, not microservices.** One binary, one deployment,
one database connection pool. Modules are Go packages with an explicit public
surface; they call each other in process. Splitting a module into its own
service stays possible because modules already talk through contract-shaped
interfaces, but nothing in Edify's scale (thousands of schools, tens of
concurrent staff) calls for it.

**gRPC only at a real boundary.** There is exactly one today: Go to Python.
Different language, different release cadence, different failure tolerance.
Go modules do not call each other over the network.

**Connect for the mobile-facing API.** The gateway serves the same handlers
over the Connect protocol, gRPC and gRPC-Web. The app uses Connect unary
calls: an ordinary HTTPS POST with a JSON (or binary) body, which works with
React Native's `fetch`, passes any proxy or load balancer, and is readable in
logs. The request and response types are still generated from the `.proto`
files, so the contract is the Protocol Buffer schema, not hand-written JSON.

**Go owns the rules.** Authorization, validation, workflow states, money and
counting are decided in Go modules and nowhere else. Python receives rows that
Go has already authorised and returns numbers. The app renders answers; where
it must predict one (enabling a button), the gateway sends the permission as
data rather than the app re-deriving it.

**SQL by hand, no ORM.** `pgx` with explicit queries against the existing
tables. There is no auto-migration and no migration code in the binary at all;
a test fails the build if a schema or write statement appears in gateway
sources before the write path is deliberately opened.

**The existing identity system stays the issuer.** See 2.5.

## 2.3 Repository layout

```
platform/
  proto/                 Protocol Buffer contracts (buf module)
    edify/common/v1        ErrorDetail, pagination
    edify/identity/v1      IdentityService          (mobile-facing)
    edify/schools/v1       SchoolService            (mobile-facing)
    edify/analytics/v1     PortfolioAnalyticsService (internal)
  tools/                 pinned generators (buf, protoc-gen-*, govulncheck)
  backend/               Go module
    cmd/gateway            process entry point
    internal/config        environment configuration, refuses production
    internal/dbguard       production-database guard
    internal/trace         request id and W3C trace context
    internal/apierr        structured errors
    internal/httpmw        tracing, access log, panic recovery, headers
    internal/auth          token verification, principal
    internal/identity      account store, IdentityService
    internal/schools       policy, store, SchoolService
    internal/analytics     gRPC client for the worker
    internal/health        /healthz, /readyz
    internal/server        assembles the handler
    internal/integration   tests against the real schema
    gen/                   generated Go code (committed)
  workers/analytics/     Python worker (gRPC server, no database)
  mobile/                React Native app (Expo, TypeScript)
  deploy/db/             least-privilege roles
  tools/parity/          parity check against the existing API
```

Each Go domain module has the same three parts:

| Part | Holds | Depends on |
|---|---|---|
| `service.go` | Contract handlers: validate input, call policy and store, map to messages | policy, store interface |
| `policy.go` | The rules: who may do what, and what follows | nothing but values |
| `store.go` | SQL against the existing tables | pgx |

The service depends on a small interface it declares itself, so rules are unit
tested with fakes and the SQL is tested against the real schema.

## 2.4 Contracts

- One buf module, packages versioned `v1`. `buf lint` (STANDARD) and
  `buf format` gate every change.
- `buf breaking` (FILE rules) compares each change with its base: a field or
  RPC may not be removed, renumbered or retyped.
- Generation is reproducible: generators are pinned in `platform/tools/go.mod`
  (Go), `platform/mobile/package-lock.json` (TypeScript) and the worker's
  `requirements-dev.txt` (Python). Generated code is committed, and CI fails
  when regenerating changes it.
- **Identifiers are the existing ones.** Messages carry the existing CUIDs and
  Edify School IDs as strings. No contract introduces a new identifier for an
  existing record.
- **Existing vocabularies travel verbatim** as strings (`school_type`, role
  names, statuses) until a domain's migration fixes its enum, so the contract
  cannot silently rename a stored value.
- Optional scalars use `optional`, so "no enrolment figure" is not `0`.

## 2.5 Authentication

```
app --email, password--> existing identity system (/api/auth/login)
app <--access token (HS256, 15 min) + refresh token--
app --Authorization: Bearer--> Go gateway
                                 verify signature (HS256 only, expiry required)
                                 load the account from `user` on every request
                                 resolve the active role as the existing API does
```

- The gateway mints nothing and stores no credential. Password checking, MFA,
  lockout and refresh rotation are not reimplemented.
- The account is re-read on every request, so deactivating or deleting an
  account stops a live token at once.
- The gateway's database role cannot read password hashes, MFA secrets or
  refresh tokens (column-level grants).
- The signing secret is per environment. A token from one environment does not
  verify in another.

Planned next (milestone 1): the app talks to the gateway only. The gateway
gains an `AuthService` that forwards sign-in, MFA and refresh to the existing
identity system server to server, so the app needs one base URL and the
identity system is not exposed to devices directly. Moving token issuance
itself into Go is a later, separately approved step; when it happens, the move
to asymmetric signing (the gateway holding only a public key) happens with it.

## 2.6 Errors, tracing, health

- **Errors**: every failure is a Connect error with a status code, a message
  safe to show a person, and an `edify.common.v1.ErrorDetail` carrying a
  stable reason code (`AUTH_TOKEN_EXPIRED`, `ROLE_NOT_MIGRATED`, ...), the
  request id and the trace id. Unknown errors are logged with those ids and
  replaced by a generic internal error; a database message never reaches a
  client.
- **Tracing**: W3C `traceparent` is continued or started, a request id is
  accepted only if it is safe to log, both are echoed on the response, written
  on every log line, and forwarded to the worker as gRPC metadata. Exporting
  spans to a collector (OpenTelemetry SDK) is a staging task; the propagation
  it needs is in place.
- **Logs**: structured JSON, one line per request. Headers, query strings and
  bodies are never logged.
- **Health**: `GET /healthz` (process is up, touches nothing), `GET /readyz`
  (database answers), and the standard gRPC health service.

## 2.7 Python workers

A worker is a gRPC server on the private network.

| Rule | How it is held |
|---|---|
| No database writes | The analytics worker has no database driver installed; a test fails if one is added or imported |
| No database configuration | The worker refuses to start if its environment carries `DATABASE_URL` or libpq settings |
| No business rules | It receives authorised rows and returns statistics; its contract has no identifiers and no permissions |
| Failure is survivable | The gateway bounds each call (3 s) and answers without the worker, saying so in the response |

Workers that later need to read large data sets (exports, model fitting) get
their own read-only role limited to named views, and their own guard, by the
same pattern as the gateway's.

## 2.8 Mobile app

Expo (React Native 0.88, TypeScript strict), one codebase for iOS and Android.

```
platform/mobile/
  App.tsx                 validates configuration, picks the screen
  src/config/environment  which backends this build may reach
  src/api/connect         typed Connect client over fetch
  src/api/edifyApi        the gateway calls, typed by generated contracts
  src/auth/tokenStore     Keychain / Keystore (expo-secure-store)
  src/auth/identityClient sign-in against the existing identity system
  src/auth/SessionContext the signed-in person
  src/shell/AppShell      top bar and bottom navigation
  src/screens             SignIn, Home, Schools, More
  src/theme               Edify tokens, type scale, Geist
  src/gen                 generated TypeScript (committed)
```

- **It looks like Edify.** The app draws from the web app's own `--edify-*`
  tokens (light and dark), Geist Sans, the same logo, sign-in card, top bar,
  five-item bottom navigation and page-header pattern (`src/theme.ts`,
  `src/shell/AppShell.tsx`). A native screen is built by opening the same
  page on the web at phone width and matching it.
- Areas not yet migrated say so and open the same page of the web app,
  rather than showing a screen that looks finished and is not.
- Tokens live only in the platform keystore.
- A build is `development` or `staging`. The app refuses to start as anything
  else and refuses any `edifyplanning.app` host, until a production release is
  approved.
- No rule is written in the app.

Next for the app: Expo Router for navigation, a server-state cache for lists,
EAS build profiles, crash reporting, and the native features in the plan
(camera for evidence, location, offline visit capture, push).

## 2.9 Screens served from the existing application

Almost every page of the existing application is rendered on the server and
has no data feed. So that the whole app can be rebuilt natively without
waiting for each domain's Go module, a screen can be served in two steps:

```
app --GetHome--> Go gateway --GET /api/mobile/v1/home (caller's token)--> existing application
```

- The contract is still Protocol Buffers (`edify.screens.v1`). The existing
  application returns the message's JSON form; the gateway decodes it strictly
  and refuses anything the contract does not know.
- The feed (`apps/mobile_feed`) calls the same service the web page renders
  from, behind the same permission check, with any acting capacity attached as
  the web does. It computes nothing.
- The app still talks to the gateway only. When a domain's rules are ported to
  Go, the gateway's handler for that screen is replaced and the feed deleted;
  the contract and the screen do not change.
- This is the one deliberate exception to "rules live in Go", and it is
  temporary by construction: each feed is a pointer to a rule not yet ported.

## 2.9 Redis and queues

Not introduced. The gateway is stateless and the slice needs neither. They
enter when a migrated domain needs them, and not before:

- **Redis**: rate limiting on sign-in forwarding, and shared cache for
  expensive scope resolution, once those exist in Go.
- **Durable messages**: the existing transactional outbox table is already
  the durable queue. Go will append to the same outbox in the same
  transaction as its write, and the existing dispatcher keeps delivering,
  until notifications themselves move.
