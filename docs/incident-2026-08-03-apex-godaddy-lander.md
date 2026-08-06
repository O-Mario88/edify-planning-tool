# INC-2026-08-03-01 — Apex domain serves GoDaddy lander

| Field | Value |
|---|---|
| Severity | P1 (public production domain serves non-Edify content) |
| First observed | 2026-08-03 (reported by owner; screenshot) |
| Diagnosed | 2026-08-03 16:06 UTC |
| Affected host | `edifyplanning.app` (apex) — HTTP and HTTPS |
| Unaffected host | `www.edifyplanning.app` — serving Edify normally |
| Affected users | Anyone typing the bare domain or following an apex link |
| Status | Root cause proven; awaiting controlled DigitalOcean/GoDaddy cutover |

## Symptom

`http(s)://edifyplanning.app/` returns HTTP 200 with a 114-byte body:

```html
<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>
```

The browser then loads `/lander`, GoDaddy's parked-domain page. Note this is a
**client-side** redirect, not a 3xx — `curl -L` reports `redirects=0`, which is
why the failure does not show up in redirect-chain checks.

## Root cause

The apex A records point at GoDaddy's **Domain Forwarding** service, not at the
application origin:

```
edifyplanning.app.  565  IN  A  15.197.148.33
edifyplanning.app.  565  IN  A  3.33.130.190
```

Those two addresses are GoDaddy's forwarding endpoints. The forwarding entry
exists but has no working destination, so GoDaddy serves its own lander stub
instead of forwarding to the application.

`/lander` does **not** exist in the Edify codebase — a repo-wide search for
`lander` across `*.py`, `*.html`, `*.js`, `*.conf`, `*.yml`, `*.json` returns
zero matches. The path is entirely GoDaddy's.

### Why the forwarding was there

`DEPLOY_DIGITALOCEAN.md` §3a and `.do/app.yaml` lines 37–47 document option A,
"keep DNS at GoDaddy":

> GoDaddy cannot CNAME the apex. Use GoDaddy's Forwarding feature to send
> edifyplanning.app → https://www.edifyplanning.app (permanent, 301)

That guidance was stale. App Platform now publishes stable ingress A/AAAA
records for externally managed DNS, so GoDaddy can host apex A records directly
without forwarding or a nameserver migration. The forwarding-era deployment
documentation allowed this failure mode and is corrected by this incident.

## Authoritative DNS

| Item | Value |
|---|---|
| Nameservers | `ns39.domaincontrol.com`, `ns40.domaincontrol.com` |
| SOA | `ns39.domaincontrol.com. dns.jomax.net.` (serial 2026080100) |
| Provider | **GoDaddy** — registrar and authoritative DNS are the same |
| DNSSEC | not enabled |
| Resolver agreement | 8.8.8.8, 9.9.9.9, 208.67.222.222 all return the same apex A pair — fully propagated, not a caching artifact |

## Complete zone contents (as observed)

| Name | Type | Value | TTL |
|---|---|---|---|
| `@` | A | `15.197.148.33`, `3.33.130.190` (GoDaddy Forwarding) | 565 |
| `@` | AAAA | *(none)* | — |
| `www` | CNAME | `edify-planning-app-gu9a6.ondigitalocean.app.` | 3544 |
| `_dmarc` | TXT | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;` | — |
| `_domainconnect` | CNAME | `_domainconnect.gd.domaincontrol.com.` | — |
| `@` | CAA | *(none)* | — |
| `@` | MX / SPF / DKIM | **none** | — |

**No mail records exist.** No nameserver migration is required for this repair;
GoDaddy remains authoritative and the existing `_dmarc` record is untouched.

## Current origin

- Real origin: DigitalOcean App Platform, app alias
  `edify-planning-app-gu9a6.ondigitalocean.app`, region `fra`
- Edge: Cloudflare (DigitalOcean's own edge — `server: cloudflare`,
  `x-do-app-origin: 0d146c6d-5db0-42be-aef0-456edef2a940`)
- App spec: `.do/app.yaml` — `www` is `PRIMARY`, apex is `ALIAS`

## Observed behaviour, before repair

| Request | Result |
|---|---|
| `http://edifyplanning.app/` | 200, GoDaddy JS stub → `/lander` |
| `https://edifyplanning.app/` | 200, GoDaddy JS stub → `/lander` |
| `http://www.edifyplanning.app/` | 301 → `https://www.edifyplanning.app/` (one hop, correct) |
| `https://www.edifyplanning.app/` | 200, Edify application |

## TLS

| Host | Subject | Issuer | Valid |
|---|---|---|---|
| `www.edifyplanning.app` | `CN=www.edifyplanning.app` | Google Trust Services WE1 | 2026-08-01 → 2026-10-30 |
| `edifyplanning.app` | served by GoDaddy Forwarding | — | apex is **not** on the DigitalOcean certificate |

The DigitalOcean certificate covers `www` only. It will not cover the apex until
the apex resolves to the App Platform origin.

## Mobile `www` latency — measured

From the diagnosing host (Kampala):

| Path | DNS | TCP | TLS | TTFB | Total |
|---|---|---|---|---|---|
| IPv4 | 0.002s | 0.030s | 0.080s | **0.712s** | 0.712s |
| IPv6 | 0.003s | 0.130s | 0.190s | **1.153s** | 1.153s |

The `www` AAAA records (`2a06:98c1:58::60`, `2606:4700:7::60`) **do resolve and
connect**. The "stale or invalid AAAA record" hypothesis is disproven for `www` —
IPv6 is reachable, just ~440 ms slower to first byte on this network. The apex
has no AAAA at all.

TTFB of 0.7 s on a 2 KB root response is the more likely mobile complaint, and it
is an application/origin concern, not DNS. It is not yet root-caused — see
"Open" below.

## Repair — required actions

The repair uses DigitalOcean's documented static App Platform ingress records
while retaining GoDaddy as authoritative DNS. Do not use Domain Forwarding and
do not change nameservers.

### Stage 1 — provision the apex before touching live DNS

1. DigitalOcean App Platform → the Edify app → **Settings → Domains**.
2. Add `edifyplanning.app` and choose **You manage your domain**.
3. Keep `www.edifyplanning.app` attached and serving traffic.
4. Wait until DigitalOcean accepts the apex and is ready to provision a
   certificate. Do not alter GoDaddy records during this step.

### Stage 2 — replace the parked apex records

1. Remove GoDaddy Domain Forwarding. This releases the provider-managed parked
   A records.
2. Add these externally managed DNS records at GoDaddy:

   ```text
   A  @  162.159.140.98
   A  @  172.66.0.96
   ```

3. Keep the existing `www` CNAME pointing to
   `edify-planning-app-gu9a6.ondigitalocean.app.`.
4. Wait for authoritative and public resolvers to return the new apex pair.
5. Confirm DigitalOcean has issued a certificate covering
   `edifyplanning.app` before considering the cutover complete.

DigitalOcean also publishes `2606:4700:7::60` and `2a06:98c1:58::60` as static
IPv6 ingress records. They may be added after the IPv4 recovery is verified;
they are not required to eliminate the lander.

### Stage 3 — make the apex canonical

1. Verify apex HTTPS returns the Edify application and `/api/health/` reports
   healthy.
2. Flip `.do/app.yaml` to apex `PRIMARY` and `www` `ALIAS`.
3. Deploy the canonical-host middleware while it remains disabled.
4. Set `CANONICAL_HOST=edifyplanning.app` only after apex DNS and TLS are both
   proven healthy.
5. Verify `www` reaches apex in one permanent redirect while preserving path
   and query string.

**Order matters.** Direct TLS to the DigitalOcean ingress currently fails for
apex SNI because the apex is not attached there yet. Changing GoDaddy first
would replace the lander with a certificate failure. The `.app` TLD is
HSTS-preloaded, so there is no usable HTTP fallback.

## Verification (to run after each stage)

```bash
curl -sS -I https://edifyplanning.app/
curl -sS -o /dev/null -L --max-redirs 10 -w 'final=%{url_effective} redirects=%{num_redirects}\n' https://www.edifyplanning.app/
curl -sS https://edifyplanning.app/ | grep -c lander   # must be 0
```

Pass criteria: apex returns the Edify application; `www` reaches it in exactly
one redirect; zero occurrences of GoDaddy content; no certificate errors.

## Open, not yet root-caused

- `www` root TTFB 0.712 s. Not investigated — deferred until the domain is
  correct, per the incident's own sequencing rule.

## Application repair prepared

- `/` now invokes the normal login view directly for anonymous users and sends
  authenticated users to `/dashboard` without the former two-second launch
  timer.
- The unreferenced launch template, stylesheet, and JavaScript were removed.
- `/lander` permanently redirects to `/` after the request reaches Edify.
- Canonical-host middleware preserves path/query, collapses scheme and host
  normalization into one redirect, and remains disabled until apex TLS is ready.

## Timeline

| Time (UTC) | Event |
|---|---|
| 2026-08-03 ~16:00 | Reported with screenshot |
| 2026-08-03 16:06 | DNS, HTTP, TLS and timing evidence captured |
| 2026-08-03 16:0x | Root cause proven: GoDaddy Forwarding with no destination |
| — | **Pending**: attach apex in DigitalOcean, then replace GoDaddy parked A records |
