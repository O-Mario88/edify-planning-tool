import { RouteSkeleton } from "@/components/shell/RouteSkeleton";

// Per-route loading skeleton — list shape (summary strip + queue lists).
export default function Loading() {
  return <RouteSkeleton variant="list" />;
}
