"use server";

// Composer + reply server actions. Permissions are re-checked here so
// a client can't fabricate a recipient outside the sender's scope.
// Writes through the mock store façade; Phase 3 swaps the body for
// real API calls.

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { recipientsForSender, userByEmail } from "@/lib/messages-v2/directory";
import { appendMessage, appendReply } from "@/lib/messages-v2/mock";
import type {
  MessageCategory,
  MessageContext,
  MessageContextType,
  MessagePriority,
  MessageSenderRole,
} from "@/lib/messages-v2/types";

// Mapping demo roles → display role for the senderRole stamp.
function displaySenderRole(role: string): MessageSenderRole {
  switch (role) {
    case "CCEO":                return "CCEO";
    case "CountryProgramLead":  return "Program Lead";
    case "CountryDirector":     return "Country Director";
    case "RVP":                 return "RVP";
    case "HumanResource":       return "HR";
    case "ProgramAccountant":   return "Accountant";
    case "ImpactAssessment":    return "M&E";
    case "PartnerAdmin":
    case "PartnerFieldOfficer":
    case "PartnerViewer":       return "Partner";
    case "Admin":               return "Admin";
    default:                    return "CCEO";
  }
}

export async function sendMessageAction(formData: FormData): Promise<void> {
  const sender = await getCurrentUser();

  const subject = String(formData.get("subject") ?? "").trim();
  const body = String(formData.get("body") ?? "").trim();
  const category = String(formData.get("category") ?? "general") as MessageCategory;
  const priority = String(formData.get("priority") ?? "Normal") as MessagePriority;
  const recipientEmails = String(formData.get("recipientEmails") ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const relatedSchool = String(formData.get("relatedSchool") ?? "").trim();
  const backHref = String(formData.get("backHref") ?? "/messages");

  // Context — REQUIRED. Multi-context list is shipped as
  // pipe-delimited parallel arrays (`|`); comma is reserved for the
  // email list. The legacy single fields (contextType / contextId /
  // contextLabel) stay populated from index 0 so older callers don't
  // break.
  const contextTypesRaw  = String(formData.get("contextTypes")  ?? "");
  const contextIdsRaw    = String(formData.get("contextIds")    ?? "");
  const contextLabelsRaw = String(formData.get("contextLabels") ?? "");
  const sendMode = (String(formData.get("sendMode") ?? "one_thread") === "separate_threads")
    ? "separate_threads"
    : "one_thread";

  const ctxTypes  = contextTypesRaw.split("|").map((s) => s.trim()).filter(Boolean);
  const ctxIds    = contextIdsRaw.split("|").map((s) => s.trim()).filter(Boolean);
  const ctxLabels = contextLabelsRaw.split("|").map((s) => s.trim()).filter(Boolean);

  if (!subject || !body || recipientEmails.length === 0 || ctxIds.length === 0
      || ctxTypes.length !== ctxIds.length || ctxLabels.length !== ctxIds.length) {
    // Validation failure — bounce back. A real impl would round-trip
    // form state; for the demo the composer pre-validates so this is
    // a defence-in-depth path.
    redirect(`${backHref}/new?error=missing`);
  }

  const contexts: MessageContext[] = ctxIds.map((id, i) => ({
    type:  ctxTypes[i] as MessageContextType,
    id,
    label: ctxLabels[i],
  }));

  // Permission re-check: filter recipientEmails to ones the sender's
  // role is actually allowed to message.
  const allowedUsers = recipientsForSender(sender.role);
  const allowedEmails = new Set(allowedUsers.map((u) => u.email.toLowerCase()));
  const validRecipients = recipientEmails
    .map((e) => userByEmail(e))
    .filter((u): u is NonNullable<typeof u> => !!u && allowedEmails.has(u.email.toLowerCase()));

  if (validRecipients.length === 0) {
    redirect(`${backHref}/new?error=forbidden`);
  }

  // Persistence branches by sendMode:
  //   one_thread       → one Message with N contexts (grouped thread)
  //   separate_threads → N Messages, one per context (per-record audit)
  let landingId: string;
  if (sendMode === "separate_threads" && contexts.length > 1) {
    // Create one thread per context. The recipients + subject + body
    // are reused across each — same payload, different operational
    // anchor. We land on the FIRST created message; the rest sit in
    // the inbox/sent folder.
    const created = contexts.map((ctx) =>
      appendMessage({
        subject,
        body,
        sender:   { userId: sender.staffId, role: displaySenderRole(sender.role) },
        recipients: validRecipients.map((u) => ({ userId: u.userId, status: "unread" })),
        category,
        priority,
        contexts: [ctx],
        related:  relatedSchool ? { schoolName: relatedSchool } : undefined,
      }),
    );
    landingId = created[0]?.id ?? "";
  } else {
    const row = appendMessage({
      subject,
      body,
      sender:   { userId: sender.staffId, role: displaySenderRole(sender.role) },
      recipients: validRecipients.map((u) => ({ userId: u.userId, status: "unread" })),
      category,
      priority,
      contexts,
      related:  relatedSchool ? { schoolName: relatedSchool } : undefined,
    });
    landingId = row.id;
  }

  revalidatePath(backHref);
  revalidatePath(`${backHref}/${landingId}`);
  redirect(`${backHref}/${landingId}`);
}

export async function replyMessageAction(formData: FormData): Promise<void> {
  const sender = await getCurrentUser();

  const parentMessageId = String(formData.get("parentMessageId") ?? "");
  const body = String(formData.get("body") ?? "").trim();
  const backHref = String(formData.get("backHref") ?? "/messages");

  if (!parentMessageId || !body) {
    redirect(`${backHref}/${parentMessageId}?error=missing`);
  }

  const row = appendReply({
    parentMessageId,
    body,
    sender: { userId: sender.staffId, role: displaySenderRole(sender.role) },
  });

  if (!row) {
    redirect(`${backHref}?error=notfound`);
  }

  revalidatePath(`${backHref}/${parentMessageId}`);
  revalidatePath(backHref);
  redirect(`${backHref}/${parentMessageId}`);
}
