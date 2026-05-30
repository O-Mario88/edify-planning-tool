"use server";

// Debrief submission server action.
//
// Persists the debrief (mock for now — Phase 4 swaps for real storage)
// and emits a system message into the inbox of every reviewer the
// routing engine flagged. This is the pattern for every future
// system-event hook: write the operational record, then
// `emitSystemMessage` so the right inboxes light up.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitDebriefSubmitted } from "@/lib/messages-v2/system-events";
import { routeRecipients } from "@/lib/debrief/routing";
import type { DebriefSubmitterRole } from "@/lib/debrief/types";
import type { MessagePriority } from "@/lib/messages-v2/types";

// Map the debrief routing engine's reviewer-role keys to the directory
// userIds that should receive the system message. Phase 4 replaces
// this with a real users-by-role query.
const DIRECTORY_USERS_BY_ROLE: Record<string, string[]> = {
  HumanResource:      ["STF-AW-019"],                  // Anne Wairimu (HR)
  CountryDirector:    ["STF-SO-007"],                  // Sarah Okello (CD)
  CountryProgramLead: ["STF-DM-001"],                  // Daniel Mwangi (PL)
  CCEO:               ["STF-PC-001", "STF-SN-101", "STF-IM-005"],
  ImpactAssessment:   ["STF-GA-042"],
  ProgramAccountant:  ["STF-MT-006"],
};

export async function submitDebriefAction(formData: FormData): Promise<{ ok: true; messageId: string } | { ok: false; error: string }> {
  const user = await getCurrentUser();

  const submitterRole = String(formData.get("submitterRole") ?? "") as DebriefSubmitterRole;
  const categoryCsv   = String(formData.get("categories")    ?? "");
  const priority      = String(formData.get("priority")      ?? "Normal") as MessagePriority;
  const categories    = categoryCsv.split(",").filter(Boolean);

  if (!submitterRole || categories.length === 0) {
    return { ok: false, error: "Missing submitter role or categories." };
  }

  // Routing engine returns reviewer roles (e.g. ["HumanResource",
  // "CountryDirector"]). Flatten through the directory map to user
  // ids — production swaps this for a real query.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const reviewerRoles = routeRecipients(submitterRole, categories as any, priority);
  const recipientUserIds = Array.from(
    new Set(reviewerRoles.flatMap((r) => DIRECTORY_USERS_BY_ROLE[r] ?? [])),
  );

  // Emit the system message into the inbox of every reviewer the
  // routing engine flagged. Mock storage now; real DB writes later.
  const debriefId = `D-${Date.now()}`;
  const msg = emitDebriefSubmitted({
    debriefId,
    submittedByName: user.name,
    submittedByRole: submitterRole === "CCEO" ? "CCEO" : submitterRole === "CountryProgramLead" ? "Program Lead" : "Partner",
    category: categories[0],
    priority,
    recipientUserIds,
  });

  revalidatePath("/messages");
  revalidatePath("/debriefs");
  return { ok: true, messageId: msg.id };
}
