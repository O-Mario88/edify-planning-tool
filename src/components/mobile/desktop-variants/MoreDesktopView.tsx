import Link from "next/link";
import {
  CalendarCheck,
  ClipboardList,
  Award,
  Map,
  Database,
  Wallet,
  Eye,
  Sparkles,
  HelpCircle,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { MobileViewDesktopShell } from "@/components/mobile/MobileViewDesktopShell";
import { todayHeader, todaysTaskCounts, sfQueueCounts } from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

type Tile = { label: string; href: string; Icon: LucideIcon; badge?: number; sub?: string };

const QUICK: Tile[] = [
  { label: "Today's Tasks",         href: "/today",          Icon: CalendarCheck, badge: todaysTaskCounts.planned + todaysTaskCounts.inProgress, sub: todayHeader.dateLabel },
  { label: "My Plan",               href: "/my-plan",        Icon: ClipboardList, sub: "Current month activities" },
  { label: "My Targets",            href: "/my-targets",     Icon: Award,         sub: "Personal achievement" },
  { label: "Routes",                href: "/route",          Icon: Map,           sub: "Smart route planning" },
  { label: "Salesforce Queue",      href: "/queue",          Icon: Database,      badge: sfQueueCounts.awaiting, sub: "IDs to submit" },
  { label: "Fund Requests",         href: "/fund-requests",  Icon: Wallet,        sub: "Review + track funds" },
];

const DASHBOARDS: Tile[] = [
  { label: "Country Director",      href: "/dashboards/director",   Icon: Eye, sub: "National cockpit" },
  { label: "RVP",                   href: "/dashboards/rvp",        Icon: Eye, sub: "Regional rollups" },
  { label: "Country Program Lead",  href: "/dashboards/cpl",        Icon: Eye, sub: "Team management" },
  { label: "Accountant",            href: "/dashboards/accountant", Icon: Wallet, sub: "Finance console" },
  { label: "Impact Assessment",     href: "/dashboards/impact",     Icon: Eye, sub: "Verification + data quality" },
];

const ACCOUNT: Tile[] = [
  { label: "Demo Guide",     href: "/demo-guide",     Icon: Sparkles, sub: "Scenarios + scripts" },
  { label: "Help",           href: "/help",           Icon: HelpCircle },
  { label: "Settings",       href: "/settings",       Icon: Settings },
];

export function MoreDesktopView() {
  return (
    <MobileViewDesktopShell
      title="More"
      subtitle="On desktop the left sidebar covers most navigation — this page is the quick-link tile hub for everything else."
    >
      <Section title="Quick links" tiles={QUICK} />
      <Section title="Dashboards by role" tiles={DASHBOARDS} />
      <Section title="Account" tiles={ACCOUNT} />
    </MobileViewDesktopShell>
  );
}

function Section({ title, tiles }: { title: string; tiles: Tile[] }) {
  return (
    <section className="space-y-2 mb-4">
      <h2 className="text-body font-extrabold tracking-tight uppercase muted px-1">{title}</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
        {tiles.map((t) => (
          <Link
            key={t.label}
            href={t.href}
            className="card rounded-2xl p-3 flex items-center gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
          >
            <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
              <t.Icon size={16} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-body font-extrabold tracking-tight">{t.label}</span>
                {t.badge != null && t.badge > 0 && (
                  <span className={cn(
                    "inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-md text-caption font-extrabold tabular",
                    "bg-rose-500 text-white",
                  )}>{t.badge}</span>
                )}
              </div>
              {t.sub && <div className="text-caption muted truncate">{t.sub}</div>}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
