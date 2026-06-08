"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Search as SearchIcon, Building2, Users, Sparkles, Wallet, FileText, Layers, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { LoadingState, EmptyState, ErrorState } from "@/components/ui/DataStates";
import type { SearchResult } from "@/app/api/search/route";

// Backend-backed search. The page reads `?q=` (shareable URL), fetches the
// role-scoped DB search via /api/search, and renders grouped results with
// loading / empty / error states. No mock data.

type Group = { title: string; Icon: typeof FileText; items: SearchResult[] };

// Map backend result `type` onto display groups (in render order).
const GROUPS: { key: string; title: string; Icon: typeof FileText; types: string[] }[] = [
  { key: "schools", title: "Schools", Icon: Building2, types: ["school", "core_school"] },
  { key: "clusters", title: "Clusters", Icon: Layers, types: ["cluster"] },
  { key: "projects", title: "Special Projects", Icon: Sparkles, types: ["project"] },
  { key: "staff", title: "Staff", Icon: Users, types: ["staff"] },
  { key: "funds", title: "Fund Requests", Icon: Wallet, types: ["fund_request"] },
];

export default function SearchPage() {
  // useSearchParams must be used inside Suspense in the app router to avoid a
  // client-side-rendering bailout at build time.
  return (
    <Suspense fallback={null}>
      <SearchInner />
    </Suspense>
  );
}

function SearchInner() {
  const router = useRouter();
  const params = useSearchParams();
  const q = (params.get("q") ?? "").trim();

  const [input, setInput] = useState(q);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [failedAt, setFailedAt] = useState<Date | null>(null);

  useEffect(() => {
    setInput(q);
  }, [q]);

  const load = useCallback(async () => {
    if (q.length < 2) {
      setResults([]);
      setState("idle");
      return;
    }
    setState("loading");
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || data.live === false) {
        setFailedAt(new Date());
        setState("error");
        return;
      }
      setResults(Array.isArray(data.results) ? data.results : []);
      setState("ready");
    } catch {
      setFailedAt(new Date());
      setState("error");
    }
  }, [q]);

  useEffect(() => {
    load();
  }, [load]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const next = input.trim();
    router.push(next ? `/search?q=${encodeURIComponent(next)}` : "/search");
  };

  const groups: Group[] = GROUPS
    .map((g) => ({ title: g.title, Icon: g.Icon, items: results.filter((r) => g.types.includes(r.type)) }))
    .filter((g) => g.items.length > 0);

  return (
    <StubPage
      title="Search"
      subtitle="Find a school, cluster, project, staff member, or fund request. Shareable — the query is part of the URL."
    >
      <form onSubmit={onSubmit} className="card rounded-2xl p-3 flex items-center gap-3">
        <SearchIcon size={15} className="text-[var(--color-edify-muted)]" />
        <input
          name="q"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          aria-label="Search"
          placeholder="Search for a school, cluster, project, staff member, fund request…"
          className="flex-1 bg-transparent focus:outline-none text-[13px]"
        />
        <button
          type="submit"
          className="h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold"
        >
          Search
        </button>
      </form>

      {q.length < 2 ? (
        <p className="text-[11.5px] muted text-center py-6">Type at least two characters to search across schools, clusters, projects, staff, and fund requests.</p>
      ) : state === "loading" ? (
        <LoadingState message="Searching…" />
      ) : state === "error" ? (
        <ErrorState message="Search is unavailable." onRetry={load} at={failedAt ?? undefined} />
      ) : groups.length === 0 ? (
        <EmptyState
          title="No results"
          message={`Nothing matched “${q}”.`}
          icon={SearchIcon}
          compact
        />
      ) : (
        <>
          {groups.map((g) => (
            <ResultGroup key={g.title} title={g.title} Icon={g.Icon} items={g.items} />
          ))}
        </>
      )}
    </StubPage>
  );
}

function ResultGroup({
  title,
  Icon,
  items,
}: {
  title: string;
  Icon: typeof FileText;
  items: SearchResult[];
}) {
  return (
    <section>
      <h2 className="text-body font-extrabold uppercase tracking-wide muted px-1 mb-1.5 inline-flex items-center gap-1.5">
        <Icon size={12} />
        {title} ({items.length})
      </h2>
      <div className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {items.map((it) => (
          <Link
            key={it.id}
            href={it.route}
            className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40"
          >
            <div className="flex-1 min-w-0">
              <div className="text-body font-extrabold tracking-tight truncate">{it.title}</div>
              <div className="text-[11px] muted truncate">
                {it.subtitle}
                {it.status ? ` · ${it.status}` : ""}
              </div>
            </div>
            <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        ))}
      </div>
    </section>
  );
}
