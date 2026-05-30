"use client";

import Link from "next/link";
import {
  Building2,
  ClipboardCheck,
  UserCheck,
  Users,
  type LucideIcon,
} from "lucide-react";
import { keyTargets, type KeyTarget } from "@/lib/work-plan-mock";

const ICON: Record<KeyTarget["icon"], LucideIcon> = {
  school:    Building2,
  clipboard: ClipboardCheck,
  userCheck: UserCheck,
  users:     Users,
};

const RING_STROKE: Record<KeyTarget["color"], string> = {
  emerald: "#10b981",
  blue:    "#2563eb",
  orange:  "#f97316",
  violet:  "#8b5cf6",
};

const TEXT: Record<KeyTarget["color"], string> = {
  emerald: "text-emerald-600",
  blue:    "text-blue-600",
  orange:  "text-orange-600",
  violet:  "text-violet-600",
};

const BAR: Record<KeyTarget["color"], string> = {
  emerald: "bg-emerald-500",
  blue:    "bg-blue-500",
  orange:  "bg-orange-500",
  violet:  "bg-violet-500",
};

const ICON_BG: Record<KeyTarget["color"], string> = {
  emerald: "bg-emerald-50 text-emerald-600",
  blue:    "bg-blue-50 text-blue-600",
  orange:  "bg-orange-50 text-orange-600",
  violet:  "bg-violet-50 text-violet-600",
};

export function KeyTargetsCard() {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[15px] font-extrabold tracking-tight">Key Targets</h3>
        <Link href="/my-targets" className="text-body font-semibold text-emerald-600">
          View All
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {keyTargets.map((t) => {
          const Icon = ICON[t.icon];
          return (
            <div
              key={t.key}
              className="rounded-2xl border border-[var(--color-edify-border)] p-3 flex flex-col items-center text-center overflow-hidden"
            >
              <Ring pct={t.percent} stroke={RING_STROKE[t.color]} icon={<Icon size={16} className={TEXT[t.color]} />} bg={ICON_BG[t.color]} />
              <div className="text-[11px] muted font-semibold mt-2 leading-tight line-clamp-1">
                {t.label}
              </div>
              <div className="mt-1 text-[15px] font-extrabold tabular leading-none">
                {t.current}
                <span className="text-[11px] muted font-semibold ml-0.5">/ {t.total}</span>
              </div>
              <div className={`text-[11px] font-extrabold mt-1 ${TEXT[t.color]}`}>{t.percent}%</div>
              <div className="mt-1.5 w-full h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div
                  className={`h-full rounded-full ${BAR[t.color]}`}
                  style={{ width: `${t.percent}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Ring({
  pct,
  stroke,
  icon,
  bg,
}: {
  pct: number;
  stroke: string;
  icon: React.ReactNode;
  bg: string;
}) {
  const size = 56;
  const sw = 5;
  const r = size / 2 - sw;
  const c = 2 * Math.PI * r;
  const off = c * (1 - pct / 100);
  return (
    <span className="relative inline-block shrink-0" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef2f4" strokeWidth={sw} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth={sw}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={off}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className={`absolute inset-2 rounded-full grid place-items-center ${bg}`}>{icon}</span>
    </span>
  );
}
