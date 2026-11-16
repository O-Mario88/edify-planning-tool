package mytargets

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// Path is the page this package answers.
const Path = "/my-targets"

// errPassOn is a reader or a year Go does not draw yet.
var errPassOn = errors.New("mytargets: passed to the existing application")

// drawnRoles are the staff roles Go draws the page for: a partner's page
// and the Project Coordinator's (shown a section strip) are handed on.
var drawnRoles = []string{"Admin", "CCEO", "ImpactAssessment", "Program Lead"}

var local = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic(fmt.Sprintf("mytargets: the local zone: %v", err))
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// page is one answer: the reader, the year and month asked for, and today.
type page struct {
	p                   auth.Principal
	person              targets.Person
	fy                  string
	month, currentMonth int
	current             bool
	today, now          time.Time
	roster              *targets.Roster
}

// choose is the year and month the query asks for (get_page's defaults),
// or false when the query names one the page does not offer.
func choose(query url.Values, now time.Time) (fy string, month int, ok bool) {
	for key := range query {
		if key != "fy" && key != "month" {
			return "", 0, false
		}
	}
	today := targets.Day(now.In(local))
	operational := operationalFY(today)
	fy = strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = operational
	} else if !slices.Contains(schooldirectory.FYOptions(now), fy) {
		return "", 0, false
	}
	// str.isdigit() then 1–12, as the view reads it; a digit outside ASCII
	// (which int() also reads) is handed on.
	raw := strings.TrimSpace(query.Get("month"))
	digits := raw != ""
	for _, r := range raw {
		if !unicode.IsDigit(r) {
			digits = false
		} else if r > '9' {
			return "", 0, false
		}
	}
	if m, err := strconv.Atoi(raw); digits && err == nil && m >= 1 && m <= 12 {
		month = m
	}
	return fy, month, true
}

// Build answers /my-targets.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path || !slices.Contains(drawnRoles, p.ActiveRole) || !slices.Contains(rules.PageRoles, p.ActiveRole) ||
		p.StaffProfileID == "" || p.InActingAppointment {
		return nil, false, nil
	}
	now := s.now()
	fy, month, ok := choose(query, now)
	if !ok {
		return nil, false, nil
	}
	resp, err := s.build(ctx, p, fy, month, now)
	if errors.Is(err, errPassOn) || errors.Is(err, targets.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) build(ctx context.Context, p auth.Principal, fy string, month int, now time.Time) (*screensv1.GetPageResponse, error) {
	today := targets.Day(now.In(local))
	pg := &page{p: p, person: targets.Person{UserID: p.UserID, StaffID: p.StaffProfileID}, fy: fy, today: today, now: now}
	operational := operationalFY(today)
	pg.current = fy == operational
	pg.currentMonth = 12
	if pg.current {
		pg.currentMonth = max(targets.MonthOfFY(today, fy), 1)
	}
	pg.month = month
	if pg.month == 0 {
		pg.month = 1
		if pg.current {
			pg.month = pg.currentMonth
		}
	}
	exist, err := allocations.Exist(ctx, s.db, fy)
	if err != nil {
		return nil, err
	}
	if exist {
		// Approved allocations draw the distributed contract, the milestone
		// table and the planning feed, which Go does not draw yet.
		return nil, errPassOn
	}
	if pg.roster, err = targets.Prepare(ctx, s.db, []targets.Person{pg.person}, fy, nil); err != nil {
		return nil, err
	}
	blocks := append([]*screensv1.PageBlock{pg.filters()}, distributedSummary()...)
	figures, err := pg.figures(ctx, s.db)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, figures.top(pg)...)
	if opens(p.ActiveRole, "/priorities") {
		blocks = append(blocks, textPanel("", "Open distributed priorities →"))
	}
	strategic, err := strategicPriorities(ctx, s.db, pg)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, strategic...)
	projects, err := projectPriorities(ctx, s.db, pg)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, projects)
	portfolio, err := priorityPortfolio(ctx, s.db, pg)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, portfolio, milestonesPanel())
	blocks = append(blocks, figures.charts(pg)...)
	blocks = append(blocks, figures.focusPanel())
	tracker, err := coreTracker(ctx, s.db, pg)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, tracker...)
	blocks = append(blocks, textPanel("", "Last refreshed "+now.In(local).Format("02 Jan 2006 15:04")))
	return &screensv1.GetPageResponse{
		Header:  header(),
		Blocks:  blocks,
		Dialogs: dialogs(),
		WebPath: Path,
	}, nil
}

// operationalFY is get_operational_fy: the year starts on 1 October.
func operationalFY(day time.Time) string {
	if day.Month() >= time.October {
		return strconv.Itoa(day.Year() + 1)
	}
	return strconv.Itoa(day.Year())
}

func header() *screensv1.PageHeader {
	return &screensv1.PageHeader{
		Eyebrow:     "Performance",
		Title:       "My Targets",
		Description: "Track your personal performance across monthly, quarterly, and financial-year targets.",
		Actions: []*screensv1.PageAction{{Key: "submit_mscs", Label: "Submit MSCS", Enabled: true,
			Href: "#dialog=showMscs", Drawer: true}},
	}
}

// filters is the year and month the page reads.
func (pg *page) filters() *screensv1.PageBlock {
	year := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: pg.fy, Caption: "FY"}
	for _, y := range schooldirectory.FYOptions(pg.now) {
		year.Options = append(year.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	month := &screensv1.PageFilter{Name: "month", Label: "Month", Value: strconv.Itoa(pg.month)}
	for m := 1; m <= 12; m++ {
		month.Options = append(month.Options, &screensv1.PageFilterOption{Value: strconv.Itoa(m), Label: targets.MonthLabel(pg.fy, m)})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{year, month}}}}
}

// distributedSummary is partials/hr/distributed_summary.html for a reader
// with no approved contract.
func distributedSummary() []*screensv1.PageBlock {
	cols := []*screensv1.PageColumn{}
	for _, c := range []string{"Priority", "Scope", "Target", "Verified", "Achievement"} {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	return []*screensv1.PageBlock{
		textPanel("Distributed priority performance", "No configured score for this reporting scope"),
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: []*screensv1.PageRow{
			{Cells: []*screensv1.PageCell{{Text: "No approved distributed priorities in this record."}}}}}}},
	}
}

func milestonesPanel() *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:    "My Strategic Milestone Allocations",
		Subtitle: "Only approved allocations appear here. Actuals come from canonical source records and cannot be typed.",
		Items: []*screensv1.PagePanelItem{text("No approved milestone allocations yet"),
			text("Your existing operational targets remain unchanged. Strategic milestones will appear here automatically after definition, approval, and allocation. In accordance with the single-source rule, unallocated milestones do not create targets, reduce achievement, or generate risk.")},
	}}}
}

// dialogs are the page's MSCS form and its roll-up explanation.
func dialogs() []*screensv1.PageDialog {
	field := func(name, label, kind, placeholder string, required bool, maxLength *int32) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
			Name: name, Label: label, Kind: kind, Required: required, Placeholder: placeholder, MaxLength: maxLength}}}
	}
	titleLength := int32(255)
	form := &screensv1.PageForm{
		Text: "Most Significant Change Story — counts toward your MSCS target once approved.",
		Items: []*screensv1.PageFormItem{
			field("title", "Title", "text", "A short, specific story title", true, &titleLength),
			field("story_date", "Story Date", "date", "", true, nil),
			field("school_id", "School ID", "text", "optional", false, nil),
			field("narrative", "Narrative", "textarea", "What changed, for whom, and why it matters…", true, nil),
		},
		SubmitLabel: "Submit for Review", Key: "/my-targets/mscs", CanSave: true,
	}
	rollup := []*screensv1.PageLink{}
	for _, line := range []string{
		"Monthly targets are the source. Quarter and FY values are never entered — they are sums of your monthly targets and validated achievements.",
		"Monthly achievements roll into their quarter; Q1–Q4 roll into the financial year.",
		"Only validated work counts — executed, evidenced, with its Activity SF ID, and verified (by the Programme Lead; by IA for partner work).",
		"Late verification is credited to the month the work actually happened.",
		"Returned work loses its credit until fixed.",
	} {
		rollup = append(rollup, &screensv1.PageLink{Text: line})
	}
	return []*screensv1.PageDialog{
		{Key: "showMscs", Title: "Submit MSCS", Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: form}}}},
		{Key: "showRollup", Title: "How roll-up works", Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "How roll-up works",
			Items: []*screensv1.PagePanelItem{
				{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: rollup}}},
				text("Got it"),
			}}}}}},
	}
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func toned(s, tone string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}, Tone: tone}
}

func heading(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: s}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func textPanel(title string, lines ...string) *screensv1.PageBlock {
	panel := &screensv1.PagePanel{Title: title}
	for _, l := range lines {
		panel.Items = append(panel.Items, text(l))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
}
