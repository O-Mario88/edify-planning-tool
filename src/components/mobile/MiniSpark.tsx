"use client";

import { MiniSparkline } from "@/components/ui/primitives";

// Tiny trend chart used in mobile metric tiles.
export function MiniSpark({
  seed,
  trend,
  color = "#10b981",
}: {
  seed: number;
  trend: "up" | "down";
  color?: string;
}) {
  return (
    <div className="-mx-1">
      <MiniSparkline seed={seed} trend={trend} color={color} height={28} />
    </div>
  );
}
