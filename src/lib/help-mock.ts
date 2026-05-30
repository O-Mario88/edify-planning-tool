// Help articles. Shared between /help (index) and /help/[slug] (detail).
//
// Body is plain text — the detail page renders it across simple paragraphs
// so we don't need a Markdown pipeline for the demo. Add `keyPoints` when
// the article should also surface a callout list at the top.

export type HelpCategory = "Getting Started" | "SSA" | "Planning" | "Funds" | "People";

export type HelpArticle = {
  slug:       string;
  title:      string;
  summary:    string;
  category:   HelpCategory;
  iconKey:    "bookOpen" | "shieldCheck" | "wallet" | "clipboardList" | "activity" | "users";
  body:       string[];
  keyPoints?: string[];
};

export const helpArticles: HelpArticle[] = [
  {
    slug:     "welcome",
    title:    "Welcome to Edify",
    summary:  "How the platform is organized, by role.",
    category: "Getting Started",
    iconKey:  "bookOpen",
    body: [
      "Edify is built around 8 roles — CCEO, Country Program Lead, Country Director, Regional VP, Program Accountant, Impact Assessment, Human Resource, and Admin. Each role lands on a dedicated console that surfaces only the work they own.",
      "Field operations roles (CCEO and CPL) start on a work-plan; supervisory roles (Director, RVP) start on a regional dashboard; back-office roles (Accountant, Impact, HR) start on the queue most relevant to them.",
      "Every page is navigable from the left sidebar — its contents change with your role.",
    ],
  },
  {
    slug:     "first-day",
    title:    "Your first day as a CCEO",
    summary:  "Log in, plan your week, submit your debrief.",
    category: "Getting Started",
    iconKey:  "clipboardList",
    body: [
      "Sign in with your work email and the password your CPL set. You'll land on My Work Plan.",
      "On day 1, scan your Today list, claim a school visit, and confirm the route. Schedule the rest of the week using Plan a Visit.",
      "After every field activity, submit a Daily Field Debrief. The engine uses this for your weekly reflection and feeds the leaderboard.",
    ],
    keyPoints: [
      "Land on My Work Plan after login",
      "Submit a Daily Field Debrief after every activity",
      "Use Plan a Visit to schedule out the week",
    ],
  },
  {
    slug:     "ssa-field-guide",
    title:    "SSA field guide — 8 interventions",
    summary:  "What counts, examples, common scoring pitfalls.",
    category: "SSA",
    iconKey:  "shieldCheck",
    body: [
      "The Self-School Assessment scores each school across eight interventions: leadership, instructional practice, learner culture, discipleship, parental engagement, governance, operations, and finance.",
      "A score of 0–4 per intervention is observable. Use the rubric — never your gut — and bring photo evidence for each level above 2.",
      "Common pitfalls: scoring on a single classroom visit, conflating leadership with operations, and forgetting to attach the conversation note.",
    ],
  },
  {
    slug:     "valid-visit",
    title:    "Valid Visit rules",
    summary:  "The five conditions a visit must meet to count toward targets.",
    category: "SSA",
    iconKey:  "activity",
    keyPoints: [
      "Visit must be ≥ 90 minutes on-site",
      "Salesforce log filed within 5 days",
      "At least one photo of the school + signoff",
      "Headteacher signature in the visit log",
      "Activity recorded on the same calendar day",
    ],
    body: [
      "A visit only counts toward your target when all five conditions above are met. Invalid visits remain visible in your history but don't accrue toward the monthly or quarterly count.",
      "If you genuinely visited the school but a condition was missed (e.g. photo failed to upload), open the visit and add the missing evidence. The Impact Assessor can re-verify within 7 days of the visit date.",
      "Persistent invalidity is a leading indicator the engine watches for early-warning support review.",
    ],
  },
  {
    slug:     "fund-requests",
    title:    "Fund request lifecycle",
    summary:  "Accountant → Director → RVP → Disbursement, and common rejects.",
    category: "Funds",
    iconKey:  "wallet",
    body: [
      "A CCEO files a fund request from My Work Plan. The Program Accountant reviews receipts and bank details, the Country Director gates approval against the country budget, and the RVP signs off on requests above the country threshold.",
      "Disbursement happens within 3 business days of the final approval. Funds are released against the specific plan item — you can't reallocate without re-filing.",
      "Most common rejections: missing receipt, wrong school assigned, prior month's reconciliation outstanding.",
    ],
  },
  {
    slug:     "debrief-video",
    title:    "Daily Field Debrief (video)",
    summary:  "Walkthrough of the new form and the engine behind it.",
    category: "Planning",
    iconKey:  "bookOpen",
    body: [
      "The Daily Field Debrief is six questions and takes under two minutes when done at the school. The engine clusters answers by theme and feeds your weekly reflection plus the team intelligence summary.",
      "If you debrief at the end of the day instead of on-site, expect the reflection to be less actionable — context decays quickly.",
      "Video walkthrough is in production; for now, the form is self-explanatory and CPLs are available for one-on-one onboarding.",
    ],
  },
  {
    slug:     "support-review",
    title:    "Support-Review checklist",
    summary:  "Humane pre-PIP review — required before any escalation.",
    category: "People",
    iconKey:  "users",
    body: [
      "Before any Performance Improvement Plan is considered, the CPL and Country Director must complete a Support Review. The review documents what *support* the staff member is asking for and what's been provided.",
      "Approved leave, route difficulty, partner blocks, and funding delays are all surfaced in the review pack — these factors typically explain most apparent under-performance.",
      "Only after the Support Review concludes — and the documented support has been delivered — can a PIP be opened.",
    ],
    keyPoints: [
      "Required before any PIP",
      "Documents support asked for vs. provided",
      "Surfaces leave, route, partner, and funding context",
    ],
  },
  {
    slug:     "cluster-training",
    title:    "Cluster training toolkit",
    summary:  "Lesson plans, facilitator notes, attendance sheets.",
    category: "Planning",
    iconKey:  "users",
    body: [
      "Cluster trainings happen at the Cluster Hub and bring 4–8 schools together for a half-day on a single intervention (christ-like behaviour, learner culture, leadership, etc.). Each toolkit ships with a 90-minute facilitator script, two activity stations, and a sign-in sheet.",
      "Schedule the training in My Plan at least 7 days ahead so headteachers can confirm attendance. The CPL needs to sign off on training expenditure through the Weekly Fund Request before the training date.",
      "After delivery, file a Daily Field Debrief and attach the attendance sheet — that's what counts the training toward your target.",
    ],
    keyPoints: [
      "Schedule ≥ 7 days ahead",
      "Get CPL sign-off on the fund request",
      "Attach signed attendance to the debrief",
    ],
  },
  {
    slug:     "salesforce",
    title:    "Salesforce logging — how to",
    summary:  "Salesforce IDs, evidence rules, return reasons.",
    category: "SSA",
    iconKey:  "shieldCheck",
    body: [
      "Every verified visit, training, and SSA assessment must be logged in Salesforce within 48 hours. Use the Salesforce Queue (left sidebar → Insights → Salesforce Queue) to see your pending items and any returns from the Impact Assessment team.",
      "The Salesforce record ID lives on every school card (SF-…). Paste it into the Edify activity form so the engine can match your work to the right school — unmatched activities don't roll up into your targets.",
      "Common return reasons: missing photo evidence, wrong intervention code, partner mismatch, and Salesforce ID typo. Fix the activity and re-submit — the engine doesn't auto-retry.",
    ],
    keyPoints: [
      "Log within 48 hours",
      "Always include the SF-… ID from the school card",
      "Fix returns and re-submit — no auto-retry",
    ],
  },
];
