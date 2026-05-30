"use client";

// Tiny client-only helper that registers a page's title with the
// PageTitleContext. Extracted so server-component scaffolds (StubPage,
// EntityIndex) can register the title for the MobileTopBar without
// becoming client components themselves — which would break their
// ability to receive non-serializable props (e.g. Lucide Icon
// functions passed from server pages).

import { useSetPageTitle } from "@/components/shell/PageTitleContext";

export function TitleRegister({
  title,
  dateLabel,
}: {
  title: string;
  dateLabel?: string;
}) {
  useSetPageTitle(title, dateLabel);
  return null;
}
