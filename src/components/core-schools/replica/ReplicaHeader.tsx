"use client";

import { PageHeader } from "@/components/ui/PageHeader";
import { replicaHeaderText } from "@/lib/core-school-replica-mock";

// Chrome for the Core School Dashboard. Previously a bespoke header
// with its own bell + avatar + photo profile chip — now delegates to
// the canonical <PageHeader> so the page reads in lockstep with every
// other surface (breadcrumbs · back button · ⌘K · avatar menu all
// come for free).
//
// The replica filter bar (FY · Quarter · Region · Filters · Export
// Report) stays as a separate component rendered below this header.
export function ReplicaHeader() {
  const h = replicaHeaderText;
  return (
    <PageHeader
      title={h.title}
      subtitle={h.subtitle}
    />
  );
}
