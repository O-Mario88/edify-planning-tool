"use client";

import {
  Users,
  UsersRound,
  Building2,
  UserPlus,
  CalendarCheck,
  Wallet,
  WalletCards,
  ArrowUpRight,
  ArrowDownRight,
} from "lucide-react";
import { motion } from "motion/react";
import { AreaChart, Area } from "recharts";
import { planningKpis, type PlanningKpi } from "@/lib/planning-mock";
import { cn } from "@/lib/utils";

const iconMap = {
  users: Users,
  users2: UsersRound,
  school: Building2,
  userPlus: UserPlus,
  calendarCheck: CalendarCheck,
  wallet: Wallet,
  wallet2: WalletCards,
} as const;

const PRIMARY = "#527083";
const GREEN = "#16a34a";
const RED = "#ef4444";

function makeSpark(seed: number, trendType: "up" | "down") {
  const out: { x: number; y: number }[] = [];
  let v = 50;
  for (let i = 0; i < 14; i++) {
    v +=
      Math.sin((i + seed) * 1.3) * 6 +
      (trendType === "up" ? 1.2 : -1.2) +
      Math.cos((i + seed) * 0.7) * 4;
    v = Math.max(8, Math.min(56, v));
    out.push({ x: i, y: v });
  }
  return out;
}

function Spark({ idx, trendType }: { idx: number; trendType: "up" | "down" }) {
  const data = makeSpark(idx + 1, trendType);
  const stroke = trendType === "up" ? GREEN : RED;
  const id = `pspark-${idx}`;
  return (
    <div className="mt-2">
      <AreaChart
        width={140}
        height={32}
        data={data}
        margin={{ top: 2, right: 0, left: 0, bottom: 0 }}
        className="!w-full"
      >
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
            <stop offset="100%" stopColor={stroke} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area
          type="monotone"
          dataKey="y"
          stroke={stroke}
          strokeWidth={1.8}
          fill={`url(#${id})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </div>
  );
}

function KpiCard({ kpi, idx }: { kpi: PlanningKpi; idx: number }) {
  const Icon = iconMap[kpi.icon];
  const trendCls =
    kpi.trendType === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: idx * 0.03 }}
      className="card p-3.5"
    >
      <div className="flex items-center gap-2.5">
        <span
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ background: "var(--color-edify-soft)", color: PRIMARY }}
        >
          <Icon size={16} />
        </span>
        <div className="text-[11.5px] muted font-semibold leading-tight">
          {kpi.label}
        </div>
      </div>
      <div className="text-[26px] font-extrabold tabular mt-2 leading-none">
        {kpi.value}
      </div>
      <div className="text-[11px] muted font-medium mt-0.5">{kpi.status}</div>
      <div
        className={cn(
          "text-[11px] font-semibold mt-1.5 flex items-center gap-1",
          trendCls,
        )}
      >
        {kpi.trendType === "up" ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
        {kpi.trend}
      </div>
      <Spark idx={idx} trendType={kpi.trendType} />
    </motion.div>
  );
}

export function PlanningKpiRow() {
  return (
    <section className="grid grid-cols-7 gap-3">
      {planningKpis.map((k, i) => (
        <KpiCard key={k.label} kpi={k} idx={i} />
      ))}
    </section>
  );
}
