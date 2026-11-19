package schoolprofile

import (
	"math/big"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// kpi is one figure of a strip as the page's {% kpi_metric %} writes it.
type kpi struct {
	label, value, link, helper string
}

// The line under a KPI (apps.core.metrics.payload.brief_helper): a short
// second figure, or nothing; the whole sentence goes to the note.
var (
	helperClauses  = regexp.MustCompile(`\s+[·—–|]\s+|;\s+`)
	helperFigure   = regexp.MustCompile(`(?i)^(?:of\s+|about\s+|≈\s*|~\s*|UGX\s+)?[+\-−]?\d`)
	helperQuantity = regexp.MustCompile(`(?i)^(?:of\s+|about\s+|≈\s*|~\s*|UGX\s+)?[+\-−]?\d[\d,.]*%?(?:\s+of\s+\d[\d,.]*)?(?:\s+[A-Za-z][\w'’-]*)?`)
	helperBrackets = regexp.MustCompile(`\s*\([^)]*\)`)
)

func briefHelper(helper string) string {
	text := strings.Join(strings.Fields(helper), " ")
	if text == "" || !helperFigure.MatchString(text) {
		return ""
	}
	kept := ""
	for _, clause := range helperClauses.Split(text, -1) {
		clause = strings.Trim(helperBrackets.ReplaceAllString(clause, ""), " .,")
		joined := clause
		if kept != "" {
			joined = kept + " · " + clause
		}
		if utf8.RuneCountInString(joined) > rules.Engine.HelperFigureChars {
			break
		}
		kept = joined
	}
	if kept != "" {
		return kept
	}
	return strings.TrimSpace(helperQuantity.FindString(text))
}

// interventionNames matches an intervention's full name, longest first
// (apps.core.interventions._LABEL_PATTERN).
var interventionNames = func() *regexp.Regexp {
	labels := []string{}
	for _, l := range rules.SSAInterventions {
		labels = append(labels, l)
	}
	sort.SliceStable(labels, func(i, j int) bool { return len(labels[i]) > len(labels[j]) })
	quoted := []string{}
	for _, l := range labels {
		quoted = append(quoted, regexp.QuoteMeta(l))
	}
	return regexp.MustCompile("(?i)" + strings.Join(quoted, "|"))
}()

func abbreviate(text string) string {
	byLower := map[string]string{}
	for code, l := range rules.SSAInterventions {
		byLower[strings.ToLower(l)] = rules.Engine.InterventionAbbreviations[code]
	}
	return interventionNames.ReplaceAllStringFunc(text, func(m string) string { return byLower[strings.ToLower(m)] })
}

// strip is {% kpi_strip %} as the page blocks read it: each figure once (by
// its label), the line under it cut to a second figure and the sentence it
// was kept as the note (kpi_metrics.professional_kpis).
func strip(title string, figures ...kpi) *screensv1.PageBlock {
	seen := map[string]bool{}
	metrics := []*screensv1.PageMetric{}
	for _, f := range figures {
		key := strings.ToLower(strings.TrimSpace(f.label))
		if f.label == "" || seen[key] {
			continue
		}
		seen[key] = true
		helper, note := helperAndNote(f.helper)
		value := f.value
		if value == "" {
			value = "—"
		}
		if interventionNames.MatchString(value) {
			value = abbreviate(value)
		} else {
			value = compactMoney(value)
		}
		metrics = append(metrics, &screensv1.PageMetric{Label: f.label, Value: value, Helper: helper, Note: note, Href: f.link})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: title, Metrics: metrics}}}
}

// ── Record tables (partials/profiles/_records.html) ─────────────────────────

// cell is profile_records.cell: a value, its link and tone, and how it is
// written ("num", "opt", "date", "score", "change" or text).
type cell struct {
	text, href, tone string
	strong           bool
}

func textCell(text, href string) cell {
	if text == "" {
		text = "—"
	}
	return cell{text: text, href: href}
}

// optCell is an optional figure: a dash where none was recorded.
func optCell(n *int, tone string) cell {
	if n == nil {
		return cell{text: "—", tone: tone}
	}
	return cell{text: intcomma(*n), tone: tone}
}

// recordTable is one table of records: its title, the summary under it,
// its columns (label, numeric), rows, and the note under it.
type recordTable struct {
	title, summary, footer, empty string
	columns                       [][2]string
	rows                          [][]cell
}

// maxRows is a table page (TABLE_PAGE_SIZE); a longer table is paged on
// the web and is not answered here.
const maxRows = 50

func (t recordTable) block() *screensv1.PageBlock {
	table := &screensv1.PageTable{Title: t.title, Subtitle: t.summary, Columns: []*screensv1.PageColumn{}, Rows: []*screensv1.PageRow{}}
	if len(t.rows) == 0 {
		table.EmptyMessage = t.empty
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
	}
	for _, c := range t.columns {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: c[0], Numeric: c[1] == "num"})
	}
	for _, row := range t.rows {
		cells := []*screensv1.PageCell{}
		for _, c := range row {
			cells = append(cells, &screensv1.PageCell{Text: c.text, Href: c.href, Tone: c.tone, Strong: c.strong})
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: cells})
	}
	table.Footnote = t.footer
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
}

// recordsSummary is the line under a records table: "3 records · FY 2026/27".
func recordsSummary(n int, l lens) string {
	s := intcomma(n) + " record" + plural(n) + " · " + fyLabel(l.fy)
	if l.window.label != "" {
		s += " · " + l.window.label
	}
	return s
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// intcomma is Django's |intcomma of an integer.
func intcomma(n int) string {
	s := itoa(n)
	negative := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if negative {
		return "-" + s
	}
	return s
}

// score is partials/profiles/_score.html: two places, or a dash.
func score(v *float64) string {
	if v == nil {
		return "—"
	}
	return twoPlaces(*v)
}

// moneyValue is a figure in a currency, as kpi_metrics.kpi_value reads one.
var moneyValue = regexp.MustCompile(`^(UGX|USD|EUR|GBP|KES|TZS|RWF)\s+(-?\d[\d,]*(?:\.\d+)?)$`)

// compactMoney is kpi_metrics.kpi_value: a currency figure of a million or
// more shown in millions (billions, trillions) to two places, trailing zeros
// dropped, rounded as Python's Decimal rounds (half to even).
func compactMoney(value string) string {
	m := moneyValue.FindStringSubmatch(value)
	if m == nil {
		return value
	}
	amount, ok := new(big.Rat).SetString(strings.ReplaceAll(m[2], ",", ""))
	if !ok {
		return value
	}
	for _, unit := range []struct {
		divisor int64
		suffix  string
	}{{1_000_000_000_000, "T"}, {1_000_000_000, "B"}, {1_000_000, "M"}} {
		d := big.NewRat(unit.divisor, 1)
		if new(big.Rat).Abs(amount).Cmp(d) < 0 {
			continue
		}
		hundredths := new(big.Rat).Mul(new(big.Rat).Quo(amount, d), big.NewRat(100, 1))
		short := halfEven(hundredths)
		text := new(big.Rat).SetFrac(short, big.NewInt(100)).FloatString(2)
		text = strings.TrimRight(strings.TrimRight(text, "0"), ".")
		return m[1] + " " + text + unit.suffix
	}
	return value
}

// halfEven rounds a rational to the nearest integer, a half to the even one.
func halfEven(r *big.Rat) *big.Int {
	floor := new(big.Int).Div(r.Num(), r.Denom()) // Euclidean: floor for a positive denominator
	rest := new(big.Rat).Sub(r, new(big.Rat).SetInt(floor))
	switch rest.Cmp(big.NewRat(1, 2)) {
	case 1:
		return floor.Add(floor, big.NewInt(1))
	case 0:
		if floor.Bit(0) == 1 {
			return floor.Add(floor, big.NewInt(1))
		}
	}
	return floor
}

// StripFigure is one figure of a strip, for a page outside the profile
// (internal/clusterpage) that writes its strip the same way.
type StripFigure struct {
	Label, Value, Link, Helper string
}

// Strip is a strip as the page blocks read it (see strip).
func Strip(title string, figures []StripFigure) *screensv1.PageBlock {
	kpis := make([]kpi, len(figures))
	for i, f := range figures {
		kpis[i] = kpi{label: f.Label, value: f.Value, link: f.Link, helper: f.Helper}
	}
	return strip(title, kpis...)
}

// BriefHelper is apps.core.metrics.payload.brief_helper, for the other pages
// whose context figures are drawn by components/context_metrics.html.
func BriefHelper(helper string) string { return briefHelper(helper) }

// HelperAndNote is a figure's line under it as components/context_metrics.html
// draws it: an intervention's name shortened to its code, kept whole when
// that is short enough, else cut to a second figure (BriefHelper) with the
// sentence kept as the note.
func HelperAndNote(helper string) (string, string) { return helperAndNote(helper) }

func helperAndNote(full string) (helper, note string) {
	helper, exact := full, ""
	if interventionNames.MatchString(helper) {
		exact = helper
		helper = abbreviate(helper)
	}
	if helper != "" && !(exact != "" && utf8.RuneCountInString(helper) <= rules.Engine.HelperFigureChars) {
		if brief := briefHelper(helper); brief != helper {
			note = exact
			if note == "" {
				note = full
			}
			helper = brief
		}
	}
	return helper, note
}

// CompactMoney is kpi_metrics.kpi_value's figure as a strip shows it ("UGX
// 1.23M" for a million or more), for the other pages whose figures are drawn
// by components/context_metrics.html.
func CompactMoney(value string) string { return compactMoney(value) }
