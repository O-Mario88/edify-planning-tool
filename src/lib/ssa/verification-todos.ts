// SSA verification-todo completions — overlay store on top of the static
// ssaVerificationTodos mock. When a staffer marks a todo done they enter the
// new SSA Verification ID; we persist the EXACT entered id (ID-consistency
// rule: the verifier displays back precisely what was entered) plus the
// resulting flag. The page reads this overlay to render done rows.
//
// globalThis-backed, shaped like a future Prisma `SsaVerificationTodo` patch.

import "server-only";

export type SsaTodoFlag = "Potential Core School" | "Verified — Not Core Ready";

export type SsaTodoCompletion = {
  todoId: string;
  /** The exact SSA Verification ID the staffer entered — displayed verbatim. */
  ssaVerificationId: string;
  flag: SsaTodoFlag;
  newStatus: "Verified" | "Closed";
  octoberFy?: string;
  completedAt: string;
  completedById: string;
  completedByName: string;
};

type SsaTodoStore = { completions: SsaTodoCompletion[] };
const STORE_KEY = "__edify_ssa_todo_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: SsaTodoStore };

function getStore(): SsaTodoStore {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { completions: [] };
  return g[STORE_KEY]!;
}

export function ssaTodoCompletions(): SsaTodoCompletion[] {
  return getStore().completions;
}

export function ssaTodoCompletionFor(todoId: string): SsaTodoCompletion | undefined {
  return getStore().completions.find((c) => c.todoId === todoId);
}

export function recordSsaTodoCompletion(c: SsaTodoCompletion): SsaTodoCompletion {
  const store = getStore();
  const idx = store.completions.findIndex((x) => x.todoId === c.todoId);
  if (idx === -1) store.completions.push(c);
  else store.completions[idx] = c;
  return c;
}

export function __resetSsaTodoStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { completions: [] };
}
