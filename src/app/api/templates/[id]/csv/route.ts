import { NextResponse } from "next/server";
import { getTemplate } from "@/lib/data-intake-mock";

// GET /api/templates/[id]/csv
//
// Returns the system-generated CSV upload template for the requested
// DataTemplate. Header row is `RequiredColumns + OptionalColumns`. A second
// row is included as an example so users see the expected shape.

function csvEscape(v: string | number): string {
  const s = String(v);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const t = getTemplate(id);
  if (!t) {
    return NextResponse.json({ error: "Template not found" }, { status: 404 });
  }

  const columns = [...t.requiredColumns, ...t.optionalColumns];
  const header  = columns.map(csvEscape).join(",");
  const example = t.exampleRows.length > 0
    ? columns.map((c) => csvEscape(t.exampleRows[0][c] ?? "")).join(",")
    : columns.map(() => "").join(",");

  const csv = `${header}\n${example}\n`;

  const safeName = t.name.replace(/[^A-Za-z0-9._-]+/g, "_");
  return new NextResponse(csv, {
    status: 200,
    headers: {
      "Content-Type":         "text/csv; charset=utf-8",
      "Content-Disposition":  `attachment; filename="${safeName}.csv"`,
      "Cache-Control":        "no-store",
    },
  });
}
