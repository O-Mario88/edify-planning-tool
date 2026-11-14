package parity

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

func fixture(t *testing.T) *List {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("testdata", "fixture.json"))
	if err != nil {
		t.Fatal(err)
	}
	l, err := Load(raw)
	if err != nil {
		t.Fatal(err)
	}
	return l
}

func TestAnEntryAcceptsOnlyAnExactMatch(t *testing.T) {
	l := fixture(t)
	field := ".blocks[1].filters[0].options[1].selected"
	cases := []struct {
		name   string
		answer Answer
		diff   Diff
		want   string // the entry that accepts it; "" for none
	}{
		{"the listed difference", Answer{ToolPage, "/team-plan", "(as it opens)"}, Diff{Field: field, Existing: "false", Go: "true"}, "fixture-period-select"},
		{"its other listed question", Answer{ToolPage, "/team-plan", "period=month"}, Diff{Field: field, Existing: "false", Go: "true"}, "fixture-period-select"},
		{"a question not listed", Answer{ToolPage, "/team-plan", "period=fy"}, Diff{Field: field, Existing: "false", Go: "true"}, ""},
		{"another page", Answer{ToolPage, "/team-plans", "(as it opens)"}, Diff{Field: field, Existing: "false", Go: "true"}, ""},
		{"another tool", Answer{ToolProfile, "/team-plan", "(as it opens)"}, Diff{Field: field, Existing: "false", Go: "true"}, ""},
		{"a neighbouring field", Answer{ToolPage, "/team-plan", "(as it opens)"}, Diff{Field: ".blocks[1].filters[0].options[2].selected", Existing: "false", Go: "true"}, ""},
		{"the values the other way round", Answer{ToolPage, "/team-plan", "(as it opens)"}, Diff{Field: field, Existing: "true", Go: "false"}, ""},
		{"a pattern only part of the value matches", Answer{ToolPage, "/staff-activity", "on=9999-12-31"}, Diff{Field: ErrorField, Existing: "status 500 and more", Go: "<nil>"}, ""},
		{"an error difference listed", Answer{ToolPage, "/staff-activity", "on=9999-12-31"}, Diff{Field: ErrorField, Existing: "status 500", Go: "<nil>"}, "fixture-staff-activity-far-day"},
		{"Go failing instead of answering", Answer{ToolPage, "/staff-activity", "on=9999-12-31"}, Diff{Field: ErrorField, Existing: "status 500", Go: "unavailable"}, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			e, ok := l.Match(c.answer, c.diff)
			if got := map[bool]string{true: e.ID}[ok]; got != c.want {
				t.Fatalf("accepted by %q, want %q", got, c.want)
			}
		})
	}
}

func TestSplitKeepsEveryOtherDifferenceFailing(t *testing.T) {
	l := fixture(t)
	a := Answer{ToolPage, "/team-plan", "(as it opens)"}
	diffs := []Diff{
		{Field: ".blocks[1].filters[0].options[1].selected", Existing: "false", Go: "true", Text: "  selected"},
		{Field: ".blocks[2].table.rows[0].cells[1]", Existing: "3", Go: "4", Text: "  a count"},
	}
	unexpected, intended := l.Split(a, diffs)
	if len(intended) != 1 || intended[0].Entry != "fixture-period-select" {
		t.Fatalf("intended: %v", intended)
	}
	if len(unexpected) != 1 || unexpected[0].Field != ".blocks[2].table.rows[0].cells[1]" {
		t.Fatalf("still failing: %v", unexpected)
	}
	if !strings.Contains(IntendedLines(intended), "intended (fixture-period-select)") {
		t.Fatalf("printed: %q", IntendedLines(intended))
	}
}

func TestShadowRowsPairOnlyWhenEveryDifferingColumnIsIntended(t *testing.T) {
	l := fixture(t)
	a := Answer{ToolShadow, "snooze_todo", "todo_snooze"}
	long, cut := strings.Repeat("x", 200), strings.Repeat("x", 128)
	row := func(id, until string) string {
		return `{"id":"<new>","todo_id":"` + id + `","until":"` + until + `"}`
	}
	cases := []struct {
		name          string
		existing, got []string
		pairs, left   int
	}{
		{"only the listed column differs", []string{row(long, "2026-11-20")}, []string{row(cut, "2026-11-20")}, 1, 0},
		{"another column differs too", []string{row(long, "2026-11-20")}, []string{row(cut, "2026-11-21")}, 0, 2},
		{"the listed column's values are not the pattern", []string{row("abc", "2026-11-20")}, []string{row("ab", "2026-11-20")}, 0, 2},
		{"a column only one side has", []string{row(long, "2026-11-20")}, []string{`{"id":"<new>","todo_id":"` + cut + `"}`}, 0, 2},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			pairs, restA, restB := l.PairRows(a, c.existing, c.got)
			if len(pairs) != c.pairs || len(restA)+len(restB) != c.left {
				t.Fatalf("pairs %d, left %d; want %d, %d", len(pairs), len(restA)+len(restB), c.pairs, c.left)
			}
		})
	}
}

func TestLoadRefusesAnEntryThatCannotBeChecked(t *testing.T) {
	good := `{"id":"x","tool":"page","where":"/p","questions":["q"],"fields":["f"],"existing":"a","go":"b","defect":"d","decision":"o","test":"internal/x.TestY"}`
	cases := map[string]string{
		"no defect":           strings.Replace(good, `"defect":"d"`, `"defect":""`, 1),
		"no question":         strings.Replace(good, `"questions":["q"]`, `"questions":[]`, 1),
		"an unknown tool":     strings.Replace(good, `"tool":"page"`, `"tool":"guess"`, 1),
		"the same two values": strings.Replace(good, `"go":"b"`, `"go":"a"`, 1),
		"no test":             strings.Replace(good, `"test":"internal/x.TestY"`, `"test":"none"`, 1),
		"a broken pattern":    strings.Replace(good, `"go":"b"`, `"go":"("`, 1),
		"an unknown key":      strings.Replace(good, `"id":"x"`, `"id":"x","note":"n"`, 1),
	}
	for name, entry := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := Load([]byte("[" + entry + "]")); err == nil {
				t.Fatal("loaded")
			}
		})
	}
	if _, err := Load([]byte("[" + good + "," + good + "]")); err == nil {
		t.Fatal("an id listed twice loaded")
	}
	if _, err := Load([]byte("[" + good + "]")); err != nil {
		t.Fatalf("a complete entry: %v", err)
	}
}

// Every checked-in entry names a unit test that exists, so no difference is
// accepted without a test proving Go's corrected behaviour.
func TestTheCheckedInListLoadsAndEveryEntryHasItsTest(t *testing.T) {
	l, err := CheckedIn()
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range l.Entries() {
		dir := filepath.Join("..", "..", e.TestPackage())
		files, _ := filepath.Glob(filepath.Join(dir, "*_test.go"))
		found := false
		decl := regexp.MustCompile(`(?m)^func ` + regexp.QuoteMeta(e.TestName()) + `\(`)
		for _, f := range files {
			if b, err := os.ReadFile(f); err == nil && decl.Match(b) {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("entry %q names %s, which does not exist", e.ID, e.Test)
		}
	}
}

func TestADeduplicatedRelationAcceptsOnlyTheSameListWithoutRepeats(t *testing.T) {
	l, err := Load([]byte(`[{"id":"cats","tool":"notifications","where":"/notifications","questions":["*"],"fields":["filters.categories"],
		"relation":"deduplicated","defect":"d","decision":"o","test":"internal/x.TestY"}]`))
	if err != nil {
		t.Fatal(err)
	}
	a := Answer{ToolNotifications, "/notifications", "page 1"}
	ok := func(old, new string) bool {
		_, matched := l.Match(a, Diff{Field: "filters.categories", Existing: old, Go: new})
		return matched
	}
	if !ok(`["a","b","a","c","b"]`, `["a","b","c"]`) {
		t.Fatal("the list without its repeats, in first-seen order")
	}
	for name, pair := range map[string][2]string{
		"another order":       {`["a","b","a"]`, `["b","a"]`},
		"an item dropped":     {`["a","b","a"]`, `["a"]`},
		"an item added":       {`["a","a"]`, `["a","z"]`},
		"no repeats to fix":   {`["a","b"]`, `["a","b","c"]`},
		"not a list":          {`a`, `a`},
		"the same list again": {`["a","a"]`, `["a","a"]`},
	} {
		if ok(pair[0], pair[1]) {
			t.Fatalf("%s: accepted", name)
		}
	}
}

func TestAnyQuestionMatchesOnlyItsPageFieldAndValues(t *testing.T) {
	l, err := Load([]byte(`[{"id":"p","tool":"page","where":"/p","questions":["*"],"fields":[".f"],"existing":"week","go":"month|fy","defect":"d","decision":"o","test":"internal/x.TestY"}]`))
	if err != nil {
		t.Fatal(err)
	}
	ok := func(where, field, old, new string) bool {
		_, matched := l.Match(Answer{ToolPage, where, "anything=1"}, Diff{Field: field, Existing: old, Go: new})
		return matched
	}
	if !ok("/p", ".f", "week", "fy") {
		t.Fatal("any question on its page")
	}
	if ok("/q", ".f", "week", "fy") || ok("/p", ".g", "week", "fy") || ok("/p", ".f", "week", "quarter") {
		t.Fatal("matched outside its page, field or values")
	}
}

func TestAReorderedListIsAcceptedWholeOnlyWithTheSameItems(t *testing.T) {
	list, err := Load([]byte(`[{"id": "r", "tool": "page", "where": "/p", "questions": ["*"], "fields": [".blocks[0].table.rows"],
	  "relation": "reordered", "defect": "d", "decision": "o", "test": "internal/x.TestY"}]`))
	if err != nil {
		t.Fatal(err)
	}
	page := func(rows ...string) map[string]any {
		items := []any{}
		for _, r := range rows {
			items = append(items, map[string]any{"cells": []any{map[string]any{"text": r}}})
		}
		return map[string]any{"blocks": []any{map[string]any{"table": map[string]any{"rows": items}}}}
	}
	answer := Answer{Tool: "page", Where: "/p", Question: "(as it opens)"}
	mine, old := page("b", "a"), page("a", "b")
	if got := list.AcceptReordered(answer, mine, old); len(got) != 1 || got[0].Entry != "r" {
		t.Fatalf("reordered: %v", got)
	}
	if rows, _, _ := listAt(mine, ".blocks[0].table.rows"); rows[0].(map[string]any)["cells"].([]any)[0].(map[string]any)["text"] != "a" {
		t.Error("Go's list was not replaced by the existing one")
	}
	for _, c := range [][2]map[string]any{{page("a", "c"), page("a", "b")}, {page("a", "b"), page("a", "b")}, {page("a"), page("a", "b")}} {
		if got := list.AcceptReordered(answer, c[0], c[1]); len(got) != 0 {
			t.Errorf("not a reordering, accepted: %v", got)
		}
	}
	if got := list.AcceptReordered(Answer{Tool: "page", Where: "/q", Question: "x"}, page("b", "a"), page("a", "b")); len(got) != 0 {
		t.Error("another page's list was accepted")
	}
}
