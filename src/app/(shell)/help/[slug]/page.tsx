import { notFound } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  BookOpen,
  ShieldCheck,
  Wallet,
  ClipboardList,
  Activity,
  Users,
  CheckCircle2,
  Mail,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { isMockAllowed } from "@/lib/mock-policy";
import type { HelpArticle } from "@/lib/help-mock";

const ICON: Record<HelpArticle["iconKey"], LucideIcon> = {
  bookOpen:      BookOpen,
  shieldCheck:   ShieldCheck,
  wallet:        Wallet,
  clipboardList: ClipboardList,
  activity:      Activity,
  users:         Users,
};

export default async function HelpArticlePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  // Help articles are static reference content. In dev (mock enabled) we load
  // the seed articles; in production the mock module is never imported, so the
  // detail page 404s — which is the honest "not available" signal.
  const helpArticles = isMockAllowed()
    ? (await import("@/lib/help-mock")).helpArticles
    : [];
  const article = helpArticles.find((a) => a.slug === slug);
  if (!article) return notFound();
  const Icon = ICON[article.iconKey];

  const related = helpArticles
    .filter((a) => a.category === article.category && a.slug !== article.slug)
    .slice(0, 3);

  return (
    <StubPage title={article.title} subtitle={article.summary}>
      <Link
        href="/help"
        className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline -mt-2"
      >
        <ArrowLeft size={11} />
        Back to Help Center
      </Link>

      <article className="card p-3.5 flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <span className="h-11 w-11 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
            <Icon size={18} />
          </span>
          <div>
            <div className="text-caption font-bold uppercase tracking-wide muted">
              {article.category}
            </div>
            <h1 className="text-[18px] font-extrabold tracking-tight">{article.title}</h1>
          </div>
        </div>

        {article.keyPoints && (
          <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-3 mt-1">
            <h2 className="text-[11.5px] font-extrabold uppercase tracking-wide muted mb-2">
              Key points
            </h2>
            <ul className="space-y-1.5">
              {article.keyPoints.map((p, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[12px] leading-snug">
                  <CheckCircle2 size={12} className="text-emerald-600 mt-0.5 shrink-0" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="space-y-2.5 mt-1">
          {article.body.map((para, i) => (
            <p key={i} className="text-body leading-relaxed text-[var(--color-edify-text)]">
              {para}
            </p>
          ))}
        </div>
      </article>

      {related.length > 0 && (
        <section>
          <h2 className="text-body font-extrabold uppercase tracking-wide muted px-1 mb-1.5">
            Related in {article.category}
          </h2>
          <div className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
            {related.map((a) => {
              const RelIcon = ICON[a.iconKey];
              return (
                <Link
                  key={a.slug}
                  href={`/help/${a.slug}`}
                  className="flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40"
                >
                  <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                    <RelIcon size={15} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight">{a.title}</div>
                    <div className="text-[11px] muted">{a.summary}</div>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      <section className="card p-3.5 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="text-[13px] font-extrabold tracking-tight">Need more help?</h2>
          <p className="text-[11.5px] muted">
            Email{" "}
            <a href="mailto:support@edify.org" className="text-[var(--color-edify-primary)] font-semibold">
              support@edify.org
            </a>{" "}
            — we aim to respond within one business day.
          </p>
        </div>
        <a
          href="mailto:support@edify.org"
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold inline-flex items-center gap-1.5 shrink-0"
        >
          <Mail size={12} />
          Contact support
        </a>
      </section>
    </StubPage>
  );
}
