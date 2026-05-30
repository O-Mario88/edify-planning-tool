# Edify product principles — Simple → Healthy → Focused

Every feature in this codebase must pass **three tests**.
A feature that fails one of these tests should not ship — not without an
explicit, documented exception in the PR description.

---

## 1. Simple

> _Can a CCEO who has used the app for one week understand this feature
> in under 30 seconds?_

A feature is **Simple** when:

- The user knows what to do without reading documentation.
- The primary CTA is obvious — one button per card, named for the
  outcome ("Approve plan", not "Submit").
- Numbers come with sentences: `46 schools` becomes `Schools we're losing. Don't.`
- New jargon is rare. When we must introduce a term (FWI, SSA),
  the first surface that uses it explains it inline.

Anti-patterns:

- Two equally-prominent CTAs on one card.
- Acronyms without an inline expansion on first use.
- A user has to compare three charts to decide one thing.
- An empty state that doesn't tell the user what would fill it.

---

## 2. Healthy

> _Does this feature reduce the staff member's mental load, protect
> them from unfair judgment, and help leadership notice burnout?_

A feature is **Healthy** when:

- It does not surveil. Performance scores carry workload context;
  a person at 70% pace with a 95th-percentile portfolio is not the
  same person as 70% pace with a 5th-percentile portfolio.
- It does not interrupt without a reason. Notifications are
  classified Critical / Important / Informational. Quiet hours apply.
- It does not require the user to interpret data before they know
  what to do. The action comes first; the data justifies the action.
- It does not punish what the system caused. Funds blocked by a
  cost-settings draft do not count against the CCEO who can't submit.
- It surfaces overload, not just underperformance. Workload
  guardrails flag staff carrying too much; leadership sees a
  recommendation to rebalance, not to discipline.

Anti-patterns:

- A leaderboard that ranks staff by completion percentage alone.
- Notifications that fire at 22:00 for non-urgent items.
- A red badge on something the user is helpless to fix.
- Performance reviews that don't show the portfolio difficulty.

---

## 3. Focused

> _Does this feature move productivity, efficiency, effectiveness,
> target achievement, or quality support to schools?_

A feature is **Focused** when:

- It removes work-about-work. Plan Cascade: one write → three views.
  Bulk approve: 12 plans → 1 click.
- It connects to a school outcome. The Quality-of-Support Score
  weights SSA improvement, follow-up completion, and school feedback
  above raw activity count.
- It saves a measurable amount of time on a known workflow.
  "Approve safe plans in bulk" saves 11 clicks.

Anti-patterns:

- A new dashboard with no clear primary user.
- An analytics page with no action handoff.
- A KPI tile that's interesting but doesn't change behavior.
- A new chart above the action that pushed the action below the fold.

---

## How to use this in code review

When opening a PR that adds or changes a user-facing feature, the
description should answer:

> **Simple** — In one sentence, how does a brand-new CCEO know what to do with this?
>
> **Healthy** — What did we do to avoid adding cognitive load or surveillance pressure?
>
> **Focused** — Which of {productivity, efficiency, effectiveness, target achievement, school quality} does this move?

Reviewers should request changes when the answer to any test is "I'm not sure."

---

## The final principle

> _The system should reduce work about work, protect staff energy,
> and focus everyone on better support to schools._

If a feature doesn't help a CCEO spend more time helping a school,
or a CPL spend more time coaching a CCEO, we should not ship it.
