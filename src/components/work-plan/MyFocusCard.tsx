"use client";

import Link from "next/link";
import { Target, ArrowRight } from "lucide-react";
import { focusThisMonth } from "@/lib/work-plan-mock";

export function MyFocusCard() {
  return (
    <section
      className="rounded-2xl text-white p-4 shadow-sm relative overflow-hidden"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #0e1c2c 0%, #11243a 60%, #0a1623 100%)",
      }}
    >
      {/* Subtle radial highlight */}
      <span
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(360px 220px at 18% 0%, rgba(82,112,131,0.30), transparent 70%)",
        }}
      />
      <div className="relative grid grid-cols-[auto_1fr_1px_auto] gap-3 items-start">
        <div className="w-12 h-12 rounded-full bg-white/[.08] border border-white/15 grid place-items-center text-white">
          <Target size={20} />
        </div>
        <div className="min-w-0">
          <div className="text-body-lg font-extrabold tracking-tight leading-tight">
            My Focus This Month
          </div>
          <p className="text-[12px] text-white/85 mt-1.5 leading-snug">
            {focusThisMonth.title}
          </p>
          <Link
            href="/my-targets"
            className="inline-flex items-center gap-1 text-[12px] font-semibold text-emerald-300 mt-2"
          >
            View Objectives
            <ArrowRight size={12} />
          </Link>
        </div>
        <span className="bg-white/15 w-px self-stretch mx-1" />
        <div className="leading-tight">
          <div className="text-caption uppercase tracking-wide text-white/65 font-semibold">
            Priority
          </div>
          <span className="inline-flex items-center mt-1 px-2.5 py-1 rounded-md bg-violet-500/30 text-violet-100 text-[12px] font-extrabold">
            {focusThisMonth.priority}
          </span>
          <div className="mt-3 text-caption uppercase tracking-wide text-white/65 font-semibold">
            Due Date
          </div>
          <div className="text-[13px] font-extrabold tracking-tight mt-1">
            {focusThisMonth.dueDate}
          </div>
        </div>
      </div>
    </section>
  );
}
