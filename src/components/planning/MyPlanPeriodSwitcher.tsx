"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { MyPlanPeriodTabs } from "./MyPlanPeriodTabs";
import type { BeMyPlanPeriod } from "@/lib/api/surfaces";

export function MyPlanPeriodSwitcher() {
  const router = useRouter();
  const params = useSearchParams();
  const period = (params.get("period") ?? "month") as BeMyPlanPeriod;

  return (
    <MyPlanPeriodTabs
      value={period}
      onChange={(p) => {
        const next = new URLSearchParams(params.toString());
        next.set("period", p);
        router.push(`/my-plan?${next.toString()}`);
      }}
    />
  );
}
