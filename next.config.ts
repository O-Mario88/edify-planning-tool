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

const nextConfig: NextConfig = {
  // NOTE: We tried `modularizeImports` for `lucide-react` to speed up dev
  // HMR, but the icon-file paths differ across lucide-react versions and
  // the rewrite broke at least one icon import. Modern lucide-react
  // tree-shakes well in production builds, so leaving the default barrel.

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
