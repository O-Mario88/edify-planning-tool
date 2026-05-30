"use client";

// DashboardPageHeader — thin role-aware adapter over the canonical
// PageHeader.
//
// Replaces the chrome half of DashboardHeroServer (title · filters ·
// MessageBell · NotificationBell · Avatar) after the global hero
// removal pass retired DashboardHero. The hero data lives in
// dashboard-hero-mock.ts; we read just the title + filter labels and
// hand them to PageHeader so every dashboard keeps its standard top
// chrome without re-rendering the dark gradient hero band.

import { Calendar, GitCompare, MapPin } from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import {
  heroContentForRole,
  type HeroRole,
} from "@/lib/dashboard-hero-mock";

export function DashboardPageHeader({ role }: { role: HeroRole }) {
  const hero = heroContentForRole(role);
  const filters: PageHeaderFilter[] = [
    { Icon: Calendar,   label: hero.filters.month   },
    { Icon: GitCompare, label: hero.filters.compare },
    { Icon: MapPin,     label: hero.filters.region  },
  ];
  return (
    <PageHeader
      title={hero.title}
      filters={filters}
      searchPlaceholder="Search everything…"
    />
  );
}
