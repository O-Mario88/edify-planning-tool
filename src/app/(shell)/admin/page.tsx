import Link from "next/link";
import {
  Users,
  Building2,
  Database,
  Workflow,
  Sliders,
  ShieldCheck,
  ChevronRight,
  UserPlus,
  KeyRound,
  AlertTriangle,
  CheckCircle2,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { DEMO_USERS } from "@/lib/auth-public";
import { schoolsMock } from "@/lib/schools-mock";
import { fundRequests, planApprovals, conflicts } from "@/lib/workflow-mock";
import { cn } from "@/lib/utils";

type AdminSection = {
  key:      string;
  title:    string;
  body:     string;
  href:     string;
  Icon:     LucideIcon;
  iconBg:   string;
  iconText: string;
};

const SECTIONS: AdminSection[] = [
  { key: "people",     title: "People & Roles",         body: "Manage staff, supervisors, and role assignments.",        href: "/admin/users",          Icon: Users,        iconBg: "bg-violet-100",  iconText: "text-violet-700"  },
  { key: "schools",    title: "School Directory",       body: "Onboard, edit, archive schools across districts.",         href: "/schools",              Icon: Building2,    iconBg: "bg-sky-100",     iconText: "text-sky-700"     },
  { key: "salesforce", title: "Salesforce Integration", body: "Verification Queue, ID mapping, evidence rules.",          href: "/dashboards/impact",    Icon: Database,     iconBg: "bg-amber-100",   iconText: "text-amber-700"   },
  { key: "workflows",  title: "Workflows",              body: "Approval routing, support reviews, escalation gates.",     href: "/admin/feature-flags",  Icon: Workflow,     iconBg: "bg-emerald-100", iconText: "text-emerald-700" },
  { key: "rules",      title: "Planning Rules",         body: "Holidays, blackouts, conference weeks, auto-blocking.",    href: "/leave",                Icon: Sliders,      iconBg: "bg-rose-100",    iconText: "text-rose-700"    },
  { key: "audit",      title: "Audit & Compliance",     body: "Sign-In trail, role changes, data exports, GDPR ledger.",  href: "/admin/audit-log",      Icon: ShieldCheck,  iconBg: "bg-slate-100",   iconText: "text-slate-700"   },
];

type ActivityKind = "user" | "role" | "flag" | "audit" | "rollback";

const RECENT_ACTIVITY: { kind: ActivityKind; actor: string; text: string; when: string }[] = [
  { kind: "user",     actor: "Anne Wairimu",  text: "added a new CCEO account for Joyce Akinyi (Kitgum cluster)",                 when: "Today · 09:32" },
  { kind: "role",     actor: "Edify Demo",    text: "promoted Daniel Mwangi from CCEO to Country Program Lead",                   when: "Today · 08:10" },
  { kind: "flag",     actor: "Edify Demo",    text: "enabled feature flag verified_impact_v2 for the Uganda tenant",              when: "Yesterday · 16:40" },
  { kind: "audit",    actor: "System",        text: "exported the FY 24/25 audit ledger (1,284 entries) for compliance review",   when: "Yesterday · 11:00" },
  { kind: "rollback", actor: "Edify Demo",    text: "rolled back planning_rules_v3 after partner-block regression",               when: "2 days ago · 14:22" },
];

const ICON: Record<ActivityKind, LucideIcon> = {
  user:     UserPlus,
  role:     KeyRound,
  flag:     CheckCircle2,
  audit:    ShieldCheck,
  rollback: RotateCcw,
};

const TONE: Record<ActivityKind, string> = {
  user:     "bg-violet-100  text-violet-700",
  role:     "bg-sky-100     text-sky-700",
  flag:     "bg-emerald-100 text-emerald-700",
  audit:    "bg-slate-100   text-slate-700",
  rollback: "bg-amber-100   text-amber-700",
};

export default function AdminPage() {
  const userCount       = Object.keys(DEMO_USERS).length;
  const schoolCount     = schoolsMock.length;
  const openApprovals   = planApprovals.length + fundRequests.filter((f) => f.status !== "Disbursed").length;
  const openIncidents   = conflicts.filter((c) => c.severity === "High" || c.severity === "Critical").length;

  return (
    <StubPage
      title="Administration"
      subtitle="Tenant-level overview. The KPI strip surfaces what's outstanding across the platform; each section card opens the operational dashboard that governs it."
    >
      {/* Tenant KPIs */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Users"          value={String(userCount)}     Icon={Users}         tone="bg-violet-100 text-violet-700" sub="across 8 roles" />
        <Kpi label="Schools"        value={String(schoolCount)}   Icon={Building2}     tone="bg-sky-100 text-sky-700"       sub="active in directory" />
        <Kpi label="Open approvals" value={String(openApprovals)} Icon={Workflow}      tone="bg-emerald-100 text-emerald-700" sub="plans + fund requests" />
        <Kpi label="High-severity"  value={String(openIncidents)} Icon={AlertTriangle} tone="bg-rose-100 text-rose-700"     sub="conflicts pending" />
      </section>

      {/* Section cards */}
      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        {SECTIONS.map((s) => (
          <Link
            key={s.key}
            href={s.href}
            className="card p-3.5 col-span-12 md:col-span-6 lg:col-span-4 hover:bg-[var(--color-edify-soft)]/40 flex items-start gap-3"
          >
            <span className={`h-10 w-10 rounded-xl grid place-items-center shrink-0 ${s.iconBg} ${s.iconText}`}>
              <s.Icon size={18} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-body-lg font-extrabold tracking-tight">{s.title}</h2>
                <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
              </div>
              <p className="text-[11.5px] muted leading-snug mt-0.5">{s.body}</p>
            </div>
          </Link>
        ))}
      </section>

      {/* Recent admin activity */}
      <article className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Recent admin activity</h2>
          <Link href="/admin/audit-log" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            View Audit Log →
          </Link>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {RECENT_ACTIVITY.map((e, i) => {
            const Icon = ICON[e.kind];
            return (
              <li key={i} className="py-3 flex items-start gap-3">
                <span className={cn("h-9 w-9 rounded-full grid place-items-center shrink-0", TONE[e.kind])}>
                  <Icon size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-body leading-snug">
                    <span className="font-extrabold">{e.actor}</span> <span>{e.text}</span>
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

function Kpi({ label, value, Icon, tone, sub }: { label: string; value: string; Icon: LucideIcon; tone: string; sub: string }) {
  return (
    <div className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className={cn("h-9 w-9 rounded-full grid place-items-center", tone)}>
          <Icon size={14} />
        </span>
        <span className="text-[11.5px] muted font-semibold">{label}</span>
      </div>
      <div className="text-[24px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}
