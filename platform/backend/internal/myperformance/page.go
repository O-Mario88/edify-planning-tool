// Package myperformance is the staff member's Priorities page
// (/my-performance), as the existing page draws it
// (apps.frontend.views.hr_views.my_performance_view and
// pages/hr/my_performance.html) and the app's feed reads it: the
// performance headline, the four tabs (distributed priorities, core values,
// spiritual formation, professional development) and the conversation
// records.
//
// It reads; it never writes. Passed on to the existing page:
//   - a reader with no review in a year that has a performance cycle: the
//     existing page drafts their agreement on that read (owner, 2026-11-14);
//   - a contract longer than one table page;
//   - an officer with guidance from their Programme Lead, a review with
//     conversation snapshots or amendments, a manager whose conversation
//     window is closed, a role shown a section strip, a reader with no People
//     record, and a year the page refuses.
//
// The doors and words are exported to rules.json by `manage.py
// export_my_performance_rules`; apps/hr/test_my_performance_rules_export.py
// fails when the two differ.
package myperformance

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	_ "time/tzdata" // the review's day is Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Path is the page Go answers.
const Path = "/my-performance"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool            `json:"page"`
		Strip json.RawMessage `json:"strip"`
	} `json:"roles"`
	ManagerRoles        []string          `json:"manager_roles"`
	DistributeRoles     []string          `json:"distribute_roles"`
	DistributeTeamRoles []string          `json:"distribute_team_roles"`
	ConfigureRoles      []string          `json:"configure_roles"`
	WindowLabels        map[string]string `json:"window_labels"`
	StageLabels         map[string]string `json:"stage_labels"`
	SignedStages        []string          `json:"signed_stages"`
	Tabs                [][2]string       `json:"tabs"`
	ValueKinds          map[string]string `json:"value_kinds"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || len(r.Tabs) != 4 || len(r.ValueKinds) == 0 {
		panic(fmt.Sprintf("myperformance: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("myperformance: " + err.Error())
	}
	return z
}()

// Service answers My Performance from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its moment read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type review struct {
	id, stage string
	updatedAt time.Time
}

type commitment struct{ name, kind, behaviour, reflection, evidence string }

var errPassOn = errors.New("myperformance: the existing page answers this reader")

// Build answers /my-performance; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	resp, err := s.build(ctx, p, query, len(role.Strip) > 0 && string(role.Strip) != "null")
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) build(ctx context.Context, p auth.Principal, query url.Values, strip bool) (*screensv1.GetPageResponse, error) {
	if strip || p.StaffProfileID == "" {
		return nil, errPassOn
	}
	operational := schooldirectory.OperationalFY(s.now())
	fy := query.Get("fy")
	if fy == "" {
		fy = operational
	}
	if n, err := strconv.Atoi(fy); err != nil || len(fy) != 4 || n < 2000 || n > 2100 || strings.TrimFunc(fy, unicode.IsDigit) != "" {
		return nil, errPassOn // reporting_period refuses it
	}
	now := s.now()
	local := now.In(zone)
	contract, err := allocations.Read(ctx, s.db, p, fy, now, time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC))
	if err != nil {
		return nil, err
	}
	if len(contract.Rows) > pageSize {
		return nil, errPassOn // the table's own pager
	}
	var window *string
	hasCycle := true
	if err := s.db.QueryRow(ctx, `SELECT active_window FROM hr_performance_cycle WHERE fy = $1 ORDER BY id LIMIT 1`, fy).Scan(&window); errors.Is(err, pgx.ErrNoRows) {
		hasCycle = false
	} else if err != nil {
		return nil, fmt.Errorf("myperformance: reading the cycle: %w", err)
	}
	var rv *review
	r := review{}
	switch err := s.db.QueryRow(ctx, `
SELECT id, COALESCE(stage, ''), updated_at FROM hr_performance_review
WHERE staff_id = $1 AND fy = $2 AND review_type = 'annual_priorities' ORDER BY id LIMIT 1`, p.StaffProfileID, fy).Scan(&r.id, &r.stage, &r.updatedAt); {
	case err == nil:
		rv = &r
	case errors.Is(err, pgx.ErrNoRows):
		if hasCycle {
			return nil, errPassOn // build_draft_agreement writes on this read
		}
	default:
		return nil, fmt.Errorf("myperformance: reading the review: %w", err)
	}
	if p.ActiveRole == "CCEO" {
		var guided bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cce_team_guidance_receipt WHERE recipient_user_id = $1 OR recipient_staff_id = $2)`,
			p.UserID, p.StaffProfileID).Scan(&guided); err != nil {
			return nil, fmt.Errorf("myperformance: reading the guidance: %w", err)
		}
		if guided {
			return nil, errPassOn
		}
	}
	caps := rv != nil && fy == operational && hasCycle && (window == nil || *window != "none")
	manager := slices.Contains(rules.ManagerRoles, p.ActiveRole)
	if rv != nil {
		var records bool
		if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM hr_performance_snapshot WHERE review_id = $1)
    OR EXISTS (SELECT 1 FROM hr_priority_amendment a JOIN hr_performance_priority pr ON pr.id = a.priority_id WHERE pr.review_id = $1)`,
			rv.id).Scan(&records); err != nil {
			return nil, fmt.Errorf("myperformance: reading the conversation records: %w", err)
		}
		if records || (manager && !caps) {
			return nil, errPassOn
		}
	}
	tab := query.Get("tab")
	if tab != "values" && tab != "spiritual" && tab != "development" {
		tab = "distributed"
	}
	blocks := []*screensv1.PageBlock{headline(rv, hasCycle, window, contract.Pct)}
	if p.ActiveRole == "CCEO" {
		blocks = append(blocks, guidance()...)
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Hidden: map[string]string{"tab": tab}}}},
		tabs(fy, tab))
	content, err := s.tabContent(ctx, p, rv, fy, tab, caps, contract)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, content...)
	if rv != nil {
		blocks = append(blocks, panel("Conversation records and amendments", "Frozen conversation snapshots and the amendments made since."),
			panel("", "", "No conversation snapshots yet."))
	}
	return &screensv1.GetPageResponse{Header: header(p.ActiveRole, fy, rv != nil), Blocks: blocks, WebPath: Path}, nil
}

func panel(title, subtitle string, texts ...string) *screensv1.PageBlock {
	pn := &screensv1.PagePanel{Title: title, Subtitle: subtitle}
	for _, t := range texts {
		pn.Items = append(pn.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: pn}}
}

// scope is _contract_scope_label for the reader's own contract.
func scope(role string) string {
	switch role {
	case "Program Lead":
		return "You and your team"
	case "CountryDirector", "RegionalVicePresident", "Admin":
		return "Country delivery"
	}
	return "Your delivery and monitored partners"
}

func header(role, fy string, hasReview bool) *screensv1.PageHeader {
	h := &screensv1.PageHeader{Eyebrow: "Priority Setting Dashboard", Title: "Priorities", Description: scope(role) + " · FY" + fy}
	link := func(key, label, href string) {
		h.Actions = append(h.Actions, &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href})
	}
	if slices.Contains(rules.DistributeRoles, role) {
		link("distribute_targets", "Distribute targets", "/target-distribution?fy="+fy)
	}
	if slices.Contains(rules.DistributeTeamRoles, role) {
		link("distribute_to_my_team", "Distribute to my team", "/target-distribution/team?fy="+fy)
	}
	if slices.Contains(rules.ConfigureRoles, role) {
		link("strategy_approval", "Strategy & approval", "/strategic-priorities?fy="+fy)
	}
	if hasReview {
		link("performance_conversation", "Performance conversation", "/performance-conversation")
	}
	return h
}

// fact is one legacy_kpi_item as components/context_metrics.html draws it.
func fact(label, value, helper, tone string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: label, Value: value}
	brief := schoolprofile.BriefHelper(helper)
	m.Helper = brief
	if brief != helper {
		m.Note = helper
	}
	if brief != "" {
		m.Tone = tone
	}
	return m
}

// stageLabel is the view's stage_label.
func stageLabel(stage string) string {
	if l, ok := rules.StageLabels[stage]; ok {
		return l
	}
	words := strings.ReplaceAll(stage, "_", " ")
	if words == "" {
		return ""
	}
	return strings.ToUpper(words[:1]) + strings.ToLower(words[1:])
}

func headline(rv *review, hasCycle bool, window *string, overall *float64) *screensv1.PageBlock {
	status, updated := "—", ""
	if rv != nil {
		status = stageLabel(rv.stage)
		if status == "" {
			status = "—"
		}
		u := rv.updatedAt.In(zone)
		updated = fmt.Sprintf("%d %s", u.Day(), u.Format("Jan 2006"))
	}
	label := ""
	if hasCycle && window != nil {
		label = rules.WindowLabels[*window]
	}
	progress := fact("Overall progress", "—", "No verified work yet", "neutral")
	if overall != nil {
		progress = fact("Overall progress", allocations.Repr(*overall)+"%", "Weighted verified progress", "primary")
	}
	windowFact := fact("Conversation window", "None open", "HR schedules the next window", "neutral")
	if label != "" {
		windowFact = fact("Conversation window", label, "Open performance conversation", "warning")
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance headline", Metrics: []*screensv1.PageMetric{
		fact("Agreement status", status, updated, "success"),
		progress,
		windowFact,
	}}}}
}

// guidance is guidance_inbox_panel for an officer with no guidance.
func guidance() []*screensv1.PageBlock {
	const empty = "No guidance from your Programme Lead yet."
	return []*screensv1.PageBlock{
		panel("Guidance from your Programme Lead", ""),
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{EmptyMessage: empty, Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{
			{Text: empty + " Guidance your Programme Lead issues on the priorities appears here for you to acknowledge."}}}}}}},
	}
}

func tabs(fy, active string) *screensv1.PageBlock {
	t := &screensv1.PageLinkTabs{}
	for _, def := range rules.Tabs {
		t.Tabs = append(t.Tabs, &screensv1.PageLinkTab{Label: def[1], Href: "?fy=" + fy + "&tab=" + def[0], Active: def[0] == active})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: t}}
}

func (s *Service) tabContent(ctx context.Context, p auth.Principal, rv *review, fy, tab string, caps bool, contract allocations.Contract) ([]*screensv1.PageBlock, error) {
	switch tab {
	case "values", "spiritual":
		title, kind := "Core Values", "value"
		if tab == "spiritual" {
			title, kind = "Spiritual Formation", "spiritual"
		}
		items := []string{}
		if rv != nil {
			list, err := s.commitments(ctx, rv.id, kind)
			if err != nil {
				return nil, err
			}
			signed := slices.Contains(rules.SignedStages, rv.stage)
			for _, c := range list {
				items = append(items, nonEmpty(c.name, labelOf(rules.ValueKinds, c.kind))...)
				if !(caps && !signed) {
					if c.behaviour != "" {
						items = append(items, "Commitment: "+c.behaviour)
					}
					if c.reflection != "" {
						items = append(items, "Reflection: "+c.reflection)
					}
				}
				if c.evidence != "" {
					items = append(items, "Manager: "+c.evidence)
				}
			}
		}
		if len(items) == 0 {
			items = []string{"Commitments become available when your performance cycle opens."}
		}
		return []*screensv1.PageBlock{
			panel(title, "", "Personal commitments and reflections, agreed in your performance conversation."),
			panel("", "", items...),
		}, nil
	case "development":
		items := []string{}
		if rv != nil {
			var err error
			if items, err = s.development(ctx, p.StaffProfileID, rv.id, fy); err != nil {
				return nil, err
			}
		}
		if len(items) == 0 {
			items = []string{"Your professional development plans appear here."}
		}
		manage := &screensv1.PagePanel{Title: "Professional Development", Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
			Links: []*screensv1.PageLink{{Text: "Manage development", Href: "/my-professional-development"}}}}}}}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: manage}}, panel("", "", items...)}, nil
	}
	return []*screensv1.PageBlock{
		distributed(contract, fy),
		panel("", "", "Completion updates as work is completed. Verified achievement updates after verification; returned work is removed from achievement."),
	}, nil
}

// pageSize is the distributed table's page (TABLE_PAGE_SIZE); a longer
// contract is passed on with its pager.
const pageSize = 50

// distributed is the Distributed priorities card as the feed reads it.
func distributed(c allocations.Contract, fy string) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: fmt.Sprintf("Distributed priorities (%d)", len(c.Rows))}
	if len(c.Rows) == 0 {
		t.EmptyMessage = "No approved priorities distributed for FY" + fy + "."
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	for _, label := range []string{"Priority", "Approved target", "Plan and completion", "Verified", "Action"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
	}
	for _, r := range c.Rows {
		verified := "Awaiting metric configuration"
		if r.Pct != nil {
			verified = allocations.FloatFormat(r.Actual, -2) + " · " + allocations.Repr(*r.Pct) + "%"
		}
		cells := []*screensv1.PageCell{
			{Text: collapse(r.Title + r.Priority)},
			{Text: collapse(allocations.FloatFormat(r.Target, -2) + " " + r.Unit + r.Source + " · FY" + fy)},
			{Text: collapse(allocations.Meter(r.Progress))},
			{Text: verified},
			{Text: "Open planning", Href: "/planning?fy=" + fy},
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }

func nonEmpty(texts ...string) []string {
	out := []string{}
	for _, t := range texts {
		if t = strings.Join(strings.Fields(t), " "); t != "" {
			out = append(out, t)
		}
	}
	return out
}

func labelOf(labels map[string]string, value string) string {
	if l, ok := labels[value]; ok {
		return l
	}
	return value
}

func (s *Service) commitments(ctx context.Context, reviewID, kind string) ([]commitment, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(value_name, ''), COALESCE(kind, ''), COALESCE(agreed_behaviour, ''), COALESCE(employee_reflection, ''), COALESCE(manager_evidence, '')
FROM hr_value_commitment WHERE review_id = $1 AND kind = $2`, reviewID, kind)
	if err != nil {
		return nil, fmt.Errorf("myperformance: reading the commitments: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (commitment, error) {
		var c commitment
		err := row.Scan(&c.name, &c.kind, &c.behaviour, &c.reflection, &c.evidence)
		return c, err
	})
}

// development is development_rows: the year's development requests, then
// the review's own items, each read by its description.
func (s *Service) development(ctx context.Context, staffID, reviewID, fy string) ([]string, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(course_name, '') FROM pd_request WHERE staff_id = $1 AND fy = $2 ORDER BY created_at`, staffID, fy)
	if err != nil {
		return nil, fmt.Errorf("myperformance: reading the development requests: %w", err)
	}
	courses, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("myperformance: reading the development requests: %w", err)
	}
	irows, err := s.db.Query(ctx, `SELECT COALESCE(description, '') FROM hr_development_plan_item WHERE review_id = $1`, reviewID)
	if err != nil {
		return nil, fmt.Errorf("myperformance: reading the development items: %w", err)
	}
	items, err := pgx.CollectRows(irows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("myperformance: reading the development items: %w", err)
	}
	return nonEmpty(append(courses, items...)...), nil
}
