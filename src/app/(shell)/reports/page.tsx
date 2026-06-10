import Link from "next/link";
import {
  FileText,
  ChevronRight,
  CalendarRange,
  Trophy,
  ShieldCheck,
  Wallet,
  Users,
  Activity,
  Clock,
  Pause,
  Play,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ExportButton } from "@/components/ui/ExportButton";
import { EmptyState } from "@/components/ui/DataStates";
import { CceoAutoReports } from "@/components/reports/CceoAutoReports";
import { cn } from "@/lib/utils";
import { getCurrentUser } from "@/lib/auth";
import type { EdifyRole } from "@/lib/auth-public";

type ReportTile = {
  title:       string;
  description: string;
  href:        string;
  Icon:        LucideIcon;
  iconBg:      string;
  iconText:    string;
  roles:       EdifyRole[];
};

// Each report is tagged with the roles it's relevant to; the catalog
// below is filtered to the signed-in user so the page only shows
// roll-ups that role would actually open.
const REPORTS: ReportTile[] = [
  { title: "Country Performance",   description: "Country Director rollup — KPIs, leadership attention, regional comparison.", href: "/dashboards/director", Icon: Activity,      iconBg: "bg-emerald-100", iconText: "text-emerald-700", roles: ["CountryDirector", "RVP", "Admin"] },
  { title: "Team Targets",          description: "Achievement, pace status, mid-year flags, support reviews.",                  href: "/team-targets",        Icon: Users,         iconBg: "bg-violet-100",  iconText: "text-violet-700",  roles: ["CountryProgramLead", "CountryDirector", "RVP", "HumanResource", "Admin"] },
  { title: "SSA Performance",       description: "Annual SSA trend, intervention scores, district heatmap.",                    href: "/ssa",                 Icon: ShieldCheck,   iconBg: "bg-sky-100",     iconText: "text-sky-700",     roles: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ImpactAssessment", "Admin"] },
  { title: "Verified Impact",       description: "Leaderboard of verified work across categories + most-improved.",             href: "/team-targets",         Icon: Trophy,        iconBg: "bg-yellow-100",  iconText: "text-yellow-700",  roles: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "HumanResource", "ImpactAssessment", "Admin"] },
  { title: "Daily Field Debrief",   description: "Daily debriefs → weekly leadership decisions.",                                href: "/field-intelligence",  Icon: FileText,      iconBg: "bg-amber-100",   iconText: "text-amber-700",   roles: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ImpactAssessment", "HumanResource", "Admin"] },
  { title: "Funds & Disbursement",  description: "Pending review, disbursed, returned — by request and by district.",           href: "/dashboards/accountant", Icon: Wallet,      iconBg: "bg-rose-100",    iconText: "text-rose-700",    roles: ["ProgramAccountant", "CountryDirector", "RVP", "Admin"] },
  { title: "Leave & Holidays",      description: "Approved leave, holidays, blocked planning days, conflicts.",                   href: "/leave",               Icon: CalendarRange, iconBg: "bg-orange-100",  iconText: "text-orange-700",  roles: ["CCEO", "CountryProgramLead", "CountryDirector", "RVP", "ProgramAccountant", "ImpactAssessment", "HumanResource", "Admin"] },
];

const FORMAT_TONE = {
  PDF:  "bg-rose-100    text-rose-700",
  XLSX: "bg-emerald-100 text-emerald-700",
  CSV:  "bg-sky-100     text-sky-700",
} as const;

// No backend reports source exists yet — render empty states, never fabricated
// rows. These become live fetches once a reports endpoint ships.
type RecentReport = { id: string; title: string; period: string; generatedBy: string; generatedAt: string; format: keyof typeof FORMAT_TONE; sizeKb: number };
type ScheduledReport = { id: string; title: string; cadence: string; nextRun: string; recipients: string; status: "Active" | "Paused" };
const recentReports: RecentReport[] = [];
const scheduledReports: ScheduledReport[] = [];

export default async function ReportsPage() {
  const user = await getCurrentUser();

  // CCEO (spec §21): seven auto-generated reports assembled from the
  // records the CCEO already produces — no manual report writing.
  if (user.role === "CCEO") {
    return (
      <StubPage
        title="My Reports"
        subtitle="Auto-generated from your workflow records — plans, completions, evidence, SSA, partner work, cluster meetings and targets. View the detail or export."
      >
        <CceoAutoReports />
      </StubPage>
    );
  }

  const reports = REPORTS.filter((r) => r.roles.includes(user.role));

  return (
    <StubPage
      title="Reports"
      subtitle="The roll-ups relevant to your role. Open a report to drill into live data, download a recent snapshot, or manage what's scheduled."
    >
      {/* Report sources */}
      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        {reports.map((r) => (
          <Link
            key={r.title}
            href={r.href}
            className="card p-3.5 col-span-12 md:col-span-6 lg:col-span-4 hover:bg-[var(--color-edify-soft)]/40 transition-colors flex items-start gap-3"
          >
            <span className={`h-10 w-10 rounded-xl grid place-items-center shrink-0 ${r.iconBg} ${r.iconText}`}>
              <r.Icon size={18} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-body-lg font-extrabold tracking-tight">{r.title}</h2>
                <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
              </div>
              <p className="text-[11.5px] muted leading-snug mt-0.5">{r.description}</p>
            </div>
          </Link>
        ))}
      </section>

      {/* Recent generated reports */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <div>
            <h2 className="text-body-lg font-extrabold tracking-tight">Recent reports</h2>
            <p className="text-[11.5px] muted">{recentReports.length} snapshots generated in the last 30 days.</p>
          </div>
          <ExportButton
            rows={recentReports.map((r) => ({
              Report: r.title, Period: r.period, Format: r.format,
              "Generated by": r.generatedBy, "Generated at": r.generatedAt, "Size (MB)": (r.sizeKb / 1024).toFixed(1),
            }))}
            filename="reports-manifest"
            label="Export manifest"
            className="!h-9 !px-3 !rounded-xl"
          />
        </header>
        {recentReports.length === 0 && (
          <EmptyState compact title="No reports generated yet" message="Generated report snapshots will appear here once the backend is producing them." />
        )}
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {recentReports.map((r) => (
            <li key={r.id} className="py-2.5 flex items-center gap-3">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <FileText size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{r.title}</div>
                <div className="text-caption muted truncate">
                  {r.period} · {r.generatedBy} · {r.generatedAt}
                </div>
              </div>
              <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", FORMAT_TONE[r.format])}>
                {r.format}
              </span>
              <span className="text-caption muted tabular shrink-0 w-[64px] text-right">
                {(r.sizeKb / 1024).toFixed(1)} MB
              </span>
              <ExportButton
                rows={[{ Report: r.title, Period: r.period, Format: r.format, "Generated by": r.generatedBy, "Generated at": r.generatedAt }]}
                filename={r.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}
                iconOnly
                ariaLabel={`Download ${r.title}`}
                className="!rounded-md shrink-0"
              />
            </li>
          ))}
        </ul>
      </section>

      {/* Scheduled reports */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <div>
            <h2 className="text-body-lg font-extrabold tracking-tight">Scheduled reports</h2>
            <p className="text-[11.5px] muted">Auto-generated and emailed to recipients on cadence.</p>
          </div>
          <button
            type="button"
            className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Clock size={13} />
            Schedule new
          </button>
        </header>
        {scheduledReports.length === 0 ? (
          <EmptyState compact title="No scheduled reports" message="Scheduled report jobs will appear here once configured against the backend." />
        ) : (
        <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full text-[12px] min-w-[640px]">
          <thead>
            <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th scope="col" className="py-2 pr-2">Report</th>
              <th scope="col" className="py-2 px-2">Cadence</th>
              <th scope="col" className="py-2 px-2">Next run</th>
              <th scope="col" className="py-2 px-2">Recipients</th>
              <th scope="col" className="py-2 px-2">Status</th>
              <th scope="col" className="py-2 pl-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {scheduledReports.map((s) => {
              const ActionIcon = s.status === "Active" ? Pause : Play;
              return (
                <tr key={s.id} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 pr-2 font-extrabold">{s.title}</td>
                  <td className="py-2.5 px-2">{s.cadence}</td>
                  <td className="py-2.5 px-2 muted whitespace-nowrap">{s.nextRun}</td>
                  <td className="py-2.5 px-2 muted truncate max-w-[260px]">{s.recipients}</td>
                  <td className="py-2.5 px-2">
                    <span className={cn(
                      "inline-flex items-center px-1.5 py-[2px] rounded-md text-caption font-extrabold whitespace-nowrap",
                      s.status === "Active" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
                    )}>
                      {s.status}
                    </span>
                  </td>
                  <td className="py-2.5 pl-2 text-right">
                    <button
                      type="button"
                      className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]/40"
                      aria-label={s.status === "Active" ? `Pause ${s.title}` : `Resume ${s.title}`}
                    >
                      <ActionIcon size={12} className="text-[var(--color-edify-muted)]" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
        )}
      </section>
    </StubPage>
  );
}
