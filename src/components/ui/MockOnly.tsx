import { type ReactNode } from "react";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "./InsufficientData";

// Server wrapper: render children only when dev mock is enabled; otherwise
// show an honest insufficient-data card so production never surfaces fabricated figures.
export function MockOnly({
  surface,
  detail,
  children,
}: {
  surface: string;
  detail?: string;
  children: ReactNode;
}) {
  if (!isMockAllowed()) return <InsufficientData surface={surface} detail={detail} />;
  return <>{children}</>;
}
