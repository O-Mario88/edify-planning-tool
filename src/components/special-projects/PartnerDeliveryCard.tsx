"use client";

import Link from "next/link";
import { Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { partnerKpis, partnerDelivery } from "@/lib/special-projects-mock";

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
      <MetricStrip
        bare
        className="mb-3"
        columns="grid-cols-3"
        metrics={partnerKpis.map((k) => ({
          key: k.key,
          label: k.label,
          value: k.value,
          delta: { dir: k.deltaTone === "up" ? "up" : "down", text: `${k.delta} vs Apr` },
        }))}
      />

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
