import { OperatingTargetsSkeleton } from "@/components/operating-targets/OperatingTargetsSkeleton";

// Skeleton mirror of the Team Targets dashboard. Team Targets renders
// the same OperatingTargetsView (aggregated from CCEO data) so the
// loading shape matches /my-targets exactly.
export default function Loading() {
  return <OperatingTargetsSkeleton />;
}
