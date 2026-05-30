"use client";

import { RouteError } from "@/components/shell/RouteError";

// Per-route error boundary. Catches thrown errors in this segment
// without unmounting the shell — sidebar + top bar + bottom nav stay
// visible so the user can navigate away. Customise the title / subtitle
// or homeHref by editing this file directly.
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <RouteError error={error} reset={reset} />;
}
