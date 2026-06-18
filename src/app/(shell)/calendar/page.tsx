import Link from "next/link";
import {
  Calendar,
  CalendarRange,
  GraduationCap,
  Building2,
  Footprints,
  Handshake,
  ClipboardCheck,
  FileText,
  MessageSquare,
  CalendarCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { publicHolidays } from "@/lib/leave-mock";
import { getCurrentUser } from "@/lib/auth";
import { fetchApprovedLeave } from "@/lib/api/surfaces";
import { todayDataForRole, type TodayTone } from "@/lib/today-mock";
import { isMockAllowed } from "@/lib/mock-policy";

type Bucket = "today" | "this-week" | "this-month" | "leave";
type CalTone = "edify" | "amber" | "violet" | "rose" | "green";

type Entry = {
  id: string;
  date: string;
  title: string;
  context: string;
  Icon: LucideIcon;
  tone: CalTone;
  href: string;
  bucket: Bucket;
};

const TONE: Record<CalTone, string> = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100  text-amber-700",
  violet: "bg-violet-100 text-violet-700",
  rose:   "bg-rose-100   text-rose-700",
  green:  "bg-emerald-100 text-emerald-700",
};

// today-mock carries icon names + its own tone vocabulary; map both into
// the calendar's.
const ICONS: Record<string, LucideIcon> = {
  graduationCap: GraduationCap, building2: Building2, footprints: Footprints,
  clipboardCheck: ClipboardCheck, handshake: Handshake, fileText: FileText,
  messageSquare: MessageSquare, calendarCheck: CalendarCheck, users: Users,
};

const TONE_MAP: Record<TodayTone, CalTone> = {
  green: "green", blue: "edify", amber: "amber", rose: "rose", violet: "violet", slate: "edify",
};

export default async function CalendarPage() {
  // Role-scoped: the timeline reflects the signed-in user's day. A
  // Program Lead and a CCEO see their own agenda + upcoming activities;
  // public holidays are shared by everyone.
  const user = await getCurrentUser();
  // The "today / this-week" agenda is fixture data — withhold it in production so
  // the calendar shows only live entries (approved leave + real public holidays).
  const today = isMockAllowed() ? todayDataForRole(user.role) : { agenda: [], upcoming: [] };

  // Approved leave from the backend — the caller's own (HR/CD: the team's).
  // Linked here so leave schedules surface on the same timeline.
  const leaveRes = await fetchApprovedLeave(user);
  const leaveEntries: Entry[] = (leaveRes.live ? leaveRes.data : []).map((l) => ({
    id: `leave-${l.id}`,
    date: l.dates.length > 1 ? `${l.startDate} → ${l.endDate}` : l.startDate,
    title: `${l.type[0].toUpperCase()}${l.type.slice(1)} leave — ${l.staffName}`,
    context: `${l.dates.length} day${l.dates.length === 1 ? "" : "s"} · planning auto-blocked`,
    Icon: Users,
    tone: "violet",
    href: "/leave",
    bucket: "leave" as const,
  }));

  const todayEntries: Entry[] = today.agenda.flatMap((block) =>
    block.tasks.map((t, i) => ({
      id: `today-${block.label}-${i}`,
      date: block.label,
      title: t.title,
      context: t.place,
      Icon: ICONS[t.icon] ?? Building2,
      tone: TONE_MAP[t.tone],
      href: "/today",
      bucket: "today" as const,
    })),
  );

  const weekEntries: Entry[] = today.upcoming.map((u, i) => ({
    id: `week-${i}`,
    date: u.date,
    title: u.title,
    context: u.sub,
    Icon: ICONS[u.icon] ?? CalendarCheck,
    tone: TONE_MAP[u.tone],
    href: "/today",
    bucket: "this-week" as const,
  }));

  const holidayEntries: Entry[] = publicHolidays.map((h) => ({
    id: `hol-${h.date}`,
    date: h.date,
    title: h.title,
    context: "Public holiday — planning auto-blocked",
    Icon: CalendarRange,
    tone: "rose",
    href: "/leave",
    bucket: "this-month",
  }));

  const buckets: { key: Bucket; label: string; subtitle: string; entries: Entry[] }[] = [
    { key: "today",      label: "Today",      subtitle: todayEntries.length ? "Your agenda for today" : "Nothing on today", entries: todayEntries },
    { key: "this-week",  label: "This Week",  subtitle: "Your upcoming activities this week", entries: weekEntries },
    { key: "this-month", label: "This Month", subtitle: "Holidays, blackouts, and conference weeks", entries: [...holidayEntries].sort((a, b) => a.date.localeCompare(b.date)) },
    { key: "leave",      label: "Approved Leave", subtitle: leaveEntries.length ? "Leave schedules blocking planning days" : "No approved leave on the books", entries: [...leaveEntries].sort((a, b) => a.date.localeCompare(b.date)) },
  ];

  return (
    <StubPage
      title="Calendar"
      subtitle="Every activity that affects your time — today's tasks, this week's plans, this month's holidays — in one timeline."
    >
      {buckets.map((b) => (
        <section key={b.key} className="card rounded-2xl overflow-hidden">
          <header className="px-4 pt-4 pb-2 flex items-baseline justify-between">
            <div>
              <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
                <Calendar size={14} className="text-[var(--color-edify-primary)]" />
                {b.label}
              </h2>
              <p className="text-[11px] muted">{b.subtitle}</p>
            </div>
            <span className="text-[11px] muted">{b.entries.length}</span>
          </header>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {b.entries.length === 0 ? (
              <li className="px-4 py-6 text-[12px] muted text-center">No items.</li>
            ) : (
              b.entries.map((e) => (
                <li key={e.id}>
                  <Link
                    href={e.href}
                    className="flex items-start gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40"
                  >
                    <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${TONE[e.tone]}`}>
                      <e.Icon size={15} />
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-body font-extrabold tracking-tight">{e.title}</div>
                      <div className="text-[11px] muted truncate">{e.context}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-body font-extrabold tabular leading-none">{e.date}</div>
                    </div>
                  </Link>
                </li>
              ))
            )}
          </ul>
        </section>
      ))}
    </StubPage>
  );
}
