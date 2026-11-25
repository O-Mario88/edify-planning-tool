package iapages

// A submitted report's frozen evidence on its page
// (impact_report_views._evidence_tables): the summary, school change by
// outcome area, the project enrolments and the approved findings, read
// from the snapshot as it was stored.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// figure is the feed reader's FIGURE: a value a label line pairs with.
var figure = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)

var pagerCaption = regexp.MustCompile(`^Showing\s+\d`)

// paired is the feed reader's _paired over a panel's lines: a label line
// followed by its figure becomes one of the panel's data rows, consecutive
// rows sharing one list.
func paired(lines []string) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	for i := 0; i < len(lines); i++ {
		line := lines[i]
		if i+1 < len(lines) && !pagerCaption.MatchString(line) && strings.ContainsFunc(line, isLetter) &&
			figure.MatchString(strings.TrimSpace(lines[i+1])) {
			r := &screensv1.PageDataRow{Label: line, Value: strings.TrimSpace(lines[i+1])}
			if n := len(out); n > 0 && out[n-1].GetRows() != nil {
				out[n-1].GetRows().Rows = append(out[n-1].GetRows().Rows, r)
			} else {
				out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{r}}}})
			}
			i++
			continue
		}
		out = append(out, text(line))
	}
	return out
}

func isLetter(r rune) bool {
	return (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || r > 127 && strings.ToUpper(string(r)) != strings.ToLower(string(r))
}

// jsonValue is a stored snapshot read with its numbers as written.
type jsonValue = any

func obj(v jsonValue) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func list(v jsonValue) []any {
	l, _ := v.([]any)
	return l
}

// pyStr is Python's str() of a value read from the snapshot.
func pyStr(v jsonValue) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case json.Number:
		return x.String()
	case string:
		return x
	}
	return fmt.Sprint(v)
}

// orZero is d.get(key, 0) written as Python writes it.
func orZero(m map[string]any, key string) string {
	v, ok := m[key]
	if !ok {
		return "0"
	}
	return pyStr(v)
}

// truthy is Python truthiness of a snapshot value.
func truthy(v jsonValue) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case json.Number:
		f, _ := x.Float64()
		return f != 0
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

// shareText is the view's _share: "Not measured" for none, else n%.
func shareText(v jsonValue) string {
	if v == nil {
		return "Not measured"
	}
	return pyStr(v) + "%"
}

// signedText is the view's _signed: "+0.66", "" for none.
func signedText(v jsonValue) string {
	n, ok := v.(json.Number)
	if !ok {
		if s, isString := v.(string); isString && s != "" {
			return s
		}
		return ""
	}
	f, err := n.Float64()
	if err != nil {
		return n.String()
	}
	return fmt.Sprintf("%+.2f", f)
}

func labelOf(v jsonValue, fallback string) string {
	if l, ok := obj(v)["label"].(string); ok {
		return l
	}
	return fallback
}

// frozenTable is _table over rows: a page of them under its title, its pager
// after it.
func frozenTable(reportTitle, title, param string, columns []string, rows [][]string, empty, body string, query url.Values) []*screensv1.PageBlock {
	blocks := []*screensv1.PageBlock{titled(title)}
	if len(rows) == 0 {
		return append(blocks, emptyTable(reportTitle, empty, body))
	}
	size := 50
	number, pages := closedschools.PageOf(query.Get(param), len(rows), size)
	t := &screensv1.PageTable{}
	for _, c := range columns {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, r := range rows[(number-1)*size : min(number*size, len(rows))] {
		cells := []*screensv1.PageCell{}
		for _, c := range r {
			cells = append(cells, dashCell(c))
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(param, number, pages, len(rows), size, query, rules.QueryKeysNotPassed))
	}
	return blocks
}

func frozenEvidence(x pageReport, query url.Values) ([]*screensv1.PageBlock, error) {
	d := json.NewDecoder(bytes.NewReader(x.snapshot))
	d.UseNumber()
	var snapshot map[string]any
	if err := d.Decode(&snapshot); err != nil {
		return nil, fmt.Errorf("iapages: reading the frozen evidence: %w", err)
	}
	cohort, portfolio, evidence, lending := obj(snapshot["cohort"]), obj(snapshot["portfolio"]), obj(snapshot["evidence"]), obj(snapshot["lending"])
	learning, discipleship, edtech := obj(evidence["learning"]), obj(evidence["discipleship"]), obj(evidence["edtech"])
	school := pyStr(snapshot["portfolio_note"])
	if snapshot["portfolio_note"] == nil {
		school = ""
	}
	if truthy(snapshot["portfolio"]) {
		school = fmt.Sprintf("%s of %s schools, FY%s → FY%s · %s · %s", orZero(portfolio, "measured"), orZero(portfolio, "schools_in_scope"),
			pyStr(portfolio["prev_fy"]), pyStr(portfolio["fy"]), labelOf(portfolio["grade"], ""), strOr(portfolio["rule_label"]))
	}
	versions := []string{}
	for _, m := range list(snapshot["mapping_versions"]) {
		mv := obj(m)
		versions = append(versions, fmt.Sprintf("%s v%s (%s)", pyStr(mv["intervention"]), pyStr(mv["mapping_version"]), pyStr(mv["enrolments"])))
	}
	mapping := strings.Join(versions, ", ")
	if mapping == "" {
		mapping = "No enrolments"
	}
	generated := strOr(snapshot["generated_at"])
	if len([]rune(generated)) > 16 {
		generated = string([]rune(generated)[:16])
	}
	generated = strings.ReplaceAll(generated, "T", " ")
	summary := []string{
		"Project enrolments in the period", orZero(cohort, "total") + " in " + orZero(cohort, "unique_schools") + " schools",
		"Measured enrolments", orZero(cohort, "measured") + " (" + orZero(cohort, "measured_schools") + " schools)",
		"Improved / declined (share of measured)", shareText(cohort["improved_pct"]) + " / " + shareText(cohort["declined_pct"]),
		"Previous FY SSA missing / current FY SSA overdue", orZero(cohort, "baseline_missing") + " / " + orZero(cohort, "overdue"),
		"Enrolments with no date to place in the period", orZero(cohort, "outside_period_undated"),
		"School change across the portfolio", school,
		"Student learning results", fmt.Sprintf("%s class comparisons in %s schools · %s", orZero(learning, "comparisons"),
			orZero(learning, "schools"), labelOf(learning["grade"], "")),
		"Discipleship practice", fmt.Sprintf("%s schools with confirmed records · %s approved change stories", orZero(discipleship, "schools"),
			orZero(discipleship, "stories_approved")),
		"EdTech rollout", fmt.Sprintf("%s confirmed deployments · %s of checked units working", orZero(edtech, "deployments"),
			shareText(edtech["functional_pct"])),
		"Verified loan impact conclusions", strconv.Itoa(len(list(lending["verified_ids"]))),
		"Approved findings cited", strconv.Itoa(len(list(snapshot["findings"]))),
		"Mapping versions", mapping,
		"Evidence frozen", generated + " · sha256 " + x.snapshotHash,
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Section{Section: "Evidence frozen at submission"}},
		titled("", paired(summary)...)}
	change := [][]string{}
	for _, raw := range list(portfolio["rows"]) {
		row := obj(raw)
		n := truthy(row["n"])
		measured := "Not measured"
		if n {
			measured = pyStr(row["n"])
		}
		improved, declined := "—", "—"
		if n {
			improved, declined = shareText(row["improved_pct"]), shareText(row["declined_pct"])
		}
		median := signedText(row["median_change"])
		if median == "" {
			median = "Not measured"
		}
		if truthy(row["withheld"]) {
			median = "n too small"
		}
		change = append(change, []string{strOr(row["name"]), measured, improved, declined, median, labelOf(row["grade"], "Insufficient evidence")})
	}
	blocks = append(blocks, frozenTable(x.title, "School change by outcome area (frozen)", "change_page",
		[]string{"Outcome area / domain", "Schools measured", "Improved", "Declined", "Median change", "Evidence"}, change,
		"Not measured", "No school had two comparable confirmed SSAs when the report was submitted.", query)...)
	schools := [][]string{}
	for _, raw := range list(snapshot["rows"]) {
		row := obj(raw)
		baseline, follow := "Missing", "Missing"
		if row["baseline"] != nil {
			baseline = pyStr(row["baseline"])
		}
		if row["follow_up"] != nil {
			follow = pyStr(row["follow_up"])
		}
		when := strOr(row["follow_up_date"])
		if when == "" {
			when = strOr(row["due"])
		}
		if when == "" {
			when = "Not scheduled"
		}
		mapping := ""
		if truthy(row["mapping_version"]) {
			mapping = "v" + pyStr(row["mapping_version"])
		}
		schools = append(schools, []string{strOr(row["school"]), strOr(row["project"]), strOr(row["intervention"]),
			baseline + " → " + follow, strOr(row["status"]), when, mapping})
	}
	blocks = append(blocks, frozenTable(x.title, "Project enrolments (frozen)", "schools_page",
		[]string{"School", "Project", "Domain", "SSA scores", "Evidence", "Follow-up", "Mapping"}, schools,
		"No project enrolments", "The period and project chosen held no enrolments.", query)...)
	findings := [][]string{}
	for _, raw := range list(snapshot["findings"]) {
		f := obj(raw)
		findings = append(findings, []string{strOr(f["statement"]), strOr(f["programme"]), strOr(f["evidence"]), strOr(f["limitations"])})
	}
	blocks = append(blocks, frozenTable(x.title, "Approved findings cited", "findings_page",
		[]string{"Approved finding", "Programme", "Evidence", "Limitations"}, findings,
		"No approved findings", "No finding of these programmes was approved in the period.", query)...)
	if limitation := strOr(snapshot["limitation"]); limitation != "" {
		blocks = append(blocks, titled("", text(limitation)))
	}
	return blocks, nil
}

// strOr is a snapshot string, "" for none.
func strOr(v jsonValue) string {
	if v == nil {
		return ""
	}
	return pyStr(v)
}
