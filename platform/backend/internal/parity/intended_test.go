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
