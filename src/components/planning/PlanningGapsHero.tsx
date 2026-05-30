// PlanningGapsHero — calm, question-driven header for /planning.
//
// The 6-tile gap strip that used to sit below this header was removed:
// the same counts already appear inline on the SchoolGapsBoard and
// ClusterGapsBoard tab pills, and the Core Schools dashboard owns the
// per-school aggregates. Keeping the tiles here meant the same number
// in three places — high noise, zero new information.

export function PlanningGapsHero() {
  return (
    <section className="card p-3.5 sm:p-6">
      <p className="text-[10px] uppercase tracking-[0.12em] font-extrabold text-[var(--color-edify-muted)]">
        Planning Console
      </p>
      <h1
        className="font-extrabold tracking-tight leading-tight mt-1 text-[var(--color-edify-text)]"
        style={{ fontSize: "clamp(22px, 2.6vw, 28px)" }}
      >
        Which client schools and clusters are missing required support?
      </h1>
      <p className="text-[12px] sm:text-body-lg muted leading-relaxed mt-2 max-w-[80ch]">
        The system already knows which schools have no SSA, no visit, no training, or no cluster —
        and which clusters are missing meetings or School Improvement Training. Each card below shows
        the <span className="font-extrabold text-[var(--color-edify-text)]">next valid action</span>{" "}
        and who can own it.
      </p>
    </section>
  );
}
