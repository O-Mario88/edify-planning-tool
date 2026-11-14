// Package fyplanning is Fiscal Year Planning (/planning/fiscal-years): each
// fiscal year's planning policy (whether it is operational, closed, open for
// planning or not open yet, when planning opens, the delivery window and
// whether a follow-up needs a prior training), and the form that opens the
// next year, as the existing page draws them
// (apps.frontend.views.fy_planning_views.fiscal_year_planning_view,
// apps.planning.fy_policy and pages/planning/fiscal_years.html) and the app's
// feed reads them. Opening a year and changing its follow-up rule stay with
// the existing application.
//
// The doors, who manages the policy and the default country are exported to
// rules.json by `manage.py export_fy_planning_rules`;
// apps/planning/test_fy_planning_rules_export.py fails when the two differ.
package fyplanning

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"time"

	_ "time/tzdata" // the opening moment is written in Nairobi wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/planning/fiscal-years"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page    bool `json:"page"`
		Manages bool `json:"manages"`
	} `json:"roles"`
	DefaultCountry string `json:"default_country"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.DefaultCountry == "" {
		panic(fmt.Sprintf("fyplanning: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// zone is settings.TIME_ZONE, the zone |date writes a moment in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("fyplanning: " + err.Error())
	}
	return z
}()

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// policy is one fiscal_year_planning_policy row.
type policy struct {
	FY                    string
	OpenAt                *time.Time
	Start, End            time.Time
	FollowUpNeedsTraining bool
}

// Build answers /planning/fiscal-years; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	rows, err := s.db.Query(ctx, `
SELECT fy, planning_open_at, execution_start, execution_end, follow_up_visit_requires_prior_training
FROM fiscal_year_planning_policy ORDER BY fy DESC`)
	if err != nil {
		return nil, true, fmt.Errorf("fyplanning: reading the policies: %w", err)
	}
	policies, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (policy, error) {
		var pl policy
		err := r.Scan(&pl.FY, &pl.OpenAt, &pl.Start, &pl.End, &pl.FollowUpNeedsTraining)
		return pl, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("fyplanning: reading the policies: %w", err)
	}
	now := s.now()
	operational := schooldirectory.OperationalFY(now)
	next := nextFY(operational)
	var nextOpen bool
	if role.Manages {
		// is_planning_open(next): a later year opens once its policy (for the
		// default country) has an opening moment that has passed.
		var openAt *time.Time
		err := s.db.QueryRow(ctx, `SELECT planning_open_at FROM fiscal_year_planning_policy WHERE country = $1 AND fy = $2 LIMIT 1`,
			rules.DefaultCountry, next).Scan(&openAt)
		if err != nil && err != pgx.ErrNoRows {
			return nil, true, fmt.Errorf("fyplanning: reading the next year's policy: %w", err)
		}
		nextOpen = openAt != nil && !openAt.After(now)
	}
	return page(policies, operational, next, role.Manages, nextOpen, now), true, nil
}

func nextFY(operational string) string {
	n, _ := strconv.Atoi(operational)
	return strconv.Itoa(n + 1)
}

// windowState is fy_policy.window_state: how a fiscal year reads today.
func windowState(pl policy, operational string, now time.Time) string {
	year, err1 := strconv.Atoi(pl.FY)
	current, err2 := strconv.Atoi(operational)
	switch {
	case err1 != nil || err2 != nil:
		return "Not open"
	case year == current:
		return "Operational"
	case year < current:
		return "Closed year"
	case pl.OpenAt != nil && !pl.OpenAt.After(now):
		return "Open for planning"
	}
	return "Not open"
}

// day is |date:"j M Y".
func day(t time.Time) string { return t.Format("2 Jan 2006") }

func page(policies []policy, operational, next string, manages, nextOpen bool, now time.Time) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Planning cycle", Title: "Fiscal Year Planning",
		Description: "FY" + operational + " is the operational year. A later year can be planned once it is opened; its work starts on its first day."}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Fiscal year", "State", "Planning opens", "Delivery window", "Follow-up needs a prior training"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, pl := range policies {
		opens := "—"
		if pl.OpenAt != nil {
			opens = day(pl.OpenAt.In(zone))
		}
		// The follow-up cell is the answer, then (for a manager) the words
		// of the button that flips it; its reason field is not read.
		rule, flip := "No", "Require a training"
		if pl.FollowUpNeedsTraining {
			rule, flip = "Yes", "Allow without training"
		}
		if manages {
			rule += " " + flip
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: "FY" + pl.FY, Strong: true},
			{Text: windowState(pl, operational, now)},
			{Text: opens},
			{Text: day(pl.Start) + " – " + day(pl.End)},
			{Text: rule},
		}})
	}
	if len(policies) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{
			Text: "No fiscal year has a planning policy yet. The operational year and earlier years remain plannable."}}}}
	}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Fiscal years"}}},
		{Kind: &screensv1.PageBlock_Table{Table: t}},
	}
	if manages && !nextOpen {
		blocks = append(blocks, openForm(operational, next))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

func field(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

// openForm is "Open FY… for planning".
func openForm(operational, next string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: "Open FY" + next + " for planning",
		Text: "Staff can plan, schedule and budget FY" + next + " work for dates from its first day while FY" + operational +
			" is still being closed. Prepare the FY" + next + " rate card in Cost Settings so the work can be costed.",
		Items: []*screensv1.PageFormItem{
			field(&screensv1.DrawerField{Name: "planning_open_at", Label: "Planning opens", Kind: "datetime-local"}),
			field(&screensv1.DrawerField{Name: "follow_up_requires_training", Label: "Follow-up needs a prior training", Kind: "select", Value: "no",
				Options: []*screensv1.DrawerOption{{Value: "no", Label: "No"}, {Value: "yes", Label: "Yes"}}}),
			field(&screensv1.DrawerField{Name: "notes", Label: "Note", Kind: "text"}),
		},
		SubmitLabel: "Open FY" + next,
		Key:         "open",
	}}}
}
