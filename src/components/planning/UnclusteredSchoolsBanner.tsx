import Link from "next/link";
import { Network, ArrowRight, AlertTriangle } from "lucide-react";

// Unclustered Schools next-action banner — sits at the very top of the
// Planning Tool. Cluster assignment is the required setup step after upload,
// so when a viewer has unclustered schools this is their primary call to
// action, ahead of any gap board.
export function UnclusteredSchoolsBanner({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Link
      href="/clusters/assign"
      className="group flex items-center gap-3 rounded-2xl border border-rose-200 bg-rose-50/70 px-4 py-3 hover:bg-rose-50 transition-colors"
    >
      <span className="grid place-items-center h-10 w-10 rounded-xl bg-white text-rose-600 shrink-0 shadow-sm">
        <Network size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[13px] font-extrabold text-rose-800">
          <AlertTriangle size={13} />
          You have {count} unclustered school{count === 1 ? "" : "s"}
        </div>
        <p className="text-[12px] text-rose-700/90 leading-snug mt-0.5">
          Assign them to clusters before planning support — clustering unlocks SSA / SIT, cluster meetings,
          partner assignment, and reporting.
        </p>
      </div>
      <span className="shrink-0 inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-rose-600 text-white text-[12px] font-extrabold group-hover:bg-rose-700 transition-colors">
        Organize into clusters <ArrowRight size={13} />
      </span>
    </Link>
  );
}
