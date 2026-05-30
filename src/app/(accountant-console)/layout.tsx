import { type ReactNode } from "react";
import { ConsoleSidebar } from "@/components/accountant-console/ConsoleSidebar";

// Accountant Console layout.
//
// A completely separate shell from the main (shell) route group. The
// console has its own dark fixed sidebar (no shared EdifySidebar) and
// no role-based bottom nav — it's a dedicated finance surface designed
// to match the design reference 1:1.
export default function AccountantConsoleLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen w-full bg-[#F5F7FA]">
      <div className="hidden md:flex">
        <ConsoleSidebar active="dashboard" />
      </div>
      <main id="main-content" className="flex-1 min-w-0 overflow-x-hidden">
        {children}
      </main>
    </div>
  );
}
