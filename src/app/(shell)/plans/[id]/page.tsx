import { notFound } from "next/navigation";
import { ClipboardList, MapPin } from "lucide-react";
import { EntityDetail, DetailFacts } from "@/components/shell/EntityDetail";
import { planItems, type PlanItemStatus } from "@/lib/mobile-mock";

const BADGE: Record<PlanItemStatus, { tone: "amber" | "blue" | "green" | "rose"; label: PlanItemStatus }> = {
  "Planned":        { tone: "amber", label: "Planned" },
  "In Progress":    { tone: "blue",  label: "In Progress" },
  "Verified":       { tone: "green", label: "Verified" },
  "Awaiting SF ID": { tone: "rose",  label: "Awaiting SF ID" },
};

export default async function PlanDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const plan = planItems.find((p) => p.id === id);
  if (!plan) return notFound();

  // Slimmed-down detail card: previously the page repeated Type / Date /
  // Week / Status as a 4-tile KPI strip AND again as DetailFacts rows.
  // The strip was decorative redundancy — users already get those four
  // facts inline via the /plans accordion, and the hero already carries
  // the status badge + week + date in the subtitle. We keep DetailFacts
  // as the single source of truth on this page.
  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",  href: "/dashboard" },
        { label: "Plans", href: "/plans" },
        { label: plan.title },
      ]}
      title={`${plan.title} — ${plan.context}`}
      subtitle={`${plan.weekLabel} · ${plan.date}`}
      Icon={ClipboardList}
      badge={BADGE[plan.status]}
    >
      <DetailFacts
        rows={[
          { label: "Plan ID",  value: plan.id },
          { label: "Type",     value: plan.type },
          { label: "Context",  value: <span className="inline-flex items-center gap-1.5"><MapPin size={12} />{plan.context}</span> },
          { label: "Date",     value: plan.date },
          { label: "Week",     value: plan.weekLabel },
          { label: "Filter",   value: plan.filter },
          { label: "Status",   value: plan.status },
        ]}
      />
    </EntityDetail>
  );
}
