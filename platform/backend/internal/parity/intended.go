// Package parity holds the checked-in list of intended differences between
// Go and the existing application (docs/migration/68-intended-differences.md).
//
// The owner decided (2026-11-13, "Can you fix those from the go side") that
// Go fixes the existing application's defects instead of copying them. Each
// such fix makes Go answer differently from the existing application, and
// the comparison tools (cmd/parity, cmd/notificationparity, cmd/shadow)
// would report it as a difference. intended.json lists each one: where it
// shows, which question or step, which field, the existing value's pattern,
// Go's corrected value's pattern, the defect, the owner's decision and the
// unit test that proves the corrected behaviour. A tool accepts a difference
// ONLY when it matches an entry exactly, and reports it as intended; any
// other difference still fails the run.
package parity

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"
)

// The tools a difference can come from.
const (
	ToolPage          = "page"          // cmd/parity -screen page: Where is the page path
	ToolProfile       = "profile"       // cmd/parity -screen profile: Where is the tab and year asked
	ToolNavigation    = "navigation"    // cmd/parity -screen navigation: Where is "navigation"
	ToolDirectory     = "directory"     // cmd/parity -screen directory: Where is "directory"
	ToolNotifications = "notifications" // cmd/notificationparity: Where is "/notifications"
	ToolShadow        = "shadow"        // cmd/shadow: Where is the scenario, Question the table, Field the column
)

var tools = []string{ToolPage, ToolProfile, ToolNavigation, ToolDirectory, ToolNotifications, ToolShadow}

// AnyQuestion, as an entry's only question, matches every question on its
// page: for a fix whose difference shows wherever the page opens on a given
// state (the period in use, say). The field and both values must still match
// exactly, and the entry's patterns should be as narrow as the defect.
const AnyQuestion = "*"

// ErrorField is the field a difference in whether (or how) a side refused
// or failed is reported under; its values are the errors as text, "<nil>"
// for a side that answered.
const ErrorField = "error"

//go:embed intended.json
var checkedIn []byte

// Entry is one intended difference.
type Entry struct {
	// ID names the entry in a tool's output ("calendar-today-evening").
	ID string `json:"id"`
	// Tool is the comparison that sees it (ToolPage …).
	Tool string `json:"tool"`
	// Where is the page path, profile tab, or save scenario, exactly as the
	// tool names it.
	Where string `json:"where"`
	// Questions are the questions (a page's query as the tool prints it,
	// "(as it opens)" for none; a profile's school id; a shadow table)
	// the difference shows on, each exactly.
	Questions []string `json:"questions"`
	// Fields are the field paths (".blocks[2].filters[0].options[1].selected",
	// a shadow column), each exactly.
	Fields []string `json:"fields"`
	// Existing and Go are the two values' patterns: regular expressions
	// that must match the whole value as text.
	Existing string `json:"existing"`
	Go       string `json:"go"`
	// Relation, instead of the two patterns, names how Go's value must
	// follow from the existing one: "deduplicated" (a JSON list, Go's is the
	// existing list with its repeats removed, first-seen order). The
	// existing value must actually hold a repeat.
	Relation string `json:"relation,omitempty"`
	// Defect is what is wrong in the existing application; Decision is the
	// owner's decision (quoted, dated); Test is the unit test proving Go's
	// corrected behaviour, as "<package dir>.<TestName>"
	// ("internal/calendarpage.TestTodayIsTheKampalaDay").
	Defect   string `json:"defect"`
	Decision string `json:"decision"`
	Test     string `json:"test"`

	existing, goValue *regexp.Regexp
}

// Answer is the one answer a difference belongs to.
type Answer struct {
	Tool, Where, Question string
}

// Diff is one difference the tool found.
type Diff struct {
	// Field is the field path; Go and Existing the two values as text.
	Field, Go, Existing string
	// Text is the line the tool prints for it.
	Text string
}

// Accepted is a difference an entry accepts.
type Accepted struct {
	Diff
	Entry string
}

// List is a checked set of entries.
type List struct {
	entries []Entry
}

// Load reads and checks a list: every field present, tools known, patterns
// that compile and differ, ids unique.
func Load(raw []byte) (*List, error) {
	var entries []Entry
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&entries); err != nil {
		return nil, fmt.Errorf("intended differences: %w", err)
	}
	seen := map[string]bool{}
	for i := range entries {
		e := &entries[i]
		if err := e.check(); err != nil {
			return nil, fmt.Errorf("intended difference %d (%q): %w", i+1, e.ID, err)
		}
		if seen[e.ID] {
			return nil, fmt.Errorf("intended difference %q is listed twice", e.ID)
		}
		seen[e.ID] = true
	}
	return &List{entries: entries}, nil
}

// CheckedIn is the list in intended.json.
func CheckedIn() (*List, error) { return Load(checkedIn) }

// Entries are the list's entries, in file order.
func (l *List) Entries() []Entry { return slices.Clone(l.entries) }

func (e *Entry) check() error {
	missing := []string{}
	required := map[string]string{
		"id": e.ID, "tool": e.Tool, "where": e.Where,
		"defect": e.Defect, "decision": e.Decision, "test": e.Test,
	}
	if e.Relation == "" {
		required["existing"], required["go"] = e.Existing, e.Go
	}
	for name, value := range required {
		if strings.TrimSpace(value) == "" {
			missing = append(missing, name)
		}
	}
	if len(e.Questions) == 0 || slices.Contains(e.Questions, "") {
		missing = append(missing, "questions")
	}
	if len(e.Fields) == 0 || slices.Contains(e.Fields, "") {
		missing = append(missing, "fields")
	}
	if len(missing) > 0 {
		slices.Sort(missing)
		return errors.New("missing " + strings.Join(missing, ", "))
	}
	if !slices.Contains(tools, e.Tool) {
		return fmt.Errorf("unknown tool %q (one of %s)", e.Tool, strings.Join(tools, ", "))
	}
	if e.Relation != "" {
		if _, known := relations[e.Relation]; !known {
			return fmt.Errorf("unknown relation %q", e.Relation)
		}
		if e.Existing != "" || e.Go != "" {
			return errors.New("an entry has a relation or two patterns, not both")
		}
		if !strings.Contains(e.Test, ".Test") {
			return fmt.Errorf("test %q is not <package dir>.<TestName>", e.Test)
		}
		return nil
	}
	if e.Existing == e.Go {
		return errors.New("the existing and go patterns are the same: that is not a difference")
	}
	if !strings.Contains(e.Test, ".Test") {
		return fmt.Errorf("test %q is not <package dir>.<TestName>", e.Test)
	}
	var err error
	if e.existing, err = whole(e.Existing); err != nil {
		return fmt.Errorf("existing pattern: %w", err)
	}
	if e.goValue, err = whole(e.Go); err != nil {
		return fmt.Errorf("go pattern: %w", err)
	}
	return nil
}

// whole compiles a pattern that must match the whole value.
func whole(pattern string) (*regexp.Regexp, error) {
	return regexp.Compile(`\A(?:` + pattern + `)\z`)
}

// TestPackage and TestName split Test ("internal/x.TestY").
func (e Entry) TestPackage() string { return e.Test[:strings.LastIndex(e.Test, ".Test")] }

// TestName is the unit test's function name.
func (e Entry) TestName() string { return e.Test[strings.LastIndex(e.Test, ".Test")+1:] }

// Match is the entry that accepts d in answer a: the same tool, where,
// one of its questions and one of its fields exactly, the existing value
// matching its existing pattern and Go's its go pattern, each whole.
func (l *List) Match(a Answer, d Diff) (Entry, bool) {
	if l == nil {
		return Entry{}, false
	}
	for _, e := range l.entries {
		if e.Tool == a.Tool && e.Where == a.Where &&
			(slices.Contains(e.Questions, a.Question) || slices.Equal(e.Questions, []string{AnyQuestion})) &&
			slices.Contains(e.Fields, d.Field) && e.values(d) {
			return e, true
		}
	}
	return Entry{}, false
}

// Split sets aside the differences an entry accepts; the rest still fail.
func (l *List) Split(a Answer, diffs []Diff) (unexpected []Diff, intended []Accepted) {
	for _, d := range diffs {
		if e, ok := l.Match(a, d); ok {
			intended = append(intended, Accepted{Diff: d, Entry: e.ID})
			continue
		}
		unexpected = append(unexpected, d)
	}
	return unexpected, intended
}

// Lines are the differences' printed lines, sorted, at most limit of them
// and then "… and N more".
func Lines(diffs []Diff, limit int) string {
	lines := make([]string, 0, len(diffs))
	for _, d := range diffs {
		lines = append(lines, d.Text)
	}
	slices.Sort(lines)
	if len(lines) > limit {
		lines = append(lines[:limit], fmt.Sprintf("… and %d more", len(lines)-limit))
	}
	return strings.Join(lines, "\n")
}

// IntendedLines are the accepted differences' lines, each marked with the
// entry that accepts it.
func IntendedLines(accepted []Accepted) string {
	lines := make([]string, 0, len(accepted))
	for _, a := range accepted {
		lines = append(lines, "  intended ("+a.Entry+"):"+strings.TrimPrefix(a.Text, " "))
	}
	slices.Sort(lines)
	return strings.Join(lines, "\n")
}

// values says whether a difference's two values are the entry's: by its
// relation, or each matching its pattern whole.
func (e Entry) values(d Diff) bool {
	if e.Relation != "" {
		return relations[e.Relation](d.Existing, d.Go)
	}
	return e.existing.MatchString(d.Existing) && e.goValue.MatchString(d.Go)
}

// relations are the ways an entry may say Go's value follows from the
// existing one.
var relations = map[string]func(existing, goValue string) bool{
	"deduplicated": deduplicated,
}

// deduplicated: both are JSON lists, the existing one holds a repeat, and
// Go's is it with every repeat removed, in first-seen order.
func deduplicated(existing, goValue string) bool {
	var old, mine []any
	if json.Unmarshal([]byte(existing), &old) != nil || json.Unmarshal([]byte(goValue), &mine) != nil {
		return false
	}
	want := []any{}
	seen := map[string]bool{}
	for _, v := range old {
		key, _ := json.Marshal(v)
		if !seen[string(key)] {
			seen[string(key)] = true
			want = append(want, v)
		}
	}
	if len(want) == len(old) {
		return false
	}
	a, _ := json.Marshal(want)
	b, _ := json.Marshal(mine)
	return string(a) == string(b)
}
