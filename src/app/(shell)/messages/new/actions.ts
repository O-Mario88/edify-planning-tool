// Shell /messages server actions. These re-export the partner-route
// actions because the logic is identical — sender role + permissions
// + persistence all flow through the same `appendMessage` /
// `appendReply` helpers. The `backHref` form field tells the action
// where to revalidate, so the same action serves both routes.
//
// When system-event emit hooks (evidence return, payment cleared,
// debrief submit) land, those will also use the same helpers — the
// action layer stays thin.

export {
  sendMessageAction,
  replyMessageAction,
} from "@/app/(shell)/partner/messages/new/actions";
