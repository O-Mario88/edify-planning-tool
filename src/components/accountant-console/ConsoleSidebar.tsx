"use client";

import {
  ChevronDown,
  ClipboardCheck,
  ClipboardList,
  Layers,
  LayoutDashboard,
  LogOut,
  Send,
  Settings,
  ShieldCheck,
  Sliders,
  UserCog,
  Inbox,
  Calculator,
  type LucideIcon,
} from "lucide-react";
import {
  accountantUser,
  consoleMainNav,
  consoleSettingsNav,
  type ConsoleNavItem,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";

const NAV_ICON: Record<ConsoleNavItem["iconKey"], LucideIcon> = {
  dashboard:      LayoutDashboard,
  queue:          ClipboardList,
  disbursements:  Send,
  fundsReceived:  Inbox,
  budget:         Calculator,
  approvals:      ClipboardCheck,
  accountability: ShieldCheck,
  reports:        Layers,
  users:          UserCog,
  rules:          Sliders,
  settings:       Settings,
};

// Program Accountant Console sidebar.
//
// Dark fixed rail, 240px wide. Vertical rhythm:
//   • Brand block — Edify diamond mark + "Program Accountant Console"
//   • WORKSPACE — country picker
//   • MAIN NAVIGATION — 8 finance-focused items
//   • SETTINGS — admin
//   • User card + Switch Role
//
// Active state is a white pill with high contrast — non-active items
// use a low-contrast slate-300 text so the active item shouts and the
// rest of the rail recedes.
export function ConsoleSidebar({ active = "dashboard" }: { active?: string }) {
  return (
    <aside className="w-[240px] shrink-0 bg-gradient-to-b from-[#0F1722] to-[#0B121C] text-slate-200 flex flex-col h-screen sticky top-0 border-r border-[#1A2331]">
      <div className="px-4 pt-5 pb-3 flex items-center gap-2.5">
        <span className="w-9 h-9 rounded-xl bg-white grid place-items-center shrink-0 shadow-[inset_0_-2px_4px_rgba(15,23,32,0.08),0_4px_10px_-4px_rgba(0,0,0,0.4)]">
          <span className="block w-[18px] h-[18px] bg-gradient-to-br from-[#1c2f3a] to-[#0F1722] rounded-sm rotate-45" />
        </span>
        <div className="min-w-0">
          <div className="text-[16px] font-extrabold tracking-tight text-white leading-none">
            edify
          </div>
          <div className="text-[10px] text-slate-400 font-semibold leading-tight mt-1">
            Program Accountant Console
          </div>
        </div>
      </div>

      <Section title="WORKSPACE">
        <button
          type="button"
          className="w-full h-12 rounded-xl bg-[#1A2331] ring-1 ring-[#26344A] hover:bg-[#212C3D] hover:ring-[#324363] flex items-center gap-2.5 px-3 transition-all"
        >
          <span className="text-[18px] leading-none">{accountantUser.flag}</span>
          <div className="min-w-0 flex-1 text-left">
            <div className="text-body font-extrabold text-white truncate">{accountantUser.country}</div>
            <div className="text-[10px] text-slate-400 font-semibold truncate">{accountantUser.region}</div>
          </div>
          <ChevronDown size={14} className="text-slate-400 shrink-0" />
        </button>
      </Section>

      <Section title="MAIN NAVIGATION">
        <ul className="flex flex-col gap-0.5">
          {consoleMainNav.map((item) => (
            <NavLink key={item.key} item={item} active={item.key === active} />
          ))}
        </ul>
      </Section>

      <Section title="SETTINGS">
        <ul className="flex flex-col gap-0.5">
          {consoleSettingsNav.map((item) => (
            <NavLink key={item.key} item={item} active={item.key === active} />
          ))}
        </ul>
      </Section>

      <div className="flex-1" />

      <div className="px-3 pb-2">
        <div className="rounded-xl bg-[#1A2331] ring-1 ring-[#26344A] p-2.5 flex items-center gap-2.5">
          <div className="relative shrink-0">
            <span className="w-9 h-9 rounded-full grid place-items-center text-[11.5px] font-extrabold text-white bg-gradient-to-br from-rose-400 to-rose-600 shadow-[0_4px_10px_-4px_rgba(244,63,94,0.55)]">
              {accountantUser.initials}
            </span>
            <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 ring-2 ring-[#1A2331]" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[12px] font-extrabold text-white truncate">{accountantUser.shortName} M.</div>
            <div className="text-[10px] text-slate-400 font-semibold truncate">{accountantUser.role}</div>
            <div className="text-[9.5px] text-emerald-400 font-extrabold mt-0.5 inline-flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Online
            </div>
          </div>
        </div>
      </div>

      <div className="px-3 pb-3">
        <button
          type="button"
          className="w-full h-10 rounded-xl bg-[#1A2331] ring-1 ring-[#26344A] hover:bg-[#212C3D] hover:ring-[#324363] text-[12px] font-extrabold text-slate-200 inline-flex items-center justify-center gap-1.5 transition-all"
        >
          <LogOut size={12} />
          Switch Role
        </button>
      </div>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="px-3 mt-4">
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.14em] text-slate-500 px-2 mb-1.5">
        {title}
      </div>
      {children}
    </div>
  );
}

function NavLink({ item, active }: { item: ConsoleNavItem; active: boolean }) {
  const Icon = NAV_ICON[item.iconKey];
  return (
    <li>
      <button
        type="button"
        className={cn(
          "w-full h-10 rounded-lg px-2.5 flex items-center gap-2.5 text-body font-semibold transition-all",
          active
            ? "bg-white text-slate-900 shadow-[0_8px_20px_-10px_rgba(255,255,255,0.18),inset_0_1px_0_rgba(255,255,255,0.8)]"
            : "text-slate-300 hover:bg-white/[0.04] hover:text-white",
        )}
      >
        <Icon size={15} className={active ? "text-slate-900" : "text-slate-400"} strokeWidth={2.2} />
        <span className="flex-1 text-left truncate">{item.label}</span>
        {typeof item.badge === "number" && (
          <span
            className={cn(
              "inline-flex items-center justify-center min-w-[20px] h-[18px] px-1.5 rounded-md text-[10px] font-extrabold tabular",
              active
                ? "bg-rose-500 text-white"
                : "bg-rose-500 text-white shadow-[0_4px_10px_-4px_rgba(244,63,94,0.5)]",
            )}
          >
            {item.badge}
          </span>
        )}
      </button>
    </li>
  );
}
