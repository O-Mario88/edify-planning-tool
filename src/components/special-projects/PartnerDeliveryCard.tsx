"use client";

import Link from "next/link";
import { ArrowUpRight, ArrowDownRight, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { partnerKpis, partnerDelivery } from "@/lib/special-projects-mock";
import { cn } from "@/lib/utils";

export function PartnerDeliveryCard() {
  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Partner Assignment & Delivery"
      actions={
        <Link className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="/partners">
          View All
        </Link>
      }
    >
      <div className="grid grid-cols-3 gap-2.5 mb-3">
        {partnerKpis.map((k) => {
          const TrendIcon = k.deltaTone === "up" ? ArrowUpRight : ArrowDownRight;
          const trendCls =
            k.deltaTone === "up" ? "text-[var(--color-success)]" : "text-[var(--color-danger)]";
          return (
            <div
              key={k.key}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 overflow-hidden"
            >
              <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">{k.label}</div>
              <div className="text-[18px] font-extrabold tabular leading-none mt-1.5 truncate">
                {k.value}
              </div>
              <div className={cn("text-[10px] font-semibold mt-1 flex items-center gap-1 truncate", trendCls)}>
                <TrendIcon size={10} className="shrink-0" />
                <span className="truncate">{k.delta} <span className="muted font-medium">vs Apr</span></span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="text-[12px] font-bold mb-1.5">Partner Delivery Overview</div>
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">Partner</th>
            <th scope="col" className="text-right">Projects</th>
            <th scope="col" className="text-left">Delivery Progress</th>
          </tr>
        </thead>
        <tbody>
          {partnerDelivery.map((p) => (
            <tr key={p.partnerId}>
              <td className="text-[12px] font-semibold whitespace-nowrap">{p.partner}</td>
              <td className="text-right tabular text-[12px]">{p.projects}</td>
              <td>
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-[var(--color-success)]"
                      style={{ width: `${p.deliveryProgressPct}%` }}
                    />
                  </div>
                  <span className="text-[11.5px] font-bold tabular w-10 text-right">
                    {p.deliveryProgressPct}%
                  </span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  );
}
