import Link from "next/link";
import {
  HelpCircle,
  BookOpen,
  ShieldCheck,
  Wallet,
  ClipboardList,
  Activity,
  Users,
  Mail,
  Search,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { helpArticles, type HelpArticle, type HelpCategory } from "@/lib/help-mock";

const ICON: Record<HelpArticle["iconKey"], LucideIcon> = {
  bookOpen:      BookOpen,
  shieldCheck:   ShieldCheck,
  wallet:        Wallet,
  clipboardList: ClipboardList,
  activity:      Activity,
  users:         Users,
};

const CATEGORIES: HelpCategory[] = ["Getting Started", "SSA", "Planning", "Funds", "People"];

export default function HelpPage() {
  return (
    <StubPage
      title="Help Center"
      subtitle="How the platform works — for the field staff and country teams. Search is wired to the same index that powers the global ⌘K palette."
    >
      <div className="card rounded-2xl p-3 flex items-center gap-3">
        <Search size={15} className="text-[var(--color-edify-muted)]" />
        <input
          aria-label="Search help articles"
          placeholder="Search for SSA, plan, valid visit, debrief…"
          className="flex-1 bg-transparent focus:outline-none text-[13px]"
        />
        <Link href="/search" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
          Advanced search →
        </Link>
      </div>

      {CATEGORIES.map((cat) => {
        const items = helpArticles.filter((a) => a.category === cat);
        if (items.length === 0) return null;
        return (
          <section key={cat}>
            <h2 className="text-body font-extrabold uppercase tracking-wide muted px-1 mb-1.5">{cat}</h2>
            <div className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
              {items.map((a) => {
                const Icon = ICON[a.iconKey];
                return (
                  <Link
                    key={a.slug}
                    href={`/help/${a.slug}`}
                    className="flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40"
                  >
                    <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                      <Icon size={15} />
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-body font-extrabold tracking-tight">{a.title}</div>
                      <div className="text-[11px] muted">{a.summary}</div>
                    </div>
                    <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0 self-center" />
                  </Link>
                );
              })}
            </div>
          </section>
        );
      })}

      <section className="card p-3.5 flex items-start gap-3">
        <span className="h-10 w-10 rounded-xl bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
          <HelpCircle size={18} />
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-body-lg font-extrabold tracking-tight">Still stuck?</h2>
          <p className="text-[11.5px] muted">
            Contact your Country Program Lead, or email{" "}
            <a href="mailto:support@edify.org" className="text-[var(--color-edify-primary)] font-semibold">
              support@edify.org
            </a>
            . We aim to respond within one business day.
          </p>
        </div>
        <a
          href="mailto:support@edify.org"
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold inline-flex items-center gap-1.5"
        >
          <Mail size={12} />
          Contact support
        </a>
      </section>
    </StubPage>
  );
}
