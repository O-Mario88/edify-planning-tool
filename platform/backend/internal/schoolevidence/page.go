// Package schoolevidence is Impact Assessment's School Evidence
// (/ia/school-evidence/, ia_school_evidence_views.school_evidence_page,
// pages/ia/school_evidence.html): the figures over every kind of evidence in
// the reader's scope, then a register tab. Go builds the Learning results
// tab: the year-on-year comparison of confirmed class results
// (evidence_services.learning_summary) and the register of results, newest
// first, each with who recorded it and whether the reader may verify it.
// The Discipleship and EdTech tabs, and a link that opens a record's drawer
// (?open=), are handed on; every save stays with the existing application.
//
// The rules are exported to rules.json by `manage.py
// export_school_evidence_rules`; apps/activities/
// test_school_evidence_rules_export.py fails when the two differ.
package schoolevidence

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Path is the page.
const Path = "/ia/school-evidence/"

const (
	learning     = "learning"
	discipleship = "discipleship"
	// pageSize is the register's database page and the summary's list page
	// (ia_collection.PAGE_SIZE, TABLE_PAGE_SIZE).
	pageSize = 50
	// firstFY is the year the page's choices start after (int(o) > 2025).
	firstFY = 2025
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page   bool               `json:"page"`
		Record bool               `json:"record"`
		Strip  *decisionlog.Strip `json:"strip"`
	} `json:"roles"`
	Tabs              [][2]string       `json:"tabs"`
	Statuses          [][2]string       `json:"statuses"`
	StatusTones       map[string]string `json:"status_tones"`
	AssessmentTypes   [][2]string       `json:"assessment_types"`
	AssetTypes        [][2]string       `json:"asset_types"`
	Funding           [][2]string       `json:"funding"`
	MinLearners       int               `json:"min_learners"`
	LearningRuleLabel string            `json:"learning_rule_label"`
	MetricLabels      map[string]string `json:"metric_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Tabs) == 0 || len(r.Statuses) == 0 || len(r.AssetTypes) == 0 || r.MinLearners <= 0 {
		panic(fmt.Sprintf("schoolevidence: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("schoolevidence: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

func label(choices [][2]string, value string) string {
	for _, c := range choices {
		if c[0] == value {
			return c[1]
		}
	}
	return value
}

// Build answers Path for the Learning results tab; any other tab, and a
// link that opens a record, are passed on.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role := rules.Roles[p.ActiveRole]
	if !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	tab := query.Get("tab")
	known := false
	for _, t := range rules.Tabs {
		known = known || t[0] == tab
	}
	if !known {
		tab = learning
	}
	if query.Get("open") != "" {
		return nil, false, nil
	}
	resp, err := s.page(ctx, p, tab, query)
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

// reader is everything the page is built from.
type reader struct {
	p        auth.Principal
	schools  string // a WHERE clause on school `s`
	args     []any
	fy       string
	status   string
	subject  string
	reviewer *iaframework.Reviewer
	scope    schooldirectory.Scope
}

// tabContent is what a register tab hands the page: its words, its record
// button, its own filters, whether it offers the CSV upload, and its tables.
type tabContent struct {
	description         string
	recordLabel, record string
	filters             []*screensv1.PageFilter
	upload              bool
	tables              []*screensv1.PageBlock
}

func (s *Service) page(ctx context.Context, p auth.Principal, tab string, query url.Values) (*screensv1.GetPageResponse, error) {
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: resolving the reader's scope: %w", err)
	}
	r := &reader{p: p, scope: scope}
	if scope.SummaryOnly {
		r.schools = "false" // evidence_schools: nothing for a summary-only reader
	} else {
		r.schools = schooldirectory.AnalyticsReach(scope, &r.args)
	}
	choices := []string{}
	for _, o := range schooldirectory.FYOptions(now) {
		if n, err := strconv.Atoi(o); err == nil && n > firstFY {
			choices = append(choices, o)
		}
	}
	if len(choices) == 0 {
		choices = schooldirectory.FYOptions(now)
	}
	r.fy = query.Get("fy")
	if !contains(choices, r.fy) {
		r.fy = schooldirectory.OperationalFY(now)
	}
	r.status = query.Get("status")
	if label(rules.Statuses, r.status) == r.status {
		r.status = "" // not one of the states
	}
	if r.reviewer, err = iaframework.NewReviewer(ctx, s.db, p); err != nil {
		return nil, err
	}
	figures, err := s.figures(ctx, r)
	if err != nil {
		return nil, err
	}
	var c tabContent
	switch tab {
	case learning:
		c, err = s.learningTab(ctx, r, query)
	case discipleship:
		c, err = s.discipleshipTab(ctx, r, query)
	default:
		c, err = s.edtechTab(ctx, r, query)
	}
	if err != nil {
		return nil, err
	}
	role := rules.Roles[p.ActiveRole]
	header := &screensv1.PageHeader{Eyebrow: "Baseline & field data", Title: "School Evidence",
		Description: "Class learning results, discipleship practice and EdTech use in partner schools — recorded by one person, confirmed by another, and only then counted."}
	if role.Record {
		header.Actions = []*screensv1.PageAction{{Key: slug(c.recordLabel), Label: c.recordLabel, Enabled: true,
			Href: Path + c.record + "/new", Drawer: true}}
	}
	blocks := []*screensv1.PageBlock{}
	if st := role.Strip; st != nil {
		tabs := &screensv1.PageLinkTabs{Label: st.Label, Scrolls: st.Scrolls}
		for _, t := range st.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks, figures)
	rail := &screensv1.PageLinkTabs{Scrolls: true}
	for _, t := range rules.Tabs {
		rail.Tabs = append(rail.Tabs, &screensv1.PageLinkTab{Label: t[1], Href: Path + "?tab=" + t[0], Active: t[0] == tab})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: rail}}, panel("", text(c.description)))
	filters := []*screensv1.PageFilter{
		{Name: "fy", Caption: "Financial year", Value: r.fy},
		{Name: "status", Caption: "Status", Value: r.status, Options: []*screensv1.PageFilterOption{{Label: "Every status"}}},
	}
	for _, o := range choices {
		filters[0].Options = append(filters[0].Options, &screensv1.PageFilterOption{Value: o, Label: "FY" + o})
	}
	for _, st := range rules.Statuses {
		filters[1].Options = append(filters[1].Options, &screensv1.PageFilterOption{Value: st[0], Label: st[1]})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: append(filters, c.filters...), Hidden: map[string]string{"tab": tab}}}})
	if c.upload && role.Record {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Title: "Upload class results (CSV)",
			Text:  "One row per class and subject. Every row is checked against schools in your country; a file with any invalid row records nothing and lists the rows to fix. Download the template.",
			Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
				Name: "results_file", Label: "Results file", Kind: "file", Required: true}}}},
			SubmitLabel: "Upload results", Key: Path + "learning/upload"}}})
	}
	blocks = append(blocks, c.tables...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, nil
}

// learningTab is _learning_tab: its subjects to filter by, the comparison
// and the register.
func (s *Service) learningTab(ctx context.Context, r *reader, query url.Values) (tabContent, error) {
	subjects, err := s.subjects(ctx, r)
	if err != nil {
		return tabContent{}, err
	}
	r.subject = strings.TrimSpace(query.Get("subject"))
	if !contains(subjects, r.subject) {
		r.subject = ""
	}
	c := tabContent{recordLabel: "Record learning result", record: learning, upload: true,
		description: "Class-level results — OneTest, national examinations and the school's own assessments — with no pupil names. " +
			"The same class and subject are compared year on year; a side with fewer than " + strconv.Itoa(rules.MinLearners) +
			" learners is withheld. " + rules.LearningRuleLabel + "."}
	if len(subjects) > 0 {
		f := &screensv1.PageFilter{Name: "subject", Caption: "Subject", Value: r.subject, Options: []*screensv1.PageFilterOption{{Label: "Every subject"}}}
		for _, sub := range subjects {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: sub, Label: sub})
		}
		c.filters = append(c.filters, f)
	}
	summary, err := s.summary(ctx, r, query)
	if err != nil {
		return tabContent{}, err
	}
	register, err := s.register(ctx, r, query)
	if err != nil {
		return tabContent{}, err
	}
	c.tables = append(summary, register...)
	return c, nil
}

// slug is the feed's key for a header button: its label in lower case,
// each run of anything but a–z and 0–9 one underscore.
func slug(label string) string {
	var b strings.Builder
	gap := false
	for _, r := range strings.ToLower(label) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			if gap && b.Len() > 0 {
				b.WriteByte('_')
			}
			gap = false
			b.WriteRune(r)
			continue
		}
		gap = true
	}
	return b.String()
}

func contains(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// figures is the page's tiles (evidence_services.counts): what waits to be
// verified and was returned, over every kind, and the schools with
// confirmed learning results, discipleship records and EdTech deployments.
func (s *Service) figures(ctx context.Context, r *reader) (*screensv1.PageBlock, error) {
	type count struct{ pending, confirmed, returned, schools int }
	counts := map[string]count{}
	for _, kind := range [][2]string{{learning, "impact_learning_result"}, {"discipleship", "impact_discipleship_record"},
		{"edtech", "impact_edtech_deployment"}, {"check", "impact_edtech_check"}} {
		var c count
		err := s.db.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE r.verification_status = 'pending'), count(*) FILTER (WHERE r.verification_status = 'confirmed'),
  count(*) FILTER (WHERE r.verification_status = 'returned'), count(DISTINCT r.school_id) FILTER (WHERE r.verification_status = 'confirmed')
FROM `+kind[1]+` r WHERE r.deleted_at IS NULL AND r.school_id IN (SELECT s.id FROM school s WHERE `+r.schools+`)`, r.args...).
			Scan(&c.pending, &c.confirmed, &c.returned, &c.schools)
		if err != nil {
			return nil, fmt.Errorf("schoolevidence: counting the %s records: %w", kind[0], err)
		}
		counts[kind[0]] = c
	}
	var pending, returned int
	for _, c := range counts {
		pending += c.pending
		returned += c.returned
	}
	checks := strconv.Itoa(counts["check"].confirmed) + " confirmed check"
	if counts["check"].confirmed != 1 {
		checks += "s"
	}
	tone := func(n int, when string) string {
		if n > 0 {
			return when
		}
		return "info"
	}
	type tile struct{ label, value, helper, tone string }
	tiles := []tile{
		{"School Evidence Awaiting Verification", strconv.Itoa(pending), "confirmed by someone other than the recorder", tone(pending, "warning")},
		{"Schools With Confirmed Learning Results", strconv.Itoa(counts[learning].schools), "class-level results, any year", "info"},
		{"Schools With Confirmed Discipleship Records", strconv.Itoa(counts["discipleship"].schools), "observed practice, any year", "info"},
		{"Schools With Confirmed EdTech Deployments", strconv.Itoa(counts["edtech"].schools), checks, "info"},
		{"School Evidence Returned for Correction", strconv.Itoa(returned), "waiting for the recorder", tone(returned, "danger")},
	}
	// components/context_metrics.html: the line under a figure cut to a
	// second figure, the sentence kept as the note; the tone only beside a
	// line that stays.
	metrics := []*screensv1.PageMetric{}
	for _, t := range tiles {
		name := t.label
		if l, ok := rules.MetricLabels[name]; ok {
			name = l
		}
		helper, note := schoolprofile.HelperAndNote(t.helper)
		m := &screensv1.PageMetric{Label: name, Value: t.value, Helper: helper, Note: note}
		if helper != "" {
			m.Tone = t.tone
		}
		metrics = append(metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "School evidence at a glance", Metrics: metrics}}}, nil
}

// subjects are the subjects of the reader's learning results, stripped,
// each once, in case-blind order.
func (s *Service) subjects(ctx context.Context, r *reader) ([]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT btrim(l.subject) FROM impact_learning_result l
WHERE l.deleted_at IS NULL AND l.school_id IN (SELECT s.id FROM school s WHERE `+r.schools+`) AND btrim(COALESCE(l.subject, '')) <> ''`, r.args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the subjects: %w", err)
	}
	subjects, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the subjects: %w", err)
	}
	sortSubjects(subjects)
	return subjects, nil
}

// sortSubjects is the existing page's sorted(..., key=lambda s: (s.lower(),
// s)): case-blind, and subjects that differ only in case in code-point order,
// so "English" and "english" come out the same way every time.
func sortSubjects(subjects []string) {
	sort.Slice(subjects, func(i, j int) bool {
		a, b := strings.ToLower(subjects[i]), strings.ToLower(subjects[j])
		if a != b {
			return a < b
		}
		return subjects[i] < subjects[j]
	})
}

// cell is the evidence table's cell: a dash for nothing. The template
// writes a status's tone on a span inside the cell, which the feed does not
// read, so the tone is the view's and not the cell's.
func cell(t, _ string) *screensv1.PageCell {
	if t == "" {
		t = "—"
	}
	return &screensv1.PageCell{Text: closedschools.Collapse(t)}
}

// table is partials/ia/evidence_table.html as the feed reads it: its title,
// then the rows (headed by the first row's headings, and an actions column
// when any row has actions) or the empty state, then its pager.
func table(title string, headings []string, rows [][]*screensv1.PageCell, actions bool, total, number, pages int,
	param, emptyTitle, emptyBody string, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	if len(rows) == 0 {
		t.EmptyMessage = emptyTitle
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: emptyTitle + " " + emptyBody}}}}
	} else {
		for _, h := range headings {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: h})
		}
		if actions {
			t.Columns = append(t.Columns, &screensv1.PageColumn{})
		}
		for _, cells := range rows {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
		}
	}
	out := []*screensv1.PageBlock{panel(title), {Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, total, pageSize, query, nil))
	}
	return out
}
