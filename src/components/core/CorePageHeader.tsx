"use client";

// Client wrapper around <PageHeader> for the Core surfaces.
//
// PageHeader is a Client Component. Passing a lucide icon (a forwardRef object)
// to it as a prop FROM a Server Component fails RSC serialization in Next/React
// ("Functions cannot be passed directly to Client Components") and trips the
// page error boundary. This wrapper owns the icon imports on the client, so the
// server pages pass only serializable strings (an icon key + filter labels).

import {
  GraduationCap, BarChart3, ShieldCheck, Calendar, MapPin, User, Filter,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

const HEADER_ICONS = {
  schools: GraduationCap,
  analytics: BarChart3,
  health: ShieldCheck,
} as const;
export type CoreHeaderIcon = keyof typeof HEADER_ICONS;

const FILTER_ICONS: Record<string, LucideIcon> = {
  calendar: Calendar, map: MapPin, user: User, filter: Filter,
};
export type CoreHeaderFilter = { iconKey: keyof typeof FILTER_ICONS; label: string };

export function CorePageHeader({
  icon,
  title,
  subtitle,
  searchPlaceholder,
  filters,
}: {
  icon?: CoreHeaderIcon;
  title: string;
  subtitle?: string;
  searchPlaceholder?: string;
  filters?: CoreHeaderFilter[];
}) {
  return (
    <PageHeader
      title={title}
      subtitle={subtitle}
      Icon={icon ? HEADER_ICONS[icon] : undefined}
      searchPlaceholder={searchPlaceholder}
      filters={filters?.map((f) => ({ Icon: FILTER_ICONS[f.iconKey], label: f.label }))}
    />
  );
}
