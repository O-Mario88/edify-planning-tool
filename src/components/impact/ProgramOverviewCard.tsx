import Link from "next/link";
import {
  School,
  Building2,
  FileSpreadsheet,
  ShieldCheck,
  Heart,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import { programTiles, type ProgramTile } from "@/lib/impact-mock";
import { cn } from "@/lib/utils";

const ICON: Record<ProgramTile["icon"], LucideIcon> = {
  school:          School,
  building:        Building2,
  fileSpreadsheet: FileSpreadsheet,
  shieldCheck:     ShieldCheck,
  heart:           Heart,
};

const TONE: Record<ProgramTile["iconTone"], string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  green:  "bg-emerald-100 text-emerald-700",
  violet: "bg-violet-100  text-violet-700",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-600",
};

export function ProgramOverviewCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Program Overview</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5 flex-1">
        {programTiles.map((t) => {
          const Icon = ICON[t.icon];
          const tone = TONE[t.iconTone];
          return (
            <Link
              key={t.key}
              href={t.href}
              className="rounded-xl border border-[var(--color-edify-border)] p-3 flex flex-col gap-2 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className={cn("w-9 h-9 rounded-full grid place-items-center shrink-0", tone)}>
                  <Icon size={15} />
                </span>
                <div className="text-[11.5px] muted font-semibold line-clamp-2 leading-tight">
                  {t.label}
                </div>
              </div>
              <div className="text-[24px] font-extrabold tabular leading-none num-hero mt-auto">{t.count}</div>
              <div className="text-caption text-emerald-600 font-semibold inline-flex items-center gap-0.5">
                <ArrowUpRight size={10} />
                {t.trend}
              </div>
            </Link>
          );
        })}
      </div>
    </article>
  );
}
