import type { NextConfig } from "next";
import bundleAnalyzer from "@next/bundle-analyzer";

// Bundle analyzer — opt-in via `ANALYZE=true npm run build` (already
// wired as `npm run analyze`). Generates HTML reports under
// .next/analyze that map every chunk to its sources, surfacing which
// dependencies are inflating the client bundle.
//
// We track three numbers: client (first-load JS shared across pages),
// server (RSC payload + edge bundle), and per-page client. Recharts +
// motion are the two heaviest deps; both are dynamic-imported via
// lib/lazy-charts.ts to keep them off the critical path.
const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

// ── Security headers (OWASP ASVS / spec §10,§13,§14) ──────────────────────
// Applied to every response. The browser only ever talks to same-origin
// (API + SSE are Next proxies; the backend URL is server-side only), so the
// CSP can keep connect-src to 'self'. Dev needs 'unsafe-eval' + ws: for HMR.
const isDev = process.env.NODE_ENV !== "production";
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'", // clickjacking: only our own origin may frame us
  "object-src 'none'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'", // Next + chart libs inject inline styles
  // 'unsafe-inline' for Next's bootstrap; 'unsafe-eval' only in dev for HMR.
  // TODO(Phase 9): move to nonce-based script-src to drop 'unsafe-inline'.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "frame-src 'self' blob: data:", // in-app PDF/image preview of proxied evidence
  `connect-src 'self'${isDev ? " ws: http://localhost:*" : ""}`,
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), browsing-topics=()" },
  // HSTS — force HTTPS for two years incl. subdomains. Harmless on localhost
  // (browsers ignore HSTS on http/localhost); active behind TLS in production.
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },

  // NOTE: We tried `modularizeImports` for `lucide-react` to speed up dev
  // HMR, but the icon-file paths differ across lucide-react versions and
  // the rewrite broke at least one icon import. Modern lucide-react
  // tree-shakes well in production builds, so leaving the default barrel.

  // Standalone output → a self-contained .next/standalone server with only the
  // traced runtime deps, for a small production Docker image.
  output: "standalone",

  images: {
    // Next 15 requires every `quality` value used by next/image to be
    // whitelisted here. The login hero photo uses `quality={85}` for
    // the premium-photography feel; 75 is the default. Keep both.
    qualities: [75, 85],
  },

  experimental: {
    // Push the chunky icon + chart libraries through SWC's optimised
    // import path so prod bundles only pull the icons + chart pieces
    // that are actually used. Big win on the CCEO + CPL dashboards
    // which import ~30 icons each.
    optimizePackageImports: [
      "lucide-react",
      "recharts",
      "motion",
    ],
  },
};

export default withBundleAnalyzer(nextConfig);
