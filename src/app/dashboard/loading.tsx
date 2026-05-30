import { RouteSkeleton } from "@/components/shell/RouteSkeleton";

// Per-route loading skeleton. Renders while this segment's server data
// resolves — keeps the shell mounted and shows a shape preview so the
// page never flashes blank. To customise the shape, swap in a variant
// (`list` | `detail` | `form` | `default`) or replace this file
// entirely with a bespoke skeleton.
export default function Loading() {
  return <RouteSkeleton />;
}
