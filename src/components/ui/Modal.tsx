// Canonical Modal primitive.
//
// Re-exports AccessibleDialog under a more discoverable name. Use
// Modal for new code; existing imports of AccessibleDialog continue
// to work. They are the same component — picking one consistent name
// means new pages reach for this when they need a dialog instead of
// hand-rolling another Framer Motion overlay.
//
// API recap:
//   <Modal
//     open={isOpen}
//     onClose={close}
//     title="Approve fund request"
//     description="Optional one-line context shown under the title."
//     variant="dialog"          // "dialog" | "drawer-right" | "sheet"
//     size="md"                 // "sm" | "md" | "lg" | "xl"
//     footer={<>…sticky action row…</>}
//     dismissOnEscape           // true by default
//     dismissOnOverlayClick     // true by default
//   >
//     …body…
//   </Modal>
//
// Guarantees: role=dialog, aria-modal, aria-labelledby wired, focus
// trap, ESC closes, overlay click closes, returns focus to trigger,
// body scroll locked, rendered into a portal.

export { AccessibleDialog as Modal } from "./AccessibleDialog";
export type { } from "./AccessibleDialog";
