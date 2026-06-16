import Link from "next/link";
import { AlertTriangle, AlertOctagon, Info, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { topQualityIssues, qualityCheckSeverity } from "@/lib/impact-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

export default function AlertsPage() {
  // Alert counts/severity come from impact-mock; withhold in production.
  if (!isMockAllowed()) return <InsufficientData surface="data-quality alerts" />;
  const critical = qualityCheckSeverity.find((s) => s.key === "critical")?.value ?? 0;
  const major    = qualityCheckSeverity.find((s) => s.key === "major")?.value    ?? 0;
  const minor    = qualityCheckSeverity.find((s) => s.key === "minor")?.value    ?? 0;

  return (
    <StubPage
      title="Alerts & Issues"
      subtitle="Active data-quality issues across every program area. Critical alerts block target counting until resolved."
    >
      <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Severity icon={<AlertOctagon  size={14} />} tone="rose"  label="Critical" value={critical} href="/quality-checks?severity=critical" />
        <Severity icon={<AlertTriangle size={14} />} tone="amber" label="Major"    value={major}    href="/quality-checks?severity=major" />
        <Severity icon={<Info          size={14} />} tone="blue"  label="Minor"    value={minor}    href="/quality-checks?severity=minor" />
      </section>

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Top open issues</h2>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {topQualityIssues.map((i) => (
            <li key={i.key}>
              <Link
                href={i.href}
                className="flex items-center gap-3 py-2.5 -mx-2 px-2 rounded-md hover:bg-[var(--color-edify-soft)]/40"
              >
                <span className="text-[12px] font-semibold flex-1 truncate">{i.label}</span>
                <span className="text-[12px] font-extrabold tabular">{i.count}</span>
                <ChevronRight size={12} className="text-[var(--color-edify-muted)]" />
              </Link>
            </li>
          ))}
        </ul>
      </article>
    </StubPage>
  );
}

const TONE: Record<"rose" | "amber" | "blue", string> = {
  rose:  "bg-rose-100  text-rose-700",
  amber: "bg-amber-100 text-amber-700",
  blue:  "bg-sky-100   text-sky-700",
};

function Severity({
  icon, tone, label, value, href,
}: {
  icon: React.ReactNode; tone: "rose" | "amber" | "blue"; label: string; value: number; href: string;
}) {
  return (
    <Link href={href} className="card p-3.5 hover:shadow-md transition-shadow">
      <div className="flex items-center gap-2 mb-2">
        <span className={cn("w-9 h-9 rounded-full grid place-items-center shrink-0", TONE[tone])}>{icon}</span>
        <span className="text-[11.5px] muted font-semibold">{label}</span>
      </div>
      <div className="text-[28px] font-extrabold tabular leading-none">{value}</div>
    </Link>
  );
}
