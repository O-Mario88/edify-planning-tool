import { Upload, Shield, FileText, Activity } from "lucide-react";
import { DashboardToolsFooter, type DashboardToolItem } from "@/components/ui/DashboardToolsFooter";
import { impactQuickActions, type ImpactQuickAction } from "@/lib/impact-mock";

// IA dashboard's Tools footer — uses the shared DashboardToolsFooter.
//
// Net-new utilities for the Impact Assessment role only. The verify /
// view-issues affordances were dropped because they exist in context
// (the Inbox handles verification; Quality Issues card already links
// to /quality-checks).

const ICON_FOR = {
  upload:        Upload,
  qc:            Shield,
  report:        FileText,
  activity:      Activity,
} as const;

const KEPT = new Set<keyof typeof ICON_FOR>(["upload", "qc", "report", "activity"]);

export function ImpactQuickActionsRow() {
  const items: DashboardToolItem[] = impactQuickActions
    .filter((a): a is ImpactQuickAction & { key: keyof typeof ICON_FOR } =>
      KEPT.has(a.key as keyof typeof ICON_FOR)
    )
    .map((a) => ({
      key:   a.key,
      label: a.label,
      href:  a.href,
      icon:  ICON_FOR[a.key],
      badge: a.badge,
    }));

  return <DashboardToolsFooter items={items} />;
}
