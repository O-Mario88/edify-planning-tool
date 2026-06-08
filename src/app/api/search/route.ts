import { NextResponse } from "next/server";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch } from "@/lib/api/backend";

// Backend-backed, role-scoped search. Proxies GET /search?q=… to the NestJS
// search module. No mock fallback — the client renders loading/empty/error.
export const dynamic = "force-dynamic";

export type SearchResult = {
  id: string;
  type: string;
  title: string;
  subtitle: string;
  status?: string;
  route: string;
  metadata?: Record<string, unknown>;
};

type SearchResponse = { query: string; context: string; results: SearchResult[] };

export async function GET(req: Request) {
  const user = await getCurrentUser();
  const q = (new URL(req.url).searchParams.get("q") ?? "").trim();
  if (q.length < 2) {
    return NextResponse.json({ live: true, query: q, results: [] as SearchResult[] });
  }
  const r = await backendFetch<SearchResponse>(`/search?q=${encodeURIComponent(q)}`, user);
  return r.ok
    ? NextResponse.json({ live: true, query: r.data.query, results: r.data.results })
    : NextResponse.json({ live: false, error: r.error }, { status: 502 });
}
