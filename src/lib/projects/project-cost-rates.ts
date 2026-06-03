// Project partner payment rates (spec — payment amount source). Flat facilitation
// / visit rate per project activity type, in UGX. Mutable in-memory store so the
// accountant/CD can adjust rates; the accountant payment step records the amount.
// Year-2 backend swap = a cost_settings row per activity type.

import type { ProjectActivityType, ProjectActivity } from "./project-activities";

const DEFAULT_RATES: Record<ProjectActivityType, number> = {
  "Project Training": 250_000,
  "Project Follow-Up Visit": 18_000,
  "Project Coaching Visit": 15_000,
  "Project In-School Support": 20_000,
  "Project Assessment": 120_000,
  "Project Cluster Session": 200_000,
  "Project Partner Support": 50_000,
  "Project Evidence Review": 0,
  "Project Closeout Visit": 18_000,
};

const rates: Record<ProjectActivityType, number> = { ...DEFAULT_RATES };

export function projectRates(): { activityType: ProjectActivityType; rate: number }[] {
  return (Object.keys(rates) as ProjectActivityType[]).map((activityType) => ({ activityType, rate: rates[activityType] }));
}

export function rateFor(activityType: ProjectActivityType): number {
  return rates[activityType] ?? 0;
}

/** The payment amount due for a completed partner activity. Flat per-activity
 *  facilitation/visit rate (per-diem/transport handled by the core cost engine). */
export function paymentAmountFor(activity: Pick<ProjectActivity, "activityType">): number {
  return rateFor(activity.activityType);
}

export function setProjectRate(activityType: ProjectActivityType, rate: number): boolean {
  if (!(activityType in rates) || !Number.isFinite(rate) || rate < 0) return false;
  rates[activityType] = Math.round(rate);
  return true;
}

export function formatUgx(n: number): string {
  if (!n) return "—";
  return `UGX ${n.toLocaleString()}`;
}
