"use client";

import Link from "next/link";
import { Search, ChevronDown, Calendar, MapPin, User as UserIcon } from "lucide-react";
import { roleProfiles, type Role } from "@/lib/workflow-mock";
import { cn } from "@/lib/utils";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { MessageBell } from "@/components/messages/MessageBell";

type FilterProps = {
  label: string;
  value: string;
  Icon: React.ComponentType<{ size?: number; className?: string }>;
};

function Filter({ label, value, Icon }: FilterProps) {
  return (
    <button className="h-10 pl-3 pr-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center gap-2 text-[13px] min-w-[150px]">
      <Icon size={14} className="text-[var(--color-edify-muted)]" />
      <span className="leading-tight text-left flex-1">
        <span className="block text-[10px] text-[var(--color-edify-muted)] font-medium">{label}</span>
        <span className="block font-semibold -mt-[1px]">{value}</span>
      </span>
      <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
    </button>
  );
}

const roleOrder: Role[] = [
  "CCEO",
  "CountryProgramLead",
  "ProgramAccountant",
  "ImpactAssessment",
  "CountryDirector",
  "RVP",
];

function RoleSwitcher({ active }: { active: Role }) {
  return (
    <div className="card px-2 py-1.5 flex items-center gap-1 border border-[var(--color-edify-border)]">
      <span className="text-[10px] uppercase tracking-wider text-[var(--color-edify-muted)] font-bold pl-1.5">
        Role
      </span>
      {roleOrder.map((r) => {
        const profile = roleProfiles[r];
        const a = r === active;
        const short =
          r === "CCEO"
            ? "CCEO"
            : r === "CountryProgramLead"
              ? "CPL"
              : r === "ProgramAccountant"
                ? "Accountant"
                : r === "ImpactAssessment"
                  ? "M&E"
                  : r === "CountryDirector"
                    ? "Director"
                    : "RVP";
        return (
          <Link
            key={r}
            href={profile.homePath}
            className={cn(
              "px-2.5 h-7 rounded-md flex items-center text-[11.5px] font-semibold transition-colors",
              a
                ? "bg-[var(--color-edify-primary)] text-white"
                : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]",
            )}
            title={profile.title}
          >
            {short}
          </Link>
        );
      })}
    </div>
  );
}

export function AppTopHeader({
  role,
  title,
  subtitle,
  filters = ["financialYear", "month", "region", "scope"],
  searchPlaceholder = "Search schools, staff, activities…",
  // RoleSwitcher is a dev-only demo widget. Hidden in production builds
  // and on client demos. Pass `showRoleSwitcher` explicitly to override.
  showRoleSwitcher = process.env.NODE_ENV !== "production",
}: {
  role: Role;
  title: string;
  subtitle: string;
  filters?: ("financialYear" | "month" | "region" | "scope")[];
  searchPlaceholder?: string;
  showRoleSwitcher?: boolean;
}) {
  const profile = roleProfiles[role];
  const scopeIcon =
    role === "RVP" ? MapPin : role === "ProgramAccountant" ? UserIcon : MapPin;
  const scopeValue =
    role === "RVP"
      ? "East Africa"
      : role === "ProgramAccountant"
        ? "All Districts"
        : role === "CountryDirector"
          ? "Uganda"
          : "Kigun District";

  // Derive FY label + month from the current time. FY runs Oct 1 → Sep 30,
  // so anything from Oct onwards uses (year)/(year+1) and Jan-Sep uses
  // (year-1)/(year). Keeps the filter chip honest as the calendar advances.
  const now = new Date();
  const m = now.getMonth(); // 0-11
  const y = now.getFullYear();
  const fyStart = m >= 9 ? y : y - 1;
  const fyEnd = (fyStart + 1) % 100;
  const fyLabel = `FY ${fyStart}/${String(fyEnd).padStart(2, "0")}`;
  const monthLabel = now.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  const filterMap: Record<typeof filters[number], { label: string; value: string; Icon: typeof Calendar }> = {
    financialYear: { label: "Financial Year", value: fyLabel,        Icon: Calendar },
    month:         { label: "Month",          value: monthLabel,     Icon: Calendar },
    region:        { label: "Region",         value: "North", Icon: MapPin },
    scope:         { label: role === "RVP" ? "Region" : "Scope", value: scopeValue, Icon: scopeIcon },
  };

  return (
    <header className="pl-16 pr-4 pt-5 pb-4 md:pl-6 md:pr-6 flex items-start gap-4 flex-wrap">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        <p className="text-body muted">{subtitle}</p>
      </div>

      <div className="ml-auto hidden md:flex items-center gap-2.5 flex-wrap justify-end">
        {showRoleSwitcher && <RoleSwitcher active={role} />}

        {filters.map((k) => {
          const f = filterMap[k];
          return <Filter key={k} {...f} />;
        })}

        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input
            className="pl-9 pr-3 h-10 w-[230px] rounded-xl border border-[var(--color-edify-border)] bg-white text-[13px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            placeholder={searchPlaceholder}
          />
        </div>

        <MessageBell variant="default" />

        <NotificationBell variant="default" />

        <button
          type="button"
          aria-label={`Open ${profile.name} profile menu`}
          className="flex items-center gap-1 pl-1"
        >
          <div className="w-9 h-9 rounded-full bg-[var(--color-edify-primary)] text-white font-bold flex items-center justify-center">
            {profile.initials}
          </div>
          <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
        </button>
      </div>
    </header>
  );
}
