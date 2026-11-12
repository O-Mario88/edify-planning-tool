//go:build integration

package integration

import (
	"context"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

const coreOversight = "/core-schools-oversight/"

// coreTable is the page's table: after its filters, strip and tabs.
func coreTable(t *testing.T, page *screensv1.GetPageResponse) *screensv1.PageTable {
	t.Helper()
	blocks := page.GetBlocks()
	if len(blocks) != 5 || blocks[0].GetFilters() == nil || blocks[1].GetStrip() == nil || blocks[2].GetLinkTabs() == nil || blocks[3].GetTable() == nil {
		t.Fatalf("the page is its filters, its strip, its tabs, its table and its note: %v", blocks)
	}
	return blocks[3].GetTable()
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestCoreSchoolOversightListsTheOfficersCoreSchools(t *testing.T) {
	var held int
	if err := admin.QueryRow(context.Background(), `
SELECT count(*) FROM school s JOIN staff_school_assignment a ON a.school_id = s.id
JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened')
  AND s.school_type IN ('core', 'core_trained', 'core_graduate', 'champion')`).Scan(&held); err != nil || held == 0 {
		t.Skip("the seeded officer holds no Core school")
	}
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, coreOversight, nil)
	if err != nil {
		t.Fatal(err)
	}
	if h := page.GetHeader(); h.GetEyebrow() != "Oversight" || h.GetTitle() != "Core School Oversight" || len(h.GetActions()) != 0 {
		t.Fatalf("the header: %v", h)
	}
	if got := page.GetBlocks()[1].GetStrip().GetMetrics()[0]; got.GetLabel() != "Core Schools" || got.GetValue() == "0" {
		t.Fatalf("the strip's first figure: %v", got)
	}
	table := coreTable(t, page)
	if len(table.GetColumns()) != 21 || len(table.GetRows()) != min(held, 50) {
		t.Fatalf("%d columns, %d rows for %d schools held", len(table.GetColumns()), len(table.GetRows()), held)
	}
	if held > 50 && (table.GetPager() == nil || table.GetFootnote() != table.GetPager().GetSummary()) {
		t.Fatalf("more than a page of schools is paged: %v", table.GetPager())
	}
	for _, row := range table.GetRows() {
		if name := row.GetCells()[0]; !strings.HasPrefix(name.GetHref(), "/schools/") {
			t.Fatalf("a school's name opens its profile: %v", name)
		}
	}
	second, err := pageOf(token, coreOversight, map[string]string{"page": "2", "sort": "latest"})
	if err != nil {
		t.Fatal(err)
	}
	if held > 50 {
		pager := coreTable(t, second).GetPager()
		if pager.GetPages()[0].GetLabel() != "Prev" || pager.GetPages()[0].GetHref() != "?sort=latest&page=1" {
			t.Fatalf("a second page links back keeping the sort: %v", pager.GetPages()[0])
		}
	}
}

func TestCoreSchoolOversightTabsAreGos(t *testing.T) {
	borrowAccount(t, "admin@edify.org")
	token := sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	for tab, want := range map[string]func(*screensv1.GetPageResponse) bool{
		"groups": func(p *screensv1.GetPageResponse) bool {
			return p.GetBlocks()[3].GetLinkTabs() != nil && p.GetBlocks()[4].GetTable() != nil
		},
		"attention": func(p *screensv1.GetPageResponse) bool { return p.GetBlocks()[3].GetPanel() != nil },
		"recommendations": func(p *screensv1.GetPageResponse) bool {
			return strings.HasPrefix(p.GetBlocks()[3].GetPanel().GetItems()[0].GetText(), "The SSA recommendations")
		},
		"champion": func(p *screensv1.GetPageResponse) bool {
			return strings.HasPrefix(p.GetBlocks()[3].GetPanel().GetItems()[0].GetText(), "Edify's Champion rule")
		},
	} {
		page, err := pageOf(token, coreOversight, map[string]string{"tab": tab})
		if err != nil {
			t.Fatalf("%s: %v", tab, err)
		}
		if hidden := page.GetBlocks()[0].GetFilters().GetHidden()["tab"]; hidden != tab || !want(page) {
			t.Fatalf("the %s tab (hidden %q): %v", tab, hidden, page.GetBlocks())
		}
	}
}

func TestCoreSchoolOversightIsNotThereForARoleOutsideItNorBelowIt(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, coreOversight, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator opening Core School Oversight: %v, want not found", err)
	}
	borrowAccount(t, "admin@edify.org")
	token = sessionOf(t, "admin@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{"/core-schools-oversight", "/core-schools-oversight/export"} {
		if _, err := pageOf(token, path, nil); connect.CodeOf(err) != connect.CodeNotFound {
			t.Fatalf("%s: %v, want not found, as the existing feed answers", path, err)
		}
	}
}
