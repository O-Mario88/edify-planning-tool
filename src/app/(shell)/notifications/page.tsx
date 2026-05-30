import Link from "next/link";
import {
  AlertTriangle,
  Bell,
  ClipboardCheck,
  ShieldCheck,
  Wallet,
  Trophy,
  CalendarRange,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { getCurrentUser } from "@/lib/auth";
import { readNotificationsFor, type NotificationRecord } from "@/lib/actions/audit";

// Notifications draws from the same engines that power the dashboards.
// Each row is a real link into the page where the underlying state lives,
// so a user can act on the alert in one tap.
//
// Live events from the canonical store (`emitNotification` / fan-out
// from server actions) appear first; the static demo rows below
// describe the kinds of events the page surfaces, so the page is
// useful even before any action has fired this session.

type DemoNotification = {
  id: string;
  title: string;
  body: string;
  href: string;
  unread: boolean;
  ago: string;
  Icon: LucideIcon;
  iconBg: string;
  iconText: string;
};

const DEMO_NOTIFICATIONS: DemoNotification[] = [
  { id: "n-1", title: "12 plans awaiting your approval",            body: "Submitted by 6 CCEOs across Kigun and Mbarara.",                       href: "/approvals",        unread: true,  ago: "12m",  Icon: ClipboardCheck, iconBg: "bg-amber-100",   iconText: "text-amber-700"   },
  { id: "n-2", title: "3 staff members behind target",              body: "Mid-year flag triggered — open the support-review checklist.",        href: "/team-targets",            unread: true,  ago: "32m",  Icon: AlertTriangle,  iconBg: "bg-rose-100",    iconText: "text-rose-700"    },
  { id: "n-3", title: "Daily Field Debrief is due",                  body: "You haven't submitted today's debrief yet.",                            href: "/field-intelligence",      unread: true,  ago: "1h",   Icon: ShieldCheck,    iconBg: "bg-emerald-100", iconText: "text-emerald-700" },
  { id: "n-4", title: "5 fund requests need disbursement",           body: "Disbursement window closes Friday at 17:00.",                          href: "/dashboards/accountant",   unread: false, ago: "3h",   Icon: Wallet,         iconBg: "bg-violet-100",  iconText: "text-violet-700"  },
  { id: "n-5", title: "You moved to #2 on the verified leaderboard", body: "Sarah Okello overtook Daniel Mwangi this cycle.",                       href: "/leaderboard",             unread: false, ago: "Yesterday", Icon: Trophy,    iconBg: "bg-yellow-100",  iconText: "text-yellow-700"  },
  { id: "n-6", title: "Public holiday on Friday",                    body: "Planning auto-blocked — your route runner skipped 2 stops.",            href: "/leave",                   unread: false, ago: "2d",   Icon: CalendarRange,  iconBg: "bg-sky-100",     iconText: "text-sky-700"     },
];

// Pick an icon for a live notification based on its template key.
// Falls back to a generic bell so an unknown template never breaks
// the page.
function iconForTemplate(template: string): { Icon: LucideIcon; bg: string; text: string } {
  if (template.startsWith("weeklyFund") || template.startsWith("fundPlan") || template.startsWith("reimbursement") || template.startsWith("balance")) {
    return { Icon: Wallet, bg: "bg-violet-100", text: "text-violet-700" };
  }
  if (template.startsWith("plan.") || template.startsWith("costSetting")) {
    return { Icon: ClipboardCheck, bg: "bg-amber-100", text: "text-amber-700" };
  }
  return { Icon: Bell, bg: "bg-[var(--color-edify-soft)]", text: "text-[var(--color-edify-primary)]" };
}

function relativeFrom(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (sec < 5)     return "just now";
  if (sec < 60)    return `${sec}s`;
  if (sec < 3600)  return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

export const dynamic = "force-dynamic";

export default async function NotificationsPage() {
  const user = await getCurrentUser();
  // Pull notifications addressed to the current user. Role tokens
  // (ACCOUNTANT / PROGRAM_LEAD / COUNTRY_DIRECTOR) are fan-out targets
  // the server actions emit when they don't know a specific recipient
  // id — surface them too so the inbox is complete in mock-mode.
  const roleToken = user.role === "ProgramAccountant" ? "ACCOUNTANT"
                  : user.role === "CountryProgramLead" ? "PROGRAM_LEAD"
                  : user.role === "CountryDirector" ? "COUNTRY_DIRECTOR"
                  : null;
  const personal = readNotificationsFor(user.staffId, { limit: 100 });
  const roleScoped = roleToken ? readNotificationsFor(roleToken, { limit: 100 }) : [];
  // Merge + sort newest-first; de-dupe on id in case fan-out doubled
  // a write (defensive — shouldn't happen).
  const live = dedupeAndSort([...personal, ...roleScoped]);

  const liveUnread = live.filter((n) => !n.read).length;
  const demoUnread = DEMO_NOTIFICATIONS.filter((n) => n.unread).length;
  const totalUnread = liveUnread + demoUnread;
  const totalCount = live.length + DEMO_NOTIFICATIONS.length;

  return (
    <StubPage
      title="Notifications"
      subtitle={`${totalUnread} unread · ${totalCount - totalUnread} read this week. ${live.length > 0 ? `${live.length} live event${live.length === 1 ? "" : "s"} from this session.` : "Drawn from the same engines that power your dashboards."}`}
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {/* Live notifications — from the canonical store */}
        {live.map((n) => {
          const { Icon, bg, text } = iconForTemplate(n.template);
          return (
            <Link
              key={n.id}
              href={n.href ?? "/notifications"}
              className={`flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40 ${!n.read ? "bg-[var(--color-edify-soft)]/20" : ""}`}
            >
              <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${bg} ${text}`}>
                <Icon size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold tracking-tight">
                    {n.title}
                    {!n.read && <span className="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-edify-primary)] align-middle" aria-label="Unread" />}
                  </div>
                  <div className="text-caption muted shrink-0 tabular">{relativeFrom(n.createdAt)}</div>
                </div>
                <div className="text-[11.5px] muted leading-snug mt-0.5">{n.body}</div>
                <div className="text-[9.5px] muted leading-snug mt-1 font-mono uppercase tracking-wide">
                  {n.template} · {n.channel}
                </div>
              </div>
            </Link>
          );
        })}
        {/* Static demo notifications — page never looks empty */}
        {DEMO_NOTIFICATIONS.map((n) => (
          <Link
            key={n.id}
            href={n.href}
            className={`flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40 ${n.unread ? "bg-[var(--color-edify-soft)]/20" : ""}`}
          >
            <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${n.iconBg} ${n.iconText}`}>
              <n.Icon size={15} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-2">
                <div className="text-body font-extrabold tracking-tight">
                  {n.title}
                  {n.unread && <span className="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-[var(--color-edify-primary)] align-middle" aria-label="Unread" />}
                </div>
                <div className="text-caption muted shrink-0">{n.ago}</div>
              </div>
              <div className="text-[11.5px] muted leading-snug mt-0.5">{n.body}</div>
            </div>
          </Link>
        ))}
      </section>
    </StubPage>
  );
}

function dedupeAndSort(rows: NotificationRecord[]): NotificationRecord[] {
  const seen = new Set<string>();
  const out: NotificationRecord[] = [];
  for (const r of rows) {
    if (seen.has(r.id)) continue;
    seen.add(r.id);
    out.push(r);
  }
  return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
