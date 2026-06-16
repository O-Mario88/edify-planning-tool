import { Database } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";

// Production-safety empty state. Rendered in place of any surface that is not
// yet wired to live backend source records, so production NEVER shows fabricated
// numbers. Pair with `isMockAllowed()` from "@/lib/mock-policy": when mock data
// is not allowed (production, or dev with the backend on) and a surface has no
// live data path, render this instead of the mock content.
//
//   if (!isMockAllowed()) return <InsufficientData surface="the fund queue" />;
//
// Honest by design: it shows nothing rather than a placeholder figure a leader
// could mistake for real data.
export function InsufficientData({
  surface = "this view",
  detail,
}: {
  surface?: string;
  detail?: string;
}) {
  return (
    <EmptyState
      Icon={Database}
      tone="amber"
      title="Insufficient data"
      body={
        detail ??
        `${surface[0].toUpperCase()}${surface.slice(1)} is not yet connected to live backend data. ` +
          `Figures are withheld until they can be traced to source records — no placeholder numbers are shown.`
      }
    />
  );
}
