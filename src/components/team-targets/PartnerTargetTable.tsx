"use client";

import Link from "next/link";
import { Handshake } from "lucide-react";
import { SectionCard, TableEmptyRow } from "@/components/ui/primitives";
import {
  partnerTargetPerformance,
  type PartnerCertification,
  type RiskLevel,
} from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const CERT_TONE: Record<PartnerCertification, string> = {
  Certified:       "bg-emerald-100 text-emerald-700",
  Pending:         "bg-amber-100 text-amber-700",
  "Not Certified": "bg-rose-100 text-rose-700",
};

const RISK_TONE: Record<RiskLevel, string> = {
  Low:      "bg-emerald-100 text-emerald-700",
  Medium:   "bg-amber-100 text-amber-700",
  High:     "bg-orange-100 text-orange-700",
  Critical: "bg-rose-100 text-rose-700",
};

export function PartnerTargetTable() {
  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Target Performance by Partner"
      actions={
        <Link href="/partners" className="text-[12px] font-semibold text-[var(--color-edify-primary)]">
          View All partner performance →
        </Link>
      }
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">Partner Name</th>
            <th scope="col" className="text-left">Region</th>
            <th scope="col" className="text-right">Assigned<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
            <th scope="col" className="text-right">Completed<br /><span className="font-medium normal-case muted text-caption">Activities</span></th>
            <th scope="col" className="text-right">Valid Visits</th>
            <th scope="col" className="text-right">Achievement %</th>
            <th scope="col" className="text-left">Certification Status</th>
            <th scope="col" className="text-left">Risk</th>
          </tr>
        </thead>
        <tbody>
          {partnerTargetPerformance.map((p) => (
            <tr key={p.partnerId}>
              <td className="text-body font-semibold whitespace-nowrap">{p.partner}</td>
              <td className="text-[12px] muted">{p.region}</td>
              <td className="text-right tabular text-body">{p.assignedActivities}</td>
              <td className="text-right tabular text-body font-semibold">{p.completedActivities}</td>
              <td className="text-right tabular text-body">{p.validVisits}</td>
              <td>
                <div className="flex items-center gap-2 min-w-[110px] justify-end">
                  <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        p.achievementPercent >= 75 ? "bg-emerald-500" :
                        p.achievementPercent >= 50 ? "bg-amber-500"   :
                                                      "bg-rose-500",
                      )}
                      style={{ width: `${p.achievementPercent}%` }}
                    />
                  </div>
                  <span className="text-[12px] font-bold tabular w-8 text-right">{p.achievementPercent}%</span>
                </div>
              </td>
              <td>
                <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold", CERT_TONE[p.certificationStatus])}>
                  {p.certificationStatus}
                </span>
              </td>
              <td>
                <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-bold", RISK_TONE[p.risk])}>
                  {p.risk}
                </span>
              </td>
            </tr>
          ))}
          {partnerTargetPerformance.length === 0 && (
            <TableEmptyRow
              colSpan={8}
              title="No partner assignments yet"
              body="Once partners are assigned to active projects, their delivery and certification status will appear here."
            />
          )}
        </tbody>
      </table>
    </SectionCard>
  );
}
