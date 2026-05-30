import Link from "next/link";
import { recentUploads, type UploadStatus } from "@/lib/impact-mock";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";

// Status → tone mapping using the canonical ChipTone vocabulary.
const STATUS_TONE: Record<UploadStatus, ChipTone> = {
  "Verified":  "green",
  "In Review": "blue",
  "Failed QC": "red",
};

export function RecentDataUploadsCard() {
  return (
    <article className="card p-3.5">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="text-body-lg font-extrabold tracking-tight">Recent Data Uploads</h2>
        <Link
          href="/data-intake/upload"
          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
        >
          View All Uploads
        </Link>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-[11px] muted font-semibold border-b border-[var(--color-edify-border)]">
              <th scope="col" className="py-2 pr-2">Program</th>
              <th scope="col" className="py-2 px-2">File Name</th>
              <th scope="col" className="py-2 px-2">Uploaded By</th>
              <th scope="col" className="py-2 px-2 text-right">Records</th>
              <th scope="col" className="py-2 px-2">Status</th>
              <th scope="col" className="py-2 pl-2">Uploaded On</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {recentUploads.map((u) => (
              <tr key={u.key} className="hover:bg-[var(--color-edify-soft)]/30">
                <td className="py-2.5 pr-2 font-semibold">{u.program}</td>
                <td className="py-2.5 px-2">
                  <Link
                    href={u.href}
                    className="font-semibold text-[var(--color-edify-primary)] hover:underline"
                  >
                    {u.fileName}
                  </Link>
                </td>
                <td className="py-2.5 px-2">{u.uploadedBy}</td>
                <td className="py-2.5 px-2 text-right font-extrabold tabular">{u.records.toLocaleString()}</td>
                <td className="py-2.5 px-2">
                  <StatusBadge tone={STATUS_TONE[u.status]}>
                    {u.status}
                  </StatusBadge>
                </td>
                <td className="py-2.5 pl-2 muted whitespace-nowrap">{u.uploadedOn}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}
