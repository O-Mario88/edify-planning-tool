"use client";

// LEGACY mobile MobileTopBar — now a metadata-only registrar.
//
// Every mobile view originally rendered its own dark top bar with
// hamburger/back · title · month chip · bell · avatar. The shell-level
// dark MobileTopBar (src/components/shell/MobileTopBar.tsx) now
// provides that chrome system-wide, so this component became
// redundant — and worse, it caused a duplicate-header bug because
// fourteen mobile views still imported and rendered it on top of the
// shell bar.
//
// Rather than touch all 14 callers, we collapse this component to a
// title-registration shim:
//   • Renders nothing (return null).
//   • Forwards `title` + `monthLabel` to PageTitleContext via
//     `useSetPageTitle`, so the shell MobileTopBar reads the right
//     page name and date pill.
//   • Honors `monthLabel = ""` (the legacy "hide pill" sentinel) by
//     not registering a date label.
//
// This file can be deleted once no callers remain — but as a shim,
// every consumer gets fixed for free with no per-page wiring.

import { useSession } from "@/components/auth/SessionContext";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import type { EdifyRole } from "@/lib/auth-public";

const ROLE_LABEL: Record<EdifyRole, string> = {
  CCEO:               "CCEO",
  CountryProgramLead: "Country Program Lead",
  CountryDirector:    "Country Director",
  RVP:                "Regional VP",
  ProgramAccountant:  "Program Accountant",
  ImpactAssessment:   "Impact Assessment",
  HumanResource:      "Human Resources",
  Admin:              "Admin",
  // Partner Operating Layer — three sub-types render distinct labels
  // so partner users can identify themselves in the topbar.
  PartnerAdmin:        "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer:       "Partner Viewer",
};

export function MobileTopBar({
  title,
  monthLabel,
  backHref:           _legacyBackHref,
  notificationsCount: _legacyNotificationsCount,
  notificationsHref:  _legacyNotificationsHref,
  className:          _legacyClassName,
}: {
  title?:              string;
  monthLabel?:         string;
  backHref?:           string;
  notificationsCount?: number;
  notificationsHref?:  string;
  className?:          string;
} = {}) {
  void _legacyBackHref;
  void _legacyNotificationsCount;
  void _legacyNotificationsHref;
  void _legacyClassName;

  const session = useSession();
  const resolvedTitle =
    title ?? (session ? ROLE_LABEL[session.role] : "Edify");

  // Empty-string month sentinel from the old API means "hide pill" —
  // map it to `undefined` so the shell bar doesn't render a date chip.
  const dateLabel = monthLabel === "" ? undefined : monthLabel;

  useSetPageTitle(resolvedTitle, dateLabel);
  return null;
}
