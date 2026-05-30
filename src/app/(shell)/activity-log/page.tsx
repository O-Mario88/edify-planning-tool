import { Upload, ShieldCheck, AlertTriangle, FileText, RotateCcw, type LucideIcon } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { cn } from "@/lib/utils";

type ActivityKind = "upload" | "verify" | "issue" | "report" | "return";

const ENTRIES: { kind: ActivityKind; actor: string; text: string; when: string }[] = [
  { kind: "upload", actor: "John Mwangi",  text: "uploaded CoreSchools_May2025.xlsx — 128 records",                          when: "May 20, 2025 · 10:30 AM" },
  { kind: "verify", actor: "Grace Alimo",  text: "verified 1,256 Exam Scores records (ExamScores_May2025.xlsx)",             when: "May 20, 2025 · 09:45 AM" },
  { kind: "issue",  actor: "Quality bot",  text: "flagged 234 Missing Exam Scores issues across 12 schools",                 when: "May 20, 2025 · 09:10 AM" },
  { kind: "return", actor: "Grace Alimo",  text: "returned SSA_May2025.xlsx to Grace A. — incomplete columns G, H, J",       when: "May 19, 2025 · 02:20 PM" },
  { kind: "report", actor: "Grace Alimo",  text: "generated April 2025 Partner Performance report (PDF)",                    when: "May 18, 2025 · 05:00 PM" },
  { kind: "upload", actor: "Sarah K.",     text: "uploaded ClientSchools_May2025.xlsx — 342 records",                        when: "May 20, 2025 · 09:15 AM" },
  { kind: "verify", actor: "Grace Alimo",  text: "verified 128 Core Schools records",                                        when: "May 20, 2025 · 11:00 AM" },
  { kind: "issue",  actor: "Quality bot",  text: "flagged 156 Duplicate Records in Client Schools upload",                   when: "May 19, 2025 · 04:50 PM" },
];

const ICON: Record<ActivityKind, LucideIcon> = {
  upload: Upload,
  verify: ShieldCheck,
  issue:  AlertTriangle,
  report: FileText,
  return: RotateCcw,
};

const TONE: Record<ActivityKind, string> = {
  upload: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  verify: "bg-emerald-100 text-emerald-700",
  issue:  "bg-rose-100    text-rose-700",
  report: "bg-sky-100     text-sky-700",
  return: "bg-amber-100   text-amber-700",
};

export default function ActivityLogPage() {
  return (
    <StubPage
      title="Activity Log"
      subtitle="Every upload, verification, return, and report. Use the log to audit data lineage and resolve disputes."
    >
      <article className="card p-3.5">
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {ENTRIES.map((e, i) => {
            const Icon = ICON[e.kind];
            return (
              <li key={i} className="py-3 flex items-start gap-3">
                <span className={cn("w-9 h-9 rounded-full grid place-items-center shrink-0", TONE[e.kind])}>
                  <Icon size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-body leading-snug">
                    <span className="font-extrabold">{e.actor}</span>{" "}
                    <span>{e.text}</span>
                  </div>
                  <div className="text-caption muted mt-0.5">{e.when}</div>
                </div>
              </li>
            );
          })}
        </ul>
      </article>
    </StubPage>
  );
}
