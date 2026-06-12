"use client";

// App-wide offline banner (spec layer #9). Sits in the shell; appears only when
// the network drops, reassuring field staff their work is held locally.

import { CloudOff } from "lucide-react";
import { useOnline } from "@/lib/offline/useOnline";

export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;

  return (
    <div
      role="status"
      className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-center gap-2 bg-amber-500 px-4 py-2 text-center text-[12.5px] font-semibold text-white shadow-lg"
    >
      <CloudOff size={15} className="shrink-0" />
      You&apos;re offline — your work is saved on this device and will sync when the connection returns.
    </div>
  );
}
