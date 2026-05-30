import Link from "next/link";
import { Search as SearchIcon, Building2, Users, Sparkles, Wallet, FileText, ChevronRight } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { schoolsMock } from "@/lib/schools-mock";
import { staffTargetPerformance } from "@/lib/team-targets-mock";
import { specialProjects } from "@/lib/special-projects-mock";
import { fundRequests } from "@/lib/workflow-mock";

// Search is a client surface, but the page itself is server-rendered so
// the initial body is fast. The input below uses a `name="q"` GET form so
// the URL becomes shareable (/search?q=hope). Client interactivity (live
// filtering, ⌘K palette) lands next.

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  const query = (q ?? "").trim().toLowerCase();

  const matched = (s: string) => query === "" || s.toLowerCase().includes(query);

  const schools = schoolsMock.filter((s) => matched(s.schoolName) || matched(s.district)).slice(0, 8);
  const staff   = staffTargetPerformance.filter((s) => matched(s.staffName) || matched(s.region)).slice(0, 8);
  const projects = specialProjects.filter((p) => matched(p.projectName) || matched(p.projectType)).slice(0, 8);
  const funds   = fundRequests.filter((f) => matched(f.id) || matched(f.staff) || matched(f.district)).slice(0, 8);

  const totalShown = schools.length + staff.length + projects.length + funds.length;

  return (
    <StubPage
      title="Search"
      subtitle="Find a school, staff member, project, or fund request. Shareable — the query is part of the URL."
    >
      <form action="/search" method="get" className="card rounded-2xl p-3 flex items-center gap-3">
        <SearchIcon size={15} className="text-[var(--color-edify-muted)]" />
        <input
          name="q"
          defaultValue={q ?? ""}
          aria-label="Search"
          placeholder="Search for a school, staff member, project, fund request…"
          className="flex-1 bg-transparent focus:outline-none text-[13px]"
        />
        <button
          type="submit"
          className="h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold"
        >
          Search
        </button>
      </form>

      {query === "" ? (
        <p className="text-[11.5px] muted text-center py-6">Type a search above to see results across schools, staff, projects, and fund requests.</p>
      ) : totalShown === 0 ? (
        <p className="text-[12px] muted text-center py-6">No results for <span className="font-extrabold">&ldquo;{q}&rdquo;</span>.</p>
      ) : (
        <>
          {schools.length > 0 && (
            <ResultGroup
              title="Schools"
              Icon={Building2}
              items={schools.map((s) => ({
                key: s.schoolId,
                title: s.schoolName,
                subtitle: `${s.district} · ${s.region} · SSA ${s.ssaScore}%`,
                href: `/schools/${s.schoolId}`,
              }))}
            />
          )}
          {staff.length > 0 && (
            <ResultGroup
              title="Staff"
              Icon={Users}
              items={staff.map((s) => ({
                key: s.staffId,
                title: s.staffName,
                subtitle: `${s.role} · ${s.region} · ${s.achievementPercent}% achievement`,
                href: `/staff/${s.staffId}`,
              }))}
            />
          )}
          {projects.length > 0 && (
            <ResultGroup
              title="Special Projects"
              Icon={Sparkles}
              items={projects.map((p) => ({
                key: p.projectId,
                title: p.projectName,
                subtitle: `${p.projectType} · ${p.status} · ${p.assignedPartnerName ?? "—"}`,
                href: `/projects/${p.projectId}`,
              }))}
            />
          )}
          {funds.length > 0 && (
            <ResultGroup
              title="Fund Requests"
              Icon={Wallet}
              items={funds.map((f) => ({
                key: f.id,
                title: `#${f.id} · ${f.district}`,
                subtitle: `${f.staff} · ${f.month} · ${f.status}`,
                href: `/fund-requests/${f.id}`,
              }))}
            />
          )}
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
  items: { key: string; title: string; subtitle: string; href: string }[];
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
            key={it.key}
            href={it.href}
            className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40"
          >
            <div className="flex-1 min-w-0">
              <div className="text-body font-extrabold tracking-tight truncate">{it.title}</div>
              <div className="text-[11px] muted truncate">{it.subtitle}</div>
            </div>
            <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        ))}
      </div>
    </section>
  );
}
