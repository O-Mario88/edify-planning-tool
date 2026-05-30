import { OperatingTargetsSkeleton } from "@/components/operating-targets/OperatingTargetsSkeleton";

// Skeleton mirror of the My Targets dashboard. Matches the real
// component's layout so there's no layout shift on hydration.
export default function Loading() {
  return <OperatingTargetsSkeleton />;
}
