import Link from "next/link";
import { topQualityIssues, type DataQualityIssue } from "@/lib/impact-mock";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";

// Issue tone (rose/amber/violet/blue/green) → canonical ChipTone so
// the count pill renders with the same primitive used everywhere else.
const COUNT_TONE: Record<DataQualityIssue["tone"], ChipTone> = {
  rose:   "red",
  amber:  "amber",
  violet: "violet",
  blue:   "blue",
  green:  "green",
};

export function TopIssuesCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="text-body-lg font-extrabold tracking-tight">Top Data Quality Issues</h2>
        <Link
          href="/quality-checks"
          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
        >
          View All
        </Link>
      </header>

      <ul className="space-y-1.5 flex-1">
        {topQualityIssues.map((i) => (
          <li key={i.key}>
            <Link
              href={i.href}
              className="flex items-center justify-between gap-2 px-2 -mx-2 py-1.5 rounded-md text-[12px] hover:bg-[var(--surface-hover)] transition-colors"
            >
              <span className="font-semibold flex-1 truncate">{i.label}</span>
              <StatusBadge tone={COUNT_TONE[i.tone]} className="tabular shrink-0">
                {i.count}
              </StatusBadge>
            </Link>
          </li>
        ))}
      </ul>
    </article>
  );
}
