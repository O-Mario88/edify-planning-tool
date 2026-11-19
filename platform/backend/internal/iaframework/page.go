// Package iaframework is Impact Assessment's Measurement Framework
// (/ia/framework/): its tiles and four registers — outcome areas,
// indicators, measurement rules and loan purposes — as the existing page
// draws them (apps.frontend.views.ia_framework_views over
// apps.impact.framework, pages/ia/framework.html and
// partials/ia/framework_register.html) and the app's feed reads them.
// Drafting, submitting and reviewing stay with the existing application.
//
// The doors, labels and filters are exported to rules.json by
// `manage.py export_ia_framework_rules`;
// apps/impact/test_ia_framework_rules_export.py fails when the two differ.
package iaframework

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/ia/framework/"

const pageParam = "register_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page   bool               `json:"page"`
		Strip  *decisionlog.Strip `json:"strip"`
		Author bool               `json:"author"`
		// Mapping opens the read-only Measurement Rules register;
		// FrameworkReader is sent on to the framework's rules instead.
		Mapping         bool `json:"mapping"`
		FrameworkReader bool `json:"framework_reader"`
	} `json:"roles"`
	Tabs                      [][2]string       `json:"tabs"`
	DefinitionStatuses        [][2]string       `json:"definition_statuses"`
	PendingDefinitionStatuses []string          `json:"pending_definition_statuses"`
	MappingStatuses           map[string]string `json:"mapping_statuses"`
	PendingMappingStatuses    []string          `json:"pending_mapping_statuses"`
	Directions                map[string]string `json:"directions"`
	Levels                    map[string]string `json:"levels"`
	Sources                   map[string]string `json:"sources"`
	MachineAuthors            []string          `json:"machine_authors"`
	ReferenceDefaultLabel     string            `json:"reference_default_label"`
	RuleStatusFilters         [][2]string       `json:"rule_status_filters"`
	LoanPurposeKeyPrefix      string            `json:"loan_purpose_key_prefix"`
	ProposedAreaCodes         []string          `json:"proposed_area_codes"`
	InterventionLabels        map[string]string `json:"intervention_labels"`
	InterventionAbbreviations map[string]string `json:"intervention_abbreviations"`
	IARole                    string            `json:"ia_role"`
	CDRole                    string            `json:"cd_role"`
	PageSize                  int               `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Tabs) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("iaframework: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the framework from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the framework over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// reader is who reads the page: their account, their People record's
// country and whether they may author definitions.
type reader struct {
	id, role, country string
	author            bool
}

// tab is one register as the page draws it.
type tab struct {
	description string
	notice      string
	// noticeTone is the notice's tone as the feed reads it: only the notice
	// that holds a form (the proposed areas) carries its data-tone through.
	noticeTone string
	actions    []*screensv1.PageAction
	title      string
	filters    []*screensv1.PageFilter
	columns    []string
	rows       [][]*screensv1.PageCell
	emptyTitle string
	emptyBody  string
}

// Build answers Path and the read-only Measurement Rules register.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == MappingPath {
		role := rules.Roles[p.ActiveRole]
		if !role.Mapping {
			return nil, true, pagegate.ErrNotAvailable
		}
		if role.FrameworkReader {
			return nil, false, nil // redirected to the framework's rules
		}
		return s.mappingPage(ctx, query)
	}
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	r := reader{id: p.UserID, role: p.ActiveRole, author: role.Author}
	err := s.db.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&r.country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, true, fmt.Errorf("iaframework: reading the reader's country: %w", err)
	}
	r.country = strings.TrimSpace(r.country)
	key := query.Get("tab")
	known := false
	for _, t := range rules.Tabs {
		known = known || t[0] == key
	}
	if !known {
		key = "areas"
	}
	counts, err := s.counts(ctx)
	if err != nil {
		return nil, true, err
	}
	res := &resolver{db: s.db, r: r, officers: map[string][]string{}}
	var t tab
	switch key {
	case "indicators":
		t, err = s.indicatorsTab(ctx, r, res, query.Get("status"))
	case "rules":
		t, err = s.rulesTab(ctx, r, res, query.Get("programme"), query.Get("status"))
	case "purposes":
		t, err = s.purposesTab(ctx, r, res)
	default:
		t, err = s.areasTab(ctx, r, res, query.Get("status"))
	}
	if err != nil {
		return nil, true, err
	}
	return page(role.Strip, key, counts, t, query), true, nil
}

// counts is framework_counts.
func (s *Service) counts(ctx context.Context) ([5]int, error) {
	var c [5]int
	err := s.db.QueryRow(ctx, `
WITH items AS (SELECT id FROM activity_catalogue_item WHERE status = 'active' AND (requires_school OR cluster_delivery_allowed OR is_training_course)),
published AS (SELECT follow_up_min_days, follow_up_expected_days, follow_up_max_days FROM activity_intervention_mapping
           WHERE active AND status = 'published' AND NOT COALESCE(not_ssa_measured_reason > '', FALSE))
SELECT (SELECT count(*) FROM items WHERE id NOT IN (SELECT catalogue_item_id FROM activity_intervention_mapping WHERE active AND is_primary)),
  (SELECT count(*) FROM published),
  (SELECT count(*) FROM published WHERE follow_up_min_days IS NULL AND follow_up_expected_days IS NULL AND follow_up_max_days IS NULL),
  (SELECT count(*) FROM impact_indicator_definition WHERE status = 'approved' AND key NOT LIKE $1 || '%'),
  (SELECT count(*) FROM bt_loan_purpose WHERE active AND NOT measurement_profile_complete)`, rules.LoanPurposeKeyPrefix).Scan(&c[0], &c[1], &c[2], &c[3], &c[4])
	if err != nil {
		return c, fmt.Errorf("iaframework: counting the framework: %w", err)
	}
	return c, nil
}

// resolver is framework.ReviewerResolver: whether the reader may review a
// record an author wrote in a country — a second IA officer of that
// country, or its Country Director where there is no other officer.
type resolver struct {
	db       schooldirectory.Querier
	r        reader
	officers map[string][]string
}

func (v *resolver) may(ctx context.Context, author, country string) (bool, error) {
	if v.r.id == "" || v.r.id == author {
		return false, nil
	}
	country = strings.TrimSpace(country)
	if country != "" && v.r.country != country {
		return false, nil
	}
	switch v.r.role {
	case rules.IARole:
		return true, nil
	case rules.CDRole:
		ids, ok := v.officers[country]
		if !ok {
			if country != "" {
				rows, err := v.db.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.roles @> ARRAY[$1]::varchar[] AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2 AND sp.deleted_at IS NULL`, rules.IARole, country)
				if err != nil {
					return false, fmt.Errorf("iaframework: reading the country's officers: %w", err)
				}
				if ids, err = pgx.CollectRows(rows, pgx.RowTo[string]); err != nil {
					return false, fmt.Errorf("iaframework: reading the country's officers: %w", err)
				}
			}
			v.officers[country] = ids
		}
		for _, id := range ids {
			if id != author {
				return false, nil
			}
		}
		return true, nil
	}
	return false, nil
}

func text(t string, tone string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}, Tone: tone}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// page is pages/ia/framework.html as the feed reads it.
func page(strip *decisionlog.Strip, key string, counts [5]int, t tab, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Framework & strategy", Title: "Measurement Framework",
		Description: "What success means in partner schools, and how each programme step is judged: from counting activities to measuring lasting change.",
		Actions:     t.actions}
	blocks := []*screensv1.PageBlock{}
	if strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: strip.Label, Scrolls: strip.Scrolls}
		for _, x := range strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: x.Label, Href: x.Href, Active: x.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Measurement framework at a glance", Metrics: []*screensv1.PageMetric{
		{Label: "Activities Without a Measurement Rule", Value: strconv.Itoa(counts[0]), Note: "school-outcome activities with no live rule"},
		{Label: "Measurement Rules Published", Value: strconv.Itoa(counts[1]), Note: "reviewed by a second person"},
		{Label: "Published Rules Without a Follow-up Window", Value: strconv.Itoa(counts[2]), Note: "judged on any later reading"},
		{Label: "Indicators Approved", Value: strconv.Itoa(counts[3]), Note: "current approved definitions"},
		{Label: "Loan Purposes Without Measurement", Value: strconv.Itoa(counts[4]), Note: "active purposes with no measurement profile"},
	}}}})
	rail := &screensv1.PageLinkTabs{Scrolls: true}
	for _, x := range rules.Tabs {
		rail.Tabs = append(rail.Tabs, &screensv1.PageLinkTab{Label: x[1], Href: Path + "?tab=" + x[0], Active: x[0] == key})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: rail}}, panel("", text(t.description, "")))
	if t.notice != "" {
		blocks = append(blocks, panel("", text(t.notice, t.noticeTone)))
	}
	blocks = append(blocks, panel(t.title))
	if t.filters != nil {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
			Filters: t.filters, Hidden: map[string]string{"tab": key}}}})
	}
	table := &screensv1.PageTable{}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(t.rows), rules.PageSize)
	if len(t.rows) == 0 {
		table.EmptyMessage = t.emptyTitle
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: t.emptyTitle + " " + t.emptyBody}}}}
	} else {
		for _, c := range append(append([]string{}, t.columns...), "") {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: c})
		}
		for _, cells := range t.rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(t.rows))] {
			table.Rows = append(table.Rows, &screensv1.PageRow{Cells: cells})
		}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(t.rows), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

// cell is _cell: a dash for nothing.
func cell(t string) *screensv1.PageCell {
	if t == "" {
		t = "—"
	}
	return &screensv1.PageCell{Text: closedschools.Collapse(t)}
}

// actions are a row's drawer buttons, in the last cell, which has no words.
func actions(pairs ...[2]string) *screensv1.PageCell {
	c := &screensv1.PageCell{}
	for _, a := range pairs {
		c.Actions = append(c.Actions, &screensv1.PageAction{Key: "button", Label: a[0], Primary: true, Enabled: true, Href: a[1], Drawer: true})
	}
	return c
}

// choice is a select as the feed reads it: its value only when one of its
// options is chosen.
func choice(name, caption, blank, value string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Caption: caption, Options: []*screensv1.PageFilterOption{{Value: "", Label: blank}}}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if value != "" && o[0] == value {
			f.Value = value
		}
	}
	return f
}
