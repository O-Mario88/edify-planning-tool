"use client";

// Today's Tasks console — role-scoped.
// Renders inside the shared app shell — the main EdifySidebar (from the
// (shell) layout) provides navigation. Data comes from today-mock keyed
// by role; the signed-in user's identity is threaded in from today/page.tsx.

import Link from "next/link";
import { useState } from "react";
import {
  ChevronDown, CalendarCheck, Users, Calendar, ClipboardCheck, Wallet,
  Navigation, FileText, CheckCircle2, Loader, Flame,
  Sun, Moon, GraduationCap, Building2, Footprints, Handshake,
  MessageSquare, Clock, CircleDashed, MoreVertical, List, CalendarDays,
  Target, Upload, type LucideIcon,
} from "lucide-react";
import type {
  TodayData, TodayTone, TodayStatus, TodayGlance,
} from "@/lib/today-mock";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { Pill, TaskPill } from "@/components/ui/Pill";
import { BackButton } from "@/components/ui/BackButton";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";

/* ─────────────────────────── Maps ─────────────────────────── */

const TILE: Record<TodayTone, string> = {
  green:  "bg-[#e4f6ec] text-[#13a45c]",
  blue:   "bg-[#e6f0fc] text-[#2f74d9]",
  amber:  "bg-[#fdf0db] text-[#d2901f]",
  rose:   "bg-[#fce8e6] text-[#e0524a]",
  violet: "bg-[#efe9fb] text-[#7c5cc4]",
  slate:  "bg-[var(--color-edify-divider)] text-[#5b6b78]",
};

const STATUS: Record<TodayStatus, { chip: string; icon: LucideIcon }> = {
  "Completed":   { chip: "bg-[#e4f6ec] text-[#15803d]", icon: CheckCircle2 },
  "In Progress": { chip: "bg-[#fdf0db] text-[#b06a12]", icon: Clock        },
  "Planned":     { chip: "bg-[var(--color-edify-divider)] text-[#5b6b78]", icon: CircleDashed },
  "Overdue":     { chip: "bg-[#fce8e6] text-[#b42318]", icon: Flame        },
};

// Data files carry icon names (strings); resolve them here.
const ICONS: Record<string, LucideIcon> = {
  checkCircle2: CheckCircle2, loader: Loader, clipboardCheck: ClipboardCheck,
  flame: Flame, sun: Sun, moon: Moon, graduationCap: GraduationCap,
  building2: Building2, footprints: Footprints, handshake: Handshake,
  fileText: FileText, messageSquare: MessageSquare, calendarCheck: CalendarCheck,
  users: Users, wallet: Wallet, navigation: Navigation, upload: Upload,
};

/* ─────────────────────────── Pieces ─────────────────────────── */

function Donut({ glance, total }: { glance: TodayGlance[]; total: number }) {
  const r = 46, c = 2 * Math.PI * r, gap = 3;
  // Prefix-sum offset for each arc, computed purely so React Compiler
  // can memoize the JSX. A `let offset += len` inside .map() would
  // trip cannot-reassign-after-render.
  const lens = glance.map((s) => (s.pct / 100) * c);
  const offsets = lens.map((_, i) => lens.slice(0, i).reduce((a, b) => a + b, 0));
  return (
    <svg viewBox="0 0 120 120" className="h-[118px] w-[118px] shrink-0">
      <circle cx="60" cy="60" r={r} fill="none" stroke="#eef1f4" strokeWidth="15" />
      {glance.map((s, i) => {
        const len = lens[i];
        const dash = `${Math.max(len - gap, 0)} ${c - Math.max(len - gap, 0)}`;
        return (
          <circle
            key={s.label}
            cx="60" cy="60" r={r} fill="none"
            stroke={s.color} strokeWidth="15"
            strokeDasharray={dash} strokeDashoffset={-offsets[i]}
            transform="rotate(-90 60 60)"
          />
        );
      })}
      <text x="60" y="56" textAnchor="middle" className="fill-[#0f1720]" style={{ fontSize: 26, fontWeight: 800 }}>{total}</text>
      <text x="60" y="73" textAnchor="middle" className="fill-[#7c8896]" style={{ fontSize: 10, fontWeight: 600 }}>Total Tasks</text>
    </svg>
  );
}

function RailCard({ title, action, children }: { title: string; action?: string; children: React.ReactNode }) {
  return (
    <section className="bg-white rounded-2xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04),0_8px_24px_-16px_rgba(15,23,32,0.12)]">
      <div className="flex items-center justify-between px-4 pt-3.5 pb-2.5">
        <h3 className="text-[11px] font-bold uppercase tracking-[0.07em] text-[#5b6b78]">{title}</h3>
        {action && <button className="text-[11px] font-semibold text-[#2f74d9] hover:underline">{action}</button>}
      </div>
      {children}
    </section>
  );
}

// State-aware greeting sub-line. Reads from kpis + agenda so the
// header reflects today's actual workload, not a static brand line.
// Falls back gracefully if data is sparse.
function buildTodaySubline(data: TodayData): string {
  const kpiVal = (label: string): number => {
    const k = data.kpis.find((k) => k.label.toUpperCase() === label);
    return typeof k?.value === "number" ? k.value : 0;
  };
  const overdue = kpiVal("OVERDUE");
  const planned = kpiVal("PLANNED");
  const inProgress = kpiVal("IN PROGRESS");
  const toDo = planned + inProgress;

  // Surface the first not-yet-done task in the agenda so the user
  // has a concrete "start here" pointer.
  const firstOpen = data.agenda
    .flatMap((b) => b.tasks)
    .find((t) => t.status === "In Progress" || t.status === "Planned" || t.status === "Overdue");
  const firstTitle = firstOpen?.title?.split(" — ")[1] ?? firstOpen?.title;

  if (overdue > 0 && toDo > 0) {
    return firstTitle
      ? `${overdue} overdue · ${toDo} to do today — start with ${firstTitle}.`
      : `${overdue} overdue · ${toDo} to do today.`;
  }
  if (toDo > 0) {
    return firstTitle
      ? `${toDo} tasks today — start with ${firstTitle}.`
      : `${toDo} tasks today.`;
  }
  if (overdue > 0) {
    return `${overdue} overdue — clear these first.`;
  }
  return "You're all clear. A quiet day to plan ahead.";
}

function Avatar({ initials, color, size = 36 }: { initials: string; color: string; size?: number }) {
  return (
    <span
      className="grid place-items-center rounded-full text-white font-bold ring-2 ring-white"
      style={{ background: color, height: size, width: size, fontSize: size * 0.34 }}
    >
      {initials}
    </span>
  );
}

/* ─────────────────────────── Console ─────────────────────────── */

export function TodayConsole({
  data,
  userName,
  userInitials,
}: {
  data: TodayData;
  userName: string;
  userInitials: string;
}) {
  const [view, setView] = useState<"list" | "cal" | "grid">("list");
  const firstName = userName.split(" ")[0];

  // State-aware greeting sub-line — derived from today's actual data
  // so the header reflects what's on the user's plate, not generic
  // motivational filler. Reads: "{N} overdue · {M} to do today —
  // start with {first task}".
  const subline = buildTodaySubline(data);

  // Surface this page's title + date pill to the shell-level
  // MobileTopBar so the dark chrome shows "Today" + the week label.
  useSetPageTitle("Today's Tasks", "Mon, May 12 · Wk 3");

  return (
    <div className="text-[#0f1720]">
      {/* Header.
          Mobile + tablet (< lg): the shell-level dark MobileTopBar
          covers title + date + bell + avatar. Here we only render
          the friendly greeting + subtitle as a content header below.
          Desktop (≥ lg, sidebar pinned): classic title-left /
          actions-right layout with the full role pill on the right. */}
      <header className="px-4 pt-4 pb-4 lg:px-7 lg:pt-6 lg:pb-5 lg:flex lg:items-start lg:justify-between lg:gap-4">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <BackButton size="sm" className="mt-1 lg:mt-1.5" />
          <div className="min-w-0">
            <h1 className="text-[18px] md:text-[20px] lg:text-[24px] font-extrabold tracking-tight">Good morning, {firstName} 👋</h1>
            <p className="text-[12px] md:text-body lg:text-[13px] text-[#6b7785] mt-0.5">{subline}</p>
          </div>
        </div>

        {/* Desktop action bar (≥ lg, sidebar pinned) */}
        <div className="hidden lg:flex items-center gap-2.5 shrink-0">
          <button className="flex items-center gap-2 h-10 px-3.5 rounded-xl bg-white border border-[var(--color-edify-divider)] text-body font-semibold shadow-[0_1px_2px_rgba(15,23,32,0.04)]">
            <Calendar size={15} className="text-[#6b7785]" />
            Mon, May 12, 2025 · Week 3
            <ChevronDown size={14} className="text-muted" />
          </button>
          <Link
            href="/messages"
            aria-label="Messages"
            className="relative grid place-items-center h-10 w-10 rounded-xl bg-white border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04)]"
          >
            <MessageSquare size={17} className="text-secondary" />
          </Link>
          <NotificationBell variant="today" />
          <button className="flex items-center gap-2.5 h-10 pl-1 pr-2.5 rounded-xl bg-white border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04)]">
            <Avatar initials={userInitials} color="#2f5f7a" size={32} />
            <span className="leading-tight text-left">
              <span className="block text-body font-bold">{userName}</span>
              <span className="block text-caption text-muted">{data.roleLabel}</span>
            </span>
            <ChevronDown size={14} className="text-muted" />
          </button>
        </div>
      </header>

      {/* Body grid */}
      <div className="px-4 md:px-7 pb-24 md:pb-8 grid grid-cols-12 gap-4 md:gap-5 items-start">
        {/* ───── Left column ───── */}
        <div className="col-span-12 xl:col-span-8 space-y-5">
          {/* KPI cards */}
          <MetricStrip
            bare
            columns="grid-cols-2 lg:grid-cols-4"
            metrics={data.kpis.map((k) => ({
              key: k.label,
              label: k.label,
              value: k.value,
              delta: {
                dir: k.dir === "flat" ? "flat" : k.dir === "bad" ? "down" : "up",
                text: k.trend,
              },
            }))}
          />

          {/* Today's Agenda */}
          <section className="bg-white rounded-2xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(15,23,32,0.04),0_10px_30px_-18px_rgba(15,23,32,0.14)]">
            <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-3">
              <div className="flex items-center gap-2.5">
                <h2 className="text-[16px] font-extrabold tracking-tight">Today&apos;s Agenda</h2>
                <span className="px-2 h-[20px] grid place-items-center rounded-full bg-[#e7f0fb] text-[#2f6fd0] text-[11px] font-bold">{data.totalTasks} tasks</span>
              </div>
              <div className="flex items-center gap-2">
                <button className="flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-divider)] text-[11.5px] font-semibold text-secondary">
                  Sort by: <span className="text-[#0f1720]">Priority</span>
                  <ChevronDown size={13} className="text-muted" />
                </button>
                <div className="flex items-center gap-1 p-0.5 rounded-lg border border-[var(--color-edify-divider)]">
                  {([
                    ["list", List],
                    ["cal", Calendar],
                    ["grid", CalendarDays],
                  ] as const).map(([key, Icon]) => (
                    <button
                      key={key}
                      onClick={() => setView(key)}
                      className={
                        "grid place-items-center h-7 w-7 rounded-md " +
                        (view === key ? "bg-[#eef4f7] text-[#2f5f7a]" : "text-muted hover:text-secondary")
                      }
                    >
                      <Icon size={15} />
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="px-5">
              {data.agenda.map((block) => {
                const BlockIcon = ICONS[block.icon] ?? Sun;
                return (
                  <div key={block.label} className="py-1">
                    <div className="flex items-center gap-2 py-2">
                      <BlockIcon size={14} className={block.tone} />
                      <span className={"text-[12px] font-extrabold uppercase tracking-[0.05em] " + block.tone}>{block.label}</span>
                      <span className="text-[11px] text-muted font-medium">{block.tasks.length} task{block.tasks.length > 1 ? "s" : ""}</span>
                    </div>
                    {block.tasks.map((t, i) => {
                      const st = STATUS[t.status];
                      const TIcon = ICONS[t.icon] ?? Building2;
                      return (
                        <div
                          key={t.title}
                          className={"flex items-start gap-3 py-3 " + (i > 0 ? "border-t border-[var(--color-edify-divider)]" : "")}
                        >
                          <span className={"grid place-items-center h-10 w-10 rounded-xl shrink-0 " + TILE[t.tone]}>
                            <TIcon size={18} />
                          </span>
                          {/* Title + place own the full row width on
                              mobile so the school name reads cleanly.
                              The status pill + SF / people chips drop
                              to a wrap-line below the place on small
                              screens. From `lg` (where the sidebar
                              pins and width opens up) they snap back
                              to the inline desktop layout. */}
                          <div className="flex-1 min-w-0">
                            <div className="text-[13.5px] font-bold leading-snug">{t.title}</div>
                            <div className="text-[11.5px] text-muted truncate mt-0.5">{t.place}</div>
                            <div className="flex items-center gap-2 flex-wrap mt-1.5 lg:hidden">
                              <TaskPill status={t.status} size="xs" icon={st.icon} />
                              {t.sf && (
                                <span className="inline-flex items-center gap-1 text-caption font-bold text-[#15803d]">
                                  SF ✓
                                </span>
                              )}
                              {t.people != null && (
                                <span className="inline-flex items-center gap-0.5 text-caption font-semibold text-muted">
                                  <Users size={11} />
                                  {t.people}
                                </span>
                              )}
                            </div>
                          </div>
                          {/* Desktop-only inline chips (≥ lg) — the
                              wider canvas pays for the at-a-glance
                              read of every dimension on one row. */}
                          <div className="hidden lg:flex items-center gap-3 shrink-0">
                            <TaskPill status={t.status} size="sm" icon={st.icon} />
                            {t.sf && (
                              <span className="text-[11px] font-bold text-[#15803d] shrink-0">SF ✓</span>
                            )}
                            {t.people != null && (
                              <span className="flex items-center gap-1 text-[11.5px] font-semibold text-muted shrink-0">
                                <Users size={13} />
                                {t.people}
                              </span>
                            )}
                          </div>
                          <button
                            type="button"
                            aria-label="Task actions"
                            className="grid place-items-center h-7 w-7 rounded-md text-[#b3bcc5] hover:text-secondary hover:bg-[#f4f6f8] shrink-0 mt-0.5"
                          >
                            <MoreVertical size={16} />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>

            <div className="flex items-center justify-between px-5 py-3.5 mt-1 border-t border-[var(--color-edify-divider)]">
              <button className="text-body font-semibold text-[#2f74d9] hover:underline">View Full Calendar</button>
              <button className="flex items-center gap-1 text-body font-semibold text-[#2f74d9] hover:underline">
                + Add Personal Task
              </button>
            </div>
          </section>

          {/* Bottom strip */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Priority focus */}
            <section className="bg-white rounded-2xl border border-[var(--color-edify-divider)] p-4 shadow-[0_1px_2px_rgba(15,23,32,0.04),0_8px_24px_-16px_rgba(15,23,32,0.12)]">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold uppercase tracking-[0.07em] text-[#5b6b78]">Priority Focus</h3>
                <button className="flex items-center gap-1 text-[11px] font-semibold text-secondary">
                  This Week <ChevronDown size={12} className="text-muted" />
                </button>
              </div>
              <div className="flex items-start gap-3">
                <span className="grid place-items-center h-9 w-9 rounded-xl bg-[#e2f2f4] text-[#1f8a8f] shrink-0">
                  <Target size={18} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-snug">{data.priorityFocus.title}</div>
                  <div className="text-[11.5px] text-muted mt-0.5">{data.priorityFocus.sub}</div>
                </div>
              </div>
              <div className="flex items-center gap-2.5 mt-3">
                <div className="flex-1 h-2 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
                  <div className="h-full rounded-full bg-[#16a34a]" style={{ width: `${data.priorityFocus.pct}%` }} />
                </div>
                <span className="text-[12px] font-extrabold text-[#15803d] shrink-0">{data.priorityFocus.pct}%</span>
              </div>
              <div className="text-[11px] text-muted font-medium mt-1.5">{data.priorityFocus.target}</div>
            </section>

            {/* Team check-in */}
            <section className="bg-white rounded-2xl border border-[var(--color-edify-divider)] p-4 shadow-[0_1px_2px_rgba(15,23,32,0.04),0_8px_24px_-16px_rgba(15,23,32,0.12)]">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold uppercase tracking-[0.07em] text-[#5b6b78]">{data.team.label}</h3>
                <button className="text-[11px] font-semibold text-[#2f74d9] hover:underline">View All</button>
              </div>
              <div className="flex items-center gap-1.5 flex-wrap">
                {data.team.members.map((m) => (
                  <span key={m.initials} className="relative shrink-0">
                    <Avatar initials={m.initials} color={m.color} size={32} />
                    <span className="absolute bottom-0 right-0 h-2 w-2 rounded-full bg-emerald-400 ring-2 ring-white" />
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-2 mt-3 flex-wrap">
                <Pill tone="success" size="md" dot subtle>
                  {data.team.activeToday} Active
                </Pill>
                <Pill tone="neutral" size="md" dot subtle>
                  {data.team.offline} Offline
                </Pill>
              </div>
            </section>
          </div>
        </div>

        {/* ───── Right rail ───── */}
        <aside className="col-span-12 xl:col-span-4 space-y-5">
          {/* At a glance */}
          <RailCard title="At a Glance" action="View full analytics">
            <div className="flex items-center gap-4 px-4 pb-4">
              <Donut glance={data.glance} total={data.totalTasks} />
              <div className="flex-1 space-y-2.5">
                {data.glance.map((s) => (
                  <div key={s.label} className="flex items-center gap-2 text-[12px]">
                    <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: s.color }} />
                    <span className="text-secondary font-medium flex-1">{s.label}</span>
                    <span className="font-bold">{s.value}</span>
                    <span className="text-muted font-medium tabular-nums">({s.pct}%)</span>
                  </div>
                ))}
              </div>
            </div>
          </RailCard>

          {/* Upcoming this week */}
          <RailCard title="Upcoming This Week" action="View All">
            <div className="px-4 pb-2">
              {data.upcoming.map((u, i) => {
                const UIcon = ICONS[u.icon] ?? CalendarCheck;
                return (
                  <div key={u.title} className={"flex items-center gap-3 py-3 " + (i > 0 ? "border-t border-[var(--color-edify-divider)]" : "")}>
                    <span className={"grid place-items-center h-10 w-10 rounded-xl shrink-0 " + TILE[u.tone]}>
                      <UIcon size={17} />
                    </span>
                    <div className="min-w-0">
                      <div className="text-caption text-muted font-semibold">{u.date}</div>
                      <div className="text-body font-bold truncate">{u.title}</div>
                      <div className="text-[11px] text-muted truncate">{u.sub}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </RailCard>

          {/* Pending approvals */}
          <RailCard title={data.approvals.label} action="View All">
            <div className="px-4 pb-2">
              {data.approvals.items.map((a, i) => (
                <div key={a.title} className={"flex items-center gap-3 py-3 " + (i > 0 ? "border-t border-[var(--color-edify-divider)]" : "")}>
                  <span className="grid place-items-center h-9 w-9 rounded-xl shrink-0 bg-[#e6f0fc] text-[#2f74d9]">
                    <FileText size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-body font-bold truncate">{a.title}</div>
                    <div className="text-[11px] text-muted truncate">{a.sub}</div>
                  </div>
                  <span className="px-2 h-[22px] grid place-items-center rounded-full bg-[#fdf0db] text-[#b06a12] text-caption font-bold shrink-0">
                    Awaiting
                  </span>
                </div>
              ))}
            </div>
          </RailCard>

          {/* Quick actions */}
          <RailCard title="Quick Actions">
            <div className="grid grid-cols-4 gap-2.5 px-4 pb-4">
              {data.quick.map((q) => {
                const QIcon = ICONS[q.icon] ?? CalendarCheck;
                return (
                  <button key={q.label} className="flex flex-col items-center gap-2 rounded-xl border border-[var(--color-edify-divider)] py-3 px-1 hover:bg-[#f8fafb] transition-colors">
                    <span className={"grid place-items-center h-9 w-9 rounded-xl " + TILE[q.tone]}>
                      <QIcon size={17} />
                    </span>
                    <span className="text-caption font-semibold text-secondary text-center leading-tight">{q.label}</span>
                  </button>
                );
              })}
            </div>
          </RailCard>
        </aside>
      </div>
    </div>
  );
}
